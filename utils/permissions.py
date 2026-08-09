"""Проверка прав модераторов по ID ролей."""
from __future__ import annotations

import config
from utils.errors import PermissionDeniedError


def is_moderator(member) -> bool:
    """True, если у участника есть хотя бы одна разрешённая роль.

    Всегда пропускаем участников с правами администратора сервера.
    """
    if member is None:
        return False
    if member.guild_permissions.administrator:
        return True

    allowed_ids = set(config.AFK_REVIEW_ROLE_IDS)
    if config.ADMIN_ROLE_ID:
        allowed_ids.add(config.ADMIN_ROLE_ID)
    if config.MODERATOR_ROLE_ID:
        allowed_ids.add(config.MODERATOR_ROLE_ID)

    member_role_ids = {role.id for role in member.roles}
    return bool(member_role_ids & allowed_ids)


def require_moderator(member) -> None:
    if not is_moderator(member):
        raise PermissionDeniedError("❌ У вас нет прав для обработки заявок АФК.")
