from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class FighterConfig:
    name: str
    provider: str
    model: str
    system_prompt: str
    temperature: float = 0.7
    max_tokens: int = 1024
    seed: int = 0
    extra: dict[str, Any] = field(default_factory=dict)
