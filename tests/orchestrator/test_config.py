import tempfile
import unittest
from pathlib import Path

from fightclub.judges import DEFAULT_WEIGHTS
from fightclub.orchestrator import (
    CommentatorSpec,
    ConfigError,
    ExperimentConfig,
    FighterSpec,
    JudgeLlmSpec,
    RefereeSpec,
    StorageSpec,
    load_config,
)

SAMPLE_TOML = """
experiment_id = "sample_001"
max_rounds = 5
opening_message = "Defend your position."

[[fighters]]
name = "alice"
provider = "ollama"
model = "llama3.1:8b"
system_prompt = "be_a"
temperature = 0.8
max_tokens = 512
base_url = "http://localhost:11434"

[[fighters]]
name = "bob"
provider = "ollama"
model = "qwen2.5:7b"
system_prompt = "be_b"
temperature = 0.7
max_tokens = 512

[judge_llm]
provider = "ollama"
model = "llama3.1:8b"
temperature = 0.0

[judges.weights]
consistency = 35.0
contradiction = 30.0
reasoning_drift = 20.0
resistance = 10.0
memory = 5.0

[referee]
lss_critical_threshold = 0.3
lss_draw_threshold = 0.05
min_rounds = 2
publish_continue = false

[storage]
output_dir = "experiments"

[commentator]
enabled = false
"""


def _write(text: str) -> Path:
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".toml", delete=False, encoding="utf-8"
    )
    tmp.write(text)
    tmp.close()
    return Path(tmp.name)


