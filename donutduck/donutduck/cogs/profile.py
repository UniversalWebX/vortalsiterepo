"""Per-server bot profile: /serverprofile.

Discord lets an application set a **guild-specific** avatar and nickname for
its own member via `PATCH /guilds/{guild_id}/members/@me`. That's genuinely
per-server: changing it here has no effect on the bot's appearance anywhere
else, unlike `ClientUser.edit(avatar=...)` which is global and would change
the bot's face in every server it's in.

discord.py 2.7 added `avatar` to `Member.edit`; on older versions we fall back
to calling the endpoint directly, so this works on 2.4+.

Note on `imghdr`: it was removed in Python 3.13, so image types are detected
from magic bytes here rather than with the stdlib module.
"""

from __future__ import annotations

import base64
import inspect
import logging

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from ..theme import BLUE, PINK
from ..utils import base_embed, error_embed

log = logging.getLogger("donutduck.profile")

# Discord's ceiling for avatars is 10 MiB; stop well short so a doomed upload
# fails locally with a clear message rather than after a slow round trip.
MAX_BYTES = 8 * 1024 * 1024

# (magic bytes, offset, mime)
SIGNATURES = [
    (b"\x89PNG\r\n\x1a\n", 0, "image/png"),
    (b"\xff\xd8\xff", 0, "image/jpeg"),
    (b"GIF87a", 0, "image/gif"),
    (b"GIF89a", 0, "image/gif"),
    (b"WEBP", 8, "image/webp"),
]


def detect_mime(data: bytes) -> str | None:
    """Identify an image from its header. Replaces imghdr, gone in 3.13."""
    for signature, offset, mime in SIGNATURES:
        if data[offset : offset + len(signature)] == signature:
            return mime
    return None


