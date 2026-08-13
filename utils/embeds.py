"""Все embed-сообщения бота: единый стиль, emoji, цвета."""
from __future__ import annotations

from datetime import datetime

from discord import Color, Embed

from database import (
    STATUS_APPROVED,
    STATUS_CANCELLED,
    STATUS_EXPIRED,
    STATUS_PENDING,
    STATUS_REJECTED,
)
from utils.validators import discord_timestamp, format_local, parse_iso

# === Цвета статусов ===
COLOR_PENDING = Color.from_rgb(241, 196, 15)
COLOR_APPROVED = Color.from_rgb(46, 204, 113)
COLOR_REJECTED = Color.from_rgb(231, 76, 60)
COLOR_CANCELLED = Color.from_rgb(149, 165, 166)
COLOR_EXPIRED = Color.from_rgb(52, 152, 219)
COLOR_INFO = Color.from_rgb(52, 152, 219)
COLOR_ERROR = Color.from_rgb(231, 76, 60)
COLOR_SUCCESS = COLOR_APPROVED

STATUS_META = {
    STATUS_PENDING: {"emoji": "🟡", "label": "На рассмотрении", "color": COLOR_PENDING},
    STATUS_APPROVED: {"emoji": "🟢", "label": "Одобрено", "color": COLOR_APPROVED},
    STATUS_REJECTED: {"emoji": "🔴", "label": "Отклонено", "color": COLOR_REJECTED},
    STATUS_CANCELLED: {"emoji": "⚪", "label": "Отменено", "color": COLOR_CANCELLED},
    STATUS_EXPIRED: {"emoji": "🔵", "label": "Завершён", "color": COLOR_EXPIRED},
}

TITLES = {
    STATUS_PENDING: "💤 НОВАЯ ЗАЯВКА НА АФК",
    STATUS_APPROVED: "💤 ЗАЯВКА НА АФК",
    STATUS_REJECTED: "💤 ЗАЯВКА ОТКЛОНЕНА",
    STATUS_CANCELLED: "💤 АФК ОТМЕНЁН",
    STATUS_EXPIRED: "💤 АФК ЗАВЕРШЁН",
}


def truncate(text, length: int = 1000) -> str:
    text = str(text or "").strip()
    if not text:
        return "—"
    if len(text) <= length:
        return text
    return text[: length - 1] + "…"


def status_meta(status: str) -> dict:
    return STATUS_META.get(status, STATUS_META[STATUS_PENDING])


def status_emoji(status: str) -> str:
    return status_meta(status)["emoji"]


def status_label(status: str) -> str:
    return status_meta(status)["label"]


def status_text(status: str) -> str:
    meta = status_meta(status)
    return f"{meta['emoji']} {meta['label']}"


def color_for(status: str) -> Color:
    return status_meta(status)["color"]


def member_mention(user_id: int) -> str:
    return f"<@{user_id}>"


def _safe_time(value) -> datetime | None:
    try:
        return parse_iso(value)
    except (TypeError, ValueError):
        return None


def _time_value(end_time: str) -> str:
    dt = _safe_time(end_time)
    if dt is None:
        return "—"
    return f"{format_local(dt)}\n({discord_timestamp(dt, 'F')})"


def request_embed(afk: dict, guild=None) -> Embed:
    """Embed заявки: любой статус."""
    status = afk["status"]
    embed = Embed(title=TITLES.get(status, TITLES[STATUS_PENDING]), color=color_for(status))
    embed.add_field(name="👤 Игрок", value=member_mention(afk["user_id"]), inline=True)
    embed.add_field(name="📅 До", value=_time_value(afk["end_time"]), inline=True)
    embed.add_field(name="📝 Причина", value=truncate(afk.get("reason"), 900), inline=False)
    embed.add_field(name="🕐 Заявка создана", value=_time_value(afk.get("created_at")), inline=True)
    embed.add_field(name="Статус", value=status_text(status), inline=True)
    if afk.get("reviewed_by"):
        label = "Одобрил" if status == STATUS_APPROVED else "Модератор"
        embed.add_field(name=label, value=member_mention(afk["reviewed_by"]), inline=True)
    if afk.get("rejection_reason"):
        embed.add_field(name="Причина отказа", value=truncate(afk["rejection_reason"], 900), inline=False)
    return embed


