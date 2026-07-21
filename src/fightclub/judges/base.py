from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class JudgeContext:
    fighter_name: str
    system_prompt: str
    responses: list[str]
    opponent_responses: list[str]
    round_number: int


@dataclass(frozen=True, slots=True)
class JudgeVerdict:
    score: float
    details: dict[str, Any] = field(default_factory=dict)


class Judge(ABC):
    """Абстрактный оценщик одного аспекта логической устойчивости бойца."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Уникальное имя Judge (идентификатор в весах и событиях)."""

    @abstractmethod
    async def judge(self, context: JudgeContext) -> JudgeVerdict:
        """Оценивает бойца по контексту и возвращает вердикт."""
