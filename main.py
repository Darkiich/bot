"""Точка входа: python main.py"""
import asyncio
import logging
import os
import sys

import aiohttp
import discord
from discord.ext import commands

from bot import config
from bot.state import State

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("main")

EXTENSIONS = ["bot.cogs.memes", "bot.cogs.punish", "bot.cogs.help"]


class MemeBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True          # видеть участников с ролью
        intents.message_content = True  # читать команды с префиксом
        super().__init__(command_prefix=commands.when_mentioned_or(config.PREFIX), intents=intents, help_command=None)
        self.state = State(config.STATE_FILE)

    async def setup_hook(self) -> None:
        for ext in EXTENSIONS:
            await self.load_extension(ext)
        synced = await self.tree.sync()
        log.info("Слэш-команды синхронизированы: %s", ", ".join(c.name for c in synced))
        if config.MAX_RUNTIME_SECONDS > 0:
            self.loop.create_task(self._stop_after(config.MAX_RUNTIME_SECONDS))
        if os.getenv("GITHUB_ACTIONS") == "true" and os.getenv("GITHUB_TOKEN"):
            self.loop.create_task(self._watch_new_deploy())

    async def on_ready(self) -> None:
        log.info("Бот запущен как %s (id %s), префикс %s", self.user, self.user.id, config.PREFIX)

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        error = getattr(error, "original", error)
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.NoPrivateMessage):
            msg = "Команда работает только на сервере."
        elif isinstance(error, commands.CheckFailure):
            msg = "⛔ У вас нет доступа к этой команде."
        elif isinstance(error, (commands.BadArgument, commands.MissingRequiredArgument, commands.BadLiteralArgument)):
            msg = f"❓ Неверные аргументы. Подсказка: `{config.PREFIX}help {ctx.command}`"
        else:
            log.error("Ошибка в команде %s", ctx.command, exc_info=error)
            msg = f"❌ Ошибка: {error}"
        try:
            await ctx.send(msg, ephemeral=True)
        except discord.HTTPException:
            pass

    async def _stop_after(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
        log.info("Лимит времени работы (%.0f c) — завершаюсь для перезапуска", seconds)
        await self.close()

    async def _watch_new_deploy(self) -> None:
        """На GitHub Actions: если появился новый запуск после push/ручного старта — уступаем ему место."""
        repo, run_id = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_RUN_ID"]
        api = f"https://api.github.com/repos/{repo}/actions"
        headers = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json"}
        async with aiohttp.ClientSession(headers=headers) as s:
            try:
                async with s.get(f"{api}/runs/{run_id}") as r:
                    workflow_id = (await r.json())["workflow_id"]
            except Exception as e:
                log.warning("Не удалось узнать workflow_id: %s", e)
                return
            while not self.is_closed():
                await asyncio.sleep(120)
                try:
                    for status in ("pending", "queued", "waiting"):
                        async with s.get(f"{api}/workflows/{workflow_id}/runs", params={"status": status, "per_page": 20}) as r:
                            runs = (await r.json()).get("workflow_runs", [])
                        if any(run["id"] != int(run_id) and run["event"] != "schedule" for run in runs):
                            log.info("Найден новый деплой — завершаюсь, чтобы он запустился")
                            await self.close()
                            return
                except Exception as e:
                    log.warning("Проверка новых запусков не удалась: %s", e)


async def main() -> int:
    if config.missing():
        log.error("В .env не заданы: %s", ", ".join(config.missing()))
        return 2
    bot = MemeBot()
    try:
        async with bot:
            await bot.start(config.TOKEN)
    except discord.LoginFailure:
        log.error("Неверный TOKEN в .env")
        return 2
    except discord.PrivilegedIntentsRequired:
        log.error("Включите в Developer Portal → Bot: Server Members Intent и Message Content Intent")
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(0)
