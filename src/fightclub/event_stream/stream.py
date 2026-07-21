from __future__ import annotations

from typing import Callable

from fightclub.core.event import Event


class EventStream:
    """
    Event Bus - центральная система передачи событий.
    
    Получает готовый Event и рассылает его всем компонентам системы.
    История событий сохраняется отдельным компонентом (storage).
    """

    def __init__(self, components: list[Callable[[Event], None]]) -> None:
        self._components = components

    def publish(self, event: Event) -> None:
        """Рассылает событие всем компонентам."""
        for component in self._components:
            component(event)