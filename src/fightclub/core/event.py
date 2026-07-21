from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class Event:
    id: int
    datetime: datetime
    experiment_id: str
    round_number: int
    source: str
    type: str
    data: dict[str, Any]