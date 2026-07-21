import unittest

import httpx

from fightclub.fighters import FighterConfig, FighterError, OllamaFighter


def _config() -> FighterConfig:
    return FighterConfig(
        name="fighter_a",
        provider="ollama",
        model="llama3.1:8b",
        system_prompt="You are a logical fighter.",
        temperature=0.3,
        max_tokens=256,
    )


class OllamaFighterTest(unittest.IsolatedAsyncioTestCase):
    def _make(self, handler) -> OllamaFighter:
        transport = httpx.MockTransport(handler)
        return OllamaFighter(_config(), base_url="http://test", transport=transport)

    async def test_generate_returns_content_and_usage(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = request.read().decode()
            self.assertIn("llama3.1:8b", body)
            self.assertIn("You are a logical fighter.", body)
            self.assertIn("hi", body)
            self.assertIn('"num_predict":256', body)
            self.assertIn('"think":false', body)
            return httpx.Response(
                200,
                json={
                    "model": "llama3.1:8b",
                    "message": {"role": "assistant", "content": "hello"},
                    "prompt_eval_count": 5,
                    "eval_count": 3,
                    "done": True,
                },
            )

        fighter = self._make(handler)
        resp = await fighter.generate("hi")
        self.assertEqual(resp.content, "hello")
        self.assertEqual(resp.model, "llama3.1:8b")
        self.assertEqual(resp.usage["eval_count"], 3)
        self.assertEqual(resp.usage["prompt_eval_count"], 5)
        self.assertGreaterEqual(resp.latency_ms, 0)

    async def test_falls_back_to_thinking_when_content_empty(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "model": "qwen3:latest",
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "thinking": "I should greet the user. Hello!",
                    },
                },
            )

        fighter = self._make(handler)
        resp = await fighter.generate("hi")
        self.assertEqual(resp.content, "I should greet the user. Hello!")

    async def test_raises_on_completely_empty_response(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"message": {"role": "assistant", "content": "", "thinking": ""}},
            )

        fighter = self._make(handler)
        with self.assertRaises(FighterError):
            await fighter.generate("hi")

    async def test_think_flag_from_extra(self) -> None:
        captured: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request.read().decode())
            return httpx.Response(200, json={"message": {"content": "ok"}})

        config = FighterConfig(
            name="f", provider="ollama", model="m", system_prompt="s",
            extra={"think": True},
        )
        fighter = OllamaFighter(config, base_url="http://test", transport=httpx.MockTransport(handler))
        await fighter.generate("hi")
        self.assertIn('"think":true', captured[0])

    async def test_seed_included_in_options_when_nonzero(self) -> None:
        captured: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request.read().decode())
            return httpx.Response(200, json={"message": {"content": "ok"}})

        config = FighterConfig(
            name="f", provider="ollama", model="m", system_prompt="s", seed=42,
        )
        fighter = OllamaFighter(config, base_url="http://test", transport=httpx.MockTransport(handler))
        await fighter.generate("hi")
        self.assertIn('"seed":42', captured[0])

    async def test_seed_omitted_when_zero(self) -> None:
        captured: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request.read().decode())
            return httpx.Response(200, json={"message": {"content": "ok"}})

        config = FighterConfig(
            name="f", provider="ollama", model="m", system_prompt="s", seed=0,
        )
        fighter = OllamaFighter(config, base_url="http://test", transport=httpx.MockTransport(handler))
        await fighter.generate("hi")
        self.assertNotIn("seed", captured[0])

    async def test_config_property(self) -> None:
        fighter = self._make(lambda r: httpx.Response(200, json={"message": {"content": ""}}))
        self.assertEqual(fighter.config.name, "fighter_a")
        self.assertEqual(fighter.config.provider, "ollama")

    async def test_generate_raises_on_http_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        fighter = self._make(handler)
        with self.assertRaises(FighterError):
            await fighter.generate("hi")

    async def test_generate_raises_on_invalid_response(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"unexpected": True})

        fighter = self._make(handler)
        with self.assertRaises(FighterError):
            await fighter.generate("hi")
