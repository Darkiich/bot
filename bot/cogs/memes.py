"""Мемы по расписанию и проверка реакций у участников с ролью."""
import asyncio
import io
import logging
import time
from collections import Counter

import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot import config
from bot.checks import access
from bot.memes import MemeSource

log = logging.getLogger(__name__)
RETRY_AFTER_FAIL = 5 * 60


class Memes(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.state = bot.state
        self.source = MemeSource(config.MEME_QUERY)
        self.lock = asyncio.Lock()

    async def cog_load(self) -> None:
        if not self.state["last_check_ts"]:
            # первый запуск: первая проверка через CHECK_INTERVAL_HOURS, а не сразу
            self.state["last_check_ts"] = time.time()
        if config.MEME_ON_STARTUP:
            self.state["last_meme_ts"] = 0  # мем сразу после запуска
        self.state.save()
        self.ticker.start()

    async def cog_unload(self) -> None:
        self.ticker.cancel()
        await self.source.close()

    async def channel(self) -> discord.TextChannel:
        ch = self.bot.get_channel(config.MEME_CHANNEL_ID)
        return ch or await self.bot.fetch_channel(config.MEME_CHANNEL_ID)

    # ---------- планировщик: тикает раз в минуту, время хранится в state ----------
    @tasks.loop(seconds=60)
    async def ticker(self) -> None:
        now = time.time()
        if now - self.state["last_meme_ts"] >= config.MEME_INTERVAL_SECONDS:
            try:
                await self.post_meme()
            except Exception:
                log.exception("Не удалось отправить мем, повторю через 5 минут")
                self.state["last_meme_ts"] = now - config.MEME_INTERVAL_SECONDS + RETRY_AFTER_FAIL
                self.state.save()
        if now - self.state["last_check_ts"] >= config.CHECK_INTERVAL_SECONDS:
            try:
                await self.run_check()
            except Exception:
                log.exception("Проверка упала, повторю через 5 минут")
                self.state["last_check_ts"] = now - config.CHECK_INTERVAL_SECONDS + RETRY_AFTER_FAIL
                self.state.save()

    @ticker.before_loop
    async def _wait_ready(self) -> None:
        await self.bot.wait_until_ready()

    # ---------- мемы ----------
    async def post_meme(self) -> discord.Message:
        async with self.lock:
            channel = await self.channel()
            meme = await self.source.random_meme(exclude=set(self.state["recent_urls"]))
            msg = await channel.send(file=discord.File(io.BytesIO(meme.data), filename=meme.filename))
            for emoji in config.REACTIONS:
                await msg.add_reaction(emoji)

            now = time.time()
            keep_after = now - 3 * config.CHECK_INTERVAL_SECONDS
            self.state["memes"] = [m for m in self.state["memes"] if m["ts"] > keep_after] + [{"id": msg.id, "ts": now}]
            self.state["recent_urls"] = (self.state["recent_urls"] + [meme.url])[-500:]
            self.state["last_meme_ts"] = now
            self.state.save()
            log.info("Мем отправлен: %s", meme.url)
            return msg

    # ---------- проверка ----------
    async def collect(self, channel: discord.TextChannel, message_ids: list[int]) -> tuple[int, dict, int]:
        """Считает, кто из участников с ролью не отреагировал. Возвращает (мемов, нарушители, проверено участников)."""
        role = channel.guild.get_role(config.WATCHED_ROLE_ID)
        if role is None:
            raise RuntimeError(f"Роль {config.WATCHED_ROLE_ID} не найдена на сервере")
        members = [m for m in role.members if not m.bot]

        reacted: Counter[int] = Counter()
        total = 0
        for mid in message_ids:
            try:
                msg = await channel.fetch_message(mid)
            except discord.NotFound:
                continue  # мем удалили — не считаем
            total += 1
            users: set[int] = set()
            for reaction in msg.reactions:
                async for user in reaction.users():
                    users.add(user.id)
            for uid in users:
                reacted[uid] += 1

        violators = {}
        if total:
            need = total * config.MIN_REACTED_PERCENT / 100
            now = time.time()
            for m in members:
                if reacted[m.id] < need:
                    violators[str(m.id)] = {"missed": total - reacted[m.id], "total": total, "ts": now}
        return total, violators, len(members)

    async def run_check(self) -> tuple[int, dict]:
        async with self.lock:
            now = time.time()
            since = self.state["last_check_ts"] or now - config.CHECK_INTERVAL_SECONDS
            channel = await self.channel()
            ids = [m["id"] for m in self.state["memes"] if since < m["ts"] <= now]
            total, violators, checked = await self.collect(channel, ids)

            self.state["violators"] = violators
            self.state["last_check_ts"] = now
            self.state.save()

            if total:
                await self.send_report(channel, violators, total, checked)
            log.info("Проверка: мемов %d, проверено %d, нарушителей %d", total, checked, len(violators))
            return total, violators

    async def send_report(self, channel, violators: dict, total: int, checked: int, test: bool = False) -> None:
        prefix = "🧪 ТЕСТ · " if test else ""
        if not violators:
            await channel.send(embed=discord.Embed(
                title=f"{prefix}✅ Проверка просмотра мемов",
                description=f"Все {checked} участников с ролью посмотрели мемы ({total} шт.). Нарушений нет.",
                color=discord.Color.green(),
            ))
            return

        lines = [
            f"• <@{uid}> — не просмотрел(а) **{v['missed']}** из {v['total']} мемов"
            for uid, v in sorted(violators.items(), key=lambda kv: -kv[1]["missed"])
        ]
        if test:
            footer = "Тестовая проверка — список нарушителей не изменён"
        elif self.state["punish_mode"] == "poop":
            footer = f"Режим: {config.POOP} сообщения нарушителей заменяются какашками"
        else:
            footer = "Режим: наказание не применяется"

        chunks, cur = [], ""
        for line in lines:  # описание эмбеда ограничено 4096 символами
            if len(cur) + len(line) + 1 > 3800:
                chunks.append(cur)
                cur = ""
            cur += line + "\n"
        chunks.append(cur)
        for i, chunk in enumerate(chunks):
            embed = discord.Embed(
                title=f"{prefix}🚨 Протокол о правонарушении" if i == 0 else None,
                description=("Зафиксирован **не просмотр мемов**. Нарушители:\n\n" if i == 0 else "") + chunk,
                color=discord.Color.red(),
            )
            if i == len(chunks) - 1:
                embed.set_footer(text=footer)
            await channel.send(
                content=" ".join(f"<@{uid}>" for uid in list(violators)[:50]) if i == 0 and not test else None,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(users=not test),
            )

    # ---------- команды ----------
    @commands.hybrid_command(name="meme", description="Post a meme right now")
    @access()
    @commands.guild_only()
    async def meme_now(self, ctx: commands.Context) -> None:
        await ctx.defer(ephemeral=True)
        msg = await self.post_meme()
        await ctx.send(f"Готово: {msg.jump_url}", ephemeral=True)

    @commands.hybrid_command(name="check", description="Run the reaction check right now")
    @access()
    @commands.guild_only()
    async def check_now(self, ctx: commands.Context) -> None:
        await ctx.defer(ephemeral=True)
        total, violators = await self.run_check()
        if not total:
            await ctx.send("С прошлой проверки мемов не было — проверять нечего.", ephemeral=True)
        else:
            await ctx.send(f"Проверено мемов: {total}, нарушителей: {len(violators)}.", ephemeral=True)

    @commands.hybrid_command(name="test", description="Quick test: post a meme, wait, then check reactions on it")
    @app_commands.describe(seconds="How long to wait for reactions (10-600 s)")
    @access()
    @commands.guild_only()
    async def test(self, ctx: commands.Context, seconds: commands.Range[int, 10, 600] = 60) -> None:
        await ctx.defer()
        channel = await self.channel()
        role = channel.guild.get_role(config.WATCHED_ROLE_ID)
        lines = [
            f"Канал: {channel.mention}",
            f"Роль: {role.mention if role else '❌ не найдена'} (участников: {len([m for m in role.members if not m.bot]) if role else 0})",
            f"Режим наказания: {self.state['punish_mode']}",
        ]
        try:
            msg = await self.post_meme()
        except Exception as e:
            await ctx.send("\n".join(lines + [f"❌ Мем не получилось найти/отправить: {e}"]),
                           allowed_mentions=discord.AllowedMentions.none())
            return
        await ctx.send(
            "\n".join(lines + [f"✅ Мем отправлен: {msg.jump_url}",
                               f"⏳ Ставьте реакции — проверю этот мем через {seconds} сек."]),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await asyncio.sleep(seconds)
        total, violators, checked = await self.collect(channel, [msg.id])
        await self.send_report(channel, violators, total, checked, test=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Memes(bot))
