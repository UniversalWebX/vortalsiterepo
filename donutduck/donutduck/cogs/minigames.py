"""Two minigames: guess the number, and higher or lower.

Both keep their state in memory on purpose — a game is a few minutes long and
losing one to a restart costs nothing, whereas giving every round a database
row would be a lot of writes for something disposable.
"""

from __future__ import annotations

import logging
import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from ..theme import BLUE, PINK, YELLOW
from ..utils import base_embed, error_embed

log = logging.getLogger("donutduck.games")

GAME_TTL = 1800  # abandoned games are swept after 30 minutes

CARD_NAMES = {
    1: "A", 11: "J", 12: "Q", 13: "K",
}


def card_name(value: int) -> str:
    return CARD_NAMES.get(value, str(value))


class GuessModal(discord.ui.Modal, title="Guess the number"):
    guess = discord.ui.TextInput(label="Your guess", required=True, max_length=12)

    def __init__(self, view: "GuessView"):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.guess.value.strip().replace(",", "")
        if not raw.lstrip("-").isdigit():
            await interaction.response.send_message(
                embed=error_embed("That isn't a whole number."), ephemeral=True
            )
            return
        await self.view_ref.handle_guess(interaction, int(raw))


class GuessView(discord.ui.View):
    """Guess the number. Anyone can play; guesses are public so the hints
    help everyone — that's what makes it a group game rather than a race."""

    def __init__(self, cog: "Minigames", low: int, high: int, host: discord.Member):
        super().__init__(timeout=GAME_TTL)
        self.cog = cog
        self.low = low
        self.high = high
        self.host = host
        self.answer = random.randint(low, high)
        self.attempts: dict[int, int] = {}
        self.finished = False
        self.message: discord.Message | None = None
        self.started = time.time()
        log.debug("Guess game started, answer %s", self.answer)

    @discord.ui.button(label="Guess", emoji="🔢", style=discord.ButtonStyle.primary)
    async def guess_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        if self.finished:
            await interaction.response.send_message(
                embed=error_embed("This game is over."), ephemeral=True
            )
            return
        await interaction.response.send_modal(GuessModal(self))

    async def handle_guess(self, interaction: discord.Interaction, value: int):
        if self.finished:
            await interaction.response.send_message(
                embed=error_embed("Someone just won this round."), ephemeral=True
            )
            return

        self.attempts[interaction.user.id] = self.attempts.get(interaction.user.id, 0) + 1
        total = sum(self.attempts.values())

        if value == self.answer:
            self.finished = True
            for child in self.children:
                child.disabled = True

            embed = base_embed(
                "🎯 Correct!",
                f"{interaction.user.mention} guessed **{self.answer}**.",
                accent=YELLOW,
            )
            embed.add_field(name="Range", value=f"{self.low}–{self.high}", inline=True)
            embed.add_field(name="Total guesses", value=str(total), inline=True)
            embed.add_field(
                name="Their guesses",
                value=str(self.attempts[interaction.user.id]),
                inline=True,
            )
            await interaction.response.send_message(embed=embed)
            if self.message:
                try:
                    await self.message.edit(view=self)
                except discord.HTTPException:
                    pass
            self.cog.games.pop(self.message.id if self.message else 0, None)
            self.stop()
            return

        if value < self.low or value > self.high:
            hint = f"Out of range — it's between **{self.low}** and **{self.high}**."
        elif value < self.answer:
            hint = f"**{value}** is too low. ⬆️"
        else:
            hint = f"**{value}** is too high. ⬇️"

        await interaction.response.send_message(
            embed=base_embed("🔢 " + hint, accent=BLUE), ephemeral=False
        )


