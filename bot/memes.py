"""Поиск случайного мема в интернете (картинки Bing, запасной вариант — DuckDuckGo)."""
import html
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
        urls = re.findall(r'murl&quot;:&quot;(.*?)&quot;', text)
        if not urls:  # на случай, если кавычки не экранированы
            urls = re.findall(r'"murl":"(.*?)"', text)
        return [html.unescape(u) for u in urls]

    async def search_ddg(self) -> list[str]:
        s = await self.session()
        async with s.get("https://duckduckgo.com/", params={"q": self.query, "iax": "images", "ia": "images"}) as r:
            text = await r.text()
        m = re.search(r'vqd=["\']?([\d-]+)', text)
        if not m:
            raise RuntimeError("DuckDuckGo: не нашёл vqd-токен")
        params = {"l": "ru-ru", "o": "json", "q": self.query, "vqd": m.group(1), "f": ",,,,,", "p": "1"}
        async with s.get("https://duckduckgo.com/i.js", params=params, headers={"Referer": "https://duckduckgo.com/"}) as r:
            r.raise_for_status()
            data = await r.json(content_type=None)
        return [item["image"] for item in data.get("results", []) if item.get("image")]

    # ---------- скачивание ----------
    async def download(self, url: str) -> Meme | None:
        s = await self.session()
        try:
            async with s.get(url, allow_redirects=True) as r:
                if r.status != 200:
                    return None
                ctype = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if ctype not in EXT:
                    return None
                if int(r.headers.get("Content-Length") or 0) > MAX_BYTES:
                    return None
                data = await r.content.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES or len(data) < 2048:
                    return None
                return Meme(url=url, data=data, filename=f"meme.{EXT[ctype]}")
        except Exception as e:  # битые ссылки в выдаче — норма
            log.debug("Не скачалось %s: %s", url, e)
            return None

    async def random_meme(self, exclude: set[str] | None = None) -> Meme:
        exclude = exclude or set()
        candidates: list[str] = []
        for search in (self.search_bing, self.search_ddg):
            try:
                found = [u for u in await search() if u.startswith("http") and u not in exclude]
                log.info("%s: найдено %d картинок", search.__name__, len(found))
                candidates = found
            except Exception as e:
                log.warning("%s не сработал: %s", search.__name__, e)
            if candidates:
                break
        if not candidates:
            raise RuntimeError("Не удалось найти ни одного мема")

        random.shuffle(candidates)
        for url in candidates[:10]:
            meme = await self.download(url)
            if meme:
                return meme
        raise RuntimeError("Не удалось скачать ни одну картинку из выдачи")
