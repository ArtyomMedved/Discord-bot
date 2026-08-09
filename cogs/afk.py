"""Команды и события для обычных участников."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from cogs.views import AfkFormModal, CancelConfirmView
from database import db
from services.afk_service import AfkService
from utils import embeds


class AfkCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.service: AfkService = bot.service

    @app_commands.command(name="afk", description="Создать заявку на АФК")
    async def afk_command(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(AfkFormModal(self.service))

    @app_commands.command(name="my_afk", description="Показать вашу текущую заявку на АФК")
    async def my_afk_command(self, interaction: discord.Interaction) -> None:
        afk = await db.get_active_afk_for_user(interaction.user.id)
        if afk is None:
            embed = embeds.simple_embed("🟢", "🟢 У вас нет активного АФК.", embeds.COLOR_SUCCESS)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        await interaction.response.send_message(embed=embeds.my_afk_embed(afk), ephemeral=True)

    @app_commands.command(name="afk_cancel", description="Отменить вашу заявку на АФК")
    async def afk_cancel_command(self, interaction: discord.Interaction) -> None:
        afk = await db.get_active_afk_for_user(interaction.user.id)
        if afk is None:
            embed = embeds.simple_embed("🟢", "🟢 У вас нет активного АФК.", embeds.COLOR_SUCCESS)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        await interaction.response.send_message(
            embed=embeds.cancel_confirm_embed(afk),
            view=CancelConfirmView(afk["id"], self.service),
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        await self.service.handle_member_remove(member)
