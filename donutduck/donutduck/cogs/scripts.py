"""STScript custom commands: `/stscript` to author, `/st` to run.

The interpreter (stscript.py) never touches Discord — it returns a list of
requested actions. This cog decides which ones are permitted. That split is
deliberate: permission logic lives here, where it can see the guild and the
member, and the language stays a pure function that's easy to reason about.

Two rules that matter:

* Only staff may create or edit scripts. Script text is effectively bot
  behaviour, and a script can ping, DM and hand out roles.
* `role add` only works if the *script's author* had Manage Roles, and the
  target role sits below the bot. A script can't be used to escalate.
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from ..permissions import is_staff, staff_only
from ..stscript import (
    HELP_TEXT,
    MAX_ACTIONS,
    MAX_LINES,
    Action,
    Interpreter,
    STError,
    parse,
)
from ..theme import BLUE, PINK
from ..utils import base_embed, error_embed

log = logging.getLogger("donutduck.stscript")

EXAMPLE = """say Hello {user.name}! 👋
random roll from 1 to 6
if {roll} >= 4
  say You rolled {roll} — lucky!
else
  say You rolled {roll} — better luck next time.
end"""


class CodeModal(discord.ui.Modal):
    """Slash-command options can't hold newlines, so code is entered here."""

    def __init__(self, cog: "Scripts", name: str, existing: str = "", script_id=None):
        super().__init__(title=f"{'Edit' if script_id else 'New'} script: {name}"[:45])
        self.cog = cog
        self.script_name = name
        self.script_id = script_id

        self.code = discord.ui.TextInput(
            label="STScript code",
            style=discord.TextStyle.paragraph,
            default=existing or EXAMPLE,
            max_length=4000,
            required=True,
        )
        self.add_item(self.code)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        source = self.code.value

        # Parse now so mistakes surface at save time, not when someone runs it.
        try:
            parse(source)
        except STError as exc:
            await interaction.followup.send(
                embed=error_embed(str(exc), title="Script has an error"), ephemeral=True
            )
            return

        if self.script_id:
            await self.cog.bot.db.update_script(
                interaction.guild_id, self.script_id, code=source
            )
            script_id = self.script_id
            title = "✅ Script updated"
        else:
            script_id = await self.cog.bot.db.add_script(
                interaction.guild_id, self.script_name, source, interaction.user.id
            )
            if script_id is None:
                await interaction.followup.send(
                    embed=error_embed(f"A script called `{self.script_name}` exists."),
                    ephemeral=True,
                )
                return
            title = "✅ Script saved"

        embed = base_embed(
            title, f"Run it with `/st {script_id}` or `/st {self.script_name}`."
        )
        embed.add_field(
            name="Code", value=f"```\n{source[:900]}\n```", inline=False
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


class Scripts(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._running: set[int] = set()

    # --------------------------------------------------------- execution

    async def perform(
        self,
        interaction: discord.Interaction,
        actions: list[Action],
        author_can_manage_roles: bool,
    ) -> list[str]:
        """Carry out the interpreter's requested actions. Returns warnings."""
        warnings: list[str] = []
        sent_first = False

        for action in actions:
            if action.kind == "wait":
                await asyncio.sleep(min(action.data["seconds"], 10))
                continue

            if action.kind == "say":
                content = action.data["text"]
                ephemeral = action.data.get("ephemeral", False)
                # Scripts never ping roles or @everyone — a custom command is
                # not a good place to hand out mass mentions.
                mentions = discord.AllowedMentions(
                    everyone=False, roles=False, users=True
                )
                if not sent_first:
                    await interaction.followup.send(
                        content, ephemeral=ephemeral, allowed_mentions=mentions
                    )
                    sent_first = True
                else:
                    await interaction.followup.send(
                        content, ephemeral=ephemeral, allowed_mentions=mentions
                    )
                continue

            if action.kind == "embed":
                embed = base_embed(
                    action.data["title"] or None, action.data["body"] or None
                )
                await interaction.followup.send(embed=embed)
                sent_first = True
                continue

            if action.kind == "dm":
                try:
                    await interaction.user.send(action.data["text"])
                except discord.HTTPException:
                    warnings.append("Couldn't DM you — your DMs are closed.")
                continue

            if action.kind == "role":
                if not author_can_manage_roles:
                    warnings.append(
                        "Skipped a `role` step: the script's author doesn't have "
                        "Manage Roles."
                    )
                    continue

                ref = action.data["role"].strip().strip("<@&>")
                role = None
                if ref.isdigit():
                    role = interaction.guild.get_role(int(ref))
                if role is None:
                    role = discord.utils.get(interaction.guild.roles, name=ref)
                if role is None:
                    warnings.append(f"No role matching `{ref}`.")
                    continue
                if role >= interaction.guild.me.top_role:
                    warnings.append(f"`{role.name}` is above my highest role.")
                    continue

                try:
                    if action.data["action"] == "add":
                        await interaction.user.add_roles(role, reason="STScript")
                    else:
                        await interaction.user.remove_roles(role, reason="STScript")
                except discord.HTTPException:
                    warnings.append(f"Couldn't change `{role.name}`.")

        return warnings

    # ------------------------------------------------------------- /st

    async def script_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        scripts = await self.bot.db.scripts(interaction.guild_id)
        query = current.lower()
        return [
            app_commands.Choice(
                name=f"#{s['id']} · {s['name']}"[:100], value=str(s["id"])
            )
            for s in scripts
            if s["enabled"] and (not query or query in s["name"].lower() or query == str(s["id"]))
        ][:25]

    @app_commands.command(name="st", description="Run a custom STScript command")
    @app_commands.describe(script="Script ID or name", args="Text passed as {args}")
    @app_commands.autocomplete(script=script_autocomplete)
    @app_commands.guild_only()
    async def st(
        self, interaction: discord.Interaction, script: str, args: str | None = None
    ):
        row = await self.bot.db.get_script(interaction.guild_id, script)
        if row is None:
            await interaction.response.send_message(
                embed=error_embed(
                    f"No script `{script}` here. `/stscript list` shows them all."
                ),
                ephemeral=True,
            )
            return
        if not row["enabled"]:
            await interaction.response.send_message(
                embed=error_embed(f"`{row['name']}` is disabled."), ephemeral=True
            )
            return
        if row["staff_only"] and not await is_staff(self.bot, interaction.user):
            await interaction.response.send_message(
                embed=error_embed("That script is staff-only."), ephemeral=True
            )
            return

        # One run per person at a time — scripts can wait, and overlapping runs
        # would let one person multiply their own rate limit.
        if interaction.user.id in self._running:
            await interaction.response.send_message(
                embed=error_embed("You already have a script running."), ephemeral=True
            )
            return

        await interaction.response.defer()
        self._running.add(interaction.user.id)
        try:
            words = (args or "").split()
            variables = {
                "user": interaction.user.mention,
                "user.name": interaction.user.display_name,
                "user.id": str(interaction.user.id),
                "server": interaction.guild.name,
                "channel": interaction.channel.name,
                "args": args or "",
                "argcount": len(words),
            }
            for index, word in enumerate(words[:10], 1):
                variables[f"arg{index}"] = word

            interpreter = Interpreter(variables)
            actions = interpreter.run(parse(row["code"]))
        except STError as exc:
            await interaction.followup.send(
                embed=error_embed(
                    f"{exc}\n\nThe script's author can fix it with "
                    f"`/stscript edit script:{row['id']}`.",
                    title=f"Error in `{row['name']}`",
                )
            )
            self._running.discard(interaction.user.id)
            return
        except Exception:
            log.exception("Script %s crashed", row["id"])
            await interaction.followup.send(
                embed=error_embed("That script failed to run.")
            )
            self._running.discard(interaction.user.id)
            return

        author = interaction.guild.get_member(row["created_by"])
        can_roles = bool(author and author.guild_permissions.manage_roles)

        try:
            warnings = await self.perform(interaction, actions, can_roles)
        finally:
            self._running.discard(interaction.user.id)

        await self.bot.db.bump_script(row["id"])

        if not actions:
            await interaction.followup.send(
                embed=base_embed(
                    "✅ Script ran", "It didn't produce any output.", accent=BLUE
                )
            )
        if warnings:
            await interaction.followup.send(
                embed=error_embed("\n".join(f"• {w}" for w in warnings), title="Notes"),
                ephemeral=True,
            )

    # ------------------------------------------------------- /stscript

    group = app_commands.Group(
        name="stscript", description="Write custom bot commands", guild_only=True
    )

    @group.command(name="create", description="Write a new script")
    @app_commands.describe(name="Short name used with /st")
    @staff_only()
    async def create(self, interaction: discord.Interaction, name: str):
        name = name.lower().strip().replace(" ", "-")[:32]
        if not name.replace("-", "").replace("_", "").isalnum():
            await interaction.response.send_message(
                embed=error_embed("Names may use letters, numbers, dashes and underscores."),
                ephemeral=True,
            )
            return

        existing = await self.bot.db.get_script(interaction.guild_id, name)
        if existing:
            await interaction.response.send_message(
                embed=error_embed(
                    f"`{name}` already exists (#{existing['id']}). Use "
                    f"`/stscript edit script:{existing['id']}`."
                ),
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(CodeModal(self, name))

    @group.command(name="edit", description="Change a script's code")
    @app_commands.describe(script="Script ID or name")
    @app_commands.autocomplete(script=script_autocomplete)
    @staff_only()
    async def edit(self, interaction: discord.Interaction, script: str):
        row = await self.bot.db.get_script(interaction.guild_id, script)
        if row is None:
            await interaction.response.send_message(
                embed=error_embed(f"No script `{script}`."), ephemeral=True
            )
            return
        await interaction.response.send_modal(
            CodeModal(self, row["name"], row["code"], row["id"])
        )

    @group.command(name="list", description="All scripts in this server")
    async def list_cmd(self, interaction: discord.Interaction):
        scripts = await self.bot.db.scripts(interaction.guild_id)
        if not scripts:
            await interaction.response.send_message(
                embed=base_embed(
                    "📜 No scripts yet",
                    "Staff can write one with `/stscript create`. "
                    "`/stscript help` explains the language.",
                )
            )
            return

        embed = base_embed(f"📜 Scripts — {len(scripts)}")
        for row in scripts[:20]:
            flags = []
            if not row["enabled"]:
                flags.append("disabled")
            if row["staff_only"]:
                flags.append("staff only")
            embed.add_field(
                name=f"#{row['id']} · {row['name']}",
                value=(
                    f"{row['description'] or '*no description*'}\n"
                    f"`/st {row['id']}` · used {row['uses']}×"
                    + (f" · _{', '.join(flags)}_" if flags else "")
                ),
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @group.command(name="show", description="View a script's code")
    @app_commands.describe(script="Script ID or name")
    @app_commands.autocomplete(script=script_autocomplete)
    async def show(self, interaction: discord.Interaction, script: str):
        row = await self.bot.db.get_script(interaction.guild_id, script)
        if row is None:
            await interaction.response.send_message(
                embed=error_embed(f"No script `{script}`."), ephemeral=True
            )
            return

        embed = base_embed(f"📜 #{row['id']} · {row['name']}", row["description"])
        embed.add_field(
            name="Code", value=f"```\n{row['code'][:1000]}\n```", inline=False
        )
        embed.add_field(name="Author", value=f"<@{row['created_by']}>", inline=True)
        embed.add_field(name="Uses", value=str(row["uses"]), inline=True)
        await interaction.response.send_message(embed=embed)

    @group.command(name="delete", description="Delete a script")
    @app_commands.describe(script="Script ID or name")
    @app_commands.autocomplete(script=script_autocomplete)
    @staff_only()
    async def delete(self, interaction: discord.Interaction, script: str):
        if await self.bot.db.delete_script(interaction.guild_id, script):
            await interaction.response.send_message(
                embed=base_embed("🗑️ Deleted", f"`{script}` removed.", accent=PINK)
            )
        else:
            await interaction.response.send_message(
                embed=error_embed(f"No script `{script}`."), ephemeral=True
            )

    @group.command(name="settings", description="Enable, disable or restrict a script")
    @app_commands.describe(
        script="Script ID or name",
        enabled="Whether it can be run",
        staff_only_flag="Restrict it to staff",
        description="Short description for the list",
    )
    @app_commands.autocomplete(script=script_autocomplete)
    @staff_only()
    async def settings(
        self,
        interaction: discord.Interaction,
        script: str,
        enabled: bool | None = None,
        staff_only_flag: bool | None = None,
        description: str | None = None,
    ):
        fields = {}
        if enabled is not None:
            fields["enabled"] = 1 if enabled else 0
        if staff_only_flag is not None:
            fields["staff_only"] = 1 if staff_only_flag else 0
        if description is not None:
            fields["description"] = description

        if not fields:
            await interaction.response.send_message(
                embed=error_embed("Give me something to change."), ephemeral=True
            )
            return

        if await self.bot.db.update_script(interaction.guild_id, script, **fields):
            await interaction.response.send_message(
                embed=base_embed(
                    "✅ Updated",
                    "Changed: " + ", ".join(f"`{k}`" for k in fields),
                )
            )
        else:
            await interaction.response.send_message(
                embed=error_embed(f"No script `{script}`."), ephemeral=True
            )

    @group.command(name="help", description="How to write STScript")
    async def help_cmd(self, interaction: discord.Interaction):
        embed = base_embed(
            "📜 STScript",
            "Scratch-style custom commands. Write one with `/stscript create`, "
            "run it with `/st <id>`.",
        )
        for chunk in HELP_TEXT.split("\n\n"):
            heading, _, body = chunk.partition("\n")
            embed.add_field(name=heading.replace("**", ""), value=body, inline=False)
        embed.add_field(
            name="Example",
            value=f"```\n{EXAMPLE}\n```",
            inline=False,
        )
        embed.set_footer(
            text=f"Limits: {MAX_LINES} lines, {MAX_ACTIONS} messages, 5s runtime"
        )
        await interaction.response.send_message(embed=embed)

    @group.command(name="test", description="Run a script without saving it")
    @app_commands.describe(code="One line, or use \\n between lines")
    @staff_only()
    async def test(self, interaction: discord.Interaction, code: str):
        await interaction.response.defer(ephemeral=True)
        source = code.replace("\\n", "\n")

        try:
            variables = {
                "user": interaction.user.mention,
                "user.name": interaction.user.display_name,
                "user.id": str(interaction.user.id),
                "server": interaction.guild.name,
                "channel": interaction.channel.name,
                "args": "",
                "argcount": 0,
            }
            actions = Interpreter(variables).run(parse(source))
        except STError as exc:
            await interaction.followup.send(
                embed=error_embed(str(exc), title="Error"), ephemeral=True
            )
            return

        preview = "\n".join(
            f"**{a.kind}** — {str(a.data)[:120]}" for a in actions
        ) or "*no output*"
        await interaction.followup.send(
            embed=base_embed(
                "✅ Parsed and ran",
                f"{len(actions)} action(s):\n{preview[:3000]}",
                accent=BLUE,
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Scripts(bot))
