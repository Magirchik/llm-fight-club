from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RefereeConfig:
    experiment_id: str
    lss_critical_threshold: float = 0.3
    lss_draw_threshold: float = 0.05
    min_rounds: int = 1
    publish_continue: bool = True
