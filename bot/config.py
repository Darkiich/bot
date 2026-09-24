"""Все настройки берутся из .env (или из переменных окружения)."""
import os

from dotenv import load_dotenv

load_dotenv()

REQUIRED = ["TOKEN", "MEME_CHANNEL_ID", "WATCHED_ROLE_ID"]


def missing() -> list[str]:
    return [k for k in REQUIRED if not os.getenv(k, "").strip()]


def _str(name: str, default: str) -> str:
    return os.getenv(name, "").strip() or default


def _int(name: str, default: int = 0) -> int:
    return int(_str(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(_str(name, str(default)))


def _bool(name: str, default: bool) -> bool:
    return _str(name, str(default)).lower() in ("1", "true", "yes", "on", "да")


TOKEN = _str("TOKEN", "")
PREFIX = _str("PREFIX", "&")

MEME_CHANNEL_ID = _int("MEME_CHANNEL_ID")
WATCHED_ROLE_ID = _int("WATCHED_ROLE_ID")

MEME_QUERY = _str("MEME_QUERY", "2026 meme")
MEME_INTERVAL_SECONDS = _float("MEME_INTERVAL_MINUTES", 400) * 60
CHECK_INTERVAL_SECONDS = _float("CHECK_INTERVAL_HOURS", 8) * 3600
MIN_REACTED_PERCENT = _float("MIN_REACTED_PERCENT", 100)
MEME_ON_STARTUP = _bool("MEME_ON_STARTUP", False)

REACTIONS = [e.strip() for e in _str("REACTIONS", "😂,💩").split(",") if e.strip()]
POOP = _str("PUNISH_EMOJI", "💩")

# Кто может пользоваться админ-командами: ID ролей и/или пользователей через запятую
COMMAND_ACCESS_IDS = {int(x) for x in _str("COMMAND_ACCESS_IDS", "").replace(" ", "").split(",") if x}

STATE_FILE = _str("STATE_FILE", "data/state.json")
MAX_RUNTIME_SECONDS = _float("MAX_RUNTIME_SECONDS", 0)
