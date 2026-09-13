"""DonutDuck — a multi-purpose DonutSMP Discord bot.

Run with:  python -m donutduck.bot
"""

from __future__ import annotations

import asyncio
import logging
import os

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

from .scraper import DonutStats
from .cogs.private import PRIVATE_GUILD_ID
from .db import Database
from .ddns import FreeDNSUpdater
from .twitch import TwitchClient
from .web import Dashboard
from .utils import error_embed

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
log = logging.getLogger("donutduck")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")  # optional: instant command sync while developing
DB_PATH = os.getenv("DB_PATH", "donutduck.db")
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")

# Dashboard + dynamic DNS
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DASHBOARD_BASE_URL = os.getenv("DASHBOARD_BASE_URL")
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))
DASHBOARD_SECRET = os.getenv("DASHBOARD_SECRET")
FREEDNS_UPDATE_URL = os.getenv("FREEDNS_UPDATE_URL")

COGS = (
    "donutduck.cogs.player",
    "donutduck.cogs.auction",
    "donutduck.cogs.leaderboard",
    "donutduck.cogs.tracking",
    "donutduck.cogs.partner",
    "donutduck.cogs.commands",
    "donutduck.cogs.tickets",
    "donutduck.cogs.giveaways",
    "donutduck.cogs.vouch",
    "donutduck.cogs.staff",
    "donutduck.cogs.minigames",
    "donutduck.cogs.scripts",
    "donutduck.cogs.docs",
    "donutduck.cogs.streams",
    "donutduck.cogs.server",
    "donutduck.cogs.utility",
    "donutduck.cogs.applications",
    "donutduck.cogs.profile",
    "donutduck.cogs.private",
    "donutduck.cogs.general",
)


class DonutDuck(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=discord.Intents.default(),
            help_command=None,
            activity=discord.Game("DonutSMP • /help"),
        )
        self.api = DonutStats()
        self.db = Database(DB_PATH)
        self.twitch = TwitchClient(TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET)
        self.ddns = FreeDNSUpdater(FREEDNS_UPDATE_URL)
        self.dashboard = Dashboard(
            self,
            client_id=DISCORD_CLIENT_ID,
            client_secret=DISCORD_CLIENT_SECRET,
            base_url=DASHBOARD_BASE_URL,
            secret_key=DASHBOARD_SECRET,
            port=DASHBOARD_PORT,
        )

    async def setup_hook(self) -> None:
        await self.api.start()
        await self.db.connect()
        log.info("Database ready at %s", DB_PATH)
        await self.dashboard.start()
        if self.ddns.configured:
            self.ddns_loop.start()
            log.info("FreeDNS updater enabled")
        if self.twitch.configured:
            log.info("Twitch credentials found; live notifications enabled")
        else:
            log.info(
                "No Twitch credentials; /twitch commands will explain setup. "
                "Get them free at https://dev.twitch.tv/console/apps"
            )
        for cog in COGS:
            await self.load_extension(cog)
            log.info("Loaded %s", cog)

        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d commands to dev guild %s", len(synced), GUILD_ID)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d global commands (may take ~1h to appear)", len(synced))

        # The private cog's commands are bound to one guild and need their own
        # sync. Skipped when it's also the dev guild, since that sync covered it.
        if str(PRIVATE_GUILD_ID) != (GUILD_ID or ""):
            try:
                private = await self.tree.sync(guild=discord.Object(id=PRIVATE_GUILD_ID))
                log.info(
                    "Synced %d private command(s) to guild %s", len(private), PRIVATE_GUILD_ID
                )
            except discord.Forbidden:
                # Almost always means the bot isn't in that server. Not fatal —
                # every other command works, so carry on rather than dying here.
                log.warning(
                    "Couldn't sync private commands: the bot isn't in guild %s "
                    "(or lacks applications.commands there). /player1bal, /player2bal, "
                    "/player3bal and /balhis will be unavailable until it's invited. "
                    "Everything else is unaffected.",
                    PRIVATE_GUILD_ID,
                )
            except discord.HTTPException as exc:
                log.warning("Private command sync failed (%s); continuing.", exc)

    @tasks.loop(minutes=10)
    async def ddns_loop(self):
        changed, message = await self.ddns.update()
        if changed:
            log.info("FreeDNS: %s", message)

    @ddns_loop.before_loop
    async def before_ddns(self):
        await self.wait_until_ready()

    async def on_ready(self):
        log.info("Logged in as %s (%s)", self.user, self.user.id)
        log.info("Serving %d guild(s)", len(self.guilds))

    async def on_guild_remove(self, guild: discord.Guild):
        """Kicked or left — stop partnering and tracking for that server."""
        await self.db.set_config(guild.id, partners_enabled=0)
        log.info("Left guild %s; partnering disabled", guild.id)

    async def close(self):
        await self.api.close()
        await self.twitch.close()
        await self.dashboard.stop()
        await self.ddns.close()
        await self.db.close()
        await super().close()


bot = DonutDuck()


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: Exception):
    log.exception("Command error", exc_info=error)
    embed = error_embed(
        "That command hit an unexpected error. Try again in a moment."
    )
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except discord.HTTPException:
        pass


def main() -> None:
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set. Copy .env.example to .env.")
    bot.run(DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        asyncio.run(bot.close())
