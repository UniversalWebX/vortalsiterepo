"""A button paginator that fetches pages lazily from the API."""

from __future__ import annotations

from typing import Awaitable, Callable

import discord

from .scraper import DonutAPIError
from .utils import error_embed

PageFetcher = Callable[[int], Awaitable[discord.Embed | None]]


class PageView(discord.ui.View):
    """Pages are fetched on demand; `fetch(page)` returns None when empty."""

    def __init__(self, fetch: PageFetcher, owner_id: int, page: int = 1, timeout: float = 180.0):
        super().__init__(timeout=timeout)
        self.fetch = fetch
        self.owner_id = owner_id
        self.page = page
        self.message: discord.Message | None = None
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        self.prev_page.disabled = self.page <= 1
        self.jump.label = f"Page {self.page}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Run the command yourself to flip through pages.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    async def _go(self, interaction: discord.Interaction, page: int) -> None:
        await interaction.response.defer()
        try:
            embed = await self.fetch(page)
        except DonutAPIError as exc:
            await interaction.followup.send(embed=error_embed(str(exc)), ephemeral=True)
            return

        if embed is None:
            await interaction.followup.send(
                "That's the end of the results.", ephemeral=True
            )
            return

        self.page = page
        self._refresh_buttons()
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._go(interaction, max(1, self.page - 1))

    @discord.ui.button(label="Page 1", style=discord.ButtonStyle.primary, disabled=True)
    async def jump(self, interaction: discord.Interaction, _: discord.ui.Button):
        pass

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._go(interaction, self.page + 1)

    @discord.ui.button(label="✕", style=discord.ButtonStyle.danger)
    async def close(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.defer()
        if self.message:
            await self.message.delete()
        self.stop()
