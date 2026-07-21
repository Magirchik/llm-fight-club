import unittest

import httpx

from fightclub.fighters import AnthropicFighter, FighterConfig, FighterError


def _config() -> FighterConfig:
    return FighterConfig(
        name="claude_fighter",
        provider="anthropic",
        model="claude-3-5-sonnet-20241022",
        system_prompt="You are a logical fighter.",
        temperature=0.7,
        max_tokens=256,
    )


class AnthropicFighterTest(unittest.IsolatedAsyncioTestCase):
    def _make(self, handler) -> AnthropicFighter:
        transport = httpx.MockTransport(handler)
        return AnthropicFighter(
            _config(), api_key="sk-ant-test", base_url="https://api.test", transport=transport
        )

    async def test_generate_returns_content_and_usage(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["x-api-key"] == "sk-ant-test"
            assert "anthropic-version" in request.headers
            body = request.read().decode()
            self.assertIn('"model":"claude-3-5-sonnet-20241022"', body)
            self.assertIn('"system":"You are a logical fighter."', body)
            self.assertIn('"temperature":0.7', body)
            self.assertIn('"max_tokens":256', body)
            return httpx.Response(
                200,
                json={
                    "model": "claude-3-5-sonnet-20241022",
                    "content": [{"type": "text", "text": "hello world"}],
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
            )

        fighter = self._make(handler)
        resp = await fighter.generate("hi")
        self.assertEqual(resp.content, "hello world")
        self.assertEqual(resp.model, "claude-3-5-sonnet-20241022")
        self.assertEqual(resp.usage["input_tokens"], 10)
        self.assertEqual(resp.usage["output_tokens"], 5)

    async def test_config_property(self) -> None:
        fighter = self._make(
            lambda r: httpx.Response(200, json={"content": [{"type": "text", "text": "x"}]})
        )
        self.assertEqual(fighter.config.name, "claude_fighter")

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
            lambda r: httpx.Response(200, json={"content": [{"type": "text", "text": ""}]})
        )
        with self.assertRaises(FighterError):
            await fighter.generate("hi")
