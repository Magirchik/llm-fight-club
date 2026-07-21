import asyncio
import dataclasses
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fightclub.fighters import Fighter, FighterConfig, FighterResponse
from fightclub.orchestrator import (
    CommentatorSpec,
    ExperimentConfig,
    FighterSpec,
    JudgeLlmSpec,
    RefereeSpec,
    StorageSpec,
    batch_run,
    load_config,
    run_experiment,
    save_meta,
)
from fightclub.orchestrator import runner as runner_mod
from fightclub.orchestrator.config import LANGUAGE_INSTRUCTIONS


def _fighter_spec(name: str, prompt: str) -> FighterSpec:
    return FighterSpec(
        name=name,
        provider="ollama",
        model="m",
        system_prompt=prompt,
        temperature=0.7,
        max_tokens=256,
        base_url="http://localhost:11434",
    )


def _config(
    *,
    experiment_id: str = "exp_test",
    max_rounds: int = 2,
    output_dir: str,
    prompt_a: str = "be_a",
    prompt_b: str = "be_b",
) -> ExperimentConfig:
    return ExperimentConfig(
        experiment_id=experiment_id,
        max_rounds=max_rounds,
        opening_message="opening",
        fighters=[_fighter_spec("alice", prompt_a), _fighter_spec("bob", prompt_b)],
        judge_llm=JudgeLlmSpec(provider="ollama", model="m", temperature=0.0),
        weights={"consistency": 35.0, "contradiction": 30.0},
        referee=RefereeSpec(lss_critical_threshold=0.3, min_rounds=1, publish_continue=False),
        storage=StorageSpec(output_dir=output_dir),
    )


class _StubFighter(Fighter):
    def __init__(self, spec: FighterSpec, responses: list[str]) -> None:
        self._config = FighterConfig(
            name=spec.name,
            provider=spec.provider,
            model=spec.model,
            system_prompt=spec.system_prompt,
            temperature=spec.temperature,
            max_tokens=spec.max_tokens,
        )
        self._responses = list(responses)

    @property
    def config(self) -> FighterConfig:
        return self._config

    async def generate(self, message: str) -> FighterResponse:
        await asyncio.sleep(0)
        return FighterResponse(
            content=self._responses.pop(0), model=self._config.model, usage={}, latency_ms=1
        )


class _StubJudgeLlm(Fighter):
    def __init__(self, spec: JudgeLlmSpec, scores: dict[str, float]) -> None:
        self._config = FighterConfig(
            name="judge_llm",
            provider=spec.provider,
            model=spec.model,
            system_prompt="",
            temperature=spec.temperature,
            max_tokens=2048,
        )
        self._scores = scores

    @property
    def config(self) -> FighterConfig:
        return self._config

    async def generate(self, message: str) -> FighterResponse:
        await asyncio.sleep(0)
        score = 0.5
        for marker, value in self._scores.items():
            if marker in message:
                score = value
                break
        return FighterResponse(
            content=json.dumps({"score": score}),
            model=self._config.model,
            usage={},
            latency_ms=1,
        )


