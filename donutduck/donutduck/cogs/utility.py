"""Everyday Discord utilities: polls, reminders, an embed builder and info
commands.

Polls use Discord's native poll object (discord.py 2.4+) rather than a
reaction hack, so results are tallied by Discord itself and can't be skewed by
someone adding extra reactions.
"""

from __future__ import annotations

import datetime
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..theme import BLUE, PINK, YELLOW
from ..utils import base_embed, error_embed

log = logging.getLogger("donutduck.utility")

DURATION_RE = re.compile(r"(\d+)\s*([smhdw])", re.IGNORECASE)
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(text: str) -> int | None:
    matches = DURATION_RE.findall(text or "")
    if not matches:
        return None
    return sum(int(n) * UNIT_SECONDS[u.lower()] for n, u in matches) or None


class Utility(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.reminder_loop.start()

    async def cog_unload(self):
        self.reminder_loop.cancel()

    # ----------------------------------------------------------- reminders

    @tasks.loop(seconds=30)
    async def reminder_loop(self):
        try:
            due = await self.bot.db.due_reminders()
        except Exception:
            log.exception("Couldn't read reminders")
            return

        for reminder in due:
            await self.bot.db.complete_reminder(reminder["id"])
            channel = self.bot.get_channel(reminder["channel_id"])
            embed = base_embed(
                "⏰ Reminder",
                reminder["text"],
                accent=YELLOW,
            )
            embed.set_footer(
                text=f"Set <t:{int(reminder['created_at'])}:R>".replace("<t:", "").replace(":R>", "")
                or "DonutDuck"
            )
            try:
                if channel:
                    await channel.send(content=f"<@{reminder['user_id']}>", embed=embed)
                else:
                    user = await self.bot.fetch_user(reminder["user_id"])
                    await user.send(embed=embed)
            except discord.HTTPException:
                log.info("Couldn't deliver reminder %s", reminder["id"])

    @reminder_loop.before_loop
    async def before_reminders(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="remind", description="Set a reminder")
    @app_commands.describe(
        when="How long from now, e.g. 30m, 2h, 3d, 1d12h", text="What to remind you about"
    )
    async def remind(self, interaction: discord.Interaction, when: str, text: str):
        seconds = parse_duration(when)
        if seconds is None:
            await interaction.response.send_message(
                embed=error_embed("Use a form like `30m`, `2h`, `3d` or `1d12h`."),
                ephemeral=True,
            )
            return
        if seconds < 30:
            await interaction.response.send_message(
                embed=error_embed("Minimum is 30 seconds."), ephemeral=True
            )
            return
        if seconds > 365 * 86400:
            await interaction.response.send_message(
                embed=error_embed("Maximum is a year."), ephemeral=True
            )
            return

        remind_at = datetime.datetime.now().timestamp() + seconds
        reminder_id = await self.bot.db.add_reminder(
            interaction.guild_id, interaction.channel_id, interaction.user.id, text, remind_at
        )
        await interaction.response.send_message(
            embed=base_embed(
                "⏰ Reminder set",
                f"I'll ping you <t:{int(remind_at)}:R> about:\n>>> {text}",
                accent=YELLOW,
            ).set_footer(text=f"Reminder #{reminder_id} • cancel with /reminders")
        )

    @app_commands.command(name="reminders", description="List or cancel your reminders")
    @app_commands.describe(cancel="Reminder number to cancel")
    async def reminders(self, interaction: discord.Interaction, cancel: int | None = None):
        if cancel is not None:
            if await self.bot.db.cancel_reminder(cancel, interaction.user.id):
                await interaction.response.send_message(
                    embed=base_embed("🗑️ Cancelled", f"Reminder #{cancel} removed.", accent=PINK),
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    embed=error_embed("That isn't one of your pending reminders."),
                    ephemeral=True,
                )
            return

        rows = await self.bot.db.user_reminders(interaction.user.id)
        if not rows:
            await interaction.response.send_message(
                embed=base_embed("⏰ No reminders", "Set one with `/remind`."), ephemeral=True
            )
            return

        embed = base_embed(f"⏰ Your reminders — {len(rows)}")
        embed.description = "\n".join(
            f"**#{r['id']}** <t:{int(r['remind_at'])}:R> — {r['text'][:80]}" for r in rows[:15]
        )
        embed.set_footer(text="Cancel with /reminders cancel:<number>")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --------------------------------------------------------------- polls

    @app_commands.command(name="poll", description="Create a poll")
    @app_commands.describe(
        question="What you're asking",
        options="Answers separated by | (2–10)",
        hours="How long it runs",
        multiple="Allow picking more than one answer",
    )
    @app_commands.guild_only()
    async def poll(
        self,
        interaction: discord.Interaction,
        question: str,
        options: str,
        hours: app_commands.Range[int, 1, 768] = 24,
        multiple: bool = False,
    ):
        answers = [o.strip() for o in options.split("|") if o.strip()][:10]
        if len(answers) < 2:
            await interaction.response.send_message(
                embed=error_embed("Give at least two options, separated by `|`."),
                ephemeral=True,
            )
            return

        # Discord's own poll object: it does the tallying, so nobody can skew
        # results by piling on reactions.
        poll = discord.Poll(
            question=question[:300],
            duration=datetime.timedelta(hours=hours),
            multiple=multiple,
        )
        for answer in answers:
            poll.add_answer(text=answer[:55])

        try:
            await interaction.response.send_message(poll=poll)
        except discord.HTTPException as exc:
            await interaction.response.send_message(
                embed=error_embed(f"Couldn't create the poll: {exc}"), ephemeral=True
            )

    # ------------------------------------------------------------- embeds

    @app_commands.command(name="embed", description="Post a custom embed as the bot")
    @app_commands.describe(
        title="Embed title",
        description="Body text (use \\n for line breaks)",
        colour="blue, pink or yellow",
        channel="Where to post it",
        image="Image URL",
    )
    @app_commands.choices(
        colour=[
            app_commands.Choice(name="Blue", value="blue"),
            app_commands.Choice(name="Pink", value="pink"),
            app_commands.Choice(name="Yellow", value="yellow"),
        ]
    )
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def embed_cmd(
        self,
        interaction: discord.Interaction,
        title: str,
        description: str,
        colour: app_commands.Choice[str] | None = None,
        channel: discord.TextChannel | None = None,
        image: str | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        target = channel or interaction.channel
        palette = {"blue": BLUE, "pink": PINK, "yellow": YELLOW}
        accent = palette.get(colour.value if colour else "blue", BLUE)

        embed = base_embed(title, description.replace("\\n", "\n"), accent=accent)
        if image:
            if not image.startswith(("http://", "https://")):
                await interaction.followup.send(
                    embed=error_embed("Image must be a http(s) URL.")
                )
                return
            embed.set_image(url=image)

        try:
            await target.send(embed=embed)
        except discord.Forbidden:
            await interaction.followup.send(
                embed=error_embed(f"I can't post in {target.mention}.")
            )
            return
        await interaction.followup.send(
            embed=base_embed("✅ Posted", f"Sent to {target.mention}.")
        )

    # --------------------------------------------------------------- info

    @app_commands.command(name="serverinfo", description="Stats about this Discord server")
    @app_commands.guild_only()
    async def serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild
        embed = base_embed(f"📊 {guild.name}")
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="Members", value=f"{guild.member_count:,}", inline=True)
        embed.add_field(name="Channels", value=str(len(guild.channels)), inline=True)
        embed.add_field(name="Roles", value=str(len(guild.roles)), inline=True)
        embed.add_field(
            name="Created", value=f"<t:{int(guild.created_at.timestamp())}:D>", inline=True
        )
        embed.add_field(name="Owner", value=f"<@{guild.owner_id}>", inline=True)
        embed.add_field(name="Boosts", value=str(guild.premium_subscription_count), inline=True)

        counts = await self.bot.db.guild_counts(guild.id)
        embed.add_field(
            name="DonutDuck here",
            value=(
                f"🎫 {counts['open_tickets']} open tickets ({counts['total_tickets']} all time)\n"
                f"🎉 {counts['active_giveaways']} running giveaways\n"
                f"📋 {counts['pending_applications']} pending applications\n"
                f"📈 {counts['trackers']} stat trackers · 🟣 {counts['streams']} streamers"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="userinfo", description="Info about a member")
    @app_commands.describe(member="Who to look up (defaults to you)")
    @app_commands.guild_only()
    async def userinfo(
        self, interaction: discord.Interaction, member: discord.Member | None = None
    ):
        member = member or interaction.user
        embed = base_embed(f"👤 {member.display_name}", accent=str(member.id))
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Tag", value=str(member), inline=True)
        embed.add_field(name="ID", value=str(member.id), inline=True)
        embed.add_field(
            name="Account created",
            value=f"<t:{int(member.created_at.timestamp())}:R>",
            inline=True,
        )
        if member.joined_at:
            embed.add_field(
                name="Joined server",
                value=f"<t:{int(member.joined_at.timestamp())}:R>",
                inline=True,
            )
        roles = [r.mention for r in reversed(member.roles) if r.name != "@everyone"]
        embed.add_field(
            name=f"Roles ({len(roles)})",
            value=" ".join(roles[:15]) or "none",
            inline=False,
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Utility(bot))
