"""Доступ к админ-командам: роли/пользователи из COMMAND_ACCESS_IDS (+ администраторы сервера)."""
import discord
from discord.ext import commands

from bot import config


class NoAccess(commands.CheckFailure):
    pass


def has_access(member: discord.abc.User) -> bool:
    if not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.administrator:
        return True
    ids = config.COMMAND_ACCESS_IDS
    return member.id in ids or any(r.id in ids for r in member.roles)


def access():
    async def predicate(ctx: commands.Context) -> bool:
        if not has_access(ctx.author):
            raise NoAccess()
        return True
    return commands.check(predicate)
