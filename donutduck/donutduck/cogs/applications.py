"""Application system for staff and other roles.

Discord modals allow at most 5 inputs, which is too few for a real staff
application. This splits a form into pages of 5: submitting a page stores the
answers and offers a "Continue" button that opens the next modal. A modal
can't be opened directly from another modal's submit, but it *can* be opened
from a button click, which is what makes the chain work. Up to 25 questions.

Partial answers live in memory and are dropped after 30 minutes, so an
abandoned half-finished application doesn't linger.

Submitted applications go to a review channel with Accept/Deny buttons.
Accepting can assign a role automatically; either decision DMs the applicant.
Review buttons are persistent, so a restart doesn't leave dead pending
applications.

This is separate from the ticket system's staff-application *type*: tickets
open a private channel for a conversation, whereas this is a structured form
with a decision attached. Servers usually want one or the other — disable the
ticket type with `/tickettype toggle staff false` if you use this instead.
"""

from __future__ import annotations

import json
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

from ..theme import BLUE, PINK, YELLOW
from ..utils import base_embed, error_embed, resolve_member

log = logging.getLogger("donutduck.applications")

PAGE_SIZE = 5           # Discord's hard limit on modal inputs
MAX_QUESTIONS = 25      # 5 pages
DRAFT_TTL = 1800        # 30 minutes

ACCEPT_ID = "dd:app:accept"
DENY_ID = "dd:app:deny"

DEFAULT_QUESTIONS = [
    "How old are you, and what timezone are you in?",
    "What is your Minecraft IGN?",
    "How many hours per week can you be active?",
    "Do you have previous staff experience? Where, and for how long?",
    "Why do you want to join our staff team?",
    "How would you handle a player breaking rules in chat?",
    "How would you handle a report about a friend of yours?",
    "Is there anything else we should know?",
]


