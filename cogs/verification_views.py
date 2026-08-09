"""UI верификации: закреплённая панель с кнопкой и модальная анкета."""
from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import ButtonStyle, TextStyle
from discord.ui import Button, Modal, TextInput, View

if TYPE_CHECKING:
    from services.verification_service import VerificationService

VERIFY_BUTTON_ID = "verify_btn"


class VerificationPanelView(View):
    """Persistent-кнопка «Верифицироваться» на закреплённом сообщении."""

    def __init__(self, service: "VerificationService") -> None:
        super().__init__(timeout=None)
        self.service = service

    @discord.ui.button(
        label="Верифицироваться",
        emoji="✅",
        style=ButtonStyle.success,
        custom_id=VERIFY_BUTTON_ID,
    )
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(VerificationModal(self.service))


class VerificationModal(Modal):
    """Анкета новичка: статик, имя в игре, имя в жизни, занятие."""

    def __init__(self, service: "VerificationService") -> None:
        super().__init__(title="Верификация", custom_id="verify_modal")
        self.service = service
        self.add_item(
            TextInput(
                label="Статик",
                placeholder="Ваш статик / команда",
                max_length=100,
                required=True,
                row=0,
            )
        )
        self.add_item(
            TextInput(
                label="Имя в игре (только имя, без фамилии)",
                placeholder="Например: Angel",
                max_length=64,
                required=True,
                row=1,
            )
        )
        self.add_item(
            TextInput(
                label="Имя в жизни",
                placeholder="Например: Артём",
                max_length=64,
                required=True,
                row=2,
            )
        )
        self.add_item(
            TextInput(
                label="Чем занимаетесь?",
                placeholder="Коротко о себе",
                max_length=512,
                required=True,
                style=TextStyle.paragraph,
                row=3,
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        static = self.children[0].value or ""
        in_game = self.children[1].value or ""
        real = self.children[2].value or ""
        occupation = self.children[3].value or ""
        await self.service.verify(interaction, static, in_game, real, occupation)
