"""UI-компоненты системы Soul-Coins.

Кнопки «➕/➖ Баллы» под таблицей — persistent (переживают перезапуск).
Нажатие открывает эфемерный Select с игроками (с пагинацией при >24),
выбор — модальное окно с суммой и причиной.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import ButtonStyle, TextStyle
from discord import SelectOption
from discord.ui import Button, Modal, Select, TextInput, View

from utils import embeds
from utils.permissions import is_moderator

if TYPE_CHECKING:
    from services.soul_service import SoulCoinService

SOUL_ADD_ID = "soul_add"
SOUL_SUB_ID = "soul_sub"
SOUL_SELECT_ID = "soul_select"
SOUL_ADMIN_REFRESH_ID = "soul_admin_refresh"
SOUL_ADMIN_FINALIZE_ID = "soul_admin_finalize"

NO_PERMISSION = "❌ У вас нет прав для работы с баллами."
PAGE_SIZE = 24


class SoulPanelView(View):
    """Кнопки «➕ Баллы» / «➖ Баллы» под таблицей Soul-Coins."""

    def __init__(self, service: "SoulCoinService") -> None:
        super().__init__(timeout=None)
        self.service = service

    @discord.ui.button(
        label="Баллы", emoji="➕", style=ButtonStyle.success, custom_id=SOUL_ADD_ID
    )
    async def add_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open_member_select(interaction, delta=1)

    @discord.ui.button(
        label="Баллы", emoji="➖", style=ButtonStyle.danger, custom_id=SOUL_SUB_ID
    )
    async def sub_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open_member_select(interaction, delta=-1)

    async def _open_member_select(self, interaction: discord.Interaction, delta: int) -> None:
        # Проверка прав при нажатии, а не только при отрисовке.
        if not is_moderator(interaction.user):
            await interaction.response.send_message(
                embed=embeds.error_embed(NO_PERMISSION), ephemeral=True
            )
            return
        members = self.service.tracked_members()
        if not members:
            await interaction.response.send_message(
                embed=embeds.error_embed("❌ Нет игроков для изменения баллов."), ephemeral=True
            )
            return
        view = MemberSelectView(self.service, delta, members)
        await interaction.response.send_message(
            embed=embeds.simple_embed(
                "🪙 Выбор игрока", "Выберите игрока, которому изменить баллы:"
            ),
            view=view,
            ephemeral=True,
        )


class MemberSelectView(View):
    """Select с отслеживаемыми игроками и пагинацией (при >24 участников)."""

    def __init__(self, service: "SoulCoinService", delta: int, members: list, page: int = 0) -> None:
        super().__init__(timeout=180)
        self.service = service
        self.delta = delta
        self.members = members
        self.page = page
        self._render()

    def _render(self) -> None:
        self.clear_items()
        total_pages = max(1, (len(self.members) + PAGE_SIZE - 1) // PAGE_SIZE)
        start = self.page * PAGE_SIZE
        chunk = self.members[start:start + PAGE_SIZE]

        select = Select(
            placeholder="Выберите игрока…",
            options=[
                SelectOption(label=member.display_name[:100], value=str(member.id))
                for member in chunk
            ],
            custom_id=SOUL_SELECT_ID,
        )
        select.callback = self.on_select
        self.add_item(select)

        if total_pages > 1:
            if self.page > 0:
                prev = Button(label="◀", style=ButtonStyle.secondary, custom_id="soul_prev")
                prev.callback = self.on_prev
                self.add_item(prev)
            if self.page < total_pages - 1:
                nxt = Button(label="▶", style=ButtonStyle.secondary, custom_id="soul_next")
                nxt.callback = self.on_next
                self.add_item(nxt)

    async def on_select(self, interaction: discord.Interaction) -> None:
        values = (interaction.data or {}).get("values") or []
        if not values:
            return
        user_id = int(values[0])
        modal = PointsModal(self.service, self.delta, user_id)
        await interaction.response.send_modal(modal)

    async def on_prev(self, interaction: discord.Interaction) -> None:
        self.page -= 1
        self._render()
        await interaction.response.edit_message(view=self)

    async def on_next(self, interaction: discord.Interaction) -> None:
        self.page += 1
        self._render()
        await interaction.response.edit_message(view=self)


class PointsModal(Modal):
    """Форма: сумма баллов + причина."""

    def __init__(self, service: "SoulCoinService", delta: int, user_id: int) -> None:
        title = "➕ Начисление баллов" if delta > 0 else "➖ Списание баллов"
        super().__init__(title=title, custom_id=f"soul_modal:{delta}")
        self.service = service
        self.delta = delta
        self.user_id = user_id
        self.add_item(
            TextInput(
                label="Сумма баллов",
                placeholder="Например: 15",
                max_length=4,
                required=True,
                row=0,
            )
        )
        self.add_item(
            TextInput(
                label="Причина",
                placeholder="За что начисляются/списываются баллы",
                max_length=1000,
                required=True,
                style=TextStyle.paragraph,
                row=1,
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw_amount = (self.children[0].value or "").strip()
        try:
            amount = int(raw_amount)
        except ValueError:
            await interaction.response.send_message(
                embed=embeds.error_embed("❌ Сумма должна быть целым числом."), ephemeral=True
            )
            return
        if amount <= 0:
            await interaction.response.send_message(
                embed=embeds.error_embed("❌ Сумма должна быть больше нуля."), ephemeral=True
            )
            return
        reason = self.children[1].value or ""
        await self.service.apply_points(interaction, self.user_id, self.delta * amount, reason)


class SoulAdminView(View):
    """Меню администрирования Soul-Coins."""

    def __init__(self, service: "SoulCoinService") -> None:
        super().__init__(timeout=180)
        self.service = service

        refresh = Button(
            label="Обновить таблицу", emoji="🔄",
            style=ButtonStyle.primary, custom_id=SOUL_ADMIN_REFRESH_ID,
        )
        finalize = Button(
            label="Проверка нормы", emoji="📊",
            style=ButtonStyle.danger, custom_id=SOUL_ADMIN_FINALIZE_ID,
        )
        refresh.callback = self.on_refresh
        finalize.callback = self.on_finalize
        self.add_item(refresh)
        self.add_item(finalize)

    async def on_refresh(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await self.service.update_table()
        await interaction.followup.send(
            embed=embeds.simple_embed(
                "🔄 Таблица обновлена", "Таблица Soul-Coins обновлена.", embeds.COLOR_SUCCESS
            ),
            ephemeral=True,
        )

    async def on_finalize(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        ran = await self.service.finalize_month()
        text = (
            "Итоги месяца подведены, таблица обновлена."
            if ran
            else "Месяц ещё не закончился — итоги не подводились."
        )
        await interaction.followup.send(
            embed=embeds.simple_embed("📊 Проверка нормы", text, embeds.COLOR_INFO),
            ephemeral=True,
        )