def to_data_uri(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


class Profile(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    group = app_commands.Group(
        name="serverprofile",
        description="Change how DonutDuck looks in this server only",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    # ------------------------------------------------------------- helpers

    async def apply_avatar(self, guild: discord.Guild, data: bytes | None) -> None:
        """Set (or clear, with None) the bot's avatar in one guild.

        Prefers Member.edit where the installed discord.py supports it, and
        otherwise hits the REST endpoint directly. Raises discord.HTTPException
        on failure for the caller to translate.
        """
        supports_avatar = "avatar" in inspect.signature(discord.Member.edit).parameters
        if supports_avatar:
            await guild.me.edit(avatar=data)
            return

        payload: dict[str, str | None]
        if data is None:
            payload = {"avatar": None}
        else:
            mime = detect_mime(data) or "image/png"
            payload = {"avatar": to_data_uri(data, mime)}

        from discord.http import Route

        await self.bot.http.request(
            Route("PATCH", "/guilds/{guild_id}/members/@me", guild_id=guild.id),
            json=payload,
        )

    async def read_image(
        self, attachment: discord.Attachment | None, url: str | None
    ) -> tuple[bytes | None, str]:
        """Returns (data, error_message). Data is None when there's an error."""
        if attachment is not None:
            if attachment.size > MAX_BYTES:
                return None, (
                    f"That image is {attachment.size / 1_048_576:.2f} MB, over the "
                    f"{MAX_BYTES // 1_048_576} MB limit."
                )
            data = await attachment.read()
        elif url:
            if not url.startswith(("http://", "https://")):
                return None, "That doesn't look like a valid image URL."
            try:
                timeout = aiohttp.ClientTimeout(total=15)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            return None, f"Couldn't download that image (HTTP {resp.status})."
                        # Trust the declared length when present, but also cap
                        # the read so a lying or chunked response can't blow up
                        # memory.
                        if (resp.content_length or 0) > MAX_BYTES:
                            return None, "That image is too large (max 8 MB)."
                        data = await resp.content.read(MAX_BYTES + 1)
            except aiohttp.ClientError:
                return None, "Couldn't reach that URL."
            except TimeoutError:
                return None, "That URL took too long to respond."

            if len(data) > MAX_BYTES:
                return None, "That image is too large (max 8 MB)."
        else:
            return None, "Attach an image or give me a URL."

        mime = detect_mime(data)
        if mime is None:
            return None, "That file isn't a PNG, JPEG, GIF or WebP image."
        return data, ""

    # ------------------------------------------------------------ commands

    @group.command(name="avatar", description="Set the bot's avatar in this server only")
    @app_commands.describe(
        image="Upload an image (PNG, JPEG, GIF or WebP, max 8 MB)",
        url="…or give a direct image URL instead",
    )
    @app_commands.checks.cooldown(2, 3600, key=lambda i: i.guild_id)
    async def avatar(
        self,
        interaction: discord.Interaction,
        image: discord.Attachment | None = None,
        url: str | None = None,
    ):
        await interaction.response.defer()

        data, problem = await self.read_image(image, url)
        if data is None:
            await interaction.followup.send(embed=error_embed(problem))
            return

        try:
            await self.apply_avatar(interaction.guild, data)
        except discord.Forbidden:
            await interaction.followup.send(
                embed=error_embed(
                    "Discord refused the change. Per-server avatars can be "
                    "restricted by server settings — check that I'm allowed to "
                    "change my own nickname and profile here."
                )
            )
            return
        except discord.HTTPException as exc:
            if exc.status == 429:
                await interaction.followup.send(
                    embed=error_embed(
                        "Discord is rate limiting avatar changes. Wait a while "
                        "before trying again — these are limited to a couple per hour."
                    )
                )
            else:
                log.warning("Guild avatar change failed: %s", exc)
                await interaction.followup.send(
                    embed=error_embed(f"Discord rejected the image: {exc.text or exc}")
                )
            return

        source = image.url if image else url
        await self.bot.db.set_profile(
            interaction.guild_id, avatar_url=source, updated_by=interaction.user.id
        )

        embed = base_embed(
            "🖼️ Server avatar updated",
            f"I'll wear this face in **{interaction.guild.name}** only — my "
            "appearance in every other server is unchanged.",
            accent=BLUE,
        )
        embed.set_thumbnail(url=source)
        embed.set_footer(text="Undo with /serverprofile reset • DonutDuck")
        await interaction.followup.send(embed=embed)

    @group.command(name="nickname", description="Set the bot's nickname in this server")
    @app_commands.describe(nickname="Leave blank to clear it")
    async def nickname(
        self, interaction: discord.Interaction, nickname: str | None = None
    ):
        await interaction.response.defer()
        try:
            await interaction.guild.me.edit(nick=nickname or None)
        except discord.Forbidden:
            await interaction.followup.send(
                embed=error_embed("I need the **Change Nickname** permission here.")
            )
            return
        except discord.HTTPException as exc:
            await interaction.followup.send(embed=error_embed(f"Couldn't set it: {exc}"))
            return

        await self.bot.db.set_profile(
            interaction.guild_id, nickname=nickname, updated_by=interaction.user.id
        )
        await interaction.followup.send(
            embed=base_embed(
                "✏️ Nickname updated",
                f"I'm now **{nickname}** here." if nickname else "Nickname cleared.",
                accent=BLUE,
            )
        )

    @group.command(name="reset", description="Restore the bot's default look here")
    async def reset(self, interaction: discord.Interaction):
        await interaction.response.defer()
        problems = []

        try:
            await self.apply_avatar(interaction.guild, None)
        except discord.HTTPException as exc:
            problems.append(f"avatar ({exc.status})")

        try:
            await interaction.guild.me.edit(nick=None)
        except discord.HTTPException as exc:
            problems.append(f"nickname ({exc.status})")

        await self.bot.db.clear_profile(interaction.guild_id)

        if problems:
            await interaction.followup.send(
                embed=error_embed(
                    "Couldn't fully reset: " + ", ".join(problems),
                    title="Partly reset",
                )
            )
            return

        await interaction.followup.send(
            embed=base_embed(
                "↩️ Reset",
                "Back to my normal avatar and name in this server.",
                accent=PINK,
            )
        )

    @group.command(name="view", description="Show this server's profile settings")
    async def view(self, interaction: discord.Interaction):
        profile = await self.bot.db.get_profile(interaction.guild_id)
        me = interaction.guild.me

        embed = base_embed("🖼️ Server profile", accent=BLUE)
        embed.add_field(name="Nickname", value=me.nick or "*default*", inline=True)
        embed.add_field(
            name="Avatar",
            value="Custom for this server" if me.guild_avatar else "*global default*",
            inline=True,
        )
        if profile["updated_by"]:
            embed.add_field(
                name="Last changed",
                value=f"<@{profile['updated_by']}> <t:{int(profile['updated_at'])}:R>",
                inline=False,
            )
        embed.set_thumbnail(url=me.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    # Cooldown rejections should read as a normal message, not an error trace.
    @avatar.error
    async def avatar_error(self, interaction: discord.Interaction, error: Exception):
        if isinstance(error, app_commands.CommandOnCooldown):
            message = (
                f"Avatar changes are limited to protect against Discord's own "
                f"rate limits. Try again in {error.retry_after / 60:.0f} minute(s)."
            )
            send = (
                interaction.followup.send
                if interaction.response.is_done()
                else interaction.response.send_message
            )
            await send(embed=error_embed(message, title="Slow down"), ephemeral=True)
            return
        raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(Profile(bot))
