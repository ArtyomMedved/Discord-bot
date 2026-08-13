"""Валидация ввода и работа с датами.

В БД даты в UTC (ISO-8601), юзеру показываем в поясе сервера
(config.TIMEZONE).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import config
from utils.errors import ValidationError

DATETIME_FORMAT = "%d.%m.%Y %H:%M"

RUS_MONTHS = [
    None, "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]

FORMAT_HELP = (
    "❌ Неверный формат даты.\n\n"
    "Используйте:\n\n"
    "DD.MM.YYYY HH:MM\n\n"
    "Пример:\n"
    "10.08.2026 18:30"
)


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def parse_datetime(value: str) -> datetime:
    """Разбирает 'DD.MM.YYYY HH:MM' как локальное время сервера."""
    text = value.strip()
    try:
        naive = datetime.strptime(text, DATETIME_FORMAT)
    except ValueError:
        raise ValidationError(FORMAT_HELP)
    return naive.replace(tzinfo=config.TIMEZONE)


def validate_afk_duration(local_dt: datetime) -> None:
    """Проверяем срок АФК: не в прошлом, не слишком короткий/длинный."""
    local_now = now_utc().astimezone(config.TIMEZONE)
    if local_dt <= local_now:
        raise ValidationError("❌ Нельзя создать АФК до времени, которое уже прошло.")
    diff = local_dt - local_now
    if diff < timedelta(minutes=config.MIN_AFK_MINUTES):
        raise ValidationError(f"❌ Минимальный срок АФК — {config.MIN_AFK_MINUTES} минут.")
    if diff > timedelta(days=config.MAX_AFK_DAYS):
        raise ValidationError(f"❌ Максимальный срок АФК — {config.MAX_AFK_DAYS} дней.")


def format_local(dt: datetime) -> str:
    return dt.astimezone(config.TIMEZONE).strftime(DATETIME_FORMAT)


def discord_timestamp(dt: datetime, style: str = "F") -> str:
    return f"<t:{int(dt.timestamp())}:{style}>"


def display_datetime(dt: datetime) -> str:
    """Локальное время сервера + Discord timestamp (в поясе юзера)."""
    return f"{format_local(dt)}\n({discord_timestamp(dt, 'F')})"


def month_key(dt: datetime | None = None) -> str:
    """Ключ месяца 'YYYY-MM' в поясе сервера."""
    dt = dt or now_utc()
    return dt.astimezone(config.TIMEZONE).strftime("%Y-%m")


def month_label(month_key: str) -> str:
    """'2026-08' -> 'Август 2026'."""
    try:
        year, month = month_key.split("-")
        name = RUS_MONTHS[int(month)]
        return f"{name} {year}" if name else month_key
    except (ValueError, IndexError):
        return month_key or "—"


def days_to_end_of_month(dt: datetime | None = None) -> int:
    """Сколько дней осталось до конца месяца (в поясе сервера)."""
    local = (dt or now_utc()).astimezone(config.TIMEZONE)
    year, month = local.year, local.month
    if month == 12:
        last_day = datetime(year, 12, 31, tzinfo=config.TIMEZONE)
    else:
        last_day = datetime(year, month + 1, 1, tzinfo=config.TIMEZONE) - timedelta(days=1)
    last_day = last_day.replace(hour=23, minute=59, second=59, microsecond=0)
    return (last_day.date() - local.date()).days + 1
