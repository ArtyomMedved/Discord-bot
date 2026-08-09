"""Бизнес-логика системы Soul-Coins.

Таблица баллов в чате «Таблица баллов», начисления — кнопками модераторов
(+/− с выбором игрока и причиной), логи — в админ-чат «лог-баллов».
В конце каждого месяца бот проверяет норму: тем, кто её не выполнил,
снимает все снимаемые роли и выдаёт единственную роль «сокращён».
"""
from __future__ import annotations

import logging

import discord

import config
from database import db
from services.base import ChannelMixin
from utils import embeds, validators
from utils.errors import AfkError, ValidationError
from utils.permissions import require_moderator

logger = logging.getLogger(__name__)

GENERIC_ERROR = (
    "❌ Произошла внутренняя ошибка.\n\n"
    "Попробуйте ещё раз или обратитесь к администрации."
)

MAX_POINTS_PER_ACTION = 999


class SoulCoinService(ChannelMixin):
    def __init__(self, bot: discord.Client) -> None:
        self.bot = bot

    # ---------- участники ----------

    def _excluded_role_ids(self) -> set[int]:
        excluded = {config.ADMIN_ROLE_ID, config.LEADER_ROLE_ID}
        excluded.discard(0)
        return excluded

    def is_excluded(self, member: discord.Member) -> bool:
        """Боты и участники с ролями Leader/Admin не отслеживаются."""
        if member.bot:
            return True
        return bool({r.id for r in member.roles} & self._excluded_role_ids())

    def tracked_members(self) -> list[discord.Member]:
        guild = self.resolve_guild()
        if guild is None:
            return []
        return [m for m in guild.members if not self.is_excluded(m)]

    def current_month(self) -> str:
        return validators.month_key()

    # ---------- таблица ----------

    async def build_rows(self) -> list[tuple[str, int, bool]]:
        """(ник, баланс, под_сокращением) для всех отслеживаемых, отсортировано.

        Балансы читаются одним запросом, чтобы не делать запрос на каждого
        игрока — таблица пересобирается каждую минуту.
        """
        month = self.current_month()
        balances = {
            row["user_id"]: row["balance"]
            for row in await db.list_soul_balances(month)
        }
        rows = []
        for member in self.tracked_members():
            balance = balances.get(member.id, 0)
            rows.append((member.display_name, balance, balance < config.SOUL_COIN_NORM))
        rows.sort(key=lambda r: (-r[1], r[0].lower()))
        return rows

    def _panel_view(self):
        from cogs.soul_views import SoulPanelView

        return SoulPanelView(self)

    async def update_table(self) -> None:
        """Пересобирает таблицу и правит существующее сообщение (или создаёт новое)."""
        if not config.SOUL_COIN_TABLE_CHANNEL_ID:
            return  # не настроено — молча пропускаем (обновляется раз в минуту)
        channel = await self.get_channel(config.SOUL_COIN_TABLE_CHANNEL_ID)
        if channel is None:
            logger.warning("Канал таблицы баллов (SOUL_COIN_TABLE_CHANNEL_ID) не найден")
            return
        rows = await self.build_rows()
        under = sum(1 for _, _, u in rows if u)
        summary = f"Игроков: {len(rows)} · Выполнили норму: {len(rows) - under} · Под сокращением: {under}"
        embed = embeds.soul_table_embed(
            rows,
            validators.month_label(validators.month_key()),
            config.SOUL_COIN_NORM,
            summary,
        )
        view = self._panel_view()
        message_id = await db.get_setting("soul_table_message_id")
        if message_id:
            try:
                message = await channel.fetch_message(int(message_id))
                await message.edit(embed=embed, view=view)
                return
            except discord.NotFound:
                await db.set_setting("soul_table_message_id", None)
            except discord.HTTPException:
                logger.exception("Не удалось обновить таблицу баллов")
                return
        try:
            message = await channel.send(embed=embed, view=view)
            await db.set_setting("soul_table_message_id", str(message.id))
        except discord.HTTPException:
            logger.exception("Не удалось создать таблицу баллов")

    # ---------- начисление / списание ----------

    async def apply_points(self, interaction, user_id: int, delta: int, reason: str) -> None:
        """Модератор начисляет/списывает баллы. Отвечает в interaction."""
        embed = None
        try:
            require_moderator(interaction.user)
            embed = await self._apply(user_id, delta, reason, interaction.user)
        except AfkError as exc:
            await self._respond_error(interaction, exc.message)
            return
        except Exception:
            logger.exception("Ошибка при изменении баллов")
            await self._respond_error(interaction, GENERIC_ERROR)
            return

        try:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except (discord.InteractionResponded, discord.HTTPException):
            try:
                await interaction.followup.send(embed=embed, ephemeral=True)
            except Exception:
                pass

    async def _apply(self, user_id: int, delta: int, reason: str, moderator):
        if delta == 0 or abs(delta) > MAX_POINTS_PER_ACTION:
            raise ValidationError(f"❌ Сумма баллов должна быть от 1 до {MAX_POINTS_PER_ACTION}.")
        if not reason or not reason.strip():
            raise ValidationError("❌ Укажите причину начисления.")

        guild = self.resolve_guild()
        if guild is None:
            raise AfkError("❌ Не найден сервер.")
        member = guild.get_member(user_id)
        if member is None:
            raise AfkError("❌ Игрок не найден на сервере.")
        if self.is_excluded(member):
            raise AfkError("❌ У этого игрока роль Leader/Admin — его нельзя менять в таблице.")

        month = self.current_month()
        balance = await db.get_soul_balance(user_id, month)
        new_balance = balance + delta
        created_at = validators.utc_iso(validators.now_utc())
        await db.add_soul_transaction(
            user_id=user_id,
            guild_id=guild.id,
            month_key=month,
            change=delta,
            balance=new_balance,
            reason=reason.strip(),
            moderator_id=moderator.id,
            created_at=created_at,
        )
        # подтверждение для модератора
        sign = "+" if delta >= 0 else ""
        confirm = embeds.simple_embed(
            "✅ Баллы начислены" if delta > 0 else "➖ Баллы списаны",
            f"{embeds.member_mention(user_id)} — {sign}{delta} 🪙 · баланс: {new_balance} 🪙",
            embeds.COLOR_APPROVED if delta > 0 else embeds.COLOR_REJECTED,
        )
        # лог в админ-чат
        await self.send_to_channel(
            config.SOUL_COIN_LOG_CHANNEL_ID,
            embed=embeds.soul_log_embed(
                user_id, delta, new_balance, reason.strip(), moderator, created_at
            ),
        )
        await self.update_table()
        return confirm

    async def _respond_error(self, interaction, message: str, deferred: bool = False) -> None:
        embed = embeds.error_embed(message)
        try:
            if deferred:
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception:
            try:
                await interaction.followup.send(embed=embed, ephemeral=True)
            except Exception:
                pass

    # ---------- итоги месяца ----------

    async def finalize_month(self) -> bool:
        """Проверяет смену месяца и проводит сокращение. Идемпотентна.

        Возвращает True, если был закрыт какой-то месяц.
        """
        stored = await db.get_setting("soul_month_key")
        current = self.current_month()
        if stored is None:
            # первый запуск — просто фиксируем текущий месяц
            await db.set_setting("soul_month_key", current)
            return False
        if stored == current:
            return False  # месяц ещё не закончился

        guild = self.resolve_guild()
        if guild is None:
            logger.warning("Гильдия не найдена — итоги месяца не подведены")
            return False

        under_list: list[tuple[int, int]] = []
        restored = 0
        reduced_role = guild.get_role(config.SOUL_COIN_REDUCED_ROLE_ID)
        for member in self.tracked_members():
            balance = await db.get_soul_balance(member.id, stored)
            if balance < config.SOUL_COIN_NORM:
                await self._apply_reduction(member)
                under_list.append((member.id, balance))
            elif reduced_role is not None and reduced_role in member.roles:
                # норму выполнил — убираем маркер «сокращён», если был
                try:
                    await member.remove_roles(reduced_role, reason="Норма Soul-Coins выполнена")
                    restored += 1
                except discord.HTTPException:
                    logger.exception("Не удалось снять роль «сокращён» у %s", member)

        await self.send_to_channel(
            config.SOUL_COIN_LOG_CHANNEL_ID,
            embed=embeds.soul_finalize_report_embed(
                validators.month_label(stored), under_list, config.SOUL_COIN_NORM
            ),
        )
        # Сброс на новый месяц — атомарно с фиксацией месяца (см. database.reset_soul_balances).
        await db.reset_soul_balances(current, guild_id=guild.id)
        await self.update_table()
        logger.info(
            "Месяц %s подведён: под сокращение попали %d, маркеров снято %d",
            stored, len(under_list), restored,
        )
        return True

    async def _apply_reduction(self, member: discord.Member) -> None:
        """Снимает с игрока все снимаемые роли и выдаёт роль «сокращён»."""
        to_remove = []
        bot_top = member.guild.me.top_role
        for role in list(member.roles):
            if role.is_default() or role.is_managed():
                continue
            if role >= bot_top:  # роль выше/на уровне роли бота — не может снять
                continue
            to_remove.append(role)
        if to_remove:
            try:
                await member.remove_roles(*to_remove, reason="Не выполнена норма Soul-Coins")
            except discord.HTTPException:
                logger.exception("Не удалось снять роли у %s", member)
        reduced_role = member.guild.get_role(config.SOUL_COIN_REDUCED_ROLE_ID)
        if reduced_role is not None and reduced_role not in member.roles:
            try:
                await member.add_roles(reduced_role, reason="Не выполнена норма Soul-Coins")
            except discord.HTTPException:
                logger.exception("Не удалось выдать роль «сокращён» %s", member)

    # ---------- предупреждения ----------

    async def maybe_warn(self) -> None:
        """Раз в день, в последние SOUL_COIN_WARNING_DAYS дней месяца — напоминание."""
        days_left = validators.days_to_end_of_month()
        if days_left > config.SOUL_COIN_WARNING_DAYS:
            return
        today = validators.now_utc().astimezone(config.TIMEZONE).strftime("%Y-%m-%d")
        warned = await db.get_setting("soul_warn_date")
        if warned == today:
            return

        month = self.current_month()
        under: list[tuple[int, int]] = []
        for member in self.tracked_members():
            balance = await db.get_soul_balance(member.id, month)
            if balance < config.SOUL_COIN_NORM:
                under.append((member.id, balance))

        if under:
            await self.send_to_channel(
                config.SOUL_COIN_LOG_CHANNEL_ID,
                embed=embeds.soul_warning_embed(days_left, config.SOUL_COIN_NORM, under),
            )
        await db.set_setting("soul_warn_date", today)

    # ---------- просмотр ----------

    async def soul_status(self, user_id: int) -> dict:
        month = self.current_month()
        balance = await db.get_soul_balance(user_id, month)
        return {
            "balance": balance,
            "month": month,
            "under": balance < config.SOUL_COIN_NORM,
        }

    async def soul_history(self, user_id: int, limit: int = 20) -> list[dict]:
        return await db.get_soul_logs(user_id, limit)

    # ---------- запуск ----------

    async def on_startup(self) -> None:
        """После перезапуска: закрыть месяц при необходимости, обновить таблицу, вернуть кнопки."""
        await self.finalize_month()
        await self.update_table()
        # persistent-view кнопок таблицы — работает после перезапуска
        self.bot.add_view(self._panel_view())
