import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fightclub.arena import ArenaConfig, ArenaController
from fightclub.commentator import Commentator
from fightclub.core.event import Event
from fightclub.event_stream import EventPacker, EventStream
from fightclub.fighters import (
    AnthropicFighter,
    Fighter,
    FighterConfig,
    FighterError,
    OllamaFighter,
    OpenAIFighter,
)
from fightclub.judges import (
    ConsistencyJudge,
    ContradictionJudge,
    Judge,
    MemoryJudge,
    ReasoningDriftJudge,
    ResistanceJudge,
)
from fightclub.referee import Referee, RefereeConfig
from fightclub.scorekeeper import Scorekeeper, ScorekeeperConfig
from fightclub.storage import Storage, StorageConfig

from .config import (
    CommentatorSpec,
    ConfigError,
    ExperimentConfig,
    FighterSpec,
    JudgeLlmSpec,
    LANGUAGE_INSTRUCTIONS,
)
from .keys import get_api_key


class ResultCollector:
    """Внутренний sink composition root: собирает финальное решение и причину."""

    def __init__(self) -> None:
        self.final_decision: dict[str, Any] | None = None
        self.winner: str | None = None
        self.reason: str | None = None

    def __call__(self, event: Event) -> None:
        if event.type == "referee.decision":
            self.final_decision = event.data
            self.winner = event.data.get("winner")
        elif event.type == "arena.finished":
            self.reason = event.data.get("reason")


class ExperimentResult:
    __slots__ = (
        "experiment_id",
        "reason",
        "events_path",
        "meta_path",
        "final_decision",
        "winner",
    )

    def __init__(
        self,
        *,
        experiment_id: str,
        reason: str,
        events_path: Path,
        meta_path: Path,
        final_decision: dict[str, Any] | None,
        winner: str | None,
    ) -> None:
        self.experiment_id = experiment_id
        self.reason = reason
        self.events_path = events_path
        self.meta_path = meta_path
        self.final_decision = final_decision
        self.winner = winner

    def __repr__(self) -> str:
        return (
            f"ExperimentResult(experiment_id={self.experiment_id!r}, "
            f"reason={self.reason!r}, winner={self.winner!r})"
        )