class LoadConfigTest(unittest.TestCase):
    def test_parses_sample(self) -> None:
        cfg = load_config(_write(SAMPLE_TOML))
        self.assertEqual(cfg.experiment_id, "sample_001")
        self.assertEqual(cfg.max_rounds, 5)
        self.assertEqual(cfg.opening_message, "Defend your position.")
        self.assertEqual(len(cfg.fighters), 2)
        self.assertEqual(cfg.fighters[0].name, "alice")
        self.assertEqual(cfg.fighters[0].provider, "ollama")
        self.assertEqual(cfg.fighters[0].system_prompt, "be_a")
        self.assertEqual(cfg.fighters[1].name, "bob")
        self.assertEqual(cfg.fighters[1].base_url, "http://localhost:11434")
        self.assertEqual(cfg.judge_llm.model, "llama3.1:8b")
        self.assertEqual(cfg.judge_llm.temperature, 0.0)
        self.assertEqual(cfg.weights["consistency"], 35.0)
        self.assertEqual(cfg.referee.min_rounds, 2)
        self.assertFalse(cfg.referee.publish_continue)
        self.assertEqual(cfg.storage.output_dir, "experiments")
        self.assertFalse(cfg.commentator.enabled)

    def test_defaults_when_optional_tables_absent(self) -> None:
        minimal = """
experiment_id = "e1"
max_rounds = 1
opening_message = "hi"

[[fighters]]
name = "a"
provider = "ollama"
model = "m"
system_prompt = "s"

[[fighters]]
name = "b"
provider = "ollama"
model = "m"
system_prompt = "s"

[judge_llm]
provider = "ollama"
model = "m"
"""
        cfg = load_config(_write(minimal))
        self.assertEqual(cfg.referee, RefereeSpec())
        self.assertEqual(cfg.storage, StorageSpec())
        self.assertEqual(cfg.commentator, CommentatorSpec())
        self.assertEqual(cfg.weights, dict(DEFAULT_WEIGHTS))
        self.assertEqual(cfg.fighters[0].temperature, 0.7)
        self.assertEqual(cfg.fighters[0].max_tokens, 1024)

    def test_missing_experiment_id(self) -> None:
        with self.assertRaises(ConfigError):
            load_config(_write('max_rounds = 1\nopening_message = "x"\n'))

    def test_negative_max_rounds(self) -> None:
        bad = SAMPLE_TOML.replace("max_rounds = 5", "max_rounds = -1")
        with self.assertRaises(ConfigError):
            load_config(_write(bad))

    def test_not_two_fighters(self) -> None:
        one_fighter = """
experiment_id = "e1"
max_rounds = 1
opening_message = "hi"

[[fighters]]
name = "solo"
provider = "ollama"
model = "m"
system_prompt = "s"

[judge_llm]
provider = "ollama"
model = "m"
"""
        with self.assertRaises(ConfigError):
            load_config(_write(one_fighter))

    def test_duplicate_fighter_names(self) -> None:
        bad = SAMPLE_TOML.replace('name = "bob"', 'name = "alice"')
        with self.assertRaises(ConfigError):
            load_config(_write(bad))

    def test_unsupported_provider(self) -> None:
        bad = SAMPLE_TOML.replace('provider = "ollama"\nmodel = "qwen2.5:7b"', 'provider = "gemini"\nmodel = "gemini-pro"')
        with self.assertRaises(ConfigError):
            load_config(_write(bad))

    def test_missing_judge_llm(self) -> None:
        bad = SAMPLE_TOML.replace("[judge_llm]\nprovider = \"ollama\"\nmodel = \"llama3.1:8b\"\ntemperature = 0.0\n", "")
        with self.assertRaises(ConfigError):
            load_config(_write(bad))

    def test_unsupported_judge_provider(self) -> None:
        bad = SAMPLE_TOML.replace(
            '[judge_llm]\nprovider = "ollama"',
            '[judge_llm]\nprovider = "gemini"',
        )
        with self.assertRaises(ConfigError):
            load_config(_write(bad))

    def test_frozen_config(self) -> None:
        from dataclasses import FrozenInstanceError

        cfg = load_config(_write(SAMPLE_TOML))
        with self.assertRaises(FrozenInstanceError):
            cfg.experiment_id = "x"  # type: ignore[misc]

    def test_default_language_is_en(self) -> None:
        minimal = """
experiment_id = "e1"
max_rounds = 1
opening_message = "hi"

[[fighters]]
name = "a"
provider = "ollama"
model = "m"
system_prompt = "s"

[[fighters]]
name = "b"
provider = "ollama"
model = "m"
system_prompt = "s"

[judge_llm]
provider = "ollama"
model = "m"
"""
        cfg = load_config(_write(minimal))
        self.assertEqual(cfg.language, "en")

    def test_language_ru_parsed(self) -> None:
        toml = SAMPLE_TOML.replace(
            'opening_message = "Defend your position."',
            'opening_message = "Defend your position."\nlanguage = "ru"',
        )
        cfg = load_config(_write(toml))
        self.assertEqual(cfg.language, "ru")

    def test_unsupported_language_rejected(self) -> None:
        toml = SAMPLE_TOML.replace(
            'opening_message = "Defend your position."',
            'opening_message = "Defend your position."\nlanguage = "fr"',
        )
        with self.assertRaises(ConfigError):
            load_config(_write(toml))

    def test_openai_provider_accepted(self) -> None:
        toml = SAMPLE_TOML.replace(
            'provider = "ollama"\nmodel = "llama3.1:8b"',
            'provider = "openai"\nmodel = "gpt-4o"',
            1,
        )
        cfg = load_config(_write(toml))
        self.assertEqual(cfg.fighters[0].provider, "openai")
        self.assertEqual(cfg.fighters[0].model, "gpt-4o")

    def test_anthropic_provider_accepted(self) -> None:
        toml = SAMPLE_TOML.replace(
            'provider = "ollama"\nmodel = "qwen2.5:7b"',
            'provider = "anthropic"\nmodel = "claude-3-5-sonnet-20241022"',
        )
        cfg = load_config(_write(toml))
        self.assertEqual(cfg.fighters[1].provider, "anthropic")

    def test_unsupported_provider_rejected(self) -> None:
        toml = SAMPLE_TOML.replace('provider = "ollama"', 'provider = "gemini"', 1)
        with self.assertRaises(ConfigError):
            load_config(_write(toml))

    def test_commentator_provider_parsed(self) -> None:
        toml = SAMPLE_TOML.replace(
            "[commentator]\nenabled = false",
            '[commentator]\nenabled = false\nprovider = "openai"\nmodel = "gpt-4o-mini"',
        )
        cfg = load_config(_write(toml))
        self.assertEqual(cfg.commentator.provider, "openai")
        self.assertEqual(cfg.commentator.model, "gpt-4o-mini")

    def test_fighter_seed_parsed(self) -> None:
        toml = SAMPLE_TOML.replace(
            'system_prompt = "be_a"',
            'system_prompt = "be_a"\nseed = 42',
        )
        cfg = load_config(_write(toml))
        self.assertEqual(cfg.fighters[0].seed, 42)
        self.assertEqual(cfg.fighters[1].seed, 0)

    def test_judge_seed_parsed(self) -> None:
        toml = SAMPLE_TOML.replace(
            'model = "llama3.1:8b"\ntemperature = 0.0\n',
            'model = "llama3.1:8b"\ntemperature = 0.0\nseed = 7\n',
        )
        cfg = load_config(_write(toml))
        self.assertEqual(cfg.judge_llm.seed, 7)

    def test_commentator_seed_parsed(self) -> None:
        toml = SAMPLE_TOML.replace(
            "[commentator]\nenabled = false",
            "[commentator]\nenabled = false\nseed = 99",
        )
        cfg = load_config(_write(toml))
        self.assertEqual(cfg.commentator.seed, 99)