def user_confirmation_embed(afk: dict) -> Embed:
    """Эфемерное подтверждение игроку после создания заявки."""
    embed = Embed(title="✅ Заявка на АФК создана.", color=COLOR_PENDING)
    embed.add_field(name="До", value=_time_value(afk["end_time"]), inline=False)
    embed.add_field(name="Причина", value=truncate(afk.get("reason"), 900), inline=False)
    embed.add_field(name="Статус", value="🟡 На рассмотрении", inline=False)
    return embed


def panel_embed() -> Embed:
    """Панель на специальном канале."""
    embed = Embed(title="💤 Система АФК", color=COLOR_INFO)
    embed.description = (
        "Если вам необходимо временно отсутствовать, создайте заявку на АФК.\n\n"
        "Укажите время, до которого вы будете отсутствовать, и причину."
    )
    return embed


def status_table_embed(active: list[dict], guild=None) -> Embed:
    """Постоянно обновляемая таблица активных АФК."""
    embed = Embed(title="💤 АКТИВНЫЕ АФК", color=COLOR_APPROVED)
    if not active:
        embed.description = "🟢 Сейчас никто не находится в АФК."
        return embed

    lines = []
    for afk in active:
        end = _safe_time(afk.get("end_time"))
        if end is None:
            time_part = "—"
        else:
            time_part = f"до {format_local(end)} {discord_timestamp(end, 'R')}"
        lines.append(
            f"**{member_mention(afk['user_id'])}** — {time_part}\n"
            f"└ {truncate(afk.get('reason'), 60)}"
        )
    embed.description = "\n\n".join(lines)
    embed.set_footer(text=f"Всего активных АФК: {len(active)}")
    return embed


def active_list_embed(active: list[dict], guild=None) -> Embed:
    """Список активных АФК для команды /afk_status и кнопки «Статус АФК»."""
    embed = Embed(title="💤 Активные АФК", color=COLOR_APPROVED)
    if not active:
        embed.description = "🟢 Сейчас никто не находится в АФК."
        return embed

    lines = []
    for afk in active:
        end = _safe_time(afk.get("end_time"))
        time_part = format_local(end) if end is not None else "—"
        lines.append(
            f"{status_emoji(afk['status'])} **{member_mention(afk['user_id'])}**\n"
            f"До: {time_part}\n"
            f"Причина: {truncate(afk.get('reason'), 120)}"
        )
    embed.description = "\n\n".join(lines)
    return embed


def my_afk_embed(afk: dict) -> Embed:
    embed = Embed(title="💤 Ваш АФК", color=color_for(afk["status"]))
    embed.add_field(name="Статус", value=status_text(afk["status"]), inline=False)
    embed.add_field(name="До", value=_time_value(afk["end_time"]), inline=False)
    embed.add_field(name="Причина", value=truncate(afk.get("reason"), 900), inline=False)
    if afk.get("rejection_reason"):
        embed.add_field(name="Причина отказа", value=truncate(afk["rejection_reason"], 900), inline=False)
    return embed


def cancel_confirm_embed(afk: dict) -> Embed:
    embed = Embed(title="Вы действительно хотите отменить АФК?", color=COLOR_ERROR)
    embed.add_field(name="До", value=_time_value(afk["end_time"]), inline=False)
    embed.add_field(name="Причина", value=truncate(afk.get("reason"), 900), inline=False)
    return embed


def admin_menu_embed() -> Embed:
    embed = Embed(title="⚙️ Административное меню АФК", color=COLOR_INFO)
    embed.description = "Выберите действие кнопками ниже."
    return embed


def afk_list_embed(afks: list[dict], status: str | None = None, guild=None) -> Embed:
    if status:
        title = f"📋 Заявки АФК · {status_label(status)}"
    else:
        title = "📋 Все заявки АФК"
    embed = Embed(title=title, color=COLOR_INFO)
    if not afks:
        embed.description = "Заявок не найдено."
        return embed

    lines = []
    for afk in afks:
        end = _safe_time(afk.get("end_time"))
        time_part = format_local(end) if end is not None else "—"
        lines.append(
            f"{status_emoji(afk['status'])} **{member_mention(afk['user_id'])}** · до "
            f"{time_part} · {truncate(afk.get('reason'), 40)}"
        )
    embed.description = "\n".join(lines)
    embed.set_footer(text=f"Показано заявок: {len(afks)}")
    return embed


