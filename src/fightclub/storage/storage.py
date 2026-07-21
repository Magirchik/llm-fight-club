import json
from pathlib import Path
from typing import Any

from fightclub.core.event import Event

from .config import StorageConfig


def serialize_event(event: Event) -> dict[str, Any]:
    return {
        "id": event.id,
        "datetime": event.datetime.isoformat(),
        "experiment_id": event.experiment_id,
        "round_number": event.round_number,
        "source": event.source,
        "type": event.type,
        "data": event.data,
    }


class Storage:
    """Компонент Event Stream, сохраняющий все события в JSONL-файл.

    Синхронная append-запись по одному событию. Не фильтрует события.
    """

    def __init__(self, config: StorageConfig) -> None:
        self._config = config
        self._path = self._resolve_path(config)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _resolve_path(config: StorageConfig) -> Path:
        name = config.filename or f"{config.experiment_id}.jsonl"
        return Path(config.output_dir) / name

    @property
    def path(self) -> Path:
        return self._path

    def __call__(self, event: Event) -> None:
        line = json.dumps(serialize_event(event), ensure_ascii=False)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
