"""Команды системы верификации."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from database import db
from services.verification_service import VerificationService
from utils import embeds
from utils.permissions import is_moderator

NO_PERMISSION = "❌ У вас нет прав для работы с верификацией."


class VerificationCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.service: VerificationService = bot.verify_service

    @app_commands.command(
        name="verify_setup",
        description="Создать/обновить панель верификации (модераторы)",
    )
    async def verify_setup_command(self, interaction: discord.Interaction) -> None:
        if not is_moderator(interaction.user):
            await interaction.response.send_message(
                embed=embeds.error_embed(NO_PERMISSION), ephemeral=True
            )
            return
        await self.service.ensure_panel_message()
        await interaction.response.send_message(
            embed=embeds.simple_embed(
                "✅ Панель верификации",
                "Сообщение с кнопкой «Верифицироваться» создано/обновлено.",
                embeds.COLOR_SUCCESS,
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name="verify_info",
        description="Данные верификации игрока (модераторы)",
    )
    @app_commands.describe(user="Игрок, чью анкету показать")
    async def verify_info_command(
        self, interaction: discord.Interaction, user: discord.User
    ) -> None:
        if not is_moderator(interaction.user):
            await interaction.response.send_message(
                embed=embeds.error_embed(NO_PERMISSION), ephemeral=True
            )
            return
        record = await db.get_verification(user.id)
        if record is None:
            await interaction.response.send_message(
                embed=embeds.simple_embed(
                    "ℹ️ Нет данных",
                    "Этот игрок ещё не проходил верификацию.",
                    embeds.COLOR_INFO,
                ),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            embed=embeds.verify_info_embed(record, user.id), ephemeral=True
        )
