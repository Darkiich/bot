"""Простое хранилище состояния в JSON (переживает перезапуски через кэш GitHub Actions)."""
import json
import logging
import os
import tempfile
from typing import Any

log = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    "last_meme_ts": 0.0,
    "last_check_ts": 0.0,
    "memes": [],          # [{"id": message_id, "ts": unix_time}]
    "recent_urls": [],    # чтобы не повторять одни и те же мемы
    "violators": {},      # {user_id: {"missed": int, "total": int, "ts": unix_time}}
    "punish_mode": "off", # "poop" — заменять сообщения какашками, "off" — не заменять
}


class State:
    def __init__(self, path: str):
        self.path = path
        self.data: dict[str, Any] = {k: (v.copy() if isinstance(v, (list, dict)) else v) for k, v in DEFAULTS.items()}
        self.load()

    def load(self) -> None:
        if not os.path.exists(self.path):
            log.info("Файл состояния %s не найден — начинаю с нуля", self.path)
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data.update(json.load(f))
            log.info("Состояние загружено из %s", self.path)
        except Exception:
            log.exception("Не удалось прочитать %s — начинаю с нуля", self.path)

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path) or ".", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.data[key] = value
