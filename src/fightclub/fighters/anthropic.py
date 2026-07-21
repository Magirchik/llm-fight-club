import time

import httpx

from .base import Fighter, FighterError, FighterResponse
from .config import FighterConfig


class AnthropicFighter(Fighter):
    """Реализация Fighter для Anthropic Claude через httpx.

    Авторизация: x-api-key, заголовок anthropic-version. System prompt передаётся
    отдельным top-level параметром (особенность Anthropic API).
    """

    ANTHROPIC_VERSION = "2023-06-01"

    def __init__(
        self,
        config: FighterConfig,
        *,
        api_key: str,
        base_url: str = "https://api.anthropic.com",
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout
        self._transport = transport

    @property
    def config(self) -> FighterConfig:
        return self._config

    async def generate(self, message: str) -> FighterResponse:
        body = {
            "model": self._config.model,
            "system": self._config.system_prompt,
            "messages": [
                {"role": "user", "content": message},
            ],
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": self.ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                transport=self._transport,
                headers=headers,
            ) as client:
                response = await client.post("/v1/messages", json=body)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise FighterError(f"Anthropic request failed: {exc}") from exc
        latency_ms = int((time.monotonic() - start) * 1000)
        try:
            content = payload["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise FighterError(f"Invalid Anthropic response: {exc}") from exc
        if not content or not content.strip():
            raise FighterError("Anthropic returned empty content")
        usage = payload.get("usage", {})
        return FighterResponse(
            content=content,
            model=payload.get("model", self._config.model),
            usage={
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
            },
            latency_ms=latency_ms,
        )