def approve_confirm_embed(afk: dict) -> Embed:
    embed = Embed(title="🟢 Заявка одобрена", color=COLOR_APPROVED)
    embed.add_field(name="Игрок", value=member_mention(afk["user_id"]), inline=True)
    embed.add_field(name="До", value=_time_value(afk["end_time"]), inline=True)
    return embed


def reject_confirm_embed(afk: dict) -> Embed:
    embed = Embed(title="🔴 Заявка отклонена", color=COLOR_REJECTED)
    embed.add_field(name="Игрок", value=member_mention(afk["user_id"]), inline=True)
    embed.add_field(name="Причина", value=truncate(afk.get("rejection_reason"), 900), inline=False)
    return embed


def remove_success_embed(afk: dict) -> Embed:
    embed = Embed(title="⚪ АФК снят", color=COLOR_CANCELLED)
    embed.add_field(name="Игрок", value=member_mention(afk["user_id"]), inline=True)
    embed.add_field(name="Статус", value=status_text(afk["status"]), inline=True)
    return embed


def user_notification_embed(afk: dict) -> Embed:
    """DM игроку в зависимости от статуса."""
    status = afk["status"]
    if status == STATUS_APPROVED:
        embed = Embed(title="🟢 Ваш АФК одобрен", color=COLOR_APPROVED)
        embed.description = f"Вы получили роль AFK.\n\n**До:** {_time_value(afk['end_time'])}"
    elif status == STATUS_REJECTED:
        embed = Embed(title="❌ Заявка на АФК отклонена", color=COLOR_REJECTED)
        embed.add_field(name="Причина", value=truncate(afk.get("rejection_reason"), 900), inline=False)
        if afk.get("reviewed_by"):
            embed.add_field(name="Модератор", value=member_mention(afk["reviewed_by"]), inline=False)
    elif status == STATUS_EXPIRED:
        embed = Embed(title="⏰ Ваш АФК завершён", color=COLOR_EXPIRED)
        embed.description = "Вы больше не числитесь в АФК."
    elif status == STATUS_CANCELLED:
        embed = Embed(title="⚪ Ваш АФК отменён", color=COLOR_CANCELLED)
        if afk.get("reviewed_by"):
            embed.add_field(name="Кем отменён", value=member_mention(afk["reviewed_by"]), inline=False)
    else:
        embed = Embed(title="💤 Статус вашей заявки", color=color_for(status))
        embed.add_field(name="Статус", value=status_text(status), inline=False)
        embed.add_field(name="До", value=_time_value(afk["end_time"]), inline=False)
    return embed


def log_embed(event: str, afk: dict, moderator=None, reason: str | None = None) -> Embed:
    """Запись в лог-канал."""
    player = member_mention(afk["user_id"])
    moderator_text = member_mention(moderator.id) if moderator is not None else "—"
    end = _safe_time(afk.get("end_time"))
    end_text = format_local(end) if end is not None else "—"

    if event == "creation":
        embed = Embed(title="📝 Создана заявка", color=COLOR_INFO)
        embed.add_field(name="Игрок", value=player, inline=True)
        embed.add_field(name="До", value=end_text, inline=True)
        embed.add_field(name="Причина", value=truncate(afk.get("reason"), 900), inline=False)
    elif event == "approval":
        embed = Embed(title="🟢 Заявка одобрена", color=COLOR_APPROVED)
        embed.add_field(name="Игрок", value=player, inline=True)
        embed.add_field(name="Модератор", value=moderator_text, inline=True)
        embed.add_field(name="До", value=end_text, inline=False)
    elif event == "rejection":
        embed = Embed(title="🔴 Заявка отклонена", color=COLOR_REJECTED)
        embed.add_field(name="Игрок", value=player, inline=True)
        embed.add_field(name="Модератор", value=moderator_text, inline=True)
        embed.add_field(name="Причина", value=truncate(reason or afk.get("rejection_reason"), 900), inline=False)
    elif event == "expiration":
        embed = Embed(title="⏰ АФК завершён", color=COLOR_EXPIRED)
        embed.add_field(name="Игрок", value=player, inline=True)
        embed.add_field(name="Время окончания", value=end_text, inline=False)
    elif event == "cancellation":
        embed = Embed(title="⚪ АФК отменён", color=COLOR_CANCELLED)
        embed.add_field(name="Игрок", value=player, inline=True)
        embed.add_field(name="Кем отменён", value=moderator_text, inline=False)
    elif event == "removal":
        embed = Embed(title="⚪ АФК снят принудительно", color=COLOR_CANCELLED)
        embed.add_field(name="Игрок", value=player, inline=True)
        embed.add_field(name="Кем отменён", value=moderator_text, inline=False)
    else:
        embed = Embed(title="ℹ️ Событие", color=COLOR_INFO)
        embed.add_field(name="Игрок", value=player, inline=True)
    return embed


