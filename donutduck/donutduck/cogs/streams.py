"""Twitch live notifications, in the style of Streamcord.

A single poll every 2 minutes covers every watched streamer across every
server, because Helix takes up to 100 logins per request. Announcements are
keyed on the Twitch stream id rather than a live/offline flag, so a brief
disconnect and reconnect doesn't produce a second ping for the same broadcast.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..theme import BLUE, PINK
from ..twitch import TwitchError
from ..utils import base_embed, error_embed

log = logging.getLogger("donutduck.streams")

TWITCH_PURPLE = 0x9146FF
POLL_MINUTES = 2
MAX_PER_GUILD = 25

DEFAULT_MESSAGE = "{mention} **{name}** is live!"


def render(template: str, *, mention: str, name: str, title: str, game: str, url: str) -> str:
    """Substitute the placeholders people can use in a custom message."""
    return (
        (template or DEFAULT_MESSAGE)
        .replace("{mention}", mention)
        .replace("{name}", name)
        .replace("{title}", title)
        .replace("{game}", game)
        .replace("{url}", url)
    )[:2000]


class Streams(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.poll.start()

    async def cog_unload(self):
        self.poll.cancel()

    # ---------------------------------------------------------------- poll

    @tasks.loop(minutes=POLL_MINUTES)
    async def poll(self):
        if not self.bot.twitch.configured:
            return

        try:
            subs = await self.bot.db.all_streams()
        except Exception:
            log.exception("Couldn't read stream subscriptions")
            return

        if not subs:
            return

        logins = sorted({s["login"] for s in subs})
        try:
            live = await self.bot.twitch.get_streams(logins)
        except TwitchError as exc:
            log.warning("Twitch poll failed: %s", exc)
            return

        # One /users call for avatars, only for those actually live.
        users: dict[str, dict] = {}
        if live:
            try:
                users = await self.bot.twitch.get_users(list(live))
            except TwitchError:
                pass

        for sub in subs:
            stream = live.get(sub["login"])
            try:
                if stream:
                    await self._handle_live(sub, stream, users.get(sub["login"]))
                elif sub["is_live"]:
                    await self.bot.db.set_stream_state(sub["id"], False, sub["last_stream"])
            except Exception:
                log.exception("Stream subscription %s failed", sub["id"])

    async def _handle_live(self, sub: dict, stream: dict, user: dict | None) -> None:
        stream_id = str(stream.get("id"))
        # Same broadcast we already announced — say nothing.
        if sub["is_live"] and sub["last_stream"] == stream_id:
            return
        if sub["last_stream"] == stream_id:
            await self.bot.db.set_stream_state(sub["id"], True, stream_id)
            return

        channel = self.bot.get_channel(sub["channel_id"])
        if channel is None:
            return

        await self.bot.db.set_stream_state(sub["id"], True, stream_id)
        await self._announce(channel, sub, stream, user)

    async def _announce(
        self, channel: discord.TextChannel, sub: dict, stream: dict, user: dict | None
    ) -> None:
        name = stream.get("user_name") or sub["login"]
        title = stream.get("title") or "Untitled stream"
        game = stream.get("game_name") or "Unknown"
        url = f"https://twitch.tv/{sub['login']}"

        mention = ""
        if sub["mention_role"]:
            role = channel.guild.get_role(sub["mention_role"])
            if role:
                mention = role.mention

        embed = discord.Embed(
            title=title[:256],
            url=url,
            color=TWITCH_PURPLE,
            description=f"Playing **{game}**",
        )
        embed.set_author(
            name=f"{name} is live on Twitch",
            url=url,
            icon_url=self.bot.twitch.profile_image(user),
        )
        thumb = self.bot.twitch.thumbnail(stream)
        if thumb:
            embed.set_image(url=thumb)
        if stream.get("viewer_count") is not None:
            embed.add_field(name="Viewers", value=f"{stream['viewer_count']:,}", inline=True)
        embed.add_field(name="Watch", value=f"[twitch.tv/{sub['login']}]({url})", inline=True)
        embed.set_footer(text="DonutDuck • Twitch notifications")

        content = render(
            sub["message"], mention=mention, name=name, title=title, game=game, url=url
        )

        try:
            await channel.send(
                content=content,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(roles=True, everyone=False),
            )
            log.info("Announced %s live in guild %s", sub["login"], sub["guild_id"])
        except discord.HTTPException as exc:
            log.warning("Couldn't announce %s: %s", sub["login"], exc)

    @poll.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------ commands

    group = app_commands.Group(
        name="twitch",
        description="Twitch live notifications",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    async def login_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        subs = await self.bot.db.guild_streams(interaction.guild_id)
        return [
            app_commands.Choice(name=s["login"], value=s["login"])
            for s in subs
            if current.lower() in s["login"]
        ][:25]

    @group.command(name="add", description="Announce when a Twitch streamer goes live")
    @app_commands.describe(
        streamer="Twitch username (the name in their URL)",
        channel="Where to post the announcement",
        role="Role to ping (optional)",
        message="Custom text. Placeholders: {mention} {name} {title} {game} {url}",
    )
    async def add(
        self,
        interaction: discord.Interaction,
        streamer: str,
        channel: discord.TextChannel,
        role: discord.Role | None = None,
        message: str | None = None,
    ):
        await interaction.response.defer()

        if not self.bot.twitch.configured:
            await interaction.followup.send(
                embed=error_embed(
                    "Twitch isn't set up. Create an app at "
                    "https://dev.twitch.tv/console/apps (free), then put "
                    "TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET in `.env` and restart me.",
                    title="Twitch not configured",
                )
            )
            return

        login = streamer.lower().strip().lstrip("@")
        if login.startswith("http"):
            login = login.rstrip("/").split("/")[-1].lower()

        perms = channel.permissions_for(interaction.guild.me)
        if not (perms.send_messages and perms.embed_links):
            await interaction.followup.send(
                embed=error_embed(f"I need Send Messages and Embed Links in {channel.mention}.")
            )
            return

        existing = await self.bot.db.guild_streams(interaction.guild_id)
        if len(existing) >= MAX_PER_GUILD:
            await interaction.followup.send(
                embed=error_embed(f"This server is at the limit of {MAX_PER_GUILD} streamers.")
            )
            return

        # Verify the channel exists before storing it, so typos fail loudly now
        # rather than silently never firing.
        try:
            users = await self.bot.twitch.get_users([login])
        except TwitchError as exc:
            await interaction.followup.send(embed=error_embed(str(exc)))
            return

        if login not in users:
            await interaction.followup.send(
                embed=error_embed(f"Twitch has no channel called `{login}`.")
            )
            return

        user = users[login]
        added = await self.bot.db.add_stream(
            interaction.guild_id,
            channel.id,
            login,
            mention_role=role.id if role else None,
            message=message,
            added_by=interaction.user.id,
        )
        if not added:
            await interaction.followup.send(
                embed=error_embed(f"`{login}` is already being watched here.")
            )
            return

        embed = base_embed(
            "🟣 Now watching",
            f"I'll announce in {channel.mention} when **{user['display_name']}** goes live.",
            accent=BLUE,
        )
        embed.set_thumbnail(url=user.get("profile_image_url"))
        if role:
            embed.add_field(name="Pings", value=role.mention, inline=True)
        embed.add_field(name="Checked every", value=f"{POLL_MINUTES} minutes", inline=True)
        if message:
            embed.add_field(name="Message", value=message[:1024], inline=False)
        await interaction.followup.send(embed=embed)

    @group.command(name="remove", description="Stop watching a streamer")
    @app_commands.describe(streamer="Twitch username")
    @app_commands.autocomplete(streamer=login_autocomplete)
    async def remove(self, interaction: discord.Interaction, streamer: str):
        removed = await self.bot.db.remove_stream(interaction.guild_id, streamer.lower())
        if removed:
            await interaction.response.send_message(
                embed=base_embed("🛑 Stopped watching", f"No longer tracking `{streamer}`.", accent=PINK)
            )
        else:
            await interaction.response.send_message(
                embed=error_embed(f"`{streamer}` wasn't being watched here."), ephemeral=True
            )

    @group.command(name="list", description="Streamers watched in this server")
    async def list_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer()
        subs = await self.bot.db.guild_streams(interaction.guild_id)

        if not subs:
            await interaction.followup.send(
                embed=base_embed("🟣 Nobody watched yet", "Add one with `/twitch add`.")
            )
            return

        embed = base_embed(f"🟣 Watching {len(subs)} streamer(s)")
        lines = []
        for sub in subs[:25]:
            status = "🔴 live" if sub["is_live"] else "⚫ offline"
            ping = f" · pings <@&{sub['mention_role']}>" if sub["mention_role"] else ""
            lines.append(
                f"**{sub['login']}** — {status} · <#{sub['channel_id']}>{ping}"
            )
        embed.description = "\n".join(lines)
        await interaction.followup.send(embed=embed)

    @group.command(name="test", description="Preview the announcement for a streamer")
    @app_commands.describe(streamer="Twitch username")
    @app_commands.autocomplete(streamer=login_autocomplete)
    async def test(self, interaction: discord.Interaction, streamer: str):
        await interaction.response.defer(ephemeral=True)
        login = streamer.lower()

        subs = {s["login"]: s for s in await self.bot.db.guild_streams(interaction.guild_id)}
        sub = subs.get(login)
        if sub is None:
            await interaction.followup.send(
                embed=error_embed(f"`{login}` isn't being watched here.")
            )
            return

        try:
            live = await self.bot.twitch.get_streams([login])
            users = await self.bot.twitch.get_users([login])
        except TwitchError as exc:
            await interaction.followup.send(embed=error_embed(str(exc)))
            return

        stream = live.get(login) or {
            "id": "0",
            "user_name": users.get(login, {}).get("display_name", login),
            "title": "Example stream title",
            "game_name": "Just Chatting",
            "viewer_count": 123,
            "thumbnail_url": "",
        }

        channel = self.bot.get_channel(sub["channel_id"]) or interaction.channel
        await self._announce(channel, sub, stream, users.get(login))
        await interaction.followup.send(
            embed=base_embed(
                "✅ Test sent",
                f"Posted a preview in <#{sub['channel_id']}>."
                + ("" if live else "\n*(they're offline, so this used sample data)*"),
            )
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Streams(bot))
