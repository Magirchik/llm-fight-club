import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fightclub.__main__ import main
from fightclub.orchestrator import runner as runner_mod
from fightclub.fighters import Fighter, FighterConfig, FighterResponse
from fightclub.orchestrator import FighterSpec, JudgeLlmSpec
import asyncio


SAMPLE_TOML = """
experiment_id = "cli_test"
max_rounds = 1
opening_message = "hi"

[[fighters]]
name = "alice"
provider = "ollama"
model = "m"
system_prompt = "be_a"

[[fighters]]
name = "bob"
provider = "ollama"
model = "m"
system_prompt = "be_b"

[judge_llm]
provider = "ollama"
model = "m"
"""


class _StubFighter(Fighter):
    def __init__(self, spec: FighterSpec, responses: list[str]) -> None:
        self._config = FighterConfig(
            name=spec.name, provider=spec.provider, model=spec.model,
            system_prompt=spec.system_prompt, temperature=0.7, max_tokens=256,
        )
        self._responses = list(responses)

    @property
    def config(self) -> FighterConfig:
        return self._config

    async def generate(self, message: str) -> FighterResponse:
        await asyncio.sleep(0)
        return FighterResponse(
            content=self._responses.pop(0), model="m", usage={}, latency_ms=1
        )


class _StubJudgeLlm(Fighter):
    def __init__(self, spec: JudgeLlmSpec) -> None:
        self._config = FighterConfig(
            name="judge_llm", provider=spec.provider, model=spec.model,
            system_prompt="", temperature=0.0, max_tokens=2048,
        )

    @property
    def config(self) -> FighterConfig:
        return self._config

    async def generate(self, message: str) -> FighterResponse:
        await asyncio.sleep(0)
        score = 0.1 if "be_a" in message else 0.9
        return FighterResponse(
            content=json.dumps({"score": score}), model="m", usage={}, latency_ms=1
        )


class CliTest(unittest.TestCase):
    def _patches(self):
        f = lambda spec, language="en": _StubFighter(spec, [f"{spec.name}{i}" for i in range(1, 21)])
        j = lambda spec: _StubJudgeLlm(spec)
        return (
            patch.object(runner_mod, "_make_fighter", side_effect=f),
            patch.object(runner_mod, "_make_judge_llm", side_effect=j),
        )

    def test_run_returns_0_and_prints_result(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out_dir = tmp.name.replace("\\", "/")
        toml_content = SAMPLE_TOML + f'\n[storage]\noutput_dir = "{out_dir}"\n'
        toml_path = Path(tmp.name) / "cfg.toml"
        toml_path.write_text(toml_content, encoding="utf-8")
        p1, p2 = self._patches()
        with p1, p2:
            rc = main(["run", str(toml_path)])
        self.assertEqual(rc, 0)

    def test_run_missing_args_returns_2(self) -> None:
        rc = main(["run"])
        self.assertEqual(rc, 2)

    def test_unknown_command_returns_2(self) -> None:
        rc = main(["frobnicate", "x"])
        self.assertEqual(rc, 2)

    def test_batch_no_toml_files_returns_2(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        rc = main(["batch", tmp.name])
        self.assertEqual(rc, 2)

    def test_batch_not_a_dir_returns_2(self) -> None:
        rc = main(["batch", "nonexistent_directory_xyz"])
        self.assertEqual(rc, 2)

    def test_batch_runs_all_toml(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for i in range(2):
            content = SAMPLE_TOML.replace(
                'experiment_id = "cli_test"', f'experiment_id = "cli_{i}"'
            )
            content = content.replace(
                'name = "alice"', f'name = "alice_{i}"'
            ).replace(
                'name = "bob"', f'name = "bob_{i}"'
            ).replace(
                'system_prompt = "be_a"', f'system_prompt = "be_a_{i}"'
            ).replace(
                'system_prompt = "be_b"', f'system_prompt = "be_b_{i}"'
            )
            content += f'\n[storage]\noutput_dir = "{tmp.name.replace("\\", "/")}"\n'
            Path(tmp.name, f"e{i}.toml").write_text(content, encoding="utf-8")
        p1, p2 = self._patches()
        with p1, p2:
            rc = main(["batch", tmp.name])
        self.assertEqual(rc, 0)