def parse_questions(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        return [str(q) for q in json.loads(raw)][:MAX_QUESTIONS]
    except (json.JSONDecodeError, TypeError):
        return []


class ApplicationModal(discord.ui.Modal):
    """One page of a form."""

    def __init__(self, cog: "Applications", form: dict, questions: list[str], page: int):
        total_pages = (len(questions) + PAGE_SIZE - 1) // PAGE_SIZE
        title = form["label"][:35]
        if total_pages > 1:
            title = f"{title} ({page + 1}/{total_pages})"[:45]
        super().__init__(title=title)

        self.cog = cog
        self.form = form
        self.questions = questions
        self.page = page

        start = page * PAGE_SIZE
        self.page_questions = questions[start : start + PAGE_SIZE]
        self.inputs: list[discord.ui.TextInput] = []

        for question in self.page_questions:
            field = discord.ui.TextInput(
                label=question[:45],
                # Modal labels truncate at 45 chars, so long questions are
                # repeated in full as placeholder text.
                placeholder=question[:100] if len(question) > 45 else None,
                style=discord.TextStyle.paragraph,
                max_length=900,
                required=True,
            )
            self.inputs.append(field)
            self.add_item(field)

    async def on_submit(self, interaction: discord.Interaction):
        answers = self.cog.get_draft(interaction.user.id, self.form["key"])
        for question, field in zip(self.page_questions, self.inputs):
            answers[question] = field.value
        self.cog.save_draft(interaction.user.id, self.form["key"], answers)

        next_page = self.page + 1
        if next_page * PAGE_SIZE < len(self.questions):
            remaining = len(self.questions) - len(answers)
            view = ContinueView(self.cog, self.form, self.questions, next_page)
            await interaction.response.send_message(
                embed=base_embed(
                    f"📝 Saved — {len(answers)}/{len(self.questions)} answered",
                    f"{remaining} question(s) to go. Press Continue.",
                    accent=BLUE,
                ),
                view=view,
                ephemeral=True,
            )
            return

        await self.cog.submit(interaction, self.form, answers)


class ContinueView(discord.ui.View):
    """Bridges two modals: a modal can't open another modal on submit, but a
    button can."""

    def __init__(self, cog: "Applications", form: dict, questions: list[str], page: int):
        super().__init__(timeout=DRAFT_TTL)
        self.cog = cog
        self.form = form
        self.questions = questions
        self.page = page

    @discord.ui.button(label="Continue", style=discord.ButtonStyle.primary, emoji="➡️")
    async def continue_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(
            ApplicationModal(self.cog, self.form, self.questions, self.page)
        )
        self.stop()


class DenyReasonModal(discord.ui.Modal, title="Deny application"):
    reason = discord.ui.TextInput(
        label="Reason (sent to the applicant)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=900,
        placeholder="Optional, but usually kinder than silence.",
    )

    def __init__(self, cog: "Applications", application_id: int):
        super().__init__()
        self.cog = cog
        self.application_id = application_id

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.decide(
            interaction, self.application_id, "denied", self.reason.value or None
        )


class ReviewView(discord.ui.View):
    """Accept/Deny buttons on the review post. The application id is encoded in
    the custom_id so the view works after a restart with no state."""

    def __init__(self, cog: "Applications", application_id: int | None = None):
        super().__init__(timeout=None)
        self.cog = cog
        if application_id is not None:
            self.accept.custom_id = f"{ACCEPT_ID}:{application_id}"
            self.deny.custom_id = f"{DENY_ID}:{application_id}"

    @staticmethod
    def application_id_from(interaction: discord.Interaction) -> int | None:
        custom_id = (interaction.data or {}).get("custom_id", "")
        parts = custom_id.split(":")
        return int(parts[-1]) if parts and parts[-1].isdigit() else None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "Only staff with **Manage Server** can review applications.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Accept", style=discord.ButtonStyle.success, emoji="✅", custom_id=ACCEPT_ID
    )
    async def accept(self, interaction: discord.Interaction, _: discord.ui.Button):
        application_id = self.application_id_from(interaction)
        if application_id is None:
            await interaction.response.send_message(
                embed=error_embed("This review post is missing its application id."),
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        await self.cog.decide(interaction, application_id, "accepted", None, deferred=True)

    @discord.ui.button(
        label="Deny", style=discord.ButtonStyle.danger, emoji="✖️", custom_id=DENY_ID
    )
    async def deny(self, interaction: discord.Interaction, _: discord.ui.Button):
        application_id = self.application_id_from(interaction)
        if application_id is None:
            await interaction.response.send_message(
                embed=error_embed("This review post is missing its application id."),
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(DenyReasonModal(self.cog, application_id))


class Applications(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # (user_id, form_key) -> (expires_at, answers)
        self._drafts: dict[tuple[int, str], tuple[float, dict]] = {}

    async def cog_load(self):
        self.bot.add_view(ReviewView(self))

    # -------------------------------------------------------------- drafts

    def _sweep(self) -> None:
        now = time.time()
        for key, (expires, _) in list(self._drafts.items()):
            if expires < now:
                del self._drafts[key]

    def get_draft(self, user_id: int, form_key: str) -> dict:
        self._sweep()
        entry = self._drafts.get((user_id, form_key))
        return dict(entry[1]) if entry else {}

    def save_draft(self, user_id: int, form_key: str, answers: dict) -> None:
        self._drafts[(user_id, form_key)] = (time.time() + DRAFT_TTL, answers)

    def clear_draft(self, user_id: int, form_key: str) -> None:
        self._drafts.pop((user_id, form_key), None)

    # ---------------------------------------------------------- submission

    async def submit(
        self, interaction: discord.Interaction, form: dict, answers: dict
    ) -> None:
        self.clear_draft(interaction.user.id, form["key"])

        application_id = await self.bot.db.create_application(
            interaction.guild_id, form["key"], interaction.user.id, json.dumps(answers)
        )

        review_channel = self.bot.get_channel(form["review_channel"] or 0)
        if review_channel is None:
            await interaction.response.send_message(
                embed=error_embed(
                    "Your application was saved, but staff haven't set a review "
                    "channel yet — please let them know."
                ),
                ephemeral=True,
            )
            return

        embed = base_embed(
            f"📋 {form['label']} · #{application_id}",
            accent=YELLOW,
        )
        embed.set_author(
            name=str(interaction.user), icon_url=interaction.user.display_avatar.url
        )
        embed.add_field(name="Applicant", value=interaction.user.mention, inline=True)
        embed.add_field(
            name="Account age",
            value=f"<t:{int(interaction.user.created_at.timestamp())}:R>",
            inline=True,
        )
        member = interaction.guild.get_member(interaction.user.id)
        if member and member.joined_at:
            embed.add_field(
                name="Joined server",
                value=f"<t:{int(member.joined_at.timestamp())}:R>",
                inline=True,
            )

        # Embeds cap at 25 fields and 1024 chars per field.
        for question, answer in list(answers.items())[:20]:
            embed.add_field(name=question[:256], value=(answer or "—")[:1024], inline=False)
        embed.set_footer(text=f"Application #{application_id} • DonutDuck")

        try:
            message = await review_channel.send(
                embed=embed, view=ReviewView(self, application_id)
            )
            await self.bot.db.set_application_message(application_id, message.id)
        except discord.HTTPException as exc:
            log.warning("Couldn't post application %s: %s", application_id, exc)

        await interaction.response.send_message(
            embed=base_embed(
                "✅ Application submitted",
                f"Thanks — your **{form['label']}** application (#{application_id}) "
                "is with the staff team. You'll get a DM with the decision.",
                accent=BLUE,
            ),
            ephemeral=True,
        )

    async def decide(
        self,
        interaction: discord.Interaction,
        application_id: int,
        status: str,
        reason: str | None,
        deferred: bool = False,
    ) -> None:
        async def respond(**kwargs):
            if deferred or interaction.response.is_done():
                return await interaction.followup.send(ephemeral=True, **kwargs)
            return await interaction.response.send_message(ephemeral=True, **kwargs)

        application = await self.bot.db.get_application(application_id)
        if application is None:
            await respond(embed=error_embed("That application no longer exists."))
            return
        if application["status"] != "pending":
            await respond(
                embed=error_embed(
                    f"Already {application['status']} by <@{application['reviewer_id']}>."
                )
            )
            return

        ok = await self.bot.db.decide_application(
            application_id, status, interaction.user.id, reason
        )
        if not ok:
            await respond(embed=error_embed("Someone else just reviewed this one."))
            return

        form = await self.bot.db.get_form(interaction.guild_id, application["form_key"])
        applicant = await resolve_member(interaction.guild, application["user_id"])

        role_note = ""
        if status == "accepted" and form and form["accept_role"] and applicant:
            role = interaction.guild.get_role(form["accept_role"])
            if role:
                try:
                    await applicant.add_roles(role, reason=f"Application #{application_id}")
                    role_note = f"\nGave them {role.mention}."
                except discord.Forbidden:
                    role_note = (
                        f"\n⚠️ Couldn't give them {role.mention} — my role needs to be "
                        "above it in the role list."
                    )
                except discord.HTTPException:
                    role_note = f"\n⚠️ Couldn't give them {role.mention}."

        # Tell the applicant either way.
        dm_failed = False
        if applicant:
            label = form["label"] if form else "application"
            if status == "accepted":
                dm = base_embed(
                    "✅ Application accepted",
                    f"Your **{label}** in **{interaction.guild.name}** was accepted. "
                    "Welcome aboard!",
                    accent=BLUE,
                )
            else:
                dm = base_embed(
                    "Application update",
                    f"Your **{label}** in **{interaction.guild.name}** wasn't accepted "
                    "this time." + (f"\n\n**Reason:** {reason}" if reason else ""),
                    accent=PINK,
                )
                if form and form["cooldown_days"]:
                    dm.set_footer(
                        text=f"You can reapply in {form['cooldown_days']} days"
                    )
            try:
                await applicant.send(embed=dm)
            except discord.HTTPException:
                dm_failed = True

        # Update the review post so the decision is visible in context.
        if application["message_id"]:
            channel = self.bot.get_channel(
                (form or {}).get("review_channel") or interaction.channel_id
            )
            if channel:
                try:
                    message = await channel.fetch_message(application["message_id"])
                    embed = message.embeds[0] if message.embeds else discord.Embed()
                    embed.color = BLUE if status == "accepted" else PINK
                    embed.add_field(
                        name="Decision",
                        value=(
                            f"{'✅ Accepted' if status == 'accepted' else '✖️ Denied'} by "
                            f"{interaction.user.mention} <t:{int(time.time())}:R>"
                            + (f"\n**Reason:** {reason}" if reason else "")
                        ),
                        inline=False,
                    )
                    await message.edit(embed=embed, view=None)
                except discord.HTTPException:
                    pass

        summary = f"Application #{application_id} {status}.{role_note}"
        if dm_failed:
            summary += "\n⚠️ Couldn't DM them — their DMs are closed."
        await respond(
            embed=base_embed(
                "✅ Reviewed" if status == "accepted" else "✖️ Reviewed",
                summary,
                accent=BLUE if status == "accepted" else PINK,
            )
        )

    # ------------------------------------------------------------ /apply

    async def form_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        forms = await self.bot.db.forms(interaction.guild_id, only_enabled=True)
        return [
            app_commands.Choice(name=f["label"][:100], value=f["key"])
            for f in forms
            if current.lower() in f["key"].lower() or current.lower() in f["label"].lower()
        ][:25]

    @app_commands.command(name="apply", description="Apply for a position")
    @app_commands.describe(form="Which application to fill in")
    @app_commands.autocomplete(form=form_autocomplete)
    @app_commands.guild_only()
    async def apply(self, interaction: discord.Interaction, form: str):
        form_row = await self.bot.db.get_form(interaction.guild_id, form)

        if form_row is None or not form_row["enabled"]:
            await interaction.response.send_message(
                embed=error_embed("That application isn't open right now."), ephemeral=True
            )
            return

        questions = parse_questions(form_row["questions"])
        if not questions:
            await interaction.response.send_message(
                embed=error_embed("That form has no questions set yet."), ephemeral=True
            )
            return

        pending = await self.bot.db.pending_application(
            interaction.guild_id, form, interaction.user.id
        )
        if pending:
            await interaction.response.send_message(
                embed=error_embed(
                    f"You already have a pending **{form_row['label']}** "
                    f"(#{pending['id']}). Please wait for a decision."
                ),
                ephemeral=True,
            )
            return

        last = await self.bot.db.last_application(interaction.guild_id, form, interaction.user.id)
        if last and last["status"] == "denied" and form_row["cooldown_days"]:
            elapsed = time.time() - (last["decided_at"] or last["created_at"])
            cooldown = form_row["cooldown_days"] * 86400
            if elapsed < cooldown:
                ready_at = int((last["decided_at"] or last["created_at"]) + cooldown)
                await interaction.response.send_message(
                    embed=error_embed(
                        f"You can apply again <t:{ready_at}:R>."
                    ),
                    ephemeral=True,
                )
                return

        self.clear_draft(interaction.user.id, form)
        await interaction.response.send_modal(
            ApplicationModal(self, form_row, questions, 0)
        )

    # ------------------------------------------------- form administration

    group = app_commands.Group(
        name="application",
        description="Manage application forms",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @group.command(name="setup", description="Create a staff application with default questions")
    @app_commands.describe(
        review_channel="Where submitted applications are posted",
        accept_role="Role given automatically on acceptance",
    )
    async def setup_cmd(
        self,
        interaction: discord.Interaction,
        review_channel: discord.TextChannel,
        accept_role: discord.Role | None = None,
    ):
        created = await self.bot.db.add_form(
            interaction.guild_id,
            "staff",
            "Staff Application",
            description="Apply to join the staff team",
            emoji="🛡️",
            questions=json.dumps(DEFAULT_QUESTIONS),
            review_channel=review_channel.id,
            accept_role=accept_role.id if accept_role else None,
        )
        if not created:
            await self.bot.db.update_form(
                interaction.guild_id,
                "staff",
                review_channel=review_channel.id,
                accept_role=accept_role.id if accept_role else None,
            )

        embed = base_embed(
            "✅ Staff application ready" if created else "✅ Staff application updated",
            f"Members can now run `/apply form:staff` — {len(DEFAULT_QUESTIONS)} questions "
            f"across {(len(DEFAULT_QUESTIONS) + PAGE_SIZE - 1) // PAGE_SIZE} pages.",
        )
        embed.add_field(name="Reviews go to", value=review_channel.mention, inline=True)
        if accept_role:
            embed.add_field(name="Role on accept", value=accept_role.mention, inline=True)
        embed.add_field(
            name="Next",
            value=(
                "`/application questions` to change the questions\n"
                "`/application create` to add another form (e.g. Partner Manager)"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed)

    @group.command(name="create", description="Create another application form")
    @app_commands.describe(
        key="Short id used with /apply, e.g. 'pm'",
        label="Display name",
        review_channel="Where submissions are posted",
        questions="Questions separated by | (up to 25)",
        accept_role="Role given on acceptance",
        cooldown_days="Days before a denied applicant may reapply",
    )
    async def create(
        self,
        interaction: discord.Interaction,
        key: str,
        label: str,
        review_channel: discord.TextChannel,
        questions: str,
        accept_role: discord.Role | None = None,
        cooldown_days: app_commands.Range[int, 0, 365] = 14,
    ):
        key = key.lower().strip().replace(" ", "-")[:20]
        question_list = [q.strip() for q in questions.split("|") if q.strip()]

        if not question_list:
            await interaction.response.send_message(
                embed=error_embed("Give at least one question, separated by `|`."),
                ephemeral=True,
            )
            return
        if len(question_list) > MAX_QUESTIONS:
            await interaction.response.send_message(
                embed=error_embed(
                    f"That's {len(question_list)} questions; the maximum is "
                    f"{MAX_QUESTIONS} (5 modal pages of 5)."
                ),
                ephemeral=True,
            )
            return

        created = await self.bot.db.add_form(
            interaction.guild_id,
            key,
            label,
            questions=json.dumps(question_list),
            review_channel=review_channel.id,
            accept_role=accept_role.id if accept_role else None,
            cooldown_days=cooldown_days,
        )
        if not created:
            await interaction.response.send_message(
                embed=error_embed(f"A form with key `{key}` already exists."), ephemeral=True
            )
            return

        pages = (len(question_list) + PAGE_SIZE - 1) // PAGE_SIZE
        embed = base_embed(
            "✅ Form created",
            f"**{label}** — `/apply form:{key}`",
        )
        embed.add_field(
            name="Questions", value=f"{len(question_list)} across {pages} page(s)", inline=True
        )
        embed.add_field(name="Reviews", value=review_channel.mention, inline=True)
        embed.add_field(name="Reapply after", value=f"{cooldown_days} days", inline=True)
        await interaction.response.send_message(embed=embed)

    @group.command(name="questions", description="Replace a form's questions")
    @app_commands.describe(key="Form key", questions="Separated by | (up to 25)")
    @app_commands.autocomplete(key=form_autocomplete)
    async def questions_cmd(
        self, interaction: discord.Interaction, key: str, questions: str
    ):
        question_list = [q.strip() for q in questions.split("|") if q.strip()]
        if not question_list or len(question_list) > MAX_QUESTIONS:
            await interaction.response.send_message(
                embed=error_embed(f"Give between 1 and {MAX_QUESTIONS} questions."),
                ephemeral=True,
            )
            return

        ok = await self.bot.db.update_form(
            interaction.guild_id, key, questions=json.dumps(question_list)
        )
        if not ok:
            await interaction.response.send_message(
                embed=error_embed(f"No form with key `{key}`."), ephemeral=True
            )
            return

        body = "\n".join(f"{i}. {q}" for i, q in enumerate(question_list, 1))
        await interaction.response.send_message(
            embed=base_embed(f"✅ Questions for `{key}`", body[:4000])
        )

    @group.command(name="toggle", description="Open or close applications")
    @app_commands.describe(key="Form key", open="Whether it accepts submissions")
    @app_commands.autocomplete(key=form_autocomplete)
    async def toggle(self, interaction: discord.Interaction, key: str, open: bool):
        ok = await self.bot.db.update_form(
            interaction.guild_id, key, enabled=1 if open else 0
        )
        if not ok:
            await interaction.response.send_message(
                embed=error_embed(f"No form with key `{key}`."), ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=base_embed(
                f"{'🟢 Applications open' if open else '🔴 Applications closed'}",
                f"`{key}` is now {'accepting' if open else 'not accepting'} submissions.",
                accent=BLUE if open else PINK,
            )
        )

    @group.command(name="delete", description="Delete an application form")
    @app_commands.describe(key="Form key")
    @app_commands.autocomplete(key=form_autocomplete)
    async def delete(self, interaction: discord.Interaction, key: str):
        if await self.bot.db.delete_form(interaction.guild_id, key):
            await interaction.response.send_message(
                embed=base_embed(
                    "🗑️ Deleted",
                    f"Removed `{key}`. Past submissions are kept.",
                    accent=PINK,
                )
            )
        else:
            await interaction.response.send_message(
                embed=error_embed(f"No form with key `{key}`."), ephemeral=True
            )

    @group.command(name="list", description="Show this server's application forms")
    async def list_cmd(self, interaction: discord.Interaction):
        forms = await self.bot.db.forms(interaction.guild_id)
        if not forms:
            await interaction.response.send_message(
                embed=error_embed("No forms yet — run `/application setup`."), ephemeral=True
            )
            return

        embed = base_embed(f"📋 Application forms — {len(forms)}")
        for form in forms:
            questions = parse_questions(form["questions"])
            pending = await self.bot.db.list_applications(
                interaction.guild_id, "pending", form["key"]
            )
            embed.add_field(
                name=f"{form['emoji'] or '📋'} {form['label']} (`{form['key']}`)",
                value=(
                    f"{'🟢 open' if form['enabled'] else '🔴 closed'} · "
                    f"{len(questions)} question(s) · {len(pending)} pending\n"
                    f"Reviews: <#{form['review_channel']}>"
                    + (f" · Role: <@&{form['accept_role']}>" if form["accept_role"] else "")
                ),
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="applications", description="List pending applications")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def applications(self, interaction: discord.Interaction):
        rows = await self.bot.db.list_applications(interaction.guild_id, "pending")
        if not rows:
            await interaction.response.send_message(
                embed=base_embed("📋 No pending applications", "All caught up.")
            )
            return

        embed = base_embed(f"📋 Pending applications — {len(rows)}", accent=YELLOW)
        embed.description = "\n".join(
            f"**#{row['id']}** `{row['form_key']}` · <@{row['user_id']}> · "
            f"<t:{int(row['created_at'])}:R>"
            for row in rows[:20]
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Applications(bot))
