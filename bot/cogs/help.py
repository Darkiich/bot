"""&help — список команд."""
import discord
from discord.ext import commands

from bot import config
from bot.checks import has_access

P = config.PREFIX
PUBLIC = [
    (f"{P}help", "список команд"),
    (f"{P}violators", "текущие нарушители и режим наказания"),
]
ADMIN = [
    (f"{P}punish on", f"заменять сообщения нарушителей на {config.POOP}"),
    (f"{P}punish off", "отозвать наказание (не заменять)"),
    (f"{P}punish", "показать текущий режим"),
    (f"{P}pardon @участник", "снять статус нарушителя до следующей проверки"),
    (f"{P}check", "проверить реакции на мемы прямо сейчас"),
    (f"{P}meme", "отправить мем прямо сейчас"),
    (f"{P}test [секунды]", "тест: мем → ждёт (60 с) → проверка реакций на него"),
]


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="help", description="Show bot commands")
    async def help(self, ctx: commands.Context) -> None:
        fmt = lambda rows: "\n".join(f"`{c}` — {d}" for c, d in rows)
        embed = discord.Embed(
            title="📖 Команды мемного бота",
            description=(
                f"Мем каждые {config.MEME_INTERVAL_SECONDS / 60:g} мин в <#{config.MEME_CHANNEL_ID}>, "
                f"проверка реакций каждые {config.CHECK_INTERVAL_SECONDS / 3600:g} ч.\n"
                f"Команды работают и через `{P}`, и через `/`."
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Для всех", value=fmt(PUBLIC), inline=False)
        access = "✅ у вас есть доступ" if has_access(ctx.author) else "⛔ у вас нет доступа"
        embed.add_field(name=f"Для управляющих ({access})", value=fmt(ADMIN), inline=False)
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Help(bot))
