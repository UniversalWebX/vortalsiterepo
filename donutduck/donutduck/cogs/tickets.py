"""Ticket system.

Four types are seeded per server the first time tickets are set up: two staff
applications (general Staff and Partner Manager), Support, and Giveaway Claim.
More can be added at runtime with `/tickettype add` — a type is just a row, so
new ones need no code.

Giveaway Claim is marked `hidden`, meaning it never appears on the public
panel; the giveaway cog opens it automatically for each winner.

Panels and in-ticket buttons use fixed custom_ids and are registered as
persistent views on startup, so they keep working after a restart.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

from ..permissions import (
    is_staff as _is_staff,
    staff_overwrites,
    staff_role_objects,
)
from ..theme import BLUE, PINK, YELLOW
from ..utils import base_embed, error_embed, resolve_member

log = logging.getLogger("donutduck.tickets")

PANEL_SELECT_ID = "dd:ticket:select"
CLOSE_ID = "dd:ticket:close"
CLAIM_ID = "dd:ticket:claim"
ACTIONS_ID = "dd:ticket:actions"

MAX_QUESTIONS = 5  # Discord modals allow at most five inputs

# Seeded on first `/ticketsetup`. is_builtin types can be disabled but not
# deleted, so a server can't lose the giveaway-claim plumbing by accident.
DEFAULT_TYPES = [
    {
        "key": "staff",
        "label": "Staff Application",
        "emoji": "🛡️",
        "description": "Apply to join the staff team",
        "is_builtin": 1,
        "position": 0,
        "questions": [
            "How old are you, and what timezone are you in?",
            "How many hours a week can you be active?",
            "What's your Minecraft IGN?",
            "Do you have previous staff experience? Where?",
            "Why do you want to be staff here?",
        ],
    },
    {
        "key": "pm",
        "label": "Partner Manager Application",
        "emoji": "🤝",
        "description": "Apply to be a Partner Manager",
        "is_builtin": 1,
        "position": 1,
        "questions": [
            "How old are you, and what timezone are you in?",
            "What experience do you have managing partnerships?",
            "Which servers have you partnered with before?",
            "How many hours a week can you commit?",
            "Why should we pick you as a Partner Manager?",
        ],
    },
    {
        "key": "support",
        "label": "Support",
        "emoji": "🎫",
        "description": "Get help from the staff team",
        "is_builtin": 1,
        "position": 2,
        "questions": [
            "What do you need help with?",
            "What's your Minecraft IGN?",
        ],
    },
    {
        "key": "giveaway-claim",
        "label": "Giveaway Claim",
        "emoji": "🎁",
        "description": "Claim a giveaway prize",
        "is_builtin": 1,
        "hidden": 1,
        "position": 3,
        "questions": [],
    },
]


def type_color(key: str) -> int:
    return {"staff": BLUE, "pm": PINK, "support": YELLOW, "giveaway-claim": YELLOW}.get(
        key, BLUE
    )


def derive_reason(
    ticket_type: dict, answers: dict | None, fallback: str | None = None
) -> str:
    """The one-line 'why is this ticket open' shown in the index.

    Preference order: an explicit reason passed in (giveaway claims), then the
    applicant's first answer (the first question is almost always "what do you
    need"), then the type's own description, then its label. Something is
    always returned, so the index never has a blank row.
    """
    if fallback:
        return fallback[:200]
    if answers:
        # Prefer the answer to whichever question actually asks *why*. On a
        # support form that's question one, but on an application form question
        # one is usually age/timezone, which makes a useless index entry.
        keywords = (
            "need help",
            "reason",
            "why",
            "issue",
            "problem",
            "what do you",
            "describe",
        )
        chosen = ""
        for question, answer in answers.items():
            if any(word in question.lower() for word in keywords) and str(answer).strip():
                chosen = answer
                break
        # Single-question forms have no ambiguity, so use the only answer.
        if not chosen and len(answers) == 1:
            only = next(iter(answers.values()), "")
            if str(only).strip():
                chosen = only
        if chosen:
            return " ".join(str(chosen).split())[:200]
    return (ticket_type.get("description") or ticket_type.get("label") or "No reason given")[:200]


def render_open(
    template: str,
    *,
    user,
    number: int,
    ticket_type: dict,
    reason: str,
    guild,
    staff_mention: str = "",
) -> str:
    """Substitute placeholders in a custom opening message.

    Literal \n typed into a slash command arrives as two characters, so it's
    turned into a real newline here — otherwise custom messages come out as
    one long line.
    """
    return (
        (template or "")
        .replace("\\n", "\n")
        .replace("{user}", getattr(user, "mention", str(user)))
        .replace("{name}", getattr(user, "display_name", str(user)))
        .replace("{tag}", str(user))
        .replace("{ticket}", f"{number:04d}")
        .replace("{type}", ticket_type.get("label", ""))
        .replace("{reason}", reason or "")
        .replace("{server}", getattr(guild, "name", ""))
        .replace("{staff}", staff_mention)
    )[:4000]


def open_embed(
    ticket_type: dict,
    number: int,
    user,
    reason: str,
    answers: dict | None,
    guild,
    staff_mention: str = "",
) -> discord.Embed:
    """The first message in a new ticket.

    Uses the type's custom title/body/colour/image when set, and falls back to
    the standard layout otherwise, so a server that never touches these
    settings sees exactly what it saw before.
    """
    palette = {"blue": BLUE, "pink": PINK, "yellow": YELLOW}
    accent = palette.get(
        (ticket_type.get("open_color") or "").lower(), type_color(ticket_type["key"])
    )

    default_title = f"{ticket_type.get('emoji') or '🎫'} {ticket_type['label']} · #{number:04d}"
    title = ticket_type.get("open_title") or default_title
    title = render_open(
        title,
        user=user,
        number=number,
        ticket_type=ticket_type,
        reason=reason,
        guild=guild,
        staff_mention=staff_mention,
    )[:256]

    body = ticket_type.get("open_message")
    description = (
        render_open(
            body,
            user=user,
            number=number,
            ticket_type=ticket_type,
            reason=reason,
            guild=guild,
            staff_mention=staff_mention,
        )
        if body
        else None
    )

    embed = base_embed(title, description, accent=accent)
    embed.add_field(name="Opened by", value=getattr(user, "mention", str(user)), inline=True)
    embed.add_field(name="Opened", value=f"<t:{int(time.time())}:R>", inline=True)
    embed.add_field(name="Reason", value=reason or "No reason given", inline=False)

    if answers and ticket_type.get("show_answers", 1):
        for question, answer in list(answers.items())[:MAX_QUESTIONS]:
            embed.add_field(name=question[:256], value=(answer or "—")[:1024], inline=False)

    if ticket_type.get("open_image"):
        embed.set_image(url=ticket_type["open_image"])

    footer = ticket_type.get("open_footer") or "Staff will be with you shortly • DonutDuck"
    embed.set_footer(text=footer[:2048])
    return embed


def index_embed(ticket_type: dict, number: int, reason: str, user) -> discord.Embed:
    """Pinned at the top of every ticket. Because it's a real message in the
    channel it also lands in the transcript body, not just the file header."""
    embed = base_embed(
        f"🧾 Ticket index · #{number:04d}",
        accent=type_color(ticket_type["key"]),
    )
    embed.add_field(name="Type", value=ticket_type["label"], inline=True)
    embed.add_field(name="Opened by", value=getattr(user, "mention", str(user)), inline=True)
    embed.add_field(name="Opened", value=f"<t:{int(time.time())}:f>", inline=True)
    embed.add_field(name="Reason", value=reason or "No reason given", inline=False)
    embed.set_footer(text="This index is included in the transcript • DonutDuck")
    return embed


def parse_questions(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return [str(q) for q in data][:MAX_QUESTIONS]
    except (json.JSONDecodeError, TypeError):
        return []


async def build_transcript(channel: discord.TextChannel, ticket: dict) -> discord.File:
    """Plain-text log of the channel, oldest first."""
    def stamp(value):
        return (
            time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(value)) if value else "—"
        )

    guild = channel.guild
    opener = guild.get_member(ticket["user_id"])
    closer = guild.get_member(ticket["closed_by"]) if ticket.get("closed_by") else None
    claimer = guild.get_member(ticket["claimed_by"]) if ticket.get("claimed_by") else None

    lines = [
        "=" * 64,
        "TICKET INDEX",
        "=" * 64,
        f"Ticket      : #{ticket['number']:04d}",
        f"Type        : {ticket['type_key']}",
        f"Reason      : {ticket.get('reason') or 'No reason given'}",
        f"Opened by   : {opener or 'unknown'} ({ticket['user_id']})",
        f"Opened at   : {stamp(ticket['created_at'])}",
        f"Claimed by  : {claimer or '—'}",
        f"Closed by   : {closer or '—'}",
        f"Closed at   : {stamp(ticket.get('closed_at'))}",
        f"Close reason: {ticket.get('close_reason') or '—'}",
    ]
    if ticket.get("ign"):
        lines.append(f"IGN         : {ticket['ign']}")
    if ticket.get("giveaway_id"):
        lines.append(f"Giveaway    : #{ticket['giveaway_id']}")
    lines += ["=" * 64, ""]

    if ticket.get("answers"):
        try:
            answers = json.loads(ticket["answers"])
            lines.append("SUBMITTED ANSWERS")
            lines.append("-" * 64)
            for question, answer in answers.items():
                lines.append(f"Q: {question}\nA: {answer}\n")
            lines.append("=" * 64 + "\n")
        except (json.JSONDecodeError, AttributeError):
            pass

    lines.append("CONVERSATION")
    lines.append("-" * 64)

    participants: dict[str, int] = {}
    count = 0
    try:
        async for message in channel.history(limit=2000, oldest_first=True):
            when = message.created_at.strftime("%Y-%m-%d %H:%M")
            content = message.clean_content or ""
            if message.embeds and not content:
                content = "[embed]"
            if message.attachments:
                content += " " + " ".join(a.url for a in message.attachments)
            lines.append(f"[{when}] {message.author}: {content}")
            participants[str(message.author)] = participants.get(str(message.author), 0) + 1
            count += 1
    except discord.HTTPException:
        lines.append("(couldn't read full history)")

    lines += [
        "",
        "=" * 64,
        f"SUMMARY: {count} message(s) from {len(participants)} participant(s)",
    ]
    for who, sent in sorted(participants.items(), key=lambda kv: -kv[1]):
        lines.append(f"  {who}: {sent}")
    lines.append("=" * 64)

    data = io.BytesIO("\n".join(lines).encode("utf-8"))
    return discord.File(data, filename=f"ticket-{ticket['number']:04d}.txt")


class QuestionModal(discord.ui.Modal):
    """Built at runtime from a type's question list."""

    def __init__(self, cog: "Tickets", ticket_type: dict, questions: list[str]):
        super().__init__(title=f"{ticket_type['label']}"[:45])
        self.cog = cog
        self.ticket_type = ticket_type
        self.questions = questions
        self.inputs: list[discord.ui.TextInput] = []

        for question in questions[:MAX_QUESTIONS]:
            field = discord.ui.TextInput(
                label=question[:45],
                placeholder=question[:100] if len(question) > 45 else None,
                style=discord.TextStyle.paragraph,
                max_length=900,
                required=True,
            )
            self.inputs.append(field)
            self.add_item(field)

    async def on_submit(self, interaction: discord.Interaction):
        answers = {q: field.value for q, field in zip(self.questions, self.inputs)}
        await self.cog.open_ticket(
            interaction, self.ticket_type["key"], answers=answers
        )


