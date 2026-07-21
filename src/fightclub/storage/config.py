from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StorageConfig:
    experiment_id: str
    output_dir: str = "experiments"
    filename: str = ""