def error_embed(message: str) -> Embed:
    return Embed(title="❌ Ошибка", description=message, color=COLOR_ERROR)


def simple_embed(title: str, description: str, color: Color = COLOR_INFO) -> Embed:
    return Embed(title=title, description=description, color=color)


# ---------- Soul-Coins ----------


def _soul_table_block(rows: list[tuple[str, int, bool]]) -> str:
    """Моноширинная таблица: Ник | 🪙 | Сокращение."""
    lines = ["Ник                 🪙  Сокращение", "─" * 42]
    for nick, balance, under in rows[:80]:
        lines.append(f"{nick:<20}{balance:>5}   {'Да' if under else 'Нет'}")
    if len(rows) > 80:
        lines.append(f"… и ещё {len(rows) - 80} игроков")
    return "```md\n" + "\n".join(lines) + "\n```"


def soul_table_embed(rows, month_label: str, norm: int, summary: str) -> Embed:
    """Динамическая таблица Soul-Coins в канале «Таблица баллов»."""
    embed = Embed(title="🪙 ТАБЛИЦА SOUL-COINS", color=COLOR_INFO)
    embed.add_field(name="📅 Период", value=month_label, inline=True)
    embed.add_field(name="🎯 Норма в месяц", value=f"{norm} 🪙", inline=True)
    if not rows:
        embed.add_field(name="Игроки", value="Нет игроков для отслеживания.", inline=False)
    else:
        embed.description = _soul_table_block(rows)
    embed.set_footer(text=summary)
    return embed


def soul_self_embed(balance: int, norm: int, month_label: str, under: bool) -> Embed:
    status = "⚠️ Под сокращением" if under else "✅ Норма выполняется"
    embed = Embed(
        title="🪙 Ваши Soul-Coins",
        color=COLOR_REJECTED if under else COLOR_APPROVED,
    )
    embed.add_field(name="📅 Месяц", value=month_label, inline=True)
    embed.add_field(name="🪙 Баланс", value=str(balance), inline=True)
    embed.add_field(name="🎯 Норма", value=f"{norm} 🪙", inline=True)
    embed.add_field(name="Статус", value=status, inline=False)
    return embed


def soul_log_embed(player_id: int, change: int, balance: int, reason: str, moderator, created_at) -> Embed:
    """Запись в админ-чат «лог-баллов»."""
    positive = change >= 0
    embed = Embed(
        title="➕ Начисление баллов" if positive else "➖ Списание баллов",
        color=COLOR_APPROVED if positive else COLOR_REJECTED,
    )
    embed.add_field(name="Игрок", value=member_mention(player_id), inline=True)
    embed.add_field(name="Изменение", value=f"{'+' if positive else ''}{change} 🪙", inline=True)
    embed.add_field(name="Баланс", value=f"{balance} 🪙", inline=True)
    embed.add_field(name="Причина", value=truncate(reason, 900), inline=False)
    if moderator is not None:
        embed.add_field(name="Модератор", value=member_mention(moderator.id), inline=True)
    dt = _safe_time(created_at)
    if dt is not None:
        embed.set_footer(text=f"Время: {format_local(dt)}")
    return embed


def soul_finalize_report_embed(month_label: str, under_list, norm: int) -> Embed:
    """Отчёт по итогам месяца в «лог-баллов»."""
    embed = Embed(title="🪙 Итоги месяца", color=COLOR_EXPIRED)
    embed.add_field(name="📅 Месяц", value=month_label, inline=True)
    embed.add_field(name="🎯 Норма", value=f"{norm} 🪙", inline=True)
    if under_list:
        lines = [f"{member_mention(uid)} — {bal} 🪙" for uid, bal in under_list]
        embed.add_field(
            name=f"❌ Не выполнили норму ({len(under_list)})",
            value=truncate("\n".join(lines), 900),
            inline=False,
        )
    else:
        embed.add_field(name="❌ Не выполнили норму", value="Все выполнили норму! 🎉", inline=False)
    return embed


