"""Наши исключения с готовыми сообщениями для Discord."""


class AfkError(Exception):
    """Базовая ошибка. message показываем юзеру."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class PermissionDeniedError(AfkError):
    """Нет прав."""


class ValidationError(AfkError):
    """Кривой ввод юзера."""


class AlreadyActiveError(AfkError):
    """У юзера уже есть активная заявка."""


class RequestNotFoundError(AfkError):
    """Заявка не найдена."""


class AlreadyProcessedError(AfkError):
    """Заявку уже обработали (защита от двойной обработки)."""
