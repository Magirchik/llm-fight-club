import unittest

import httpx

from fightclub.fighters import FighterConfig, FighterError, OpenAIFighter


def _config() -> FighterConfig:
    return FighterConfig(
        name="gpt_fighter",
        provider="openai",
        model="gpt-4o",
        system_prompt="You are a logical fighter.",
        temperature=0.7,
        max_tokens=256,
    )


class OpenAIFighterTest(unittest.IsolatedAsyncioTestCase):
    def _make(self, handler) -> OpenAIFighter:
        transport = httpx.MockTransport(handler)
        return OpenAIFighter(
            _config(), api_key="sk-test", base_url="https://api.test/v1", transport=transport
        )

    async def test_generate_returns_content_and_usage(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["Authorization"] == "Bearer sk-test"
            body = request.read().decode()
            self.assertIn('"model":"gpt-4o"', body)
            self.assertIn("You are a logical fighter.", body)
            self.assertIn('"temperature":0.7', body)
            self.assertIn('"max_tokens":256', body)
            return httpx.Response(
                200,
                json={
                    "model": "gpt-4o",
                    "choices": [
                        {"message": {"role": "assistant", "content": "hello world"}}
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                },
            )

        fighter = self._make(handler)
        resp = await fighter.generate("hi")
        self.assertEqual(resp.content, "hello world")
        self.assertEqual(resp.model, "gpt-4o")
        self.assertEqual(resp.usage["prompt_tokens"], 10)
        self.assertEqual(resp.usage["completion_tokens"], 5)

    async def test_config_property(self) -> None:
        fighter = self._make(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]}))
        self.assertEqual(fighter.config.name, "gpt_fighter")

    async def test_raises_on_http_error(self) -> None:
        fighter = self._make(lambda r: httpx.Response(401, text="unauthorized"))
        with self.assertRaises(FighterError):
            await fighter.generate("hi")

    async def test_raises_on_invalid_response(self) -> None:
        fighter = self._make(lambda r: httpx.Response(200, json={"unexpected": True}))
        with self.assertRaises(FighterError):
            await fighter.generate("hi")

    async def test_raises_on_empty_content(self) -> None:
        fighter = self._make(
            lambda r: httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})
        )
        with self.assertRaises(FighterError):
            await fighter.generate("hi")

    async def test_custom_base_url_for_deepseek(self) -> None:
        captured: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(str(request.url))
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        transport = httpx.MockTransport(handler)
        fighter = OpenAIFighter(
            _config(), api_key="sk-ds", base_url="https://api.deepseek.com/v1", transport=transport
        )
        await fighter.generate("hi")
        self.assertIn("api.deepseek.com", captured[0])

    async def test_seed_included_when_nonzero(self) -> None:
        captured: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request.read().decode())
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        config = FighterConfig(
            name="f", provider="openai", model="gpt-4o", system_prompt="s", seed=42,
        )
        fighter = OpenAIFighter(
            config, api_key="sk-test", base_url="https://api.test/v1",
            transport=httpx.MockTransport(handler),
        )
        await fighter.generate("hi")
        self.assertIn('"seed":42', captured[0])

    async def test_seed_omitted_when_zero(self) -> None:
        captured: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request.read().decode())
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        config = FighterConfig(
            name="f", provider="openai", model="gpt-4o", system_prompt="s", seed=0,
        )
        fighter = OpenAIFighter(
            config, api_key="sk-test", base_url="https://api.test/v1",
            transport=httpx.MockTransport(handler),
        )
        await fighter.generate("hi")
        self.assertNotIn("seed", captured[0])
