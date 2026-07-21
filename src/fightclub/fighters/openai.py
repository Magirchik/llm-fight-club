import time

import httpx

from .base import Fighter, FighterError, FighterResponse
from .config import FighterConfig


class OpenAIFighter(Fighter):
    """Реализация Fighter для OpenAI-совместимых API через httpx.

    Покрывает OpenAI/GPT, DeepSeek, Together, Groq, локальный vLLM/LM Studio —
    любой сервер с /v1/chat/completions. base_url настраивается.
    """

    def __init__(
        self,
        config: FighterConfig,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
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
        body: dict = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": self._config.system_prompt},
                {"role": "user", "content": message},
            ],
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
        }
        if self._config.seed:
            body["seed"] = self._config.seed
        headers = {
            "Authorization": f"Bearer {self._api_key}",
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
                response = await client.post("/chat/completions", json=body)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise FighterError(f"OpenAI request failed: {exc}") from exc
        latency_ms = int((time.monotonic() - start) * 1000)
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise FighterError(f"Invalid OpenAI response: {exc}") from exc
        if not content or not content.strip():
            raise FighterError("OpenAI returned empty content")
        usage = payload.get("usage", {})
        return FighterResponse(
            content=content,
            model=payload.get("model", self._config.model),
            usage={
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
            },
            latency_ms=latency_ms,
        )