class TicketPanel(discord.ui.View):
    """A public panel. Persistent — options are rebuilt from the database on
    each interaction, so adding a type doesn't require reposting the panel.

    A server can have several panels (support desk in one channel, staff
    applications in another). Each stores its own subset of ticket types, and
    the panel key rides in the select's custom_id so one persistent view class
    serves them all.
    """

    def __init__(self, cog: "Tickets", panel_key: str | None = None):
        super().__init__(timeout=None)
        self.cog = cog
        if panel_key:
            self.select.custom_id = f"{PANEL_SELECT_ID}:{panel_key}"

    @discord.ui.select(
        custom_id=PANEL_SELECT_ID,
        placeholder="Open a ticket…",
        options=[discord.SelectOption(label="Loading…", value="__none__")],
    )
    async def select(self, interaction: discord.Interaction, select: discord.ui.Select):
        key = select.values[0]
        if key == "__none__":
            await interaction.response.send_message(
                embed=error_embed("This panel needs refreshing — ask staff to run "
                                  "`/ticketpanel` again."),
                ephemeral=True,
            )
            return

        ticket_type = await self.cog.bot.db.get_ticket_type(interaction.guild_id, key)
        if not ticket_type or not ticket_type["enabled"]:
            await interaction.response.send_message(
                embed=error_embed("That ticket type isn't available any more."),
                ephemeral=True,
            )
            return

        questions = parse_questions(ticket_type["questions"])
        if questions:
            await interaction.response.send_modal(
                QuestionModal(self.cog, ticket_type, questions)
            )
        else:
            await interaction.response.defer(ephemeral=True)
            await self.cog.open_ticket(interaction, key, answers=None, deferred=True)