class HigherLowerView(discord.ui.View):
    """Higher or lower, single player, streak-based. One wrong call ends it,
    which is what makes a long streak worth anything."""

    def __init__(self, cog: "Minigames", player: discord.Member):
        super().__init__(timeout=GAME_TTL)
        self.cog = cog
        self.player = player
        self.current = random.randint(1, 13)
        self.streak = 0
        self.best = 0
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player.id:
            await interaction.response.send_message(
                "Start your own game with `/higherlower`.", ephemeral=True
            )
            return False
        return True

    def embed(self, note: str | None = None) -> discord.Embed:
        embed = base_embed(
            "🃏 Higher or Lower",
            note or f"Current card: **{card_name(self.current)}**\nWill the next be higher or lower?",
            accent=YELLOW,
        )
        embed.add_field(name="Streak", value=str(self.streak), inline=True)
        embed.add_field(name="Best", value=str(self.best), inline=True)
        embed.set_footer(text="Cards run A (1) to K (13) • equal counts as a win")
        return embed

    async def _play(self, interaction: discord.Interaction, higher: bool):
        nxt = random.randint(1, 13)
        # A tie goes to the player: otherwise a repeat card ends a good streak
        # on something they had no way to call.
        correct = (nxt >= self.current) if higher else (nxt <= self.current)
        previous = self.current
        self.current = nxt

        if correct:
            self.streak += 1
            self.best = max(self.best, self.streak)
            note = (
                f"**{card_name(previous)}** → **{card_name(nxt)}** — correct!\n\n"
                f"Next card: **{card_name(nxt)}**. Higher or lower?"
            )
            await interaction.response.edit_message(embed=self.embed(note), view=self)
            return

        for child in self.children:
            child.disabled = True
        embed = base_embed(
            "💥 Wrong",
            f"**{card_name(previous)}** → **{card_name(nxt)}**.\n\n"
            f"Final streak: **{self.streak}**",
            accent=PINK,
        )
        await interaction.response.edit_message(embed=embed, view=self)
        self.cog.games.pop(self.message.id if self.message else 0, None)
        self.stop()

    @discord.ui.button(label="Higher", emoji="⬆️", style=discord.ButtonStyle.success)
    async def higher(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._play(interaction, True)

    @discord.ui.button(label="Lower", emoji="⬇️", style=discord.ButtonStyle.danger)
    async def lower(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._play(interaction, False)

    @discord.ui.button(label="Cash out", emoji="🏁", style=discord.ButtonStyle.secondary)
    async def stop_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            embed=base_embed(
                "🏁 Finished",
                f"You stopped on a streak of **{self.streak}**.",
                accent=BLUE,
            ),
            view=self,
        )
        self.stop()


class Minigames(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.games: dict[int, discord.ui.View] = {}

    @app_commands.command(name="guessnumber", description="Start a guess-the-number game")
    @app_commands.describe(low="Lowest possible number", high="Highest possible number")
    @app_commands.guild_only()
    async def guessnumber(
        self,
        interaction: discord.Interaction,
        low: int = 1,
        high: int = 100,
    ):
        if high - low < 1:
            await interaction.response.send_message(
                embed=error_embed("The range needs at least two numbers in it."),
                ephemeral=True,
            )
            return
        if high - low > 1_000_000:
            await interaction.response.send_message(
                embed=error_embed("Keep the range under a million — nobody will win."),
                ephemeral=True,
            )
            return

        view = GuessView(self, low, high, interaction.user)
        embed = base_embed(
            "🔢 Guess the number",
            f"I'm thinking of a number between **{low}** and **{high}**.\n"
            "Press **Guess** — hints are public, so everyone can help narrow it down.",
            accent=YELLOW,
        )
        embed.set_footer(text=f"Started by {interaction.user.display_name}")

        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()
        self.games[view.message.id] = view

    @app_commands.command(name="higherlower", description="Play higher or lower")
    @app_commands.guild_only()
    async def higherlower(self, interaction: discord.Interaction):
        view = HigherLowerView(self, interaction.user)
        await interaction.response.send_message(embed=view.embed(), view=view)
        view.message = await interaction.original_response()
        self.games[view.message.id] = view


async def setup(bot: commands.Bot):
    await bot.add_cog(Minigames(bot))
