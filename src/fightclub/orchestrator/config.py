import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fightclub.commentator import DEFAULT_SYSTEM_PROMPT
from fightclub.judges import DEFAULT_WEIGHTS

SUPPORTED_LANGUAGES: dict[str, str] = {"en": "English", "ru": "Русский"}

LANGUAGE_INSTRUCTIONS: dict[str, str] = {
    "en": "Respond in English.",
    "ru": "Respond in Russian.",
}

SUPPORTED_PROVIDERS: set[str] = {"ollama", "openai", "anthropic"}


@dataclass(frozen=True, slots=True)
class FighterSpec:
    name: str
    provider: str
    model: str
    system_prompt: str
    temperature: float = 0.7
    max_tokens: int = 1024
    seed: int = 0
    extra: dict[str, Any] = field(default_factory=dict)
    base_url: str = "http://localhost:11434"


@dataclass(frozen=True, slots=True)
class JudgeLlmSpec:
    provider: str
    model: str
    temperature: float = 0.0
    seed: int = 0
    base_url: str = "http://localhost:11434"


@dataclass(frozen=True, slots=True)
class RefereeSpec:
    lss_critical_threshold: float = 0.3
    lss_draw_threshold: float = 0.05
    min_rounds: int = 1
    publish_continue: bool = False


@dataclass(frozen=True, slots=True)
class StorageSpec:
    output_dir: str = "experiments"
    filename: str = ""


@dataclass(frozen=True, slots=True)
class CommentatorSpec:
    enabled: bool = False
    provider: str = "ollama"
    model: str = "llama3.1:8b"
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    temperature: float = 1.0
    max_tokens: int = 512
    seed: int = 0
    base_url: str = "http://localhost:11434"
    timeout: float = 60.0


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    experiment_id: str
    max_rounds: int
    opening_message: str
    fighters: list[FighterSpec]
    judge_llm: JudgeLlmSpec
    language: str = "en"
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    referee: RefereeSpec = RefereeSpec()
    storage: StorageSpec = StorageSpec()
    commentator: CommentatorSpec = CommentatorSpec()


class ConfigError(ValueError):
    """Ошибка конфигурации эксперимента."""


def load_config(path: str | Path) -> ExperimentConfig:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return _parse_config(data)


def _parse_config(data: dict[str, Any]) -> ExperimentConfig:
    experiment_id = data.get("experiment_id")
    if not isinstance(experiment_id, str) or not experiment_id:
        raise ConfigError("experiment_id is required")
    max_rounds = data.get("max_rounds")
    if not isinstance(max_rounds, int) or max_rounds < 0:
        raise ConfigError("max_rounds must be a non-negative integer")
    opening_message = data.get("opening_message")
    if not isinstance(opening_message, str):
        raise ConfigError("opening_message is required")

    fighter_list = data.get("fighters", [])
    if not isinstance(fighter_list, list) or len(fighter_list) != 2:
        raise ConfigError("exactly 2 [[fighters]] entries are required")
    fighters = [_parse_fighter(f, i) for i, f in enumerate(fighter_list)]
    names = [f.name for f in fighters]
    if len(set(names)) != 2:
        raise ConfigError("fighters must have unique names")

    judge_llm = _parse_judge_llm(data.get("judge_llm"))
    language = data.get("language", "en")
    if not isinstance(language, str) or language not in SUPPORTED_LANGUAGES:
        raise ConfigError(
            f"unsupported language: {language!r} (supported: {sorted(SUPPORTED_LANGUAGES)})"
        )
    weights = data.get("judges", {}).get("weights", {})
    if not isinstance(weights, dict) or not weights:
        weights = dict(DEFAULT_WEIGHTS)
    parsed_weights = {k: float(v) for k, v in weights.items()}

    referee = _parse_referee(data.get("referee"))
    storage = _parse_storage(data.get("storage"))
    commentator = _parse_commentator(data.get("commentator"))

    return ExperimentConfig(
        experiment_id=experiment_id,
        max_rounds=max_rounds,
        opening_message=opening_message,
        fighters=fighters,
        judge_llm=judge_llm,
        language=language,
        weights=parsed_weights,
        referee=referee,
        storage=storage,
        commentator=commentator,
    )


