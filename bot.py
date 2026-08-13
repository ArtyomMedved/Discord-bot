"""
Запуск: python bot.py
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from cogs.admin import AdminCog
from cogs.afk import AfkCog
from cogs.soul import SoulCog
from cogs.status import StatusCog
from cogs.verification import VerificationCog
from database import db
from services.afk_service import AfkService
from services.scheduler import Scheduler
from services.soul_service import SoulCoinService
from services.verification_service import VerificationService
from utils import embeds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s: %(message)s",
)
logger = logging.getLogger("afk_bot")


class AfkBot(commands.Bot):
    def __init__(self) -> None:
        # members-интент privileged — включи его в Developer Portal, иначе не заработает.
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)

        self.service = AfkService(self)
        self.soul_service = SoulCoinService(self)
        self.verify_service = VerificationService(self)
        self.scheduler = Scheduler(self.service, soul_service=self.soul_service)
        self.tree.on_error = self._tree_error
        self._ready_done = False

    async def setup_hook(self) -> None:
        await self.add_cog(AfkCog(self))
        await self.add_cog(StatusCog(self))
        await self.add_cog(AdminCog(self))
        await self.add_cog(SoulCog(self))
        await self.add_cog(VerificationCog(self))

    async def _tree_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        logger.exception("Ошибка slash-команды: %s", error)
        embed = embeds.error_embed(
            "❌ Произошла внутренняя ошибка.\n\n"
            "Попробуйте ещё раз или обратитесь к администрации."
        )
        try:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except (discord.InteractionResponded, discord.HTTPException):
            try:
                await interaction.followup.send(embed=embed, ephemeral=True)
            except Exception:
                pass

    async def on_ready(self) -> None:
        if self._ready_done:
            return
        self._ready_done = True

        logger.info("Бот запущен: %s (ID: %s)", self.user, self.user.id)
        guild = self.service.resolve_guild()
        if guild is None:
            logger.warning(
                "Не найден сервер (GUILD_ID=%s). Команды не синхронизированы.",
                config.GUILD_ID or "не задан",
            )
        else:
            logger.info("Сервер: %s (ID: %s)", guild.name, guild.id)
            if config.SYNC_GLOBALLY:
                await self.tree.sync()
                logger.info("Команды синхронизированы глобально")
            else:
                # copy_global_to обязателен: иначе sync(guild) отошлёт пустой список
                # и снесит все guild-команды (команды глобальные).
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                logger.info("Команды синхронизированы на сервер %s", guild.id)

        await self.service.restore_views()
        await self.service.ensure_panel_message()
        await self.service.sync_roles_and_recover()
        await self.soul_service.on_startup()
        await self.verify_service.on_startup()
        self.scheduler.start()
        logger.info("Инициализация завершена. Бот готов.")

    async def close(self) -> None:
        """Штатное завершение: глушим задачи и сохраняем данные."""
        self.scheduler.stop()
        await super().close()
        await db.backup_now()
        db.close()


def main() -> None:
    if not config.DISCORD_TOKEN:
        logger.error(
            "DISCORD_TOKEN не задан. Скопируйте .env.example в .env и заполните настройки."
        )
        return

    db.connect()
    bot = AfkBot()
    try:
        bot.run(config.DISCORD_TOKEN)
    finally:
        # Страховка: закрываем соединение в любом случае (WAL сведётся в файл).
        db.close()


if __name__ == "__main__":
    main()
