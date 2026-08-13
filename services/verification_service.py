"""Верификация новичков.

Новичок жмёт «Верифицироваться» на закреплённом сообщении и заполняет
анкету (статик, имя в игре, имя в жизни, занятие). После отправки:
- выдаём роль (VERIFY_ROLE_ID);
- ставим ник «{VERIFY_NICK_PREFIX}. Имя в игре (Имя в жизни)»;
- анкета в БД + лог в админ-чат.
"""
from __future__ import annotations

import logging

import discord

import config
from database import db
from services.base import ChannelMixin
from utils import embeds, validators

logger = logging.getLogger(__name__)

GENERIC_ERROR = (
    "❌ Произошла внутренняя ошибка.\n\n"
    "Попробуйте ещё раз или обратитесь к администрации."
)

# Лимит ника в Discord
NICK_MAX = 32


class VerificationService(ChannelMixin):
    def __init__(self, bot: discord.Client) -> None:
        self.bot = bot

    # ---------- панель ----------

    def _panel_view(self):
        from cogs.verification_views import VerificationPanelView

        return VerificationPanelView(self)

    async def ensure_panel_message(self) -> None:
        """Постим и закрепляем панель верификации (или правим существующую)."""
        channel = await self.get_channel(config.VERIFY_CHANNEL_ID)
        if channel is None:
            logger.warning("Канал верификации (VERIFY_CHANNEL_ID) не найден")
            return
        view = self._panel_view()
        message_id = await db.get_setting("verify_panel_message_id")
        if message_id:
            try:
                message = await channel.fetch_message(int(message_id))
                await message.edit(embed=embeds.verify_panel_embed(), view=view)
                return
            except discord.NotFound:
                await db.set_setting("verify_panel_message_id", None)
            except discord.HTTPException:
                logger.exception("Не удалось обновить панель верификации")
                return
        try:
            message = await channel.send(embed=embeds.verify_panel_embed(), view=view)
            await db.set_setting("verify_panel_message_id", str(message.id))
            if not message.pinned:
                await message.pin()
        except discord.HTTPException:
            logger.exception("Не удалось создать панель верификации")

    # ---------- никнейм ----------

    def _build_nickname(self, in_game: str, real: str) -> str:
        """«Verf. Angel (Артём)» — ужимает имя в игре под лимит 32 символа."""
        prefix = config.VERIFY_NICK_PREFIX or "Verf"
        suffix = f" ({real})"
        budget = NICK_MAX - len(prefix) - 2 - len(suffix)  # 2 = ". "
        if budget < 1:
            budget = 1
        return f"{prefix}. {in_game[:budget]}{suffix}"

    # ---------- верификация ----------

    async def verify(self, interaction, static: str, in_game: str, real: str, occupation: str) -> None:
        try:
            await self._verify(interaction, static, in_game, real, occupation)
        except Exception:
            logger.exception(
                "Ошибка при верификации пользователя %s",
                getattr(getattr(interaction, "user", None), "id", None),
            )
            await self._respond_error(interaction, GENERIC_ERROR)

    async def _verify(self, interaction, static: str, in_game: str, real: str, occupation: str) -> None:
        member = interaction.user
        guild = member.guild or self.resolve_guild()
        if guild is None:
            await self._respond_error(interaction, "❌ Не найден сервер.")
            return
        role = guild.get_role(config.VERIFY_ROLE_ID)
        if role is None:
            await self._respond_error(interaction, "❌ Роль верификации не настроена на сервере.")
            return

        if role in member.roles:
            await interaction.response.send_message(
                embed=embeds.simple_embed(
                    "ℹ️ Вы уже верифицированы",
                    "Вам уже была выдана роль.",
                    embeds.COLOR_INFO,
                ),
                ephemeral=True,
            )
            return

        in_game = (in_game or "").strip()
        real = (real or "").strip()
        if not in_game or not real:
            await self._respond_error(interaction, "❌ Укажите имя в игре и имя в жизни.")
            return

        nickname = self._build_nickname(in_game, real)
        # Важно: роль бота должна быть ВЫШЕ топ-роли игрока, иначе даже
        # с правом «Управлять никнеймами» смена ника вернёт 403.
        if member.top_role >= guild.me.top_role:
            logger.warning(
                "Смена ника заблокирована иерархией ролей: топ-роль игрока %s "
                "(%s, поз. %s) >= топ-роль бота (%s, поз. %s). "
                "Поднимите роль бота в «Настройках сервера → Роли» выше ролей игроков.",
                member.id,
                member.top_role.name,
                member.top_role.position,
                guild.me.top_role.name,
                guild.me.top_role.position,
            )
        try:
            await member.edit(nick=nickname, reason="Верификация нового игрока")
        except discord.Forbidden as exc:
            logger.warning(
                "Нет прав на смену ника %s (403 %s). Проверьте роль бота: "
                "право «Управлять никнеймами» + позиция роли выше ролей игроков.",
                member.id,
                getattr(exc, "text", "") or exc.status,
            )
        except discord.HTTPException:
            logger.warning("Не удалось изменить никнейм пользователю %s", member.id)

        try:
            await member.add_roles(role, reason="Верификация нового игрока")
        except discord.HTTPException:
            logger.exception("Не удалось выдать роль верификации %s", member.id)

        created_at = validators.utc_iso(validators.now_utc())
        await db.create_verification(
            user_id=member.id,
            guild_id=guild.id,
            static=(static or "").strip(),
            in_game_name=in_game,
            real_name=real,
            occupation=(occupation or "").strip(),
            created_at=created_at,
        )
        await self.send_to_channel(
            config.VERIFY_LOG_CHANNEL_ID,
            embed=embeds.verify_log_embed(member, static, in_game, real, occupation, created_at),
        )

        await interaction.response.send_message(
            embed=embeds.verify_confirm_embed(in_game, real, nickname),
            ephemeral=True,
        )

    async def _respond_error(self, interaction, message: str) -> None:
        embed = embeds.error_embed(message)
        try:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception:
            try:
                await interaction.followup.send(embed=embed, ephemeral=True)
            except Exception:
                pass

    # ---------- запуск ----------

    async def on_startup(self) -> None:
        """Создать/обновить панель и вернуть persistent-кнопку после рестарта."""
        await self.ensure_panel_message()
        self.bot.add_view(self._panel_view())
