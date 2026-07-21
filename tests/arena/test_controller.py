import unittest

from fightclub.arena import ArenaConfig, ArenaController
from fightclub.core.event import Event
from fightclub.event_stream import EventPacker, EventStream
from fightclub.fighters import Fighter, FighterConfig, FighterError, FighterResponse


def _cfg(name: str) -> FighterConfig:
    return FighterConfig(
        name=name,
        provider="ollama",
        model="m",
        system_prompt="s",
    )


class _FakeFighter(Fighter):
    def __init__(self, config: FighterConfig, responses: list[str]) -> None:
        self._config = config
        self._responses = list(responses)
        self.received: list[str] = []

    @property
    def config(self) -> FighterConfig:
        return self._config

    async def generate(self, message: str) -> FighterResponse:
        self.received.append(message)
        return FighterResponse(
            content=self._responses.pop(0),
            model=self._config.model,
            usage={"eval_count": 1},
            latency_ms=10,
        )


class _ErrorFighter(Fighter):
    def __init__(self, config: FighterConfig) -> None:
        self._config = config

    @property
    def config(self) -> FighterConfig:
        return self._config

    async def generate(self, message: str) -> FighterResponse:
        raise FighterError("boom")


def _record(events: list[Event]):
    def component(event: Event) -> None:
        events.append(event)

    return component


class _StopReferee:
    SOURCE = "referee"

    def __init__(self, stream: EventStream, packer: EventPacker, stop_after: int) -> None:
        self._stream = stream
        self._packer = packer
        self._stop_after = stop_after
        self._rounds = 0

    def __call__(self, event: Event) -> None:
        if event.type == "arena.round_finished":
            self._rounds += 1
            if self._rounds >= self._stop_after:
                self._stream.publish(
                    self._packer.pack(
                        experiment_id=event.experiment_id,
                        round_number=event.round_number,
                        source=self.SOURCE,
                        type="referee.stop",
                        data={"reason": "threshold reached"},
                    )
                )


class ArenaControllerTest(unittest.IsolatedAsyncioTestCase):
    def _make(
        self,
        fighters: list[Fighter],
        *,
        max_rounds: int = 3,
        opening: str = "opening",
        subscribe_arena: bool = False,
        extra_components: list | None = None,
    ) -> tuple[ArenaController, list[Event]]:
        events: list[Event] = []
        components: list = [_record(events)]
        if extra_components:
            components.extend(extra_components)
        stream = EventStream(components)
        packer = EventPacker()
        config = ArenaConfig(
            experiment_id="exp1",
            max_rounds=max_rounds,
            opening_message=opening,
        )
        arena = ArenaController(config, fighters, stream, packer)
        if subscribe_arena:
            components.append(arena)
        return arena, events

    async def test_run_completes_all_rounds(self) -> None:
        a = _FakeFighter(_cfg("a"), ["a1", "a2", "a3"])
        b = _FakeFighter(_cfg("b"), ["b1", "b2", "b3"])
        arena, events = self._make([a, b], max_rounds=3)
        reason = await arena.run()
        self.assertEqual(reason, "completed")
        types = [e.type for e in events]
        self.assertEqual(types[0], "arena.started")
        self.assertEqual(types[-1], "arena.finished")
        self.assertEqual(types.count("fighter.message"), 6)
        self.assertEqual(types.count("fighter.response"), 6)
        self.assertEqual(types.count("arena.round_finished"), 3)
        self.assertEqual(events[-1].data["reason"], "completed")

    async def test_message_alternation(self) -> None:
        a = _FakeFighter(_cfg("a"), ["a1", "a2", "a3"])
        b = _FakeFighter(_cfg("b"), ["b1", "b2", "b3"])
        arena, _ = self._make([a, b], max_rounds=3)
        await arena.run()
        self.assertEqual(a.received, ["opening", "b1", "b2"])
        self.assertEqual(b.received, ["a1", "a2", "a3"])

    async def test_event_sources_and_round_numbers(self) -> None:
        a = _FakeFighter(_cfg("a"), ["a1"])
        b = _FakeFighter(_cfg("b"), ["b1"])
        arena, events = self._make([a, b], max_rounds=1)
        await arena.run()
        for e in events:
            if e.type.startswith("fighter."):
                self.assertIn(e.source, ("a", "b"))
                self.assertEqual(e.round_number, 1)
            elif e.type.startswith("arena."):
                self.assertEqual(e.source, "arena")
        self.assertEqual(events[0].round_number, 0)
        self.assertEqual(events[0].experiment_id, "exp1")
        self.assertEqual(events[0].data["fighters"], ["a", "b"])

    async def test_stop_on_referee_stop(self) -> None:
        a = _FakeFighter(_cfg("a"), [f"a{i}" for i in range(1, 11)])
        b = _FakeFighter(_cfg("b"), [f"b{i}" for i in range(1, 11)])
        events: list[Event] = []
        packer = EventPacker()
        components: list = [_record(events)]
        stream = EventStream(components)
        config = ArenaConfig(experiment_id="exp1", max_rounds=10, opening_message="opening")
        arena = ArenaController(config, [a, b], stream, packer)
        stop_ref = _StopReferee(stream, packer, stop_after=1)
        components.append(stop_ref)
        components.append(arena)
        reason = await arena.run()
        self.assertEqual(reason, "stopped")
        types = [e.type for e in events]
        self.assertEqual(types.count("arena.round_finished"), 1)
        self.assertEqual(types[-1], "arena.finished")
        self.assertEqual(events[-1].data["reason"], "stopped")

    async def test_error_ends_fight(self) -> None:
        a = _ErrorFighter(_cfg("a"))
        b = _FakeFighter(_cfg("b"), ["b1", "b2"])
        arena, events = self._make([a, b], max_rounds=3)
        reason = await arena.run()
        self.assertEqual(reason, "error")
        types = [e.type for e in events]
        self.assertIn("fighter.error", types)
        self.assertEqual(types[-1], "arena.finished")
        self.assertNotIn("arena.round_finished", types)
        self.assertEqual(events[-1].data["reason"], "error")

    async def test_zero_rounds(self) -> None:
        a = _FakeFighter(_cfg("a"), [])
        b = _FakeFighter(_cfg("b"), [])
        arena, events = self._make([a, b], max_rounds=0)
        reason = await arena.run()
        self.assertEqual(reason, "completed")
        types = [e.type for e in events]
        self.assertEqual(types, ["arena.started", "arena.finished"])

    def test_requires_two_fighters(self) -> None:
        a = _FakeFighter(_cfg("a"), ["a1"])
        with self.assertRaises(ValueError):
            self._make([a], max_rounds=1)

    def test_requires_unique_names(self) -> None:
        a = _FakeFighter(_cfg("same"), ["a1"])
        b = _FakeFighter(_cfg("same"), ["b1"])
        with self.assertRaises(ValueError):
            self._make([a, b], max_rounds=1)
