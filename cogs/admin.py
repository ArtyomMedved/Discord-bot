"""Административные команды (модераторы)."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from cogs.views import AdminMenuView
from database import db
from utils import embeds
from utils.errors import AfkError
from utils.permissions import is_moderator

logger = logging.getLogger(__name__)

NO_PERMISSION = "❌ У вас нет прав для обработки заявок АФК."
GENERIC_ERROR = (
    "❌ Произошла внутренняя ошибка.\n\n"
    "Попробуйте ещё раз или обратитесь к администрации."
)


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.service = bot.service

    @app_commands.command(name="afk_admin", description="Административное меню АФК (модераторы)")
    async def afk_admin_command(self, interaction: discord.Interaction) -> None:
        if not is_moderator(interaction.user):
            await interaction.response.send_message(
                embed=embeds.error_embed(NO_PERMISSION), ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=embeds.admin_menu_embed(),
            view=AdminMenuView(self.service),
            ephemeral=True,
        )

    @app_commands.command(
        name="afk_remove",
        description="Принудительно снять АФК с пользователя (модераторы)",
    )
    @app_commands.describe(user="Пользователь, с которого снять АФК")
    async def afk_remove_command(
        self, interaction: discord.Interaction, user: discord.User
    ) -> None:
        try:
            afk = await self.service.remove_afk_for_user(interaction, user)
            await interaction.response.send_message(
                embed=embeds.remove_success_embed(afk), ephemeral=True
            )
        except AfkError as exc:
            await interaction.response.send_message(
                embed=embeds.error_embed(exc.message), ephemeral=True
            )
        except Exception:
            logger.exception("Ошибка в /afk_remove")
            await interaction.response.send_message(
                embed=embeds.error_embed(GENERIC_ERROR), ephemeral=True
            )

    @app_commands.command(
        name="afk_list",
        description="Просмотр заявок АФК (модераторы)",
    )
    @app_commands.describe(status="Фильтр по статусу (необязательно)")
    @app_commands.choices(status=[
        app_commands.Choice(name="🟡 В ожидании", value="PENDING"),
        app_commands.Choice(name="🟢 Одобрено", value="APPROVED"),
        app_commands.Choice(name="🔴 Отклонено", value="REJECTED"),
        app_commands.Choice(name="🔵 Завершено", value="EXPIRED"),
        app_commands.Choice(name="⚪ Отменено", value="CANCELLED"),
    ])
    async def afk_list_command(
        self, interaction: discord.Interaction, status: str | None = None
    ) -> None:
        if not is_moderator(interaction.user):
            await interaction.response.send_message(
                embed=embeds.error_embed(NO_PERMISSION), ephemeral=True
            )
            return
        afks = await db.list_afks(status=status, limit=20)
        guild = self.bot.get_guild(interaction.guild_id) if interaction.guild_id else None
        await interaction.response.send_message(
            embed=embeds.afk_list_embed(afks, status, guild), ephemeral=True
        )
