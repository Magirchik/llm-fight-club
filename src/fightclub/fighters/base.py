from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from .config import FighterConfig


@dataclass(frozen=True, slots=True)
class FighterResponse:
    content: str
    model: str
    usage: dict[str, Any]
    latency_ms: int


class FighterError(Exception):
    """Ошибка генерации ответа Fighter."""


class Fighter(ABC):
    """Абстрактный адаптер языковой модели.

    Изолирован от Event Stream и других компонентов системы.
    Знает только собственный системный промпт и входящее сообщение.
    """

    @property
    @abstractmethod
    def config(self) -> FighterConfig:
        """Конфигурация бойца."""

    @abstractmethod
    async def generate(self, message: str) -> FighterResponse:
        """Генерирует ответ на входящее сообщение."""
