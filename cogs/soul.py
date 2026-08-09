"""Команды системы Soul-Coins."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import config
from cogs.soul_views import SoulAdminView
from services.soul_service import SoulCoinService
from utils import embeds, validators
from utils.permissions import is_moderator

NO_PERMISSION = "❌ У вас нет прав для работы с баллами."


class SoulCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.service: SoulCoinService = bot.soul_service

    @app_commands.command(name="soul", description="Показать ваши Soul-Coins и статус")
    async def soul_command(self, interaction: discord.Interaction) -> None:
        status = await self.service.soul_status(interaction.user.id)
        embed = embeds.soul_self_embed(
            status["balance"],
            config.SOUL_COIN_NORM,
            validators.month_label(status["month"]),
            status["under"],
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="soul_admin",
        description="Админ-меню Soul-Coins (модераторы)",
    )
    async def soul_admin_command(self, interaction: discord.Interaction) -> None:
        if not is_moderator(interaction.user):
            await interaction.response.send_message(
                embed=embeds.error_embed(NO_PERMISSION), ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=embeds.soul_admin_menu_embed(),
            view=SoulAdminView(self.service),
            ephemeral=True,
        )

    @app_commands.command(
        name="soul_logs",
        description="История начислений игрока (модераторы)",
    )
    @app_commands.describe(user="Игрок, чью историю показать")
    async def soul_logs_command(
        self, interaction: discord.Interaction, user: discord.User
    ) -> None:
        if not is_moderator(interaction.user):
            await interaction.response.send_message(
                embed=embeds.error_embed(NO_PERMISSION), ephemeral=True
            )
            return
        logs = await self.service.soul_history(user.id)
        embed = embeds.soul_history_embed(
            user.id, logs, validators.month_label(validators.month_key())
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
