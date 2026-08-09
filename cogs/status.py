"""Команды просмотра статуса АФК."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from services.afk_service import AfkService


class StatusCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.service: AfkService = bot.service

    @app_commands.command(name="afk_status", description="Показать текущий список АФК")
    async def afk_status_command(self, interaction: discord.Interaction) -> None:
        await self.service.show_active_status(interaction)
