"""Discord UI-компоненты: кнопки и модальные окна.

Кнопки одобрения/отклонения создаются с уникальным custom_id
на основе id заявки и регистрируются как persistent-views
(bot.add_view), поэтому переживают перезапуск бота.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import ButtonStyle, TextStyle
from discord.ui import Button, Modal, TextInput, View

if TYPE_CHECKING:
    from services.afk_service import AfkService

CREATE_BUTTON_ID = "afk_create"
STATUS_BUTTON_ID = "afk_status"
APPROVE_PREFIX = "afk_approve:"
REJECT_PREFIX = "afk_reject:"
CANCEL_YES_PREFIX = "afk_cancel_yes:"
CANCEL_NO_PREFIX = "afk_cancel_no:"
ADMIN_LIST_ID = "afk_admin_list"
ADMIN_ACTIVE_ID = "afk_admin_active"
ADMIN_REFRESH_ID = "afk_admin_refresh"
ADMIN_CLEANUP_ID = "afk_admin_cleanup"


class AfkFormModal(Modal):
    """Форма создания заявки: дата окончания + причина."""

    def __init__(self, service: "AfkService") -> None:
        super().__init__(title="Заявка на АФК", custom_id="afk_form_modal")
        self.service = service
        self.add_item(
            TextInput(
                label="Дата и время окончания АФК",
                placeholder="10.08.2026 18:30",
                min_length=10,
                max_length=32,
                required=True,
                row=0,
            )
        )
        self.add_item(
            TextInput(
                label="Причина АФК",
                placeholder="Учёба, отпуск, личные обстоятельства и т.д.",
                max_length=1024,
                required=True,
                style=TextStyle.paragraph,
                row=1,
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        date_value = self.children[0].value
        reason_value = self.children[1].value
        await self.service.create_afk(interaction, date_value or "", reason_value or "")


class RejectModal(Modal):
    """Форма причины отклонения заявки."""

    def __init__(self, afk_id: int, service: "AfkService") -> None:
        super().__init__(title="Отклонение заявки", custom_id=f"afk_reject_modal:{afk_id}")
        self.afk_id = afk_id
        self.service = service
        self.add_item(
            TextInput(
                label="Причина отказа",
                placeholder="Недостаточно информации",
                max_length=1024,
                required=True,
                style=TextStyle.paragraph,
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        reason = self.children[0].value or ""
        await self.service.reject_afk(interaction, self.afk_id, reason)


class PanelView(View):
    """Кнопки на панели: «Создать заявку» и «Статус АФК»."""

    def __init__(self, service: "AfkService") -> None:
        super().__init__(timeout=None)
        self.service = service

    @discord.ui.button(
        label="Создать заявку",
        emoji="💤",
        style=ButtonStyle.primary,
        custom_id=CREATE_BUTTON_ID,
    )
    async def create_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(AfkFormModal(self.service))

    @discord.ui.button(
        label="Статус АФК",
        emoji="📊",
        style=ButtonStyle.secondary,
        custom_id=STATUS_BUTTON_ID,
    )
    async def status_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.service.show_active_status(interaction)


class AfkActionView(View):
    """Кнопки «Принять» / «Отклонить» на сообщении заявки."""

    def __init__(self, afk_id: int, service: "AfkService") -> None:
        super().__init__(timeout=None)
        self.afk_id = afk_id
        self.service = service

        approve = Button(
            label="Принять",
            emoji="🟢",
            style=ButtonStyle.success,
            custom_id=f"{APPROVE_PREFIX}{afk_id}",
        )
        reject = Button(
            label="Отклонить",
            emoji="🔴",
            style=ButtonStyle.danger,
            custom_id=f"{REJECT_PREFIX}{afk_id}",
        )
        approve.callback = self.on_approve
        reject.callback = self.on_reject
        self.add_item(approve)
        self.add_item(reject)

    async def on_approve(self, interaction: discord.Interaction) -> None:
        await self.service.approve_afk(interaction, self.afk_id)

    async def on_reject(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(RejectModal(self.afk_id, self.service))


class CancelConfirmView(View):
    """Подтверждение отмены: «Да, отменить» / «Нет»."""

    def __init__(self, afk_id: int, service: "AfkService") -> None:
        super().__init__(timeout=120)
        self.afk_id = afk_id
        self.service = service

        yes = Button(
            label="Да, отменить",
            emoji="✅",
            style=ButtonStyle.danger,
            custom_id=f"{CANCEL_YES_PREFIX}{afk_id}",
        )
        no = Button(
            label="Нет",
            emoji="❌",
            style=ButtonStyle.secondary,
            custom_id=f"{CANCEL_NO_PREFIX}{afk_id}",
        )
        yes.callback = self.on_yes
        no.callback = self.on_no
        self.add_item(yes)
        self.add_item(no)

    async def on_yes(self, interaction: discord.Interaction) -> None:
        await self.service.cancel_afk_self(interaction, self.afk_id)

    async def on_no(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.edit_message(
                content="Отмена АФК отклонена.", embed=None, view=None
            )
        except discord.HTTPException:
            pass


class AdminMenuView(View):
    """Административное меню."""

    def __init__(self, service: "AfkService") -> None:
        super().__init__(timeout=120)
        self.service = service

        list_btn = Button(label="Все заявки", emoji="📋", style=ButtonStyle.secondary, custom_id=ADMIN_LIST_ID)
        active_btn = Button(label="Активные АФК", emoji="💤", style=ButtonStyle.secondary, custom_id=ADMIN_ACTIVE_ID)
        refresh_btn = Button(label="Обновить таблицу", emoji="🔄", style=ButtonStyle.primary, custom_id=ADMIN_REFRESH_ID)
        cleanup_btn = Button(label="Очистить завершённые", emoji="🧹", style=ButtonStyle.danger, custom_id=ADMIN_CLEANUP_ID)

        list_btn.callback = self.on_list
        active_btn.callback = self.on_active
        refresh_btn.callback = self.on_refresh
        cleanup_btn.callback = self.on_cleanup

        self.add_item(list_btn)
        self.add_item(active_btn)
        self.add_item(refresh_btn)
        self.add_item(cleanup_btn)

    async def on_list(self, interaction: discord.Interaction) -> None:
        await self.service.admin_list(interaction)

    async def on_active(self, interaction: discord.Interaction) -> None:
        await self.service.admin_active(interaction)

    async def on_refresh(self, interaction: discord.Interaction) -> None:
        await self.service.admin_refresh(interaction)

    async def on_cleanup(self, interaction: discord.Interaction) -> None:
        await self.service.admin_cleanup(interaction)