class RunExperimentTest(unittest.IsolatedAsyncioTestCase):
    def _patches(self, scores: dict[str, float], n_responses: int = 20):
        fighter_responses = {
            "alice": [f"a{i}" for i in range(1, n_responses + 1)],
            "bob": [f"b{i}" for i in range(1, n_responses + 1)],
        }
        fighter_factory = lambda spec, language="en": _StubFighter(spec, fighter_responses[spec.name])
        judge_factory = lambda spec: _StubJudgeLlm(spec, scores)
        return (
            patch.object(runner_mod, "_make_fighter", side_effect=fighter_factory),
            patch.object(runner_mod, "_make_judge_llm", side_effect=judge_factory),
        )

    async def test_technical_knockout_writes_files_and_returns_winner(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p1, p2 = self._patches({"be_a": 0.1, "be_b": 0.9})
        with p1, p2:
            result = await run_experiment(_config(output_dir=tmp.name, max_rounds=5))
        self.assertEqual(result.experiment_id, "exp_test")
        self.assertEqual(result.winner, "bob")
        self.assertEqual(result.final_decision["action"], "technical_knockout")
        self.assertTrue(result.events_path.exists())
        self.assertTrue(result.meta_path.exists())
        lines = result.events_path.read_text(encoding="utf-8").strip().split("\n")
        self.assertIn("referee.decision", [json.loads(l)["type"] for l in lines])

    async def test_completed_win_by_higher_lss(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p1, p2 = self._patches({"be_a": 0.6, "be_b": 0.4})
        with p1, p2:
            result = await run_experiment(_config(output_dir=tmp.name, max_rounds=2))
        self.assertEqual(result.reason, "completed")
        self.assertEqual(result.winner, "alice")
        self.assertEqual(result.final_decision["action"], "win")

    async def test_completed_draw_when_close(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p1, p2 = self._patches({"be_a": 0.50, "be_b": 0.51})
        with p1, p2:
            result = await run_experiment(_config(output_dir=tmp.name, max_rounds=2))
        self.assertEqual(result.reason, "completed")
        self.assertIsNone(result.winner)
        self.assertEqual(result.final_decision["action"], "draw")

    async def test_meta_json_contains_configs(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p1, p2 = self._patches({"be_a": 0.6, "be_b": 0.4})
        with p1, p2:
            result = await run_experiment(_config(output_dir=tmp.name, max_rounds=1))
        meta = json.loads(result.meta_path.read_text(encoding="utf-8"))
        self.assertEqual(meta["experiment_id"], "exp_test")
        self.assertEqual(len(meta["fighters"]), 2)
        self.assertEqual(meta["fighters"][0]["name"], "alice")
        self.assertEqual(meta["fighters"][0]["system_prompt"], "be_a")
        self.assertEqual(meta["judge_llm"]["model"], "m")
        self.assertIn("consistency", meta["weights"])
        self.assertEqual(meta["referee"]["min_rounds"], 1)

    async def test_commentator_disabled_by_default(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p1, p2 = self._patches({"be_a": 0.6, "be_b": 0.4})
        with p1, p2:
            with patch.object(runner_mod, "_make_commentator") as mc:
                await run_experiment(_config(output_dir=tmp.name, max_rounds=1))
        mc.assert_not_called()

    async def test_commentator_enabled_is_created(self) -> None:
        class _DummyCommentator:
            async def await_pending(self) -> None:
                return None

            def __call__(self, event) -> None:
                return None

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config = dataclasses.replace(
            _config(output_dir=tmp.name, max_rounds=1),
            commentator=CommentatorSpec(enabled=True, model="m"),
        )
        p1, p2 = self._patches({"be_a": 0.6, "be_b": 0.4})
        with p1, p2:
            with patch.object(
                runner_mod, "_make_commentator", return_value=_DummyCommentator()
            ) as mc:
                await run_experiment(config)
        mc.assert_called_once()


class BatchRunTest(unittest.IsolatedAsyncioTestCase):
    async def test_batch_runs_sequentially(self) -> None:
        configs = []
        tmps = []
        for i in range(3):
            tmp = tempfile.TemporaryDirectory()
            self.addCleanup(tmp.cleanup)
            tmps.append(tmp)
            configs.append(_config(experiment_id=f"e{i}", output_dir=tmp.name, max_rounds=1))
        p1, p2 = (
            patch.object(
                runner_mod,
                "_make_fighter",
                side_effect=lambda spec, language="en": _StubFighter(spec, [f"{spec.name}{j}" for j in range(1, 21)]),
            ),
            patch.object(
                runner_mod,
                "_make_judge_llm",
                side_effect=lambda spec: _StubJudgeLlm(spec, {"be_a": 0.6, "be_b": 0.4}),
            ),
        )
        with p1, p2:
            results = await batch_run(configs)
        self.assertEqual(len(results), 3)
        self.assertEqual([r.experiment_id for r in results], ["e0", "e1", "e2"])
        for r in results:
            self.assertTrue(r.events_path.exists())


class SaveMetaTest(unittest.TestCase):
    def test_creates_dir_and_file(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name) / "nested"
        config = _config(output_dir=str(out), max_rounds=1)
        meta_path = save_meta(config, out)
        self.assertTrue(meta_path.exists())
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self.assertEqual(meta["experiment_id"], "exp_test")


class LanguageInjectionTest(unittest.IsolatedAsyncioTestCase):
    async def test_ru_language_prepended_to_fighter_prompt(self) -> None:
        captured: list[str] = []

        class _Capture(Fighter):
            def __init__(self, spec: FighterSpec, language: str) -> None:
                self._config = FighterConfig(
                    name=spec.name, provider=spec.provider, model=spec.model,
                    system_prompt=runner_mod._with_language(spec.system_prompt, language),
                    temperature=spec.temperature, max_tokens=spec.max_tokens,
                )

            @property
            def config(self) -> FighterConfig:
                return self._config

            async def generate(self, message: str) -> FighterResponse:
                await asyncio.sleep(0)
                captured.append(self._config.system_prompt)
                return FighterResponse(content="ok", model="m", usage={}, latency_ms=1)

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config = dataclasses.replace(_config(output_dir=tmp.name, max_rounds=1), language="ru")
        with patch.object(runner_mod, "_make_fighter", side_effect=_Capture):
            with patch.object(
                runner_mod, "_make_judge_llm",
                side_effect=lambda spec: _StubJudgeLlm(spec, {"be_a": 0.6, "be_b": 0.4}),
            ):
                await run_experiment(config)
        self.assertTrue(all(LANGUAGE_INSTRUCTIONS["ru"] in p for p in captured))
        self.assertTrue(all("be_a" in p or "be_b" in p for p in captured))

    async def test_en_language_prepended_to_fighter_prompt(self) -> None:
        captured: list[str] = []

        class _Capture(Fighter):
            def __init__(self, spec: FighterSpec, language: str) -> None:
                self._config = FighterConfig(
                    name=spec.name, provider=spec.provider, model=spec.model,
                    system_prompt=runner_mod._with_language(spec.system_prompt, language),
                    temperature=spec.temperature, max_tokens=spec.max_tokens,
                )

            @property
            def config(self) -> FighterConfig:
                return self._config

            async def generate(self, message: str) -> FighterResponse:
                await asyncio.sleep(0)
                captured.append(self._config.system_prompt)
                return FighterResponse(content="ok", model="m", usage={}, latency_ms=1)

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config = _config(output_dir=tmp.name, max_rounds=1)
        self.assertEqual(config.language, "en")
        with patch.object(runner_mod, "_make_fighter", side_effect=_Capture):
            with patch.object(
                runner_mod, "_make_judge_llm",
                side_effect=lambda spec: _StubJudgeLlm(spec, {"be_a": 0.6, "be_b": 0.4}),
            ):
                await run_experiment(config)
        self.assertTrue(all(LANGUAGE_INSTRUCTIONS["en"] in p for p in captured))

    def test_with_language_helper(self) -> None:
        self.assertEqual(
            runner_mod._with_language("be logical", "ru"),
            "Respond in Russian. be logical",
        )
        self.assertEqual(
            runner_mod._with_language("be logical", "en"),
            "Respond in English. be logical",
        )
        self.assertEqual(runner_mod._with_language("be logical", "xx"), "be logical")


class BuildFighterTest(unittest.IsolatedAsyncioTestCase):
    async def test_build_openai_fighter_requires_key(self) -> None:
        from fightclub.orchestrator.config import ConfigError

        spec = FighterSpec(
            name="gpt", provider="openai", model="gpt-4o", system_prompt="s",
            base_url="https://api.openai.com/v1",
        )
        with patch.object(runner_mod, "get_api_key", return_value=None):
            with self.assertRaises(ConfigError):
                runner_mod._build_fighter(
                    provider="openai", name="gpt", model="gpt-4o",
                    system_prompt="s", temperature=0.7, max_tokens=256,
                    base_url="https://api.openai.com/v1", extra={},
                )

    async def test_build_openai_fighter_with_key(self) -> None:
        from fightclub.fighters import OpenAIFighter

        with patch.object(runner_mod, "get_api_key", return_value="sk-test"):
            fighter = runner_mod._build_fighter(
                provider="openai", name="gpt", model="gpt-4o",
                system_prompt="s", temperature=0.7, max_tokens=256,
                base_url="https://api.openai.com/v1", extra={},
            )
        self.assertIsInstance(fighter, OpenAIFighter)

    async def test_build_anthropic_fighter_with_key(self) -> None:
        from fightclub.fighters import AnthropicFighter

        with patch.object(runner_mod, "get_api_key", return_value="sk-ant-test"):
            fighter = runner_mod._build_fighter(
                provider="anthropic", name="claude", model="claude-3-5-sonnet-20241022",
                system_prompt="s", temperature=0.7, max_tokens=256,
                base_url="https://api.anthropic.com", extra={},
            )
        self.assertIsInstance(fighter, AnthropicFighter)

    async def test_build_anthropic_fighter_requires_key(self) -> None:
        from fightclub.orchestrator.config import ConfigError

        with patch.object(runner_mod, "get_api_key", return_value=None):
            with self.assertRaises(ConfigError):
                runner_mod._build_fighter(
                    provider="anthropic", name="claude", model="claude-3",
                    system_prompt="s", temperature=0.7, max_tokens=256,
                    base_url="https://api.anthropic.com", extra={},
                )

    async def test_build_ollama_fighter_no_key_needed(self) -> None:
        from fightclub.fighters import OllamaFighter

        fighter = runner_mod._build_fighter(
            provider="ollama", name="a", model="qwen3",
            system_prompt="s", temperature=0.7, max_tokens=256,
            base_url="http://localhost:11434", extra={}, seed=42,
        )
        self.assertIsInstance(fighter, OllamaFighter)
        self.assertEqual(fighter.config.seed, 42)

    async def test_build_openai_fighter_carries_seed(self) -> None:
        with patch.object(runner_mod, "get_api_key", return_value="sk-test"):
            fighter = runner_mod._build_fighter(
                provider="openai", name="gpt", model="gpt-4o",
                system_prompt="s", temperature=0.7, max_tokens=256,
                base_url="https://api.openai.com/v1", extra={}, seed=7,
            )
        self.assertEqual(fighter.config.seed, 7)
