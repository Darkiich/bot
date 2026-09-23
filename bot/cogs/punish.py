"""Наказание нарушителей: замена их сообщений на 💩."""
import logging
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from bot import config
from bot.checks import access

log = logging.getLogger(__name__)
WEBHOOK_NAME = "Мемный надзор"


class Punish(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.state = bot.state
        self.webhooks: dict[int, discord.Webhook] = {}

    # ---------- замена сообщений ----------
    async def get_webhook(self, channel: discord.TextChannel) -> discord.Webhook:
        if channel.id in self.webhooks:
            return self.webhooks[channel.id]
        hooks = await channel.webhooks()
        hook = next((h for h in hooks if h.name == WEBHOOK_NAME and h.token), None)
        if hook is None:
            hook = await channel.create_webhook(name=WEBHOOK_NAME)
        self.webhooks[channel.id] = hook
        return hook

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if (
            message.guild is None
            or message.author.bot
            or message.webhook_id
            or self.state["punish_mode"] != "poop"
            or str(message.author.id) not in self.state["violators"]
        ):
            return

        try:
            await message.delete()
        except discord.HTTPException as e:
            log.warning("Не могу удалить сообщение %s: %s", message.id, e)
            return

        channel = message.channel
        thread = None
        if isinstance(channel, discord.Thread):
            thread, channel = channel, channel.parent
        try:
            hook = await self.get_webhook(channel)
            kwargs = {"thread": thread} if thread else {}
            await hook.send(
                config.POOP,
                username=message.author.display_name,
                avatar_url=message.author.display_avatar.url,
                allowed_mentions=discord.AllowedMentions.none(),
                **kwargs,
            )
        except (discord.HTTPException, AttributeError) as e:
            # нет права «Управлять вебхуками» или странный канал — просто пишем от бота
            log.warning("Вебхук не сработал (%s), отправляю от имени бота", e)
            self.webhooks.pop(getattr(channel, "id", 0), None)
            await message.channel.send(
                f"{config.POOP} — **{message.author.display_name}**",
                allowed_mentions=discord.AllowedMentions.none(),
            )

    # ---------- команды ----------
    @commands.hybrid_command(name="punish", description="Replace violators' messages with poop (on) or revoke (off)")
    @app_commands.describe(mode="on — replace violators' messages with poop, off — revoke")
    @access()
    @commands.guild_only()
    async def punish(self, ctx: commands.Context, mode: Literal["on", "off"] | None = None) -> None:
        if mode is None:
            current = "on (заменять какашками)" if self.state["punish_mode"] == "poop" else "off (отозвано)"
            await ctx.send(f"Сейчас: **{current}**. Использование: `{config.PREFIX}punish on` / `{config.PREFIX}punish off`")
            return
        self.state["punish_mode"] = "poop" if mode == "on" else "off"
        self.state.save()
        if mode == "on":
            await ctx.send(f"{config.POOP} Режим включён: сообщения нарушителей будут заменяться на {config.POOP}.")
        else:
            await ctx.send("🚫 Наказание отозвано: сообщения нарушителей больше не заменяются.")

    @commands.hybrid_command(name="violators", description="Show current violators")
    @commands.guild_only()
    async def violators(self, ctx: commands.Context) -> None:
        v = self.state["violators"]
        mode = f"{config.POOP} on" if self.state["punish_mode"] == "poop" else "🚫 off"
        if not v:
            await ctx.send(f"Нарушителей нет. Наказание: {mode}", ephemeral=True)
            return
        lines = [f"• <@{uid}> — пропустил(а) {d['missed']} из {d['total']}" for uid, d in v.items()]
        await ctx.send(
            (f"Наказание: {mode}\n" + "\n".join(lines))[:1990],
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.hybrid_command(name="pardon", description="Remove a member from violators until the next check")
    @app_commands.describe(member="Who to pardon")
    @access()
    @commands.guild_only()
    async def pardon(self, ctx: commands.Context, member: discord.Member) -> None:
        if self.state["violators"].pop(str(member.id), None) is None:
            await ctx.send(f"{member.mention} и так не нарушитель.", ephemeral=True,
                           allowed_mentions=discord.AllowedMentions.none())
            return
        self.state.save()
        await ctx.send(f"🕊️ {member.mention} помилован(а) до следующей проверки.",
                       allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Punish(bot))
