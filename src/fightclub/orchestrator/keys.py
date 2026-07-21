import json
import os
from pathlib import Path
from typing import Any

SECRETS_FILE = Path("secrets.json")

ENV_VAR_NAMES: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def load_secrets(path: Path | str | None = None) -> dict[str, Any]:
    p = Path(path) if path else SECRETS_FILE
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_secrets(keys: dict[str, str], path: Path | str | None = None) -> None:
    p = Path(path) if path else SECRETS_FILE
    p.write_text(
        json.dumps(keys, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_api_key(
    provider: str,
    *,
    secrets: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
) -> str | None:
    """Возвращает API-ключ для провайдера: secrets.json имеет приоритет, затем env var."""
    env_var = ENV_VAR_NAMES.get(provider)
    if not env_var:
        return None
    if secrets is None:
        secrets = load_secrets()
    value = secrets.get(env_var)
    if value:
        return str(value)
    if env is None:
        env = os.environ
    return env.get(env_var)


def configured_providers(
    *, secrets: dict[str, Any] | None = None, env: dict[str, str] | None = None
) -> dict[str, bool]:
    """Возвращает {provider: bool} — у каких провайдеров есть ключ."""
    return {
        provider: get_api_key(provider, secrets=secrets, env=env) is not None
        for provider in ENV_VAR_NAMES
    }