def save_meta(config: ExperimentConfig, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    meta_path = output_dir / f"{config.experiment_id}.meta.json"
    meta = {
        "experiment_id": config.experiment_id,
        "max_rounds": config.max_rounds,
        "opening_message": config.opening_message,
        "fighters": [asdict(f) for f in config.fighters],
        "judge_llm": asdict(config.judge_llm),
        "weights": dict(config.weights),
        "referee": asdict(config.referee),
        "storage": asdict(config.storage),
        "commentator": asdict(config.commentator),
    }
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta_path


def _make_fighter(spec: FighterSpec, language: str = "en") -> Fighter:
    return _build_fighter(
        provider=spec.provider,
        name=spec.name,
        model=spec.model,
        system_prompt=_with_language(spec.system_prompt, language),
        temperature=spec.temperature,
        max_tokens=spec.max_tokens,
        seed=spec.seed,
        base_url=spec.base_url,
        extra=dict(spec.extra),
    )


def _make_judge_llm(spec: JudgeLlmSpec) -> Fighter:
    return _build_fighter(
        provider=spec.provider,
        name="judge_llm",
        model=spec.model,
        system_prompt="",
        temperature=spec.temperature,
        max_tokens=2048,
        seed=spec.seed,
        base_url=spec.base_url,
        extra={},
    )


def _build_fighter(
    *,
    provider: str,
    name: str,
    model: str,
    system_prompt: str,
    temperature: float,
    max_tokens: int,
    base_url: str,
    extra: dict[str, Any],
    seed: int = 0,
) -> Fighter:
    config = FighterConfig(
        name=name,
        provider=provider,
        model=model,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        seed=seed,
        extra=dict(extra),
    )
    if provider == "ollama":
        return OllamaFighter(config, base_url=base_url)
    if provider == "openai":
        key = get_api_key("openai")
        if not key:
            raise ConfigError(
                "OpenAI API key not found. Set OPENAI_API_KEY env var "
                "or add it via dashboard Settings."
            )
        return OpenAIFighter(config, api_key=key, base_url=base_url)
    if provider == "anthropic":
        key = get_api_key("anthropic")
        if not key:
            raise ConfigError(
                "Anthropic API key not found. Set ANTHROPIC_API_KEY env var "
                "or add it via dashboard Settings."
            )
        return AnthropicFighter(config, api_key=key, base_url=base_url)
    raise ConfigError(f"Unsupported provider: {provider}")


def _with_language(prompt: str, language: str) -> str:
    instruction = LANGUAGE_INSTRUCTIONS.get(language)
    if not instruction:
        return prompt
    return f"{instruction} {prompt}".strip()


def _make_judges(llm: Fighter) -> list[Judge]:
    return [
        ConsistencyJudge(llm),
        ContradictionJudge(llm),
        ReasoningDriftJudge(llm),
        ResistanceJudge(llm),
        MemoryJudge(llm),
    ]


async def run_experiment(config: ExperimentConfig) -> ExperimentResult:
    packer = EventPacker()
    components: list[Any] = []
    stream = EventStream(components)

    fighters = [_make_fighter(s, config.language) for s in config.fighters]
    judge_llm = _make_judge_llm(config.judge_llm)
    judges = _make_judges(judge_llm)
    system_prompts = {s.name: s.system_prompt for s in config.fighters}

    storage = Storage(
        StorageConfig(
            experiment_id=config.experiment_id,
            output_dir=config.storage.output_dir,
            filename=config.storage.filename,
        )
    )
    keeper = Scorekeeper(
        ScorekeeperConfig(
            experiment_id=config.experiment_id,
            system_prompts=system_prompts,
            weights=dict(config.weights),
        ),
        judges,
        stream,
        packer,
    )
    referee = Referee(
        RefereeConfig(
            experiment_id=config.experiment_id,
            lss_critical_threshold=config.referee.lss_critical_threshold,
            lss_draw_threshold=config.referee.lss_draw_threshold,
            min_rounds=config.referee.min_rounds,
            publish_continue=config.referee.publish_continue,
        ),
        stream,
        packer,
    )
    arena = ArenaController(
        ArenaConfig(
            experiment_id=config.experiment_id,
            max_rounds=config.max_rounds,
            opening_message=config.opening_message,
        ),
        fighters,
        stream,
        packer,
    )
    collector = ResultCollector()
    commentator: Commentator | None = None
    if config.commentator.enabled:
        commentator = _make_commentator(config.commentator, config.language)

    components.extend([collector, storage, keeper, referee, arena])
    if commentator is not None:
        components.append(commentator)

    meta_path = save_meta(config, storage.path.parent)

    reason = await arena.run()
    await keeper.await_pending()
    if commentator is not None:
        await commentator.await_pending()

    return ExperimentResult(
        experiment_id=config.experiment_id,
        reason=reason,
        events_path=storage.path,
        meta_path=meta_path,
        final_decision=collector.final_decision,
        winner=collector.winner,
    )


async def batch_run(configs: list[ExperimentConfig]) -> list[ExperimentResult]:
    results: list[ExperimentResult] = []
    for config in configs:
        results.append(await run_experiment(config))
    return results


def _make_commentator(spec: CommentatorSpec, language: str = "en") -> Commentator:
    fighter = _build_fighter(
        provider=spec.provider,
        name="commentator",
        model=spec.model,
        system_prompt=_with_language(spec.system_prompt, language),
        temperature=spec.temperature,
        max_tokens=spec.max_tokens,
        seed=spec.seed,
        base_url=spec.base_url,
        extra={},
    )
    return Commentator(fighter)