"""Общие низкоуровневые помощники сервисов: гильдия и каналы."""
from __future__ import annotations

import logging

import discord

import config

logger = logging.getLogger(__name__)


class ChannelMixin:
    """Работа с гильдией и каналами — общая для всех сервисов."""

    def resolve_guild(self) -> discord.Guild | None:
        if config.GUILD_ID:
            guild = self.bot.get_guild(config.GUILD_ID)
            if guild is not None:
                return guild
        return self.bot.guilds[0] if self.bot.guilds else None

    async def get_channel(self, channel_id: int) -> discord.TextChannel | None:
        if not channel_id:
            return None
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                channel = None
        return channel

    async def send_to_channel(self, channel_id: int, **kwargs):
        channel = await self.get_channel(channel_id)
        if channel is None:
            logger.warning("Канал %s недоступен — сообщение не отправлено", channel_id)
            return None
        try:
            return await channel.send(**kwargs)
        except discord.Forbidden:
            logger.warning("Нет прав на отправку в канал %s", channel_id)
        except discord.HTTPException:
            logger.exception("Ошибка Discord API при отправке в канал %s", channel_id)
        return None
