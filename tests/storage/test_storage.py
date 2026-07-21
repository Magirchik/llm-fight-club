import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from fightclub.core.event import Event
from fightclub.event_stream import EventPacker, EventStream
from fightclub.storage import Storage, StorageConfig, serialize_event


def _make_event(
    packer: EventPacker,
    *,
    source: str = "arena",
    type: str = "arena.started",
    data: dict | None = None,
    round_number: int = 0,
) -> Event:
    return packer.pack(
        experiment_id="exp1",
        round_number=round_number,
        source=source,
        type=type,
        data=data or {},
    )


class SerializeEventTest(unittest.TestCase):
    def test_serializes_all_fields(self) -> None:
        packer = EventPacker()
        event = _make_event(
            packer,
            source="a",
            type="fighter.response",
            data={"content": "hi"},
            round_number=2,
        )
        out = serialize_event(event)
        self.assertEqual(out["id"], 0)
        self.assertEqual(out["experiment_id"], "exp1")
        self.assertEqual(out["round_number"], 2)
        self.assertEqual(out["source"], "a")
        self.assertEqual(out["type"], "fighter.response")
        self.assertEqual(out["data"], {"content": "hi"})
        self.assertIsInstance(out["datetime"], str)
        datetime.fromisoformat(out["datetime"])

    def test_datetime_is_iso8601(self) -> None:
        event = Event(
            id=1,
            datetime=datetime(2026, 7, 19, 12, 30, 45, 123456),
            experiment_id="exp1",
            round_number=1,
            source="a",
            type="x",
            data={},
        )
        out = serialize_event(event)
        self.assertEqual(out["datetime"], "2026-07-19T12:30:45.123456")


class StorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.output_dir = Path(self._tmp.name) / "experiments"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _make(self, **overrides) -> Storage:
        config = StorageConfig(
            experiment_id="exp1", output_dir=str(self.output_dir), **overrides
        )
        return Storage(config)

    def test_creates_output_dir_and_file(self) -> None:
        storage = self._make()
        self.assertTrue(self.output_dir.exists())
        self.assertEqual(storage.path.name, "exp1.jsonl")

    def test_appends_one_line_per_event(self) -> None:
        storage = self._make()
        packer = EventPacker()
        storage(_make_event(packer, type="arena.started", data={"fighters": ["a", "b"]}))
        storage(_make_event(packer, source="a", type="fighter.response", data={"content": "hi"}, round_number=1))
        content = storage.path.read_text(encoding="utf-8")
        lines = content.strip().split("\n")
        self.assertEqual(len(lines), 2)
        first = json.loads(lines[0])
        self.assertEqual(first["type"], "arena.started")
        self.assertEqual(first["data"], {"fighters": ["a", "b"]})
        second = json.loads(lines[1])
        self.assertEqual(second["source"], "a")
        self.assertEqual(second["round_number"], 1)

    def test_preserves_cyrillic(self) -> None:
        storage = self._make()
        packer = EventPacker()
        storage(
            _make_event(
                packer,
                source="a",
                type="fighter.response",
                data={"content": "Привет, мир"},
                round_number=1,
            )
        )
        content = storage.path.read_text(encoding="utf-8")
        self.assertIn("Привет, мир", content)

    def test_custom_filename(self) -> None:
        storage = self._make(filename="custom.jsonl")
        self.assertEqual(storage.path.name, "custom.jsonl")

    def test_round_trip_all_events(self) -> None:
        storage = self._make()
        packer = EventPacker()
        events = [
            _make_event(packer, type="arena.started", data={"fighters": ["a", "b"]}),
            _make_event(packer, source="a", type="fighter.response", data={"content": "a1"}, round_number=1),
            _make_event(packer, source="b", type="fighter.response", data={"content": "b1"}, round_number=1),
            _make_event(packer, source="scorekeeper", type="scorekeeper.round_scored", data={"scores": {}}, round_number=1),
            _make_event(packer, source="referee", type="referee.decision", data={"action": "win"}, round_number=1),
        ]
        for e in events:
            storage(e)
        lines = storage.path.read_text(encoding="utf-8").strip().split("\n")
        self.assertEqual(len(lines), len(events))
        for original, line in zip(events, lines):
            restored = json.loads(line)
            self.assertEqual(restored["id"], original.id)
            self.assertEqual(restored["type"], original.type)
            self.assertEqual(restored["source"], original.source)
            self.assertEqual(restored["round_number"], original.round_number)
            self.assertEqual(restored["data"], original.data)
            self.assertEqual(restored["experiment_id"], original.experiment_id)

    def test_does_not_filter_events(self) -> None:
        storage = self._make()
        packer = EventPacker()
        types = [
            "arena.started",
            "fighter.message",
            "fighter.response",
            "fighter.error",
            "arena.round_finished",
            "scorekeeper.judge",
            "scorekeeper.round_scored",
            "referee.continue",
            "referee.stop",
            "referee.decision",
            "arena.finished",
        ]
        for i, t in enumerate(types):
            storage(_make_event(packer, type=t, round_number=i))
        lines = storage.path.read_text(encoding="utf-8").strip().split("\n")
        self.assertEqual(len(lines), len(types))
        restored_types = [json.loads(line)["type"] for line in lines]
        self.assertEqual(restored_types, types)


class StorageIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_storage_records_full_fight(self) -> None:
        from fightclub.arena import ArenaConfig, ArenaController
        from fightclub.fighters import Fighter, FighterConfig, FighterResponse
        from fightclub.scorekeeper import Scorekeeper, ScorekeeperConfig
        from fightclub.judges import Judge, JudgeContext, JudgeVerdict
        from fightclub.referee import Referee, RefereeConfig

        class _StubFighter(Fighter):
            def __init__(self, name: str, responses: list[str]) -> None:
                self._config = FighterConfig(
                    name=name, provider="stub", model="m", system_prompt="s"
                )
                self._responses = list(responses)

            @property
            def config(self) -> FighterConfig:
                return self._config

            async def generate(self, message: str) -> FighterResponse:
                import asyncio

                await asyncio.sleep(0)
                return FighterResponse(
                    content=self._responses.pop(0), model="m", usage={}, latency_ms=1
                )

        class _StubJudge(Judge):
            def __init__(self, name: str, score: float) -> None:
                self._name = name
                self._score = score

            @property
            def name(self) -> str:
                return self._name

            async def judge(self, context: JudgeContext) -> JudgeVerdict:
                return JudgeVerdict(score=self._score)

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        output_dir = Path(tmp.name) / "experiments"
        events: list[Event] = []
        components: list = []
        stream = EventStream(components)
        packer = EventPacker()
        a = _StubFighter("a", [f"a{i}" for i in range(1, 21)])
        b = _StubFighter("b", [f"b{i}" for i in range(1, 21)])
        judge = _StubJudge("consistency", 0.5)
        arena_config = ArenaConfig(
            experiment_id="exp_full", max_rounds=2, opening_message="opening"
        )
        keeper_config = ScorekeeperConfig(
            experiment_id="exp_full",
            system_prompts={"a": "s", "b": "s"},
            weights={"consistency": 1.0},
        )
        referee_config = RefereeConfig(
            experiment_id="exp_full", publish_continue=False
        )
        storage_config = StorageConfig(
            experiment_id="exp_full", output_dir=str(output_dir)
        )

        def record(event: Event) -> None:
            events.append(event)

        keeper = Scorekeeper(keeper_config, [judge], stream, packer)
        referee = Referee(referee_config, stream, packer)
        arena = ArenaController(arena_config, [a, b], stream, packer)
        storage = Storage(storage_config)
        components.extend([record, keeper, referee, arena, storage])
        await arena.run()
        await keeper.await_pending()
        self.assertTrue(storage.path.exists())
        lines = storage.path.read_text(encoding="utf-8").strip().split("\n")
        restored_types = [json.loads(line)["type"] for line in lines]
        self.assertIn("arena.started", restored_types)
        self.assertIn("fighter.response", restored_types)
        self.assertIn("scorekeeper.round_scored", restored_types)
        self.assertIn("arena.finished", restored_types)
        self.assertEqual(len(lines), len(events))
        file_ids = {json.loads(line)["id"] for line in lines}
        event_ids = {e.id for e in events}
        self.assertEqual(file_ids, event_ids)
        file_types = {json.loads(line)["type"] for line in lines}
        event_types = {e.type for e in events}
        self.assertEqual(file_types, event_types)
