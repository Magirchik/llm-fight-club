from datetime import datetime
from typing import Any

from fightclub.core.event import Event


class EventPacker:
    """Упаковывает сырые данные в Event."""

    def __init__(self) -> None:
        self._next_id = 0

    def pack(
        self,
        *,
        experiment_id: str,
        round_number: int,
        source: str,
        type: str,
        data: dict[str, Any],
    ) -> Event:
        event = Event(
            id=self._next_id,
            datetime=datetime.now(),
            experiment_id=experiment_id,
            round_number=round_number,
            source=source,
            type=type,
            data=data,
        )

        self._next_id += 1
        return event