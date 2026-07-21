import time
from typing import Any

import httpx

from .base import Fighter, FighterError, FighterResponse
from .config import FighterConfig


class OllamaFighter(Fighter):
    """Реализация Fighter для Ollama через httpx."""

    def __init__(
        self,
        config: FighterConfig,
        *,
        base_url: str = "http://localhost:11434",
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._base_url = base_url
        self._timeout = timeout
        self._transport = transport

    @property
    def config(self) -> FighterConfig:
        return self._config

    async def generate(self, message: str) -> FighterResponse:
        think = bool(self._config.extra.get("think", False))
        options: dict[str, Any] = {
            "temperature": self._config.temperature,
            "num_predict": self._config.max_tokens,
        }
        if self._config.seed:
            options["seed"] = self._config.seed
        body = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": self._config.system_prompt},
                {"role": "user", "content": message},
            ],
            "stream": False,
            "think": think,
            "options": options,
        }
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.post("/api/chat", json=body)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise FighterError(f"Ollama request failed: {exc}") from exc
        latency_ms = int((time.monotonic() - start) * 1000)
        message_obj = payload.get("message") or {}
        content = message_obj.get("content") or ""
        if not content.strip():
            content = message_obj.get("thinking") or ""
        if not content.strip():
            raise FighterError("Ollama returned empty content")
        usage = {
            "prompt_eval_count": payload.get("prompt_eval_count"),
            "eval_count": payload.get("eval_count"),
        }
        return FighterResponse(
            content=content,
            model=payload.get("model", self._config.model),
            usage=usage,
            latency_ms=latency_ms,
        )
