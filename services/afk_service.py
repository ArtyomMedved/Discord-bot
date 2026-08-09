"""Бизнес-логика системы АФК.

Сервис не знает про конкретные кнопки и модалки — он принимает
interaction и совершает все операции: работа с БД, выдача ролей,
обновление сообщений, уведомления и логи.
"""
from __future__ import annotations

import logging
from datetime import timezone

import discord

import config
from database import (
    ACTIVE_STATUSES,
    STATUS_APPROVED,
    STATUS_CANCELLED,
    STATUS_EXPIRED,
    STATUS_PENDING,
    db,
)
from services.base import ChannelMixin
from utils import embeds, validators
from utils.errors import (
    AfkError,
    AlreadyActiveError,
    AlreadyProcessedError,
    RequestNotFoundError,
)
from utils.permissions import require_moderator

logger = logging.getLogger(__name__)

GENERIC_ERROR = (
    "❌ Произошла внутренняя ошибка.\n\n"
    "Попробуйте ещё раз или обратитесь к администрации."
)


class AfkService(ChannelMixin):
    def __init__(self, bot: discord.Client) -> None:
        self.bot = bot

    # ---------- инфраструктура ----------

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

    # ---------- роли ----------

    async def grant_afk_role(self, afk: dict) -> None:
        guild = self.bot.get_guild(afk["guild_id"])
        if guild is None:
            return
        role = guild.get_role(config.AFK_ROLE_ID)
        if role is None:
            logger.warning("Роль AFK (ID %s) не найдена на сервере", config.AFK_ROLE_ID)
            return
        member = guild.get_member(afk["user_id"])
        if member is None:
            try:
                member = await guild.fetch_member(afk["user_id"])
            except (discord.NotFound, discord.HTTPException):
                return
        if member is not None and role not in member.roles:
            try:
                await member.add_roles(role, reason="Заявка на АФК одобрена")
            except discord.HTTPException:
                logger.exception("Не удалось выдать роль AFK пользователю %s", afk["user_id"])

    async def remove_afk_role(self, afk: dict) -> None:
        guild = self.bot.get_guild(afk["guild_id"])
        if guild is None:
            return
        role = guild.get_role(config.AFK_ROLE_ID)
        if role is None:
            return
        member = guild.get_member(afk["user_id"])
        if member is None:
            return
        if role in member.roles:
            try:
                await member.remove_roles(role, reason="АФК завершён/отменён")
            except discord.HTTPException:
                logger.exception("Не удалось снять роль AFK у пользователя %s", afk["user_id"])

    # ---------- сообщения ----------

    async def edit_afk_message(self, afk: dict, embed) -> None:
        """Обновляет исходное сообщение заявки (если оно ещё существует)."""
        if not afk.get("message_id") or not afk.get("channel_id"):
            return
        channel = await self.get_channel(afk["channel_id"])
        if channel is None:
            return
        try:
            message = await channel.fetch_message(afk["message_id"])
            await message.edit(embed=embed, view=None)
        except discord.NotFound:
            logger.info("Сообщение заявки #%s удалено, редактирование пропущено", afk["id"])
        except discord.HTTPException:
            logger.exception("Не удалось отредактировать сообщение заявки #%s", afk["id"])

    async def notify_user(self, afk: dict) -> None:
        """Отправляет игроку DM. Ошибки DM не считаем критическими."""
        user = self.bot.get_user(afk["user_id"])
        if user is None:
            try:
                user = await self.bot.fetch_user(afk["user_id"])
            except Exception:
                return
        try:
            await user.send(embed=embeds.user_notification_embed(afk))
        except Exception:
            logger.info("Не удалось отправить DM пользователю %s", afk["user_id"])

    async def log_event(
        self,
        event: str,
        afk: dict,
        moderator=None,
        reason: str | None = None,
    ) -> None:
        channel = await self.get_channel(config.AFK_LOG_CHANNEL_ID)
        if channel is None:
            return
        try:
            await channel.send(embed=embeds.log_embed(event, afk, moderator, reason))
        except discord.HTTPException:
            logger.exception("Не удалось записать лог '%s'", event)

    # ---------- таблица активных АФК ----------

    async def update_status_table(self) -> None:
        channel = await self.get_channel(config.AFK_STATUS_CHANNEL_ID)
        if channel is None:
            return
        active = await db.list_approved_afks()
        embed = embeds.status_table_embed(active, self.resolve_guild())

        message_id = await db.get_setting("status_message_id")
        if message_id:
            try:
                message = await channel.fetch_message(int(message_id))
                await message.edit(embed=embed)
                return
            except discord.NotFound:
                await db.set_setting("status_message_id", None)
            except discord.HTTPException:
                logger.exception("Не удалось обновить таблицу АФК")
                return

        try:
            message = await channel.send(embed=embed)
            await db.set_setting("status_message_id", str(message.id))
        except discord.HTTPException:
            logger.exception("Не удалось создать таблицу АФК")

    # ---------- стартовая инициализация ----------

    async def ensure_panel_message(self) -> None:
        from cogs.views import PanelView

        channel = await self.get_channel(config.AFK_CHANNEL_ID)
        if channel is None:
            logger.warning("Канал панели (AFK_CHANNEL_ID) не найден")
            return
        message_id = await db.get_setting("panel_message_id")
        if message_id:
            try:
                message = await channel.fetch_message(int(message_id))
                await message.edit(embed=embeds.panel_embed(), view=PanelView(self))
                return
            except discord.NotFound:
                await db.set_setting("panel_message_id", None)
            except discord.HTTPException:
                logger.exception("Не удалось обновить панель")
                return
        try:
            message = await channel.send(embed=embeds.panel_embed(), view=PanelView(self))
            await db.set_setting("panel_message_id", str(message.id))
        except discord.HTTPException:
            logger.exception("Не удалось создать панель")

    async def restore_views(self) -> None:
        """Перерегистрирует persistent-views для заявок со статусом PENDING."""
        from cogs.views import AfkActionView

        pending = await db.list_afks(status=STATUS_PENDING)
        restored = 0
        for afk in pending:
            if afk.get("message_id"):
                self.bot.add_view(AfkActionView(afk["id"], self), message_id=afk["message_id"])
                restored += 1
        logger.info("Восстановлено views для %d заявок", restored)

    async def sync_roles_and_recover(self) -> None:
        """После перезапуска: выдать роли, завершить уже истёкшие АФК, обновить таблицу."""
        approved = await db.list_approved_afks()
        now = validators.now_utc()
        for afk in approved:
            try:
                end = validators.parse_iso(afk["end_time"])
            except (TypeError, ValueError):
                logger.warning("Повреждённая запись #%s: end_time='%s'", afk["id"], afk["end_time"])
                continue
            if end <= now:
                await self.expire_afk(afk["id"])
            else:
                await self.grant_afk_role(afk)
        await self.update_status_table()

    # ---------- создание заявки ----------

    async def create_afk(self, interaction, raw_date: str, reason: str) -> None:
        try:
            local_dt = validators.parse_datetime(raw_date)
            validators.validate_afk_duration(local_dt)
            existing = await db.get_active_afk_for_user(interaction.user.id)
            if existing:
                raise AlreadyActiveError("⚠️ У вас уже существует активная заявка на АФК.")

            end_utc = local_dt.astimezone(timezone.utc)
            now = validators.now_utc()
            start_iso = validators.utc_iso(now)
            end_iso = validators.utc_iso(end_utc)
            afk_id = await db.create_afk(
                user_id=interaction.user.id,
                guild_id=interaction.guild_id or 0,
                reason=reason.strip(),
                start_time=start_iso,
                end_time=end_iso,
                created_at=start_iso,
            )
        except AfkError as exc:
            await self._respond_error(interaction, exc.message)
            return
        except Exception:
            logger.exception("Ошибка при создании заявки")
            await self._respond_error(interaction, GENERIC_ERROR)
            return

        afk = await db.get_afk(afk_id)
        try:
            await interaction.response.send_message(
                embed=embeds.user_confirmation_embed(afk), ephemeral=True
            )
        except discord.HTTPException:
            logger.exception("Не удалось отправить подтверждение")
            return

        await self.post_review_message(afk)
        await self.update_status_table()
        await self.log_event("creation", afk)

    async def post_review_message(self, afk: dict) -> None:
        from cogs.views import AfkActionView

        guild = self.bot.get_guild(afk["guild_id"])
        view = AfkActionView(afk["id"], self)
        message = await self.send_to_channel(
            config.AFK_REVIEW_CHANNEL_ID,
            embed=embeds.request_embed(afk, guild),
            view=view,
        )
        if message is not None:
            await db.set_afk_message(afk["id"], message.id, message.channel.id)
            self.bot.add_view(view, message_id=message.id)

    # ---------- одобрение ----------

    async def approve_afk(self, interaction, afk_id: int) -> None:
        try:
            require_moderator(interaction.user)
        except AfkError as exc:
            # Ошибка прав — до defer, отвечаем напрямую.
            await self._respond_error(interaction, exc.message, deferred=False)
            return
        try:
            await interaction.response.defer()
            await self._approve(interaction, afk_id)
        except AfkError as exc:
            await self._respond_error(interaction, exc.message, deferred=True)
        except Exception:
            logger.exception("Ошибка при одобрении заявки #%s", afk_id)
            await self._respond_error(interaction, GENERIC_ERROR, deferred=True)

    async def _approve(self, interaction, afk_id: int) -> None:
        afk = await db.get_afk(afk_id)
        if afk is None:
            raise RequestNotFoundError("⚠️ Заявка не найдена.")
        if afk["status"] != STATUS_PENDING:
            raise AlreadyProcessedError("⚠️ Эта заявка уже обработана.")
        ok = await db.approve_afk(
            afk_id, interaction.user.id, validators.utc_iso(validators.now_utc())
        )
        if not ok:
            raise AlreadyProcessedError("⚠️ Эта заявка уже обработана.")

        afk = await db.get_afk(afk_id)
        guild = self.bot.get_guild(afk["guild_id"])
        embed = embeds.request_embed(afk, guild)

        await interaction.followup.send(
            embed=embeds.approve_confirm_embed(afk), ephemeral=True
        )
        await self.grant_afk_role(afk)

        message = getattr(interaction, "message", None)
        if message is not None:
            try:
                await message.edit(embed=embed, view=None)
            except discord.HTTPException:
                await self.edit_afk_message(afk, embed)
        else:
            await self.edit_afk_message(afk, embed)

        await self.update_status_table()
        await self.notify_user(afk)
        await self.log_event("approval", afk, moderator=interaction.user)

    # ---------- отклонение ----------

    async def reject_afk(self, interaction, afk_id: int, reason: str) -> None:
        try:
            require_moderator(interaction.user)
        except AfkError as exc:
            # Ошибка прав — до defer, отвечаем напрямую.
            await self._respond_error(interaction, exc.message, deferred=False)
            return
        try:
            await interaction.response.defer(ephemeral=True)
            await self._reject(interaction, afk_id, reason)
        except AfkError as exc:
            await self._respond_error(interaction, exc.message, deferred=True)
        except Exception:
            logger.exception("Ошибка при отклонении заявки #%s", afk_id)
            await self._respond_error(interaction, GENERIC_ERROR, deferred=True)

    async def _reject(self, interaction, afk_id: int, reason: str) -> None:
        afk = await db.get_afk(afk_id)
        if afk is None:
            raise RequestNotFoundError("⚠️ Заявка не найдена.")
        if afk["status"] != STATUS_PENDING:
            raise AlreadyProcessedError("⚠️ Эта заявка уже обработана.")
        ok = await db.reject_afk(
            afk_id,
            interaction.user.id,
            validators.utc_iso(validators.now_utc()),
            reason.strip(),
        )
        if not ok:
            raise AlreadyProcessedError("⚠️ Эта заявка уже обработана.")

        afk = await db.get_afk(afk_id)
        guild = self.bot.get_guild(afk["guild_id"])

        await interaction.followup.send(
            embed=embeds.reject_confirm_embed(afk), ephemeral=True
        )
        await self.edit_afk_message(afk, embeds.request_embed(afk, guild))
        await self.update_status_table()
        await self.notify_user(afk)
        await self.log_event("rejection", afk, moderator=interaction.user, reason=reason.strip())

    # ---------- отмена ----------

    async def cancel_afk_self(self, interaction, afk_id: int) -> None:
        try:
            await interaction.response.defer(ephemeral=True)
            await self._cancel_self(interaction, afk_id)
        except Exception:
            logger.exception("Ошибка при отмене заявки #%s", afk_id)
            await self._respond_error(interaction, GENERIC_ERROR, deferred=True)

    async def _cancel_self(self, interaction, afk_id: int) -> None:
        afk = await db.get_afk(afk_id)
        if afk is None or afk["user_id"] != interaction.user.id:
            await interaction.followup.send(
                embed=embeds.error_embed("⚠️ Заявка не найдена."), ephemeral=True
            )
            return
        if afk["status"] not in ACTIVE_STATUSES:
            await interaction.followup.send(
                embed=embeds.error_embed("⚠️ Эта заявка уже обработана."), ephemeral=True
            )
            return

        was_approved = afk["status"] == STATUS_APPROVED
        ok = await db.cancel_afk(
            afk_id,
            reviewed_by=interaction.user.id,
            reviewed_at=validators.utc_iso(validators.now_utc()),
        )
        if not ok:
            await interaction.followup.send(
                embed=embeds.error_embed("⚠️ Эта заявка уже обработана."), ephemeral=True
            )
            return

        afk = await db.get_afk(afk_id)
        if was_approved:
            await self.remove_afk_role(afk)

        guild = self.bot.get_guild(afk["guild_id"])
        await self.edit_afk_message(afk, embeds.request_embed(afk, guild))
        await self.update_status_table()
        await self.log_event("cancellation", afk, moderator=interaction.user)

        done_embed = embeds.simple_embed(
            "✅ Заявка отменена", "Ваш АФК отменён.", embeds.COLOR_CANCELLED
        )
        try:
            await interaction.message.edit(embed=done_embed, view=None)
        except Exception:
            await interaction.followup.send(embed=done_embed, ephemeral=True)

    async def remove_afk_for_user(self, interaction, target_user) -> dict:
        """Принудительное снятие АФК модератором (/afk_remove)."""
        require_moderator(interaction.user)
        afk = await db.get_active_afk_for_user(target_user.id)
        if afk is None:
            raise RequestNotFoundError("⚠️ У этого пользователя нет активного АФК.")

        was_approved = afk["status"] == STATUS_APPROVED
        ok = await db.cancel_afk(
            afk["id"],
            reviewed_by=interaction.user.id,
            reviewed_at=validators.utc_iso(validators.now_utc()),
        )
        if not ok:
            raise AlreadyProcessedError("⚠️ Эта заявка уже обработана.")

        afk = await db.get_afk(afk["id"])
        if was_approved:
            await self.remove_afk_role(afk)

        guild = self.bot.get_guild(afk["guild_id"])
        await self.edit_afk_message(afk, embeds.request_embed(afk, guild))
        await self.update_status_table()
        await self.notify_user(afk)
        await self.log_event("removal", afk, moderator=interaction.user)
        return afk

    # ---------- автоматическое завершение ----------

    async def expire_afk(self, afk_id: int) -> None:
        afk = await db.get_afk(afk_id)
        if afk is None or afk["status"] != STATUS_APPROVED:
            return
        ok = await db.mark_expired(afk_id)
        if not ok:
            return

        afk = await db.get_afk(afk_id)
        await self.remove_afk_role(afk)
        guild = self.bot.get_guild(afk["guild_id"])
        await self.edit_afk_message(afk, embeds.request_embed(afk, guild))
        await self.update_status_table()
        await self.notify_user(afk)
        await self.log_event("expiration", afk)

    async def handle_member_remove(self, member) -> None:
        """Пользователь покинул/был удалён с сервера — закрываем его АФК."""
        afk = await db.get_active_afk_for_user(member.id)
        if afk is None:
            return
        was_approved = afk["status"] == STATUS_APPROVED
        ok = await db.cancel_afk(
            afk["id"], reviewed_at=validators.utc_iso(validators.now_utc())
        )
        if not ok:
            return

        afk = await db.get_afk(afk["id"])
        if was_approved:
            await self.remove_afk_role(afk)
        await self.edit_afk_message(afk, embeds.request_embed(afk, member.guild))
        await self.update_status_table()
        await self.log_event("removal", afk)

    # ---------- просмотр и администрирование ----------

    async def show_active_status(self, interaction) -> None:
        active = await db.list_approved_afks()
        guild = self.bot.get_guild(interaction.guild_id) if interaction.guild_id else None
        await interaction.response.send_message(
            embed=embeds.active_list_embed(active, guild), ephemeral=True
        )

    async def admin_list(self, interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        afks = await db.list_afks(limit=20)
        guild = self.bot.get_guild(interaction.guild_id) if interaction.guild_id else None
        await interaction.followup.send(
            embed=embeds.afk_list_embed(afks, None, guild), ephemeral=True
        )

    async def admin_active(self, interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        active = await db.list_approved_afks()
        guild = self.bot.get_guild(interaction.guild_id) if interaction.guild_id else None
        await interaction.followup.send(
            embed=embeds.active_list_embed(active, guild), ephemeral=True
        )

    async def admin_refresh(self, interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await self.update_status_table()
        await interaction.followup.send(
            embed=embeds.simple_embed(
                "🔄 Таблица обновлена", "Таблица активных АФК обновлена.", embeds.COLOR_SUCCESS
            ),
            ephemeral=True,
        )

    async def admin_cleanup(self, interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        count = await db.delete_finished()
        await interaction.followup.send(
            embed=embeds.simple_embed(
                "🧹 Очистка завершена",
                f"Удалено завершённых заявок: {count}.",
                embeds.COLOR_SUCCESS,
            ),
            ephemeral=True,
        )
