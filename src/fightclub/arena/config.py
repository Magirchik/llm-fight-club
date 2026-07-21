from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ArenaConfig:
    experiment_id: str
    max_rounds: int
    opening_message: str