class TicketActions(discord.ui.Select):
    """Less-used ticket actions, tucked into a dropdown so the button row
    stays short."""

    def __init__(self, cog: "Tickets"):
        self.cog = cog
        super().__init__(
            custom_id=ACTIONS_ID,
            placeholder="More actions…",
            options=[
                discord.SelectOption(
                    label="Post transcript",
                    value="transcript",
                    emoji="📄",
                    description="Send the log so far, without closing",
                ),
                discord.SelectOption(
                    label="Show index",
                    value="index",
                    emoji="🧾",
                    description="Re-post the ticket index",
                ),
                discord.SelectOption(
                    label="Mark high priority",
                    value="priority",
                    emoji="🔴",
                    description="Rename the channel to flag it",
                ),
                discord.SelectOption(
                    label="Clear priority",
                    value="normal",
                    emoji="⚪",
                    description="Undo the priority flag",
                ),
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        ticket = await self.cog.bot.db.ticket_by_channel(interaction.channel_id)
        if not ticket:
            await interaction.response.send_message(
                embed=error_embed("This isn't a ticket channel."), ephemeral=True
            )
            return
        if not await self.cog.is_staff(interaction.user, ticket["type_key"]):
            await interaction.response.send_message(
                embed=error_embed("Only staff can use these actions."), ephemeral=True
            )
            return

        choice = self.values[0]

        if choice == "transcript":
            await interaction.response.defer()
            transcript = await build_transcript(interaction.channel, ticket)
            await interaction.followup.send(
                embed=base_embed("📄 Transcript so far", accent=BLUE), file=transcript
            )
            return

        if choice == "index":
            ticket_type = await self.cog.bot.db.get_ticket_type(
                interaction.guild_id, ticket["type_key"]
            ) or {"key": ticket["type_key"], "label": ticket["type_key"]}
            opener = interaction.guild.get_member(ticket["user_id"]) or f"<@{ticket['user_id']}>"
            await interaction.response.send_message(
                embed=index_embed(
                    ticket_type, ticket["number"], ticket.get("reason") or "", opener
                )
            )
            return

        # Priority is expressed in the channel name so it's visible in the
        # sidebar without opening the ticket.
        await interaction.response.defer()
        base = interaction.channel.name.lstrip("🔴-")
        new_name = f"🔴-{base}" if choice == "priority" else base
        try:
            await interaction.channel.edit(name=new_name[:100])
            await interaction.followup.send(
                embed=base_embed(
                    "🔴 Marked high priority" if choice == "priority" else "⚪ Priority cleared",
                    accent=PINK if choice == "priority" else BLUE,
                )
            )
        except discord.Forbidden:
            await interaction.followup.send(
                embed=error_embed("I need Manage Channels to rename this ticket."),
                ephemeral=True,
            )
        except discord.HTTPException:
            await interaction.followup.send(
                embed=error_embed("Discord rate limits channel renames; try later."),
                ephemeral=True,
            )


class TicketControls(discord.ui.View):
    """Buttons plus an action dropdown inside an open ticket."""

    def __init__(self, cog: "Tickets"):
        super().__init__(timeout=None)
        self.cog = cog
        self.add_item(TicketActions(cog))

    @discord.ui.button(
        label="Claim", style=discord.ButtonStyle.primary, emoji="✋", custom_id=CLAIM_ID
    )
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = await self.cog.bot.db.ticket_by_channel(interaction.channel_id)
        if not ticket:
            await interaction.response.send_message(
                embed=error_embed("This isn't a ticket channel."), ephemeral=True
            )
            return

        if not await self.cog.is_staff(interaction.user, ticket["type_key"]):
            await interaction.response.send_message(
                embed=error_embed("Only staff can claim tickets."), ephemeral=True
            )
            return

        await self.cog.bot.db.claim_ticket(interaction.channel_id, interaction.user.id)
        await interaction.response.send_message(
            embed=base_embed(
                "✋ Ticket claimed",
                f"{interaction.user.mention} is handling this ticket.",
                accent=BLUE,
            )
        )

    @discord.ui.button(
        label="Close", style=discord.ButtonStyle.danger, emoji="🔒", custom_id=CLOSE_ID
    )
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = await self.cog.bot.db.ticket_by_channel(interaction.channel_id)
        if not ticket:
            await interaction.response.send_message(
                embed=error_embed("This isn't a ticket channel."), ephemeral=True
            )
            return

        allowed = interaction.user.id == ticket["user_id"] or await self.cog.is_staff(
            interaction.user, ticket["type_key"]
        )
        if not allowed:
            await interaction.response.send_message(
                embed=error_embed("You can't close this ticket."), ephemeral=True
            )
            return

        await interaction.response.defer()
        await self.cog.do_close(interaction.channel, ticket, interaction.user, None)


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        # Persistent views survive restarts because their custom_ids are fixed.
        self.bot.add_view(TicketPanel(self))
        self.bot.add_view(TicketControls(self))

        # Each saved panel's select carries its key in the custom_id, so the
        # base view above doesn't match it. Without registering one view per
        # panel, custom panels would go dead after every restart.
        try:
            for guild in self.bot.guilds:
                for panel in await self.bot.db.panels(guild.id):
                    if panel["message_id"]:
                        self.bot.add_view(
                            TicketPanel(self, panel["key"]),
                            message_id=panel["message_id"],
                        )
        except Exception:
            log.exception("Couldn't restore ticket panel views")

    # ------------------------------------------------------------- helpers

    async def is_staff(self, member: discord.Member, type_key: str | None = None) -> bool:
        """Any configured staff role, any ticket-type role, or Manage Server."""
        return await _is_staff(self.bot, member)

    async def ensure_defaults(self, guild_id: int) -> int:
        added = 0
        for spec in DEFAULT_TYPES:
            payload = dict(spec)
            questions = json.dumps(payload.pop("questions", []))
            if await self.bot.db.add_ticket_type(
                guild_id, questions=questions, **payload
            ):
                added += 1
        return added

    async def panel_embed_and_view(self, guild: discord.Guild, panel: dict | None = None):
        types = [
            t
            for t in await self.bot.db.ticket_types(guild.id, only_enabled=True)
            if not t["hidden"]
        ]

        # A panel may restrict itself to a subset of types.
        wanted = []
        if panel and panel.get("type_keys"):
            try:
                wanted = json.loads(panel["type_keys"])
            except (json.JSONDecodeError, TypeError):
                wanted = []
        if wanted:
            order = {k: i for i, k in enumerate(wanted)}
            types = sorted(
                (t for t in types if t["key"] in order), key=lambda t: order[t["key"]]
            )

        embed = base_embed(
            (panel or {}).get("title") or "🎫 Support & Applications",
            (panel or {}).get("description")
            or "Pick an option below to open a private ticket with the staff team.",
        )
        if types:
            embed.add_field(
                name="Available",
                value="\n".join(
                    f"{t['emoji'] or '•'} **{t['label']}** — {t['description'] or ''}"
                    for t in types
                ),
                inline=False,
            )

        view = TicketPanel(self, (panel or {}).get("key"))
        select = view.children[0]
        if (panel or {}).get("placeholder"):
            select.placeholder = panel["placeholder"][:150]
        select.options = [
            discord.SelectOption(
                label=t["label"][:100],
                value=t["key"],
                description=(t["description"] or "")[:100] or None,
                emoji=t["emoji"] or None,
            )
            for t in types
        ] or [discord.SelectOption(label="No types configured", value="__none__")]
        return embed, view

    # -------------------------------------------------------- opening flow

    async def open_ticket(
        self,
        interaction: discord.Interaction,
        type_key: str,
        answers: dict | None = None,
        deferred: bool = False,
        *,
        for_user: discord.Member | None = None,
        giveaway_id: int | None = None,
        reason: str | None = None,
    ) -> discord.TextChannel | None:
        guild = interaction.guild
        user = for_user or interaction.user
        db = self.bot.db

        async def respond(**kwargs):
            if deferred or interaction.response.is_done():
                return await interaction.followup.send(ephemeral=True, **kwargs)
            return await interaction.response.send_message(ephemeral=True, **kwargs)

        ticket_type = await db.get_ticket_type(guild.id, type_key)
        if not ticket_type:
            await respond(embed=error_embed("That ticket type doesn't exist."))
            return None

        existing = await db.open_ticket_of_type(guild.id, user.id, type_key)
        if existing:
            await respond(
                embed=error_embed(
                    f"You already have an open **{ticket_type['label']}** ticket: "
                    f"<#{existing['channel_id']}>"
                )
            )
            return None

        config = await db.ticket_config(guild.id)
        open_now = await db.open_tickets_for(guild.id, user.id)
        if len(open_now) >= config["max_open"]:
            await respond(
                embed=error_embed(
                    f"You already have {len(open_now)} open tickets — close one first."
                )
            )
            return None

        category_id = ticket_type["category_id"] or config["category_id"]
        category = guild.get_channel(category_id) if category_id else None
        if category is not None and not isinstance(category, discord.CategoryChannel):
            category = None

        number = await db.next_ticket_number(guild.id)

        # Every staff role is added up front — previously only the type's own
        # role could see a ticket, so most staff never saw them at all.
        type_role = (
            guild.get_role(ticket_type["staff_role_id"])
            if ticket_type["staff_role_id"]
            else None
        )
        overwrites = await staff_overwrites(self.bot, guild, type_role)
        overwrites[user] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            attach_files=True,
            read_message_history=True,
        )

        try:
            channel = await guild.create_text_channel(
                name=f"{type_key}-{number:04d}",
                category=category,
                overwrites=overwrites,
                topic=f"{ticket_type['label']} · opened by {user}",
                reason=f"Ticket #{number} opened by {user}",
            )
        except discord.Forbidden:
            await respond(
                embed=error_embed(
                    "I need **Manage Channels** to create ticket channels."
                )
            )
            return None
        except discord.HTTPException as exc:
            log.warning("Ticket channel creation failed: %s", exc)
            await respond(embed=error_embed("Couldn't create the ticket channel."))
            return None

        derived_reason = derive_reason(ticket_type, answers, reason)
        await db.create_ticket(
            guild.id,
            channel.id,
            number,
            type_key,
            user.id,
            giveaway_id=giveaway_id,
            answers=json.dumps(answers) if answers else None,
            reason=derived_reason,
        )

        # Resolve the staff role first — the opening message may reference it
        # via {staff}, so it has to exist before rendering.
        staff_role = None
        if ticket_type["staff_role_id"]:
            staff_role = guild.get_role(ticket_type["staff_role_id"])
        staff_mention = staff_role.mention if staff_role else ""

        embed = open_embed(
            ticket_type,
            number,
            user,
            derived_reason,
            answers,
            guild,
            staff_mention,
        )

        mentions = []
        if ticket_type.get("ping_user", 1):
            mentions.append(user.mention)
        if staff_role and ticket_type.get("ping_staff", 1):
            mentions.append(staff_role.mention)

        try:
            await channel.send(
                content=" ".join(mentions) or None,
                embed=embed,
                view=TicketControls(self),
                allowed_mentions=discord.AllowedMentions(users=True, roles=True),
            )
        except discord.HTTPException:
            pass

        # A standalone index message, pinned for quick reference. Being a real
        # message means it also appears in the transcript body.
        try:
            index = await channel.send(
                embed=index_embed(ticket_type, number, derived_reason, user)
            )
            await index.pin(reason="Ticket index")
        except discord.Forbidden:
            log.info("No Manage Messages in %s; index posted but not pinned", channel.id)
        except discord.HTTPException:
            pass

        await respond(
            embed=base_embed(
                "🎫 Ticket opened",
                f"Your **{ticket_type['label']}** ticket is ready: {channel.mention}",
                accent=type_color(type_key),
            )
        )
        await self.log_event(
            guild,
            base_embed(
                "🎫 Ticket opened",
                f"**#{number:04d}** · {ticket_type['label']}\n"
                f"By {user.mention} in {channel.mention}\n"
                f"**Reason:** {derived_reason}",
                accent=type_color(type_key),
            ),
        )
        return channel

    async def do_close(
        self,
        channel: discord.TextChannel,
        ticket: dict,
        closed_by: discord.abc.User,
        reason: str | None,
    ) -> None:
        await self.bot.db.close_ticket(channel.id, closed_by.id, reason)

        try:
            transcript = await build_transcript(channel, ticket)
        except Exception:
            log.exception("Transcript failed")
            transcript = None

        summary = base_embed(
            f"🔒 Ticket #{ticket['number']:04d} closed",
            f"Closed by {closed_by.mention}"
            + (f"\n**Reason:** {reason}" if reason else ""),
            accent=PINK,
        )
        summary.add_field(name="Type", value=ticket["type_key"], inline=True)
        summary.add_field(name="Opened by", value=f"<@{ticket['user_id']}>", inline=True)
        summary.add_field(
            name="Ticket reason",
            value=ticket.get("reason") or "No reason given",
            inline=False,
        )

        await self.log_event(channel.guild, summary, file=transcript)

        # Vouching belongs at the end: the trade has actually happened by now,
        # and the prompt reaches the opener by DM rather than in a channel
        # that's about to be deleted.
        vouch_cog = self.bot.get_cog("Vouch")
        if vouch_cog is not None and ticket.get("giveaway_id"):
            try:
                from .vouch import VouchButton

                await channel.send(
                    embed=base_embed(
                        "🤝 Before this closes — leave a vouch",
                        "Vouch for whoever handled your prize.",
                        accent=BLUE,
                    ),
                    view=VouchButton(vouch_cog),
                )
            except discord.HTTPException:
                pass

        # Let the opener keep a copy.
        opener = await resolve_member(channel.guild, ticket["user_id"])
        if opener:
            try:
                await opener.send(embed=summary)
            except discord.HTTPException:
                pass

        try:
            delay = 60 if ticket.get("giveaway_id") else 10
            await channel.send(
                embed=base_embed(
                    "🔒 Closing",
                    f"This channel will be deleted in {delay} seconds."
                    + ("\nLeave a vouch above before it goes." if delay > 10 else ""),
                    accent=PINK,
                )
            )
            await asyncio.sleep(delay)
            await channel.delete(reason=f"Ticket closed by {closed_by}")
        except discord.HTTPException:
            pass

    async def log_event(
        self, guild: discord.Guild, embed: discord.Embed, file: discord.File | None = None
    ) -> None:
        config = await self.bot.db.ticket_config(guild.id)
        channel = guild.get_channel(config["log_channel_id"] or 0)
        if channel is None:
            return
        try:
            if file is not None:
                await channel.send(embed=embed, file=file)
            else:
                await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    # ------------------------------------------------------------ commands

    @app_commands.command(
        name="ticketsetup", description="Set up tickets and seed the default types"
    )
    @app_commands.describe(
        category="Category new ticket channels go in",
        log_channel="Where ticket logs and transcripts are posted",
        max_open="How many tickets one member may have open at once",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def ticketsetup(
        self,
        interaction: discord.Interaction,
        category: discord.CategoryChannel,
        log_channel: discord.TextChannel,
        max_open: app_commands.Range[int, 1, 10] = 3,
    ):
        await interaction.response.defer()
        added = await self.ensure_defaults(interaction.guild_id)
        await self.bot.db.set_ticket_config(
            interaction.guild_id,
            category_id=category.id,
            log_channel_id=log_channel.id,
            max_open=max_open,
        )

        embed = base_embed(
            "✅ Tickets configured",
            f"Seeded **{added}** default type(s)." if added else "Types already existed.",
        )
        embed.add_field(name="Category", value=category.mention, inline=True)
        embed.add_field(name="Logs", value=log_channel.mention, inline=True)
        embed.add_field(name="Max open per member", value=str(max_open), inline=True)
        embed.add_field(
            name="Next steps",
            value=(
                "`/tickettype role` — set who handles each type\n"
                "`/ticketpanel` — post the panel members use\n"
                "`/tickettype add` — add your own types"
            ),
            inline=False,
        )
        await interaction.followup.send(embed=embed)

    async def _resolve_types(
        self, guild_id: int, types: str | None
    ) -> tuple[list[str], str | None]:
        """Parse and validate a comma-separated list of type keys."""
        wanted = [t.strip().lower() for t in (types or "").split(",") if t.strip()]
        if not wanted:
            return [], None
        known = {t["key"] for t in await self.bot.db.ticket_types(guild_id)}
        unknown = [t for t in wanted if t not in known]
        if unknown:
            return [], (
                f"Unknown type key(s): {', '.join(f'`{u}`' for u in unknown)}.\n"
                "Run `/tickettype list` to see valid keys."
            )
        return wanted, None

    async def _refresh_panel(self, guild: discord.Guild, panel: dict) -> bool:
        """Re-render a posted panel in place so option changes show up without
        reposting (and without losing the message's position in the channel)."""
        channel = guild.get_channel(panel["channel_id"] or 0)
        if channel is None:
            return False
        try:
            message = await channel.fetch_message(panel["message_id"])
            embed, view = await self.panel_embed_and_view(guild, panel)
            await message.edit(embed=embed, view=view)
            self.bot.add_view(TicketPanel(self, panel["key"]), message_id=message.id)
            return True
        except discord.HTTPException:
            return False

    async def panel_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        panels = await self.bot.db.panels(interaction.guild_id)
        query = current.lower()
        return [
            app_commands.Choice(
                name=f"#{p['id']} · {p['title']} ({p['key']})"[:100],
                # Value is the id, so picking from the list is unambiguous even
                # if two panels somehow share a title.
                value=str(p["id"]),
            )
            for p in panels
            if not query
            or query in p["key"].lower()
            or query in p["title"].lower()
            or query == str(p["id"])
        ][:25]

    panel_group = app_commands.Group(
        name="ticketpanel",
        description="Create and manage ticket panels",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    async def _post_panel(
        self, guild: discord.Guild, target: discord.TextChannel, panel: dict | None
    ) -> discord.Message:
        """Render, send, and register the persistent view in one place, so
        posting and refreshing can't drift apart."""
        embed, view = await self.panel_embed_and_view(guild, panel)
        message = await target.send(embed=embed, view=view)
        self.bot.add_view(
            TicketPanel(self, (panel or {}).get("key")), message_id=message.id
        )
        return message

    @panel_group.command(name="create", description="Save a new panel")
    @app_commands.describe(
        key="Short id, e.g. 'applications'",
        title="Heading shown on the panel",
        types="Ticket type keys to include, comma separated (blank = all)",
        description="Text under the heading",
        placeholder="Text inside the dropdown",
        channel="Post it straight away in this channel",
    )
    async def panel_create(
        self,
        interaction: discord.Interaction,
        key: str,
        title: str,
        types: str | None = None,
        description: str | None = None,
        placeholder: str | None = None,
        channel: discord.TextChannel | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        key = key.lower().strip().replace(" ", "-")[:20]
        if not key.replace("-", "").isalnum():
            await interaction.followup.send(
                embed=error_embed("Key must be letters, numbers and dashes only.")
            )
            return

        wanted, problem = await self._resolve_types(interaction.guild_id, types)
        if problem:
            await interaction.followup.send(embed=error_embed(problem))
            return

        created = await self.bot.db.add_panel(
            interaction.guild_id,
            key,
            title,
            description=description,
            placeholder=placeholder,
            type_keys=json.dumps(wanted) if wanted else None,
        )
        if not created:
            await interaction.followup.send(
                embed=error_embed(
                    f"A panel called `{key}` already exists — use "
                    f"`/ticketpanel edit key:{key}` to change it."
                )
            )
            return

        saved = await self.bot.db.get_panel(interaction.guild_id, key)
        embed = base_embed(
            f"✅ Panel #{saved['id']} saved", f"**{title}** · name `{key}`"
        )
        embed.add_field(name="Panel ID", value=f"`{saved['id']}`", inline=True)
        embed.add_field(
            name="Includes",
            value=", ".join(f"`{t}`" for t in wanted) if wanted else "every visible type",
            inline=False,
        )

        if channel:
            try:
                message = await self._post_panel(interaction.guild, channel, saved)
            except discord.Forbidden:
                await interaction.followup.send(
                    embed=error_embed(f"Saved, but I can't post in {channel.mention}.")
                )
                return
            await self.bot.db.update_panel(
                interaction.guild_id,
                saved["id"],
                channel_id=channel.id,
                message_id=message.id,
            )
            embed.add_field(name="Posted in", value=channel.mention, inline=False)
        else:
            embed.set_footer(
                text=f"Post it with /ticketpanel post panel:{saved['id']}"
            )

        await interaction.followup.send(embed=embed)

    @panel_group.command(name="post", description="Post a panel into a channel")
    @app_commands.describe(
        panel="Panel ID or name (omit for the default all-types panel)",
        channel="Where to post it (defaults to here)",
    )
    @app_commands.autocomplete(panel=panel_autocomplete)
    async def panel_post(
        self,
        interaction: discord.Interaction,
        panel: str | None = None,
        channel: discord.TextChannel | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        target = channel or interaction.channel

        panel_row = None
        if panel:
            panel_row = await self.bot.db.get_panel(interaction.guild_id, panel)
            if panel_row is None:
                await interaction.followup.send(
                    embed=error_embed(
                        f"No panel with ID or name `{panel}`. Run `/ticketpanel list`."
                    )
                )
                return

        types = await self.bot.db.ticket_types(interaction.guild_id, only_enabled=True)
        if not [t for t in types if not t["hidden"]]:
            await interaction.followup.send(
                embed=error_embed("No visible ticket types — run `/ticketsetup` first.")
            )
            return

        try:
            message = await self._post_panel(interaction.guild, target, panel_row)
        except discord.Forbidden:
            await interaction.followup.send(
                embed=error_embed(f"I can't post in {target.mention}.")
            )
            return

        if panel_row:
            await self.bot.db.update_panel(
                interaction.guild_id,
                panel_row["id"],
                channel_id=target.id,
                message_id=message.id,
            )
        else:
            await self.bot.db.set_ticket_config(
                interaction.guild_id, panel_channel=target.id, panel_message=message.id
            )
        await interaction.followup.send(
            embed=base_embed("✅ Panel posted", f"Live in {target.mention}.")
        )

    @panel_group.command(name="edit", description="Change a saved panel")
    @app_commands.describe(
        panel="Panel ID or name",
        title="New heading",
        types="New type list, comma separated ('all' for every visible type)",
        description="New text under the heading",
        placeholder="New dropdown text",
    )
    @app_commands.autocomplete(panel=panel_autocomplete)
    async def panel_edit(
        self,
        interaction: discord.Interaction,
        panel: str,
        title: str | None = None,
        types: str | None = None,
        description: str | None = None,
        placeholder: str | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        existing = await self.bot.db.get_panel(interaction.guild_id, panel)
        if existing is None:
            await interaction.followup.send(
                embed=error_embed(
                    f"No panel with ID or name `{panel}`. Run `/ticketpanel list`."
                )
            )
            return

        fields: dict = {}
        if title is not None:
            fields["title"] = title
        if description is not None:
            fields["description"] = description
        if placeholder is not None:
            fields["placeholder"] = placeholder
        if types is not None:
            if types.strip().lower() in ("all", "*"):
                fields["type_keys"] = None
            else:
                wanted, problem = await self._resolve_types(interaction.guild_id, types)
                if problem:
                    await interaction.followup.send(embed=error_embed(problem))
                    return
                fields["type_keys"] = json.dumps(wanted)

        if not fields:
            await interaction.followup.send(
                embed=error_embed("Give me at least one thing to change.")
            )
            return

        await self.bot.db.update_panel(interaction.guild_id, panel, **fields)
        updated = await self.bot.db.get_panel(interaction.guild_id, panel)
        label = f"#{updated['id']} `{updated['key']}`"

        note = ""
        if updated["message_id"] and updated["channel_id"]:
            refreshed = await self._refresh_panel(interaction.guild, updated)
            note = (
                "\nThe posted panel was updated in place."
                if refreshed
                else "\n⚠️ Couldn't update the posted message — repost with "
                f"`/ticketpanel post panel:{updated['id']}`."
            )

        await interaction.followup.send(
            embed=base_embed(
                f"✅ Panel {label} updated",
                "Changed: " + ", ".join(f"`{name}`" for name in fields) + note,
            )
        )

    @panel_group.command(
        name="refresh", description="Redraw a posted panel after changing types"
    )
    @app_commands.describe(panel="Panel ID or name (omit to refresh all)")
    @app_commands.autocomplete(panel=panel_autocomplete)
    async def panel_refresh(
        self, interaction: discord.Interaction, panel: str | None = None
    ):
        await interaction.response.defer(ephemeral=True)

        if panel:
            rows = [await self.bot.db.get_panel(interaction.guild_id, panel)]
            if rows[0] is None:
                await interaction.followup.send(
                    embed=error_embed(
                        f"No panel with ID or name `{panel}`. Run `/ticketpanel list`."
                    )
                )
                return
        else:
            rows = await self.bot.db.panels(interaction.guild_id)

        done, failed = [], []
        for row in rows:
            if not (row["message_id"] and row["channel_id"]):
                continue
            if await self._refresh_panel(interaction.guild, row):
                done.append(f"#{row['id']} {row['key']}")
            else:
                failed.append(f"#{row['id']} {row['key']}")

        if not done and not failed:
            await interaction.followup.send(
                embed=error_embed("Nothing to refresh — no panels are posted yet.")
            )
            return

        embed = base_embed(
            "🔄 Panels refreshed",
            "Updated: " + ", ".join(f"`{k}`" for k in done) if done else "None updated.",
        )
        if failed:
            embed.add_field(
                name="Couldn't update",
                value=", ".join(f"`{k}`" for k in failed)
                + "\nThe message may have been deleted — repost it.",
                inline=False,
            )
        await interaction.followup.send(embed=embed)

    @panel_group.command(name="delete", description="Delete a saved panel")
    @app_commands.describe(
        panel="Panel ID or name", remove_message="Also delete the posted message"
    )
    @app_commands.autocomplete(panel=panel_autocomplete)
    async def panel_delete(
        self, interaction: discord.Interaction, panel: str, remove_message: bool = False
    ):
        await interaction.response.defer(ephemeral=True)
        row = await self.bot.db.get_panel(interaction.guild_id, panel)
        if row is None:
            await interaction.followup.send(
                embed=error_embed(
                    f"No panel with ID or name `{panel}`. Run `/ticketpanel list`."
                )
            )
            return

        if remove_message and row["channel_id"] and row["message_id"]:
            channel = interaction.guild.get_channel(row["channel_id"])
            if channel:
                try:
                    message = await channel.fetch_message(row["message_id"])
                    await message.delete()
                except discord.HTTPException:
                    pass

        await self.bot.db.delete_panel(interaction.guild_id, panel)
        await interaction.followup.send(
            embed=base_embed(
                "🗑️ Panel deleted",
                f"#{row['id']} `{row['key']}` removed."
                + ("" if remove_message else " The posted message is still there."),
                accent=PINK,
            )
        )

    @panel_group.command(name="list", description="List saved ticket panels")
    async def panel_list(self, interaction: discord.Interaction):
        panels = await self.bot.db.panels(interaction.guild_id)
        if not panels:
            await interaction.response.send_message(
                embed=base_embed(
                    "🎫 No saved panels",
                    "`/ticketpanel create` makes one with its own title and set "
                    "of types. `/ticketpanel post` alone posts a default panel "
                    "with every visible type.",
                )
            )
            return

        embed = base_embed(f"🎫 Ticket panels — {len(panels)}")
        for panel in panels:
            keys = json.loads(panel["type_keys"]) if panel["type_keys"] else []
            where = (
                f"<#{panel['channel_id']}>" if panel["channel_id"] else "not posted yet"
            )
            embed.add_field(
                name=f"#{panel['id']} · {panel['title']} (`{panel['key']}`)",
                value=(
                    f"{where} · "
                    + (", ".join(f"`{k}`" for k in keys) if keys else "all visible types")
                ),
                inline=False,
            )
        embed.set_footer(
            text="Reference a panel by its ID or name in any /ticketpanel command"
        )
        await interaction.response.send_message(embed=embed)

    # --- type management -------------------------------------------------

    type_group = app_commands.Group(
        name="tickettype",
        description="Manage ticket types",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    async def type_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        types = await self.bot.db.ticket_types(interaction.guild_id)
        return [
            app_commands.Choice(name=f"{t['label']} ({t['key']})"[:100], value=t["key"])
            for t in types
            if current.lower() in t["key"].lower() or current.lower() in t["label"].lower()
        ][:25]

    @type_group.command(name="add", description="Add a new ticket type")
    @app_commands.describe(
        key="Short id, used in the channel name (e.g. 'media')",
        label="Name shown on the panel",
        description="One-line description",
        emoji="Emoji for the panel",
        staff_role="Role that can see and handle these tickets",
        questions="Questions to ask, separated by | (max 5)",
    )
    async def type_add(
        self,
        interaction: discord.Interaction,
        key: str,
        label: str,
        description: str | None = None,
        emoji: str | None = None,
        staff_role: discord.Role | None = None,
        questions: str | None = None,
    ):
        key = key.lower().strip().replace(" ", "-")[:20]
        if not key.replace("-", "").isalnum():
            await interaction.response.send_message(
                embed=error_embed("Key must be letters, numbers and dashes only."),
                ephemeral=True,
            )
            return

        question_list = [q.strip() for q in (questions or "").split("|") if q.strip()]
        if len(question_list) > MAX_QUESTIONS:
            await interaction.response.send_message(
                embed=error_embed(
                    f"Discord modals allow at most {MAX_QUESTIONS} questions — "
                    f"you gave {len(question_list)}."
                ),
                ephemeral=True,
            )
            return

        existing = await self.bot.db.ticket_types(interaction.guild_id)
        created = await self.bot.db.add_ticket_type(
            interaction.guild_id,
            key,
            label,
            emoji=emoji,
            description=description,
            staff_role_id=staff_role.id if staff_role else None,
            questions=json.dumps(question_list),
            position=len(existing),
        )
        if not created:
            await interaction.response.send_message(
                embed=error_embed(f"A type with key `{key}` already exists."),
                ephemeral=True,
            )
            return

        embed = base_embed("✅ Ticket type added", f"{emoji or '🎫'} **{label}** (`{key}`)")
        if staff_role:
            embed.add_field(name="Staff role", value=staff_role.mention, inline=True)
        embed.add_field(name="Questions", value=str(len(question_list)), inline=True)
        embed.set_footer(text="Run /ticketpanel again to refresh the panel")
        await interaction.response.send_message(embed=embed)

    @type_group.command(name="remove", description="Delete a custom ticket type")
    @app_commands.autocomplete(key=type_autocomplete)
    async def type_remove(self, interaction: discord.Interaction, key: str):
        ticket_type = await self.bot.db.get_ticket_type(interaction.guild_id, key)
        if ticket_type and ticket_type["is_builtin"]:
            await interaction.response.send_message(
                embed=error_embed(
                    "Built-in types can't be deleted — disable it instead with "
                    "`/tickettype toggle`."
                ),
                ephemeral=True,
            )
            return

        if await self.bot.db.delete_ticket_type(interaction.guild_id, key):
            await interaction.response.send_message(
                embed=base_embed("🗑️ Type removed", f"Deleted `{key}`.")
            )
        else:
            await interaction.response.send_message(
                embed=error_embed(f"No custom type with key `{key}`."), ephemeral=True
            )

    @type_group.command(name="toggle", description="Enable or disable a ticket type")
    @app_commands.autocomplete(key=type_autocomplete)
    async def type_toggle(
        self, interaction: discord.Interaction, key: str, enabled: bool
    ):
        ok = await self.bot.db.update_ticket_type(
            interaction.guild_id, key, enabled=1 if enabled else 0
        )
        if ok:
            await interaction.response.send_message(
                embed=base_embed(
                    "✅ Updated",
                    f"`{key}` is now **{'enabled' if enabled else 'disabled'}**. "
                    "Re-run `/ticketpanel` to refresh.",
                )
            )
        else:
            await interaction.response.send_message(
                embed=error_embed(f"No type with key `{key}`."), ephemeral=True
            )

    @type_group.command(name="role", description="Set the staff role for a type")
    @app_commands.autocomplete(key=type_autocomplete)
    async def type_role(
        self, interaction: discord.Interaction, key: str, role: discord.Role
    ):
        ok = await self.bot.db.update_ticket_type(
            interaction.guild_id, key, staff_role_id=role.id
        )
        if ok:
            await interaction.response.send_message(
                embed=base_embed(
                    "✅ Staff role set", f"{role.mention} now handles `{key}` tickets."
                )
            )
        else:
            await interaction.response.send_message(
                embed=error_embed(f"No type with key `{key}`."), ephemeral=True
            )

    @type_group.command(name="questions", description="Set a type's application questions")
    @app_commands.describe(questions="Separated by | — leave blank to clear (max 5)")
    @app_commands.autocomplete(key=type_autocomplete)
    async def type_questions(
        self, interaction: discord.Interaction, key: str, questions: str = ""
    ):
        question_list = [q.strip() for q in questions.split("|") if q.strip()]
        if len(question_list) > MAX_QUESTIONS:
            await interaction.response.send_message(
                embed=error_embed(f"At most {MAX_QUESTIONS} questions."), ephemeral=True
            )
            return

        ok = await self.bot.db.update_ticket_type(
            interaction.guild_id, key, questions=json.dumps(question_list)
        )
        if ok:
            body = "\n".join(f"{i}. {q}" for i, q in enumerate(question_list, 1)) or "None"
            await interaction.response.send_message(
                embed=base_embed(f"✅ Questions for `{key}`", body)
            )
        else:
            await interaction.response.send_message(
                embed=error_embed(f"No type with key `{key}`."), ephemeral=True
            )

    @type_group.command(
        name="message", description="Customise what's posted when this ticket opens"
    )
    @app_commands.describe(
        key="Which ticket type",
        title="Heading. Placeholders: {user} {name} {ticket} {type} {reason} {server}",
        message="Body text. Use \\n for line breaks, same placeholders, {staff} pings the role",
        colour="Embed colour",
        image="Image URL shown in the embed",
        footer="Small text at the bottom",
    )
    @app_commands.choices(
        colour=[
            app_commands.Choice(name="Type default", value="default"),
            app_commands.Choice(name="Blue", value="blue"),
            app_commands.Choice(name="Pink", value="pink"),
            app_commands.Choice(name="Yellow", value="yellow"),
        ]
    )
    @app_commands.autocomplete(key=type_autocomplete)
    async def type_message(
        self,
        interaction: discord.Interaction,
        key: str,
        title: str | None = None,
        message: str | None = None,
        colour: app_commands.Choice[str] | None = None,
        image: str | None = None,
        footer: str | None = None,
    ):
        ticket_type = await self.bot.db.get_ticket_type(interaction.guild_id, key)
        if ticket_type is None:
            await interaction.response.send_message(
                embed=error_embed(f"No ticket type with key `{key}`."), ephemeral=True
            )
            return

        if image and not image.startswith(("http://", "https://")):
            await interaction.response.send_message(
                embed=error_embed("The image must be a http(s) URL."), ephemeral=True
            )
            return

        # Only overwrite what was actually passed, so setting a title later
        # doesn't wipe a message set earlier.
        fields = {}
        if title is not None:
            fields["open_title"] = title
        if message is not None:
            fields["open_message"] = message
        if colour is not None:
            fields["open_color"] = None if colour.value == "default" else colour.value
        if image is not None:
            fields["open_image"] = image
        if footer is not None:
            fields["open_footer"] = footer

        if not fields:
            await interaction.response.send_message(
                embed=error_embed(
                    "Give me at least one thing to change. Use `/tickettype preview` "
                    "to see the current message, or `/tickettype resetmessage` to "
                    "go back to the default."
                ),
                ephemeral=True,
            )
            return

        await self.bot.db.update_ticket_type(interaction.guild_id, key, **fields)
        updated = await self.bot.db.get_ticket_type(interaction.guild_id, key)

        await interaction.response.send_message(
            embed=base_embed(
                "✅ Opening message updated",
                "Changed: " + ", ".join(
                    f"`{name.replace('_', ' ')}`" for name in fields
                ),
            )
        )
        await interaction.followup.send(
            content="This is what someone will see:",
            embed=open_embed(
                updated,
                1234,
                interaction.user,
                "Example reason",
                None,
                interaction.guild,
                f"<@&{updated['staff_role_id']}>" if updated["staff_role_id"] else "",
            ),
        )

    @type_group.command(
        name="pings", description="Choose who gets pinged when a ticket opens"
    )
    @app_commands.describe(
        key="Which ticket type",
        ping_opener="Ping the person who opened it",
        ping_staff="Ping the staff role",
        show_answers="Include their form answers in the opening message",
    )
    @app_commands.autocomplete(key=type_autocomplete)
    async def type_pings(
        self,
        interaction: discord.Interaction,
        key: str,
        ping_opener: bool | None = None,
        ping_staff: bool | None = None,
        show_answers: bool | None = None,
    ):
        fields = {}
        if ping_opener is not None:
            fields["ping_user"] = 1 if ping_opener else 0
        if ping_staff is not None:
            fields["ping_staff"] = 1 if ping_staff else 0
        if show_answers is not None:
            fields["show_answers"] = 1 if show_answers else 0

        if not fields:
            await interaction.response.send_message(
                embed=error_embed("Give me at least one option to change."), ephemeral=True
            )
            return

        if not await self.bot.db.update_ticket_type(interaction.guild_id, key, **fields):
            await interaction.response.send_message(
                embed=error_embed(f"No ticket type with key `{key}`."), ephemeral=True
            )
            return

        updated = await self.bot.db.get_ticket_type(interaction.guild_id, key)
        embed = base_embed(f"✅ Updated `{key}`")
        embed.add_field(
            name="Pings opener", value="yes" if updated["ping_user"] else "no", inline=True
        )
        embed.add_field(
            name="Pings staff", value="yes" if updated["ping_staff"] else "no", inline=True
        )
        embed.add_field(
            name="Shows answers",
            value="yes" if updated["show_answers"] else "no",
            inline=True,
        )
        await interaction.response.send_message(embed=embed)

    @type_group.command(
        name="preview", description="See the opening message for a ticket type"
    )
    @app_commands.autocomplete(key=type_autocomplete)
    async def type_preview(self, interaction: discord.Interaction, key: str):
        ticket_type = await self.bot.db.get_ticket_type(interaction.guild_id, key)
        if ticket_type is None:
            await interaction.response.send_message(
                embed=error_embed(f"No ticket type with key `{key}`."), ephemeral=True
            )
            return

        questions = parse_questions(ticket_type["questions"])
        sample = {q: "*(their answer)*" for q in questions[:2]}
        staff = f"<@&{ticket_type['staff_role_id']}>" if ticket_type["staff_role_id"] else ""

        pings = []
        if ticket_type["ping_user"]:
            pings.append(interaction.user.mention)
        if staff and ticket_type["ping_staff"]:
            pings.append(staff)

        await interaction.response.send_message(
            content=f"**Preview of `{key}`** — sent as: {' '.join(pings) or '*no pings*'}",
            embed=open_embed(
                ticket_type,
                1234,
                interaction.user,
                "Example reason",
                sample,
                interaction.guild,
                staff,
            ),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @type_group.command(
        name="resetmessage", description="Restore the default opening message"
    )
    @app_commands.autocomplete(key=type_autocomplete)
    async def type_resetmessage(self, interaction: discord.Interaction, key: str):
        ok = await self.bot.db.update_ticket_type(
            interaction.guild_id,
            key,
            open_title=None,
            open_message=None,
            open_color=None,
            open_image=None,
            open_footer=None,
        )
        if ok:
            await interaction.response.send_message(
                embed=base_embed(
                    "↩️ Reset",
                    f"`{key}` is back to the default opening message.",
                    accent=PINK,
                )
            )
        else:
            await interaction.response.send_message(
                embed=error_embed(f"No ticket type with key `{key}`."), ephemeral=True
            )

    @type_group.command(name="list", description="List this server's ticket types")
    async def type_list(self, interaction: discord.Interaction):
        types = await self.bot.db.ticket_types(interaction.guild_id)
        if not types:
            await interaction.response.send_message(
                embed=error_embed("No types yet — run `/ticketsetup`."), ephemeral=True
            )
            return

        embed = base_embed(f"🎫 Ticket types — {len(types)}")
        for t in types:
            flags = []
            if not t["enabled"]:
                flags.append("disabled")
            if t["hidden"]:
                flags.append("hidden from panel")
            if t["is_builtin"]:
                flags.append("built-in")
            role = f"<@&{t['staff_role_id']}>" if t["staff_role_id"] else "no role set"
            count = len(parse_questions(t["questions"]))
            embed.add_field(
                name=f"{t['emoji'] or '•'} {t['label']} (`{t['key']}`)",
                value=(
                    f"{t['description'] or '*no description*'}\n"
                    f"{role} · {count} question(s)"
                    + (f" · _{', '.join(flags)}_" if flags else "")
                ),
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    # --- in-ticket commands ---------------------------------------------

    @app_commands.command(name="close", description="Close the ticket in this channel")
    @app_commands.describe(reason="Why it's being closed")
    @app_commands.guild_only()
    async def close(self, interaction: discord.Interaction, reason: str | None = None):
        ticket = await self.bot.db.ticket_by_channel(interaction.channel_id)
        if not ticket or ticket["status"] != "open":
            await interaction.response.send_message(
                embed=error_embed("This isn't an open ticket channel."), ephemeral=True
            )
            return

        if interaction.user.id != ticket["user_id"] and not await self.is_staff(
            interaction.user, ticket["type_key"]
        ):
            await interaction.response.send_message(
                embed=error_embed("You can't close this ticket."), ephemeral=True
            )
            return

        await interaction.response.send_message(
            embed=base_embed("🔒 Closing ticket", accent=PINK)
        )
        await self.do_close(interaction.channel, ticket, interaction.user, reason)

    @app_commands.command(name="ticketadd", description="Add a member to this ticket")
    @app_commands.guild_only()
    async def ticketadd(self, interaction: discord.Interaction, member: discord.Member):
        ticket = await self.bot.db.ticket_by_channel(interaction.channel_id)
        if not ticket:
            await interaction.response.send_message(
                embed=error_embed("This isn't a ticket channel."), ephemeral=True
            )
            return
        if not await self.is_staff(interaction.user, ticket["type_key"]):
            await interaction.response.send_message(
                embed=error_embed("Only staff can add members."), ephemeral=True
            )
            return

        await interaction.channel.set_permissions(
            member, view_channel=True, send_messages=True, read_message_history=True
        )
        await interaction.response.send_message(
            embed=base_embed("➕ Added", f"{member.mention} can now see this ticket.")
        )

    @app_commands.command(name="ticketremove", description="Remove a member from this ticket")
    @app_commands.guild_only()
    async def ticketremove(self, interaction: discord.Interaction, member: discord.Member):
        ticket = await self.bot.db.ticket_by_channel(interaction.channel_id)
        if not ticket:
            await interaction.response.send_message(
                embed=error_embed("This isn't a ticket channel."), ephemeral=True
            )
            return
        if not await self.is_staff(interaction.user, ticket["type_key"]):
            await interaction.response.send_message(
                embed=error_embed("Only staff can remove members."), ephemeral=True
            )
            return
        if member.id == ticket["user_id"]:
            await interaction.response.send_message(
                embed=error_embed("You can't remove the person who opened it."),
                ephemeral=True,
            )
            return

        await interaction.channel.set_permissions(member, overwrite=None)
        await interaction.response.send_message(
            embed=base_embed("➖ Removed", f"{member.mention} no longer has access.")
        )

    @app_commands.command(
        name="ticketindex", description="Index of tickets and the reason for each"
    )
    @app_commands.describe(
        show="Which tickets to include", type_key="Filter to one ticket type"
    )
    @app_commands.choices(
        show=[
            app_commands.Choice(name="Open only", value="open"),
            app_commands.Choice(name="Closed only", value="closed"),
            app_commands.Choice(name="All", value="all"),
        ]
    )
    @app_commands.guild_only()
    async def ticketindex(
        self,
        interaction: discord.Interaction,
        show: app_commands.Choice[str] | None = None,
        type_key: str | None = None,
    ):
        if not await self.is_staff(interaction.user):
            await interaction.response.send_message(
                embed=error_embed("Staff only."), ephemeral=True
            )
            return

        await interaction.response.defer()
        status = show.value if show else "open"
        rows = await self.bot.db.guild_tickets(
            interaction.guild_id, None if status == "all" else status
        )
        if type_key:
            rows = [r for r in rows if r["type_key"] == type_key.lower()]

        if not rows:
            await interaction.followup.send(
                embed=base_embed("🧾 Ticket index", "Nothing matches that filter.")
            )
            return

        embed = base_embed(f"🧾 Ticket index — {len(rows)} {status}")
        lines = []
        for row in rows[:20]:
            marker = "🟢" if row["status"] == "open" else "⚫"
            where = (
                f"<#{row['channel_id']}>"
                if row["status"] == "open"
                else f"`{row['type_key']}`"
            )
            reason = (row["reason"] or "No reason given")[:90]
            lines.append(
                f"{marker} **#{row['number']:04d}** {where} · <@{row['user_id']}>\n"
                f"　↳ {reason}"
            )
        embed.description = "\n".join(lines)

        if len(rows) > 20:
            embed.set_footer(text=f"Showing 20 of {len(rows)} • DonutDuck")
        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="ticketrename", description="Rename a ticket from anywhere"
    )
    @app_commands.describe(
        name="New channel name",
        ticket="Ticket number or channel (defaults to this channel)",
    )
    @app_commands.guild_only()
    async def ticketrename(
        self, interaction: discord.Interaction, name: str, ticket: str | None = None
    ):
        await interaction.response.defer()

        # Resolve which ticket: a number, a channel mention/id, or this channel.
        channel = None
        if ticket:
            ref = ticket.strip().strip("<#>")
            if ref.isdigit():
                by_channel = await self.bot.db.ticket_by_channel(int(ref))
                if by_channel:
                    channel = interaction.guild.get_channel(int(ref))
                else:
                    for row in await self.bot.db.guild_tickets(interaction.guild_id):
                        if row["number"] == int(ref):
                            channel = interaction.guild.get_channel(row["channel_id"])
                            break
        else:
            channel = interaction.channel

        if channel is None:
            await interaction.followup.send(
                embed=error_embed(
                    f"Couldn't find a ticket matching `{ticket}`. Use the ticket "
                    "number from `/ticketindex`, or a channel mention."
                )
            )
            return

        row = await self.bot.db.ticket_by_channel(channel.id)
        if row is None:
            await interaction.followup.send(
                embed=error_embed(f"{channel.mention} isn't a ticket channel.")
            )
            return
        if not await self.is_staff(interaction.user, row["type_key"]):
            await interaction.followup.send(embed=error_embed("Staff only."))
            return

        old = channel.name
        try:
            await channel.edit(name=name[:100], reason=f"Renamed by {interaction.user}")
        except discord.Forbidden:
            await interaction.followup.send(
                embed=error_embed("I need Manage Channels to rename tickets.")
            )
            return
        except discord.HTTPException:
            await interaction.followup.send(
                embed=error_embed(
                    "Discord rate limits channel renames to twice every 10 minutes. "
                    "Try again shortly."
                )
            )
            return

        await interaction.followup.send(
            embed=base_embed(
                "✏️ Ticket renamed",
                f"`#{old}` → {channel.mention}",
            )
        )

    @app_commands.command(
        name="ticketsync", description="Add staff roles to existing open tickets"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def ticketsync(self, interaction: discord.Interaction):
        """Channels created before a staff role was added don't have it in
        their overwrites — this backfills them."""
        await interaction.response.defer()

        roles = await staff_role_objects(self.bot, interaction.guild)
        if not roles:
            await interaction.followup.send(
                embed=error_embed("No staff roles configured — run `/staffroles add`.")
            )
            return

        updated, failed = 0, 0
        for row in await self.bot.db.guild_tickets(interaction.guild_id, "open"):
            channel = interaction.guild.get_channel(row["channel_id"])
            if channel is None:
                continue
            try:
                for role in roles:
                    await channel.set_permissions(
                        role,
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        attach_files=True,
                        reason="Staff role sync",
                    )
                updated += 1
            except discord.HTTPException:
                failed += 1

        embed = base_embed(
            "🔄 Tickets synced",
            f"Added {', '.join(r.mention for r in roles)} to **{updated}** open ticket(s).",
        )
        if failed:
            embed.add_field(name="Failed", value=f"{failed} channel(s)", inline=True)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="tickets", description="List open tickets in this server")
    @app_commands.guild_only()
    async def tickets_list(self, interaction: discord.Interaction):
        if not await self.is_staff(interaction.user):
            await interaction.response.send_message(
                embed=error_embed("Staff only."), ephemeral=True
            )
            return

        rows = await self.bot.db.guild_tickets(interaction.guild_id, "open")
        if not rows:
            await interaction.response.send_message(
                embed=base_embed("🎫 No open tickets", "All clear.")
            )
            return

        embed = base_embed(f"🎫 Open tickets — {len(rows)}")
        lines = []
        for row in rows[:20]:
            claimed = f" · claimed by <@{row['claimed_by']}>" if row["claimed_by"] else ""
            lines.append(
                f"**#{row['number']:04d}** `{row['type_key']}` <#{row['channel_id']}> "
                f"· <@{row['user_id']}> · <t:{int(row['created_at'])}:R>{claimed}"
            )
        embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
