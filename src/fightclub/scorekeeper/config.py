from dataclasses import dataclass, field

from fightclub.judges import DEFAULT_WEIGHTS


@dataclass(frozen=True, slots=True)
class ScorekeeperConfig:
    experiment_id: str
    system_prompts: dict[str, str]
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
