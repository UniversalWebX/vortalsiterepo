"""Vouch system.

A Vouch button appears in giveaway claim tickets. Pressing it asks who you're
vouching for (a real Discord user picker, not a typed name), then a message,
then posts to the vouch channel as:

    @voucher: vouch @target message

The user picker matters: a typed username can't be resolved reliably —
duplicate display names, changed nicknames, typos — and a vouch aimed at the
wrong person is worse than no vouch. Discord modals only accept text inputs,
so the flow is a select first, then the modal.

Vouches are also stored, which makes `/vouches` and `/vouchtop` possible and
gives staff something to check when someone claims a trade went fine.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from ..theme import BLUE, PINK, YELLOW
from ..utils import base_embed, error_embed

log = logging.getLogger("donutduck.vouch")

VOUCH_BUTTON_ID = "dd:vouch:open"

# Fallback used when a server hasn't set its own channel.
DEFAULT_VOUCH_CHANNEL = 1519688084973686814

MAX_MESSAGE = 500
COOLDOWN_HOURS = 24


async def resolve_vouch_channel(bot, guild: discord.Guild):
    """Server setting first, then the built-in default if it's in this guild."""
    settings = await bot.db.settings(guild.id)
    channel_id = settings.get("vouch_channel") or DEFAULT_VOUCH_CHANNEL
    channel = guild.get_channel(channel_id)
    if channel is None and settings.get("vouch_channel"):
        # Configured channel was deleted; fall back rather than silently fail.
        channel = guild.get_channel(DEFAULT_VOUCH_CHANNEL)
    return channel


