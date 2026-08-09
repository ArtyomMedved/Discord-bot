"""Пользовательские исключения с готовыми сообщениями для Discord."""


class AfkError(Exception):
    """Базовая ошибка системы АФК. message показывается пользователю."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class PermissionDeniedError(AfkError):
    """Недостаточно прав."""


class ValidationError(AfkError):
    """Неверный ввод пользователя."""


class AlreadyActiveError(AfkError):
    """У пользователя уже есть активная заявка."""


class RequestNotFoundError(AfkError):
    """Заявка не найдена."""


class AlreadyProcessedError(AfkError):
    """Заявка уже была обработана ранее (защита от двойной обработки)."""
