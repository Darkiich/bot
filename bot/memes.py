"""Поиск случайного мема в интернете.

Порядок: библиотека ddgs (Bing/DuckDuckGo с маскировкой под браузер) → свой парсер Bing → свой DuckDuckGo.
"""
import asyncio
import html
import io
import json
import logging
import random
import re
from dataclasses import dataclass

import aiohttp

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8"}
MAX_BYTES = 8 * 1024 * 1024  # лимит вложения Discord без буста — 10 МБ, берём с запасом
EXT = {"image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}
MIN_SIDE = 250  # отсекаем иконки и мелкие превью

# Обложки видео и роликов — это не мемы
BLOCKED_HOSTS = ("ytimg.com", "youtube.com", "youtu.be", "rutube.ru", "tiktok", "vkvideo", "dzen.ru", "twitch")
BLOCKED_WORDS = ("видео", "video", "подборк", "компиляц", "youtube", "ютуб", "tiktok", "тикток", "shorts",
                 "смотреть", "выпуск", "стрим", "серия", "эпизод", "#shorts")


def is_blocked(url: str, title: str = "", page: str = "") -> bool:
    text = f"{url} {page}".lower()
    if any(h in text for h in BLOCKED_HOSTS):
        return True
    t = (title or "").lower()
    return any(w in t for w in BLOCKED_WORDS)


def normalize_image(data: bytes) -> tuple[bytes, str] | None:
    """Проверяет, что картинка целая (декодируется полностью), и приводит к формату, который Discord точно покажет."""
    from PIL import Image

    try:
        im = Image.open(io.BytesIO(data))
        fmt = im.format
        animated_gif = fmt == "GIF" and getattr(im, "is_animated", False)
        im.load()  # полное декодирование — обрезанный файл тут упадёт
    except Exception:
        return None
    if min(im.size) < MIN_SIDE:
        return None
    if fmt == "JPEG":
        return data, "jpg"
    if fmt == "PNG" or (fmt == "GIF" and animated_gif):
        return data, fmt.lower()
    # webp и прочее → PNG (первый кадр), если слишком большой — JPEG
    im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
    out = io.BytesIO()
    im.save(out, "PNG", optimize=True)
    if out.tell() > MAX_BYTES:
        out = io.BytesIO()
        im.convert("RGB").save(out, "JPEG", quality=90)
        return out.getvalue(), "jpg"
    return out.getvalue(), "png"


@dataclass
class Meme:
    url: str
    data: bytes
    filename: str


class MemeSource:
    def __init__(self, query: str):
        self.query = query
        self._session: aiohttp.ClientSession | None = None

    async def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers=HEADERS, timeout=aiohttp.ClientTimeout(total=25)
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ---------- поисковики ----------
    async def search_ddgs(self) -> list[str]:
        from ddgs import DDGS  # импорт здесь, чтобы бот стартовал даже без пакета

        def run() -> list[dict]:
            return DDGS(timeout=20).images(
                self.query, region="ru-ru", safesearch="moderate",
                max_results=100, page=random.randint(1, 3),
            )

        results = await asyncio.to_thread(run)
        return [
            r["image"] for r in results
            if r.get("image") and not is_blocked(r["image"], r.get("title", ""), r.get("url", ""))
        ]

    async def search_bing(self) -> list[str]:
        s = await self.session()
        params = {
            "q": self.query,
            "first": str(random.randint(0, 6) * 35 + 1),  # случайная «страница» выдачи
            "count": "35",
            "mmasync": "1",
            "adlt": "strict",
        }
        async with s.get("https://www.bing.com/images/async", params=params) as r:
            r.raise_for_status()
            text = await r.text()
            status, final_url = r.status, str(r.url)
        urls = []
        for m in re.findall(r'\bm="(\{.*?\})"', text):
            try:
                meta = json.loads(html.unescape(m))
            except ValueError:
                continue
            if meta.get("murl") and not is_blocked(meta["murl"], meta.get("t", ""), meta.get("purl", "")):
                urls.append(meta["murl"])
        if not urls:  # запасной разбор без метаданных
            urls = [u for u in re.findall(r'murl&quot;:&quot;(.*?)&quot;', text) if not is_blocked(html.unescape(u))]
        if not urls:
            title = re.search(r"<title>(.*?)</title>", text, re.S)
            log.warning("Bing: 0 картинок (HTTP %s, %s, %d байт, title=%r)",
                        status, final_url[:120], len(text), title.group(1).strip()[:80] if title else None)
        return [html.unescape(u) for u in urls]

    async def search_ddg(self) -> list[str]:
        s = await self.session()
        async with s.get("https://duckduckgo.com/", params={"q": self.query, "iax": "images", "ia": "images"}) as r:
            text = await r.text()
        m = re.search(r'vqd=["\']?([\d-]+)', text)
        if not m:
            raise RuntimeError("DuckDuckGo: не нашёл vqd-токен")
        params = {"l": "ru-ru", "o": "json", "q": self.query, "vqd": m.group(1), "f": ",,,,,", "p": "1"}
        headers = {
            "Referer": "https://duckduckgo.com/",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
        }
        async with s.get("https://duckduckgo.com/i.js", params=params, headers=headers) as r:
            r.raise_for_status()
            data = await r.json(content_type=None)
        return [
            item["image"] for item in data.get("results", [])
            if item.get("image") and not is_blocked(item["image"], item.get("title", ""), item.get("url", ""))
        ]

    # ---------- скачивание ----------
    async def download(self, url: str) -> Meme | None:
        s = await self.session()
        try:
            async with s.get(url, allow_redirects=True) as r:
                if r.status != 200:
                    return None
                ctype = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if ctype and not ctype.startswith("image/") and ctype != "application/octet-stream":
                    return None
                if int(r.headers.get("Content-Length") or 0) > MAX_BYTES:
                    return None
                buf = bytearray()
                async for chunk in r.content.iter_chunked(64 * 1024):  # читаем файл ЦЕЛИКОМ
                    buf += chunk
                    if len(buf) > MAX_BYTES:
                        return None
        except Exception as e:  # битые ссылки в выдаче — норма
            log.debug("Не скачалось %s: %s", url, e)
            return None
        result = await asyncio.to_thread(normalize_image, bytes(buf))
        if result is None:
            log.debug("Битая/мелкая картинка: %s", url)
            return None
        data, ext = result
        return Meme(url=url, data=data, filename=f"meme.{ext}")

    async def random_meme(self, exclude: set[str] | None = None) -> Meme:
        exclude = exclude or set()
        for search in (self.search_ddgs, self.search_bing, self.search_ddg):
            name = search.__name__.removeprefix("search_")
            try:
                found = [u for u in await search() if u.startswith("http") and u not in exclude]
            except Exception as e:
                log.warning("%s не сработал: %s: %s", name, type(e).__name__, e)
                continue
            log.info("%s: найдено %d картинок", name, len(found))
            random.shuffle(found)
            for url in found[:15]:
                meme = await self.download(url)
                if meme:
                    log.info("%s: скачан мем %s", name, url)
                    return meme
            if found:
                log.warning("%s: ни одна из %d картинок не скачалась", name, min(len(found), 15))
        raise RuntimeError("Не удалось получить мем ни из одного источника (подробности выше в логе)")
