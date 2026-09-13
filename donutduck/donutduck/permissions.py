"""Who counts as staff, in one place.

Before this, "staff" meant three different things depending on the command:
ticket actions checked the per-type role, giveaways required Manage Server,
and ticket channels were only visible to a single type's role. That's why
staff couldn't see most tickets or run giveaways.

Now a server nominates its staff roles once with `/staffroles`, and everything
reads from that list: ticket visibility, giveaway commands, activity checks
and strikes. Manage Server still counts, so admins never lock themselves out.
"""

from __future__ import annotations

import discord
from discord import app_commands


async def staff_role_objects(bot, guild: discord.Guild) -> list[discord.Role]:
    """Configured staff roles, plus any role attached to a ticket type."""
    role_ids = set(await bot.db.staff_role_ids(guild.id))
    for ticket_type in await bot.db.ticket_types(guild.id):
        if ticket_type["staff_role_id"]:
            role_ids.add(ticket_type["staff_role_id"])

    roles = [guild.get_role(rid) for rid in role_ids]
    return [r for r in roles if r is not None]


async def is_staff(bot, member: discord.Member) -> bool:
    if not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.manage_guild:
        return True
    staff_ids = {r.id for r in await staff_role_objects(bot, member.guild)}
    return any(r.id in staff_ids for r in member.roles)


def staff_only():
    """Check for commands staff should run without needing Manage Server.

    Deliberately *not* `default_permissions(manage_guild=True)`: that hides the
    command from everyone else in the picker, which is what stopped staff
    running giveaways.
    """

    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            return False
        if await is_staff(interaction.client, interaction.user):
            return True
        raise app_commands.CheckFailure(
            "This is a staff command. An admin can grant access with "
            "`/staffroles add`."
        )

    return app_commands.check(predicate)


async def staff_overwrites(
    bot, guild: discord.Guild, extra_role: discord.Role | None = None
) -> dict:
    """Permission overwrites for a new ticket channel: hidden from everyone,
    visible to the opener's staff (added by the caller) and every staff role."""
    overwrites: dict = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_channels=True,
            manage_messages=True,
            read_message_history=True,
        ),
    }

    roles = await staff_role_objects(bot, guild)
    if extra_role is not None and extra_role not in roles:
        roles.append(extra_role)

    for role in roles:
        overwrites[role] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
        )
    return overwrites
