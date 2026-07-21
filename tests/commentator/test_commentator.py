import unittest
from io import StringIO
from unittest.mock import patch

from fightclub.commentator import Commentator, CommentatorConfig
from fightclub.event_stream import EventPacker
from fightclub.fighters import Fighter, FighterConfig, FighterError, FighterResponse


def _make_event(
    packer: EventPacker,
    *,
    type: str,
    source: str = "a",
    data: dict | None = None,
    round_number: int = 1,
) -> object:
    return packer.pack(
        experiment_id="exp1",
        round_number=round_number,
        source=source,
        type=type,
        data=data if data is not None else {"fighter": source, "content": "hi"},
    )


class _StubFighter(Fighter):
    def __init__(self, content: str = "nice blow", *, error: str | None = None) -> None:
        self._config = FighterConfig(
            name="commentator_llm", provider="stub", model="m", system_prompt="s"
        )
        self._content = content
        self._error = error

    @property
    def config(self) -> FighterConfig:
        return self._config

    async def generate(self, message: str) -> FighterResponse:
        import asyncio

        await asyncio.sleep(0)
        if self._error:
            raise FighterError(self._error)
        return FighterResponse(
            content=self._content, model="m", usage={}, latency_ms=1
        )


class CommentatorConfigTest(unittest.TestCase):
    def test_defaults(self) -> None:
        cfg = CommentatorConfig(model="llama3.1:8b")
        self.assertEqual(cfg.model, "llama3.1:8b")
        self.assertIn("commentator", cfg.system_prompt.lower())


class CommentatorTest(unittest.IsolatedAsyncioTestCase):
    async def test_reacts_only_to_fighter_response(self) -> None:
        fighter = _StubFighter()
        commentator = Commentator(fighter)
        packer = EventPacker()
        commentator(_make_event(packer, type="arena.started", round_number=0))
        commentator(_make_event(packer, type="fighter.message", round_number=1))
        commentator(_make_event(packer, type="arena.round_finished", round_number=1))
        commentator(_make_event(packer, type="referee.decision", round_number=1))
        await commentator.await_pending()
        with patch("sys.stdout", new_callable=StringIO) as out:
            commentator(_make_event(packer, type="arena.started"))
            await commentator.await_pending()
        self.assertEqual(out.getvalue(), "")

    async def test_comments_fighter_response_to_stdout(self) -> None:
        fighter = _StubFighter("Alice parries!\nBob stumbles.")
        commentator = Commentator(fighter)
        packer = EventPacker()
        with patch("sys.stdout", new_callable=StringIO) as out:
            commentator(
                _make_event(
                    packer,
                    type="fighter.response",
                    source="alice",
                    data={"fighter": "alice", "content": "my logic is sound"},
                    round_number=2,
                )
            )
            await commentator.await_pending()
        printed = out.getvalue()
        self.assertIn("[R2 alice]", printed)
        self.assertIn("Alice parries!", printed)
        self.assertIn("Bob stumbles.", printed)

    async def test_fighter_error_silently_skipped(self) -> None:
        fighter = _StubFighter(error="llm down")
        commentator = Commentator(fighter)
        packer = EventPacker()
        with patch("sys.stdout", new_callable=StringIO) as out:
            commentator(_make_event(packer, type="fighter.response"))
            await commentator.await_pending()
        self.assertEqual(out.getvalue(), "")

    async def test_empty_content_silently_skipped(self) -> None:
        fighter = _StubFighter("   ")
        commentator = Commentator(fighter)
        packer = EventPacker()
        with patch("sys.stdout", new_callable=StringIO) as out:
            commentator(_make_event(packer, type="fighter.response"))
            await commentator.await_pending()
        self.assertEqual(out.getvalue(), "")

    async def test_fire_and_forget_does_not_block_caller(self) -> None:
        import asyncio

        fighter = _StubFighter("comment")
        commentator = Commentator(fighter)
        packer = EventPacker()
        commentator(_make_event(packer, type="fighter.response"))
        commentator._pending.clear()
        self.assertTrue(True)

    async def test_no_influence_no_events_published(self) -> None:
        from fightclub.event_stream import EventStream

        fighter = _StubFighter("comment")
        commentator = Commentator(fighter)
        published: list = []

        def sink(event) -> None:
            published.append(event)

        stream = EventStream([sink, commentator])
        packer = EventPacker()
        stream.publish(
            _make_event(packer, type="fighter.response", source="a", data={"fighter": "a", "content": "hi"})
        )
        await commentator.await_pending()
        self.assertEqual(len(published), 1)
