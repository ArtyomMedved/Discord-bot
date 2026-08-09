"""Конфигурация бота: все настройки читаются из .env.

Ничего критичного не хардкодим — только значения по умолчанию.
"""
from __future__ import annotations

import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int = 0) -> int:
    value = os.getenv(name, "")
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _int_list(name: str) -> list[int]:
    value = os.getenv(name, "")
    return [int(x) for x in value.split(",") if x.strip().isdigit()]


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


# === Discord ===
DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
GUILD_ID: int = _int("GUILD_ID")

# === Каналы ===
AFK_CHANNEL_ID: int = _int("AFK_CHANNEL_ID")
AFK_REVIEW_CHANNEL_ID: int = _int("AFK_REVIEW_CHANNEL_ID")
AFK_LOG_CHANNEL_ID: int = _int("AFK_LOG_CHANNEL_ID")
AFK_STATUS_CHANNEL_ID: int = _int("AFK_STATUS_CHANNEL_ID")

# === Роли ===
AFK_ROLE_ID: int = _int("AFK_ROLE_ID")
AFK_REVIEW_ROLE_IDS: list[int] = _int_list("AFK_REVIEW_ROLE_IDS")
ADMIN_ROLE_ID: int = _int("ADMIN_ROLE_ID")
MODERATOR_ROLE_ID: int = _int("MODERATOR_ROLE_ID")

# === Soul-Coins ===
SOUL_COIN_TABLE_CHANNEL_ID: int = _int("SOUL_COIN_TABLE_CHANNEL_ID")
SOUL_COIN_LOG_CHANNEL_ID: int = _int("SOUL_COIN_LOG_CHANNEL_ID")
# Роль Leader — участники с ней (и с ADMIN_ROLE_ID) не попадают в таблицу
LEADER_ROLE_ID: int = _int("LEADER_ROLE_ID")
# Минимальная норма в месяц (по умолчанию 60)
SOUL_COIN_NORM: int = _int("SOUL_COIN_NORM", 60)
# Единственная роль, выдаваемая при ежемесячном сокращении
SOUL_COIN_REDUCED_ROLE_ID: int = _int("SOUL_COIN_REDUCED_ROLE_ID")
# За сколько дней до конца месяца слать предупреждения о невыполненной норме
SOUL_COIN_WARNING_DAYS: int = _int("SOUL_COIN_WARNING_DAYS", 7)

# === Верификация ===
VERIFY_CHANNEL_ID: int = _int("VERIFY_CHANNEL_ID")
VERIFY_ROLE_ID: int = _int("VERIFY_ROLE_ID")
# Канал для лога новых верификаций (🔒-админ-чат)
VERIFY_LOG_CHANNEL_ID: int = _int("VERIFY_LOG_CHANNEL_ID")
# Префикс в никнейме новичка: "Verf. Angel (Артём)"
VERIFY_NICK_PREFIX: str = os.getenv("VERIFY_NICK_PREFIX", "Verf")

# === Время ===
TIMEZONE_NAME: str = os.getenv("TIMEZONE", "Europe/Berlin")
try:
    TIMEZONE: ZoneInfo = ZoneInfo(TIMEZONE_NAME)
except Exception:  # некорректная зона — откат на UTC
    TIMEZONE = ZoneInfo("UTC")

MAX_AFK_DAYS: int = _int("MAX_AFK_DAYS", 30)
MIN_AFK_MINUTES: int = _int("MIN_AFK_MINUTES", 30)
CHECK_INTERVAL_SECONDS: int = max(15, _int("CHECK_INTERVAL_SECONDS", 60))

# === Команды ===
SYNC_GLOBALLY: bool = _bool("SYNC_GLOBALLY", False)
