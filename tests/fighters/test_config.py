import unittest
from dataclasses import FrozenInstanceError

from fightclub.fighters import FighterConfig


class FighterConfigTest(unittest.TestCase):
    def test_defaults(self) -> None:
        cfg = FighterConfig(name="a", provider="ollama", model="m", system_prompt="s")
        self.assertEqual(cfg.temperature, 0.7)
        self.assertEqual(cfg.max_tokens, 1024)
        self.assertEqual(cfg.extra, {})

    def test_custom_values(self) -> None:
        cfg = FighterConfig(
            name="a",
            provider="ollama",
            model="m",
            system_prompt="s",
            temperature=0.2,
            max_tokens=512,
            extra={"base_url": "http://x"},
        )
        self.assertEqual(cfg.temperature, 0.2)
        self.assertEqual(cfg.max_tokens, 512)
        self.assertEqual(cfg.extra["base_url"], "http://x")

    def test_frozen(self) -> None:
        cfg = FighterConfig(name="a", provider="ollama", model="m", system_prompt="s")
        with self.assertRaises(FrozenInstanceError):
            cfg.temperature = 0.5  # type: ignore[misc]
