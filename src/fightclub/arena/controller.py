from typing import Any

from fightclub.core.event import Event
from fightclub.event_stream import EventPacker, EventStream
from fightclub.fighters import Fighter, FighterError, FighterResponse

from .config import ArenaConfig


class ArenaController:
    """Оркестратор поединка.

    Вызывает Fighter'ов и публикует события от их имени.
    Сам является компонентом Event Stream: подписывается на referee.stop.
    """

    SOURCE = "arena"

    def __init__(
        self,
        config: ArenaConfig,
        fighters: list[Fighter],
        event_stream: EventStream,
        event_packer: EventPacker,
    ) -> None:
        if len(fighters) != 2:
            raise ValueError("Arena requires exactly 2 fighters")
        names = {f.config.name for f in fighters}
        if len(names) != 2:
            raise ValueError("Fighters must have unique names")
        self._config = config
        self._fighters = fighters
        self._stream = event_stream
        self._packer = event_packer
        self._stopped = False

    def __call__(self, event: Event) -> None:
        if event.type == "referee.stop":
            self._stopped = True

    async def run(self) -> str:
        self._publish(
            0,
            "arena.started",
            self.SOURCE,
            {"fighters": [f.config.name for f in self._fighters]},
        )
        last_message = self._config.opening_message
        round_number = 0
        reason = "completed"
        try:
            while round_number < self._config.max_rounds and not self._stopped:
                round_number += 1
                for fighter in self._fighters:
                    self._publish_fighter_message(fighter, last_message, round_number)
                    try:
                        resp = await fighter.generate(last_message)
                    except FighterError as exc:
                        self._publish_fighter_error(fighter, exc, round_number)
                        reason = "error"
                        return reason
                    self._publish_fighter_response(fighter, resp, round_number)
                    last_message = resp.content
                self._publish(
                    round_number,
                    "arena.round_finished",
                    self.SOURCE,
                    {"round_number": round_number},
                )
            if self._stopped:
                reason = "stopped"
        finally:
            self._publish(
                round_number,
                "arena.finished",
                self.SOURCE,
                {"reason": reason},
            )
        return reason

    def _publish(
        self,
        round_number: int,
        event_type: str,
        source: str,
        data: dict[str, Any],
    ) -> None:
        event = self._packer.pack(
            experiment_id=self._config.experiment_id,
            round_number=round_number,
            source=source,
            type=event_type,
            data=data,
        )
        self._stream.publish(event)

    def _publish_fighter_message(
        self, fighter: Fighter, message: str, round_number: int
    ) -> None:
        self._publish(
            round_number,
            "fighter.message",
            fighter.config.name,
            {"fighter": fighter.config.name, "message": message},
        )

    def _publish_fighter_response(
        self, fighter: Fighter, resp: FighterResponse, round_number: int
    ) -> None:
        self._publish(
            round_number,
            "fighter.response",
            fighter.config.name,
            {
                "fighter": fighter.config.name,
                "content": resp.content,
                "model": resp.model,
                "usage": resp.usage,
                "latency_ms": resp.latency_ms,
            },
        )

    def _publish_fighter_error(
        self, fighter: Fighter, exc: FighterError, round_number: int
    ) -> None:
        self._publish(
            round_number,
            "fighter.error",
            fighter.config.name,
            {"fighter": fighter.config.name, "error": str(exc)},
        )