async def post_vouch(
    bot,
    guild: discord.Guild,
    author: discord.Member,
    target: discord.Member,
    message: str | None,
    *,
    source: str = "command",
    giveaway_id: int | None = None,
) -> tuple[bool, str]:
    """Post and record a vouch. Returns (ok, detail)."""
    channel = await resolve_vouch_channel(bot, guild)
    if channel is None:
        return False, (
            "No vouch channel is set. Staff can set one with `/vouchchannel`."
        )

    perms = channel.permissions_for(guild.me)
    if not perms.send_messages:
        return False, f"I can't post in {channel.mention}."

    body = f"{author.mention}: vouch {target.mention}"
    if message:
        body += f" {message}"

    try:
        posted = await channel.send(
            body,
            # Mentions render but don't ping — a vouch channel would be
            # unusable if every entry notified two people.
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except discord.HTTPException as exc:
        return False, f"Couldn't post the vouch: {exc}"

    await bot.db.add_vouch(
        guild.id,
        author.id,
        target.id,
        message,
        source=source,
        giveaway_id=giveaway_id,
        message_id=posted.id,
    )
    return True, channel.mention


class VouchMessageModal(discord.ui.Modal, title="Leave a vouch"):
    message = discord.ui.TextInput(
        label="Your vouch message",
        style=discord.TextStyle.paragraph,
        placeholder="e.g. paid instantly, smooth trade, thanks!",
        required=False,
        max_length=MAX_MESSAGE,
    )

    def __init__(self, cog: "Vouch", target: discord.Member, giveaway_id: int | None):
        super().__init__()
        self.cog = cog
        self.target = target
        self.giveaway_id = giveaway_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ok, detail = await post_vouch(
            self.cog.bot,
            interaction.guild,
            interaction.user,
            self.target,
            self.message.value or None,
            source="giveaway" if self.giveaway_id else "command",
            giveaway_id=self.giveaway_id,
        )
        if not ok:
            await interaction.followup.send(embed=error_embed(detail), ephemeral=True)
            return

        await interaction.followup.send(
            embed=base_embed(
                "✅ Vouch posted",
                f"Your vouch for {self.target.mention} is in {detail}.",
                accent=YELLOW,
            ),
            ephemeral=True,
        )


class VouchUserSelect(discord.ui.UserSelect):
    def __init__(self, cog: "Vouch", giveaway_id: int | None):
        super().__init__(placeholder="Who are you vouching for?", min_values=1, max_values=1)
        self.cog = cog
        self.giveaway_id = giveaway_id

    async def callback(self, interaction: discord.Interaction):
        target = self.values[0]

        if target.id == interaction.user.id:
            await interaction.response.send_message(
                embed=error_embed("You can't vouch for yourself."), ephemeral=True
            )
            return
        if getattr(target, "bot", False):
            await interaction.response.send_message(
                embed=error_embed("You can't vouch for a bot."), ephemeral=True
            )
            return
        if await self.cog.bot.db.already_vouched(
            interaction.guild_id, interaction.user.id, target.id, COOLDOWN_HOURS
        ):
            await interaction.response.send_message(
                embed=error_embed(
                    f"You've already vouched for {target.mention} in the last "
                    f"{COOLDOWN_HOURS} hours."
                ),
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            VouchMessageModal(self.cog, target, self.giveaway_id)
        )


class VouchUserView(discord.ui.View):
    def __init__(self, cog: "Vouch", giveaway_id: int | None):
        super().__init__(timeout=300)
        self.add_item(VouchUserSelect(cog, giveaway_id))


class VouchButton(discord.ui.View):
    """Persistent button attached to giveaway claim tickets."""

    def __init__(self, cog: "Vouch"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Vouch", emoji="🤝", style=discord.ButtonStyle.success,
        custom_id=VOUCH_BUTTON_ID,
    )
    async def vouch(self, interaction: discord.Interaction, _: discord.ui.Button):
        ticket = await self.cog.bot.db.ticket_by_channel(interaction.channel_id)
        giveaway_id = ticket.get("giveaway_id") if ticket else None

        await interaction.response.send_message(
            embed=base_embed(
                "🤝 Leave a vouch",
                "Pick the person you're vouching for, then write your message.",
                accent=BLUE,
            ),
            view=VouchUserView(self.cog, giveaway_id),
            ephemeral=True,
        )


class Vouch(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(VouchButton(self))

    # ------------------------------------------------------------ commands

    @app_commands.command(name="vouch", description="Vouch for someone")
    @app_commands.describe(user="Who you're vouching for", message="Why")
    @app_commands.guild_only()
    async def vouch(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        message: str | None = None,
    ):
        await interaction.response.defer(ephemeral=True)

        if user.id == interaction.user.id:
            await interaction.followup.send(
                embed=error_embed("You can't vouch for yourself."), ephemeral=True
            )
            return
        if user.bot:
            await interaction.followup.send(
                embed=error_embed("You can't vouch for a bot."), ephemeral=True
            )
            return
        if await self.bot.db.already_vouched(
            interaction.guild_id, interaction.user.id, user.id, COOLDOWN_HOURS
        ):
            await interaction.followup.send(
                embed=error_embed(
                    f"You've already vouched for {user.mention} in the last "
                    f"{COOLDOWN_HOURS} hours."
                ),
                ephemeral=True,
            )
            return

        ok, detail = await post_vouch(
            self.bot,
            interaction.guild,
            interaction.user,
            user,
            (message or "")[:MAX_MESSAGE] or None,
        )
        if not ok:
            await interaction.followup.send(embed=error_embed(detail), ephemeral=True)
            return

        await interaction.followup.send(
            embed=base_embed(
                "✅ Vouch posted", f"Posted in {detail}.", accent=YELLOW
            ),
            ephemeral=True,
        )

    @app_commands.command(name="vouches", description="See someone's vouches")
    @app_commands.describe(user="Whose vouches to show (defaults to you)")
    @app_commands.guild_only()
    async def vouches(
        self, interaction: discord.Interaction, user: discord.Member | None = None
    ):
        await interaction.response.defer()
        user = user or interaction.user

        total = await self.bot.db.vouch_count(interaction.guild_id, user.id)
        rows = await self.bot.db.vouches_for(interaction.guild_id, user.id, limit=10)

        embed = base_embed(f"🤝 Vouches for {user.display_name}", accent=YELLOW)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Total", value=str(total), inline=True)

        if rows:
            embed.add_field(
                name="Recent",
                value="\n".join(
                    f"<@{r['from_user']}> · <t:{int(r['created_at'])}:R>"
                    + (f"\n> {r['message'][:120]}" if r["message"] else "")
                    for r in rows
                )[:1024],
                inline=False,
            )
        else:
            embed.description = "No vouches yet."
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="vouchtop", description="Most vouched members")
    @app_commands.guild_only()
    async def vouchtop(self, interaction: discord.Interaction):
        await interaction.response.defer()
        rows = await self.bot.db.vouch_leaderboard(interaction.guild_id, 10)

        if not rows:
            await interaction.followup.send(
                embed=base_embed("🤝 No vouches yet", "Be the first with `/vouch`.")
            )
            return

        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        embed = base_embed("🤝 Most vouched", accent=YELLOW)
        embed.description = "\n".join(
            f"{medals.get(i, f'`#{i}`')} <@{r['user_id']}> — **{r['count']}**"
            for i, r in enumerate(rows, 1)
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="vouchchannel", description="Set where vouches are posted")
    @app_commands.describe(channel="Channel for vouches")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def vouchchannel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        perms = channel.permissions_for(interaction.guild.me)
        if not perms.send_messages:
            await interaction.response.send_message(
                embed=error_embed(f"I can't post in {channel.mention}."), ephemeral=True
            )
            return

        await self.bot.db.set_settings(interaction.guild_id, vouch_channel=channel.id)
        await interaction.response.send_message(
            embed=base_embed("✅ Vouch channel set", f"Vouches now go to {channel.mention}.")
        )

    @app_commands.command(name="vouchdelete", description="Remove a vouch (staff)")
    @app_commands.describe(vouch_id="ID shown in the vouch record")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def vouchdelete(self, interaction: discord.Interaction, vouch_id: int):
        if await self.bot.db.delete_vouch(interaction.guild_id, vouch_id):
            await interaction.response.send_message(
                embed=base_embed(
                    "🗑️ Vouch removed",
                    f"Record #{vouch_id} deleted. The posted message stays.",
                    accent=PINK,
                )
            )
        else:
            await interaction.response.send_message(
                embed=error_embed(f"No vouch #{vouch_id} in this server."), ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Vouch(bot))