def _parse_fighter(data: dict[str, Any], index: int) -> FighterSpec:
    if not isinstance(data, dict):
        raise ConfigError(f"fighter #{index} must be a table")
    name = data.get("name")
    if not isinstance(name, str) or not name:
        raise ConfigError(f"fighter #{index}: name is required")
    provider = data.get("provider", "ollama")
    if not isinstance(provider, str):
        raise ConfigError(f"fighter #{index}: provider must be a string")
    if provider not in SUPPORTED_PROVIDERS:
        raise ConfigError(
            f"fighter #{index}: provider '{provider}' is not supported "
            f"(supported: {sorted(SUPPORTED_PROVIDERS)})"
        )
    model = data.get("model")
    if not isinstance(model, str) or not model:
        raise ConfigError(f"fighter #{index}: model is required")
    system_prompt = data.get("system_prompt", "")
    return FighterSpec(
        name=name,
        provider=provider,
        model=model,
        system_prompt=system_prompt,
        temperature=float(data.get("temperature", 0.7)),
        max_tokens=int(data.get("max_tokens", 1024)),
        seed=int(data.get("seed", 0)),
        extra=dict(data.get("extra", {})),
        base_url=data.get("base_url", "http://localhost:11434"),
    )


def _parse_judge_llm(data: dict[str, Any] | None) -> JudgeLlmSpec:
    if not isinstance(data, dict):
        raise ConfigError("[judge_llm] table is required")
    provider = data.get("provider", "ollama")
    if provider not in SUPPORTED_PROVIDERS:
        raise ConfigError(
            f"judge_llm provider '{provider}' is not supported "
            f"(supported: {sorted(SUPPORTED_PROVIDERS)})"
        )
    model = data.get("model")
    if not isinstance(model, str) or not model:
        raise ConfigError("judge_llm: model is required")
    return JudgeLlmSpec(
        provider=provider,
        model=model,
        temperature=float(data.get("temperature", 0.0)),
        seed=int(data.get("seed", 0)),
        base_url=data.get("base_url", "http://localhost:11434"),
    )


def _parse_referee(data: dict[str, Any] | None) -> RefereeSpec:
    if data is None:
        return RefereeSpec()
    if not isinstance(data, dict):
        raise ConfigError("[referee] must be a table")
    return RefereeSpec(
        lss_critical_threshold=float(data.get("lss_critical_threshold", 0.3)),
        lss_draw_threshold=float(data.get("lss_draw_threshold", 0.05)),
        min_rounds=int(data.get("min_rounds", 1)),
        publish_continue=bool(data.get("publish_continue", False)),
    )


def _parse_storage(data: dict[str, Any] | None) -> StorageSpec:
    if data is None:
        return StorageSpec()
    if not isinstance(data, dict):
        raise ConfigError("[storage] must be a table")
    return StorageSpec(
        output_dir=data.get("output_dir", "experiments"),
        filename=data.get("filename", ""),
    )


def _parse_commentator(data: dict[str, Any] | None) -> CommentatorSpec:
    if data is None:
        return CommentatorSpec()
    if not isinstance(data, dict):
        raise ConfigError("[commentator] must be a table")
    provider = data.get("provider", "ollama")
    if provider not in SUPPORTED_PROVIDERS:
        raise ConfigError(
            f"commentator provider '{provider}' is not supported "
            f"(supported: {sorted(SUPPORTED_PROVIDERS)})"
        )
    return CommentatorSpec(
        enabled=bool(data.get("enabled", False)),
        provider=provider,
        model=data.get("model", "llama3.1:8b"),
        system_prompt=data.get("system_prompt", DEFAULT_SYSTEM_PROMPT),
        temperature=float(data.get("temperature", 1.0)),
        max_tokens=int(data.get("max_tokens", 512)),
        seed=int(data.get("seed", 0)),
        base_url=data.get("base_url", "http://localhost:11434"),
        timeout=float(data.get("timeout", 60.0)),
    )
