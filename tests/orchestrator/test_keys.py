import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fightclub.orchestrator.keys import (
    ENV_VAR_NAMES,
    configured_providers,
    get_api_key,
    load_secrets,
    save_secrets,
)


class KeysTest(unittest.TestCase):
    def test_get_api_key_from_secrets(self) -> None:
        secrets = {ENV_VAR_NAMES["openai"]: "sk-from-secrets"}
        self.assertEqual(get_api_key("openai", secrets=secrets, env={}), "sk-from-secrets")

    def test_get_api_key_falls_back_to_env(self) -> None:
        secrets = {}
        env = {ENV_VAR_NAMES["openai"]: "sk-from-env"}
        self.assertEqual(get_api_key("openai", secrets=secrets, env=env), "sk-from-env")

    def test_secrets_takes_priority_over_env(self) -> None:
        secrets = {ENV_VAR_NAMES["openai"]: "sk-secrets"}
        env = {ENV_VAR_NAMES["openai"]: "sk-env"}
        self.assertEqual(get_api_key("openai", secrets=secrets, env=env), "sk-secrets")

    def test_get_api_key_missing_returns_none(self) -> None:
        self.assertIsNone(get_api_key("openai", secrets={}, env={}))
        self.assertIsNone(get_api_key("unknown_provider", secrets={}, env={}))

    def test_configured_providers(self) -> None:
        secrets = {ENV_VAR_NAMES["openai"]: "sk-x"}
        env = {}
        result = configured_providers(secrets=secrets, env=env)
        self.assertTrue(result["openai"])
        self.assertFalse(result["anthropic"])

    def test_save_and_load_secrets(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "secrets.json"
        save_secrets({ENV_VAR_NAMES["openai"]: "sk-1"}, path=path)
        loaded = load_secrets(path=path)
        self.assertEqual(loaded[ENV_VAR_NAMES["openai"]], "sk-1")

    def test_load_secrets_missing_file_returns_empty(self) -> None:
        self.assertEqual(load_secrets(path="/nonexistent/path/secrets.json"), {})

    def test_load_secrets_invalid_json_returns_empty(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "secrets.json"
        path.write_text("not json", encoding="utf-8")
        self.assertEqual(load_secrets(path=path), {})

    def test_get_api_key_reads_real_env(self) -> None:
        with patch.dict(os.environ, {ENV_VAR_NAMES["anthropic"]: "sk-ant-real"}, clear=False):
            self.assertEqual(get_api_key("anthropic", secrets={}), "sk-ant-real")