def soul_warning_embed(days_left: int, norm: int, under_list) -> Embed:
    """Предупреждение за N дней до конца месяца."""
    embed = Embed(title="⚠️ До конца месяца осталось мало времени", color=COLOR_ERROR)
    embed.add_field(name="⏳ Осталось дней", value=str(days_left), inline=True)
    if under_list:
        lines = [f"{member_mention(uid)} — {bal} 🪙" for uid, bal in under_list]
        embed.add_field(
            name=f"📉 Не дотягивают до нормы ({len(under_list)})",
            value=truncate("\n".join(lines), 900),
            inline=False,
        )
    embed.set_footer(text=f"Норма: {norm} 🪙")
    return embed


def soul_history_embed(user_id: int, logs: list[dict], month_label: str) -> Embed:
    """История начислений игрока (/soul_logs)."""
    embed = Embed(title=f"🪙 История баллов — {member_mention(user_id)}", color=COLOR_INFO)
    embed.add_field(name="📅 Месяц", value=month_label, inline=True)
    if not logs:
        embed.add_field(name="Записи", value="Пока нет начислений.", inline=False)
        return embed
    lines = []
    for log in logs:
        change = log["change"]
        sign = "+" if change >= 0 else ""
        lines.append(f"{sign}{change} 🪙 → {log['balance']} 🪙 · {truncate(log.get('reason'), 40)}")
    embed.add_field(name=f"Последние записи ({len(logs)})", value=truncate("\n".join(lines), 900), inline=False)
    return embed


def soul_admin_menu_embed() -> Embed:
    embed = Embed(title="🪙 Админ-меню Soul-Coins", color=COLOR_INFO)
    embed.description = "Выберите действие кнопками ниже."
    return embed


# ---------- Верификация ----------


def verify_panel_embed() -> Embed:
    """Закреплённое сообщение в канале «✅│верификация»."""
    embed = Embed(title="✅ Верификация", color=COLOR_INFO)
    embed.description = (
        "Добро пожаловать в нашу семью! 🎉\n\n"
        "Нажмите кнопку **«Верифицироваться»** ниже и заполните небольшую анкету — "
        "после этого вам будет выдана роль и установлен никнейм."
    )
    return embed


def verify_confirm_embed(in_game: str, real: str, nickname: str) -> Embed:
    """Подтверждение игроку после анкеты (ephemeral)."""
    embed = Embed(title="✅ Вы верифицированы!", color=COLOR_APPROVED)
    embed.add_field(name="Имя в игре", value=truncate(in_game, 100), inline=True)
    embed.add_field(name="Имя в жизни", value=truncate(real, 100), inline=True)
    embed.add_field(name="Ваш никнейм", value=nickname, inline=False)
    return embed


def verify_log_embed(
    member, static: str, in_game: str, real: str, occupation: str, created_at
) -> Embed:
    """Запись о новой верификации в админ-чат."""
    embed = Embed(title="✅ Новая верификация", color=COLOR_APPROVED)
    embed.add_field(name="Игрок", value=member_mention(member.id), inline=True)
    embed.add_field(name="Имя в игре", value=truncate(in_game, 100), inline=True)
    embed.add_field(name="Имя в жизни", value=truncate(real, 100), inline=True)
    embed.add_field(name="Статик", value=truncate(static or "—", 100), inline=True)
    embed.add_field(name="Чем занимается", value=truncate(occupation or "—", 900), inline=False)
    dt = _safe_time(created_at)
    if dt is not None:
        embed.set_footer(text=f"Время: {format_local(dt)}")
    return embed


def verify_info_embed(record: dict, user_id: int) -> Embed:
    """Данные верификации игрока (/verify_info)."""
    embed = Embed(title=f"✅ Верификация — {member_mention(user_id)}", color=COLOR_INFO)
    embed.add_field(name="Имя в игре", value=truncate(record.get("in_game_name"), 100), inline=True)
    embed.add_field(name="Имя в жизни", value=truncate(record.get("real_name"), 100), inline=True)
    embed.add_field(name="Статик", value=truncate(record.get("static") or "—", 100), inline=True)
    embed.add_field(name="Чем занимается", value=truncate(record.get("occupation") or "—", 900), inline=False)
    dt = _safe_time(record.get("created_at"))
    if dt is not None:
        embed.set_footer(text=f"Время: {format_local(dt)}")
    return embed
