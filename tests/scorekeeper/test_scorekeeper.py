import unittest

from fightclub.core.event import Event
from fightclub.event_stream import EventPacker, EventStream
from fightclub.judges import Judge, JudgeContext, JudgeVerdict
from fightclub.scorekeeper import Scorekeeper, ScorekeeperConfig


class _StubJudge(Judge):
    def __init__(self, name: str, score: float, *, record: list | None = None) -> None:
        self._name = name
        self._score = score
        self._record = record

    @property
    def name(self) -> str:
        return self._name

    async def judge(self, context: JudgeContext) -> JudgeVerdict:
        if self._record is not None:
            self._record.append(
                (
                    self._name,
                    context.fighter_name,
                    list(context.responses),
                    list(context.opponent_responses),
                    context.system_prompt,
                    context.round_number,
                )
            )
        return JudgeVerdict(score=self._score, details={"raw": self._score})


class _FailJudge(Judge):
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def judge(self, context: JudgeContext) -> JudgeVerdict:
        raise RuntimeError("judge crashed")


def _record(events: list[Event]):
    def component(event: Event) -> None:
        events.append(event)

    return component


class ScorekeeperTest(unittest.IsolatedAsyncioTestCase):
    def _make(
        self,
        judges: list[Judge],
        *,
        weights: dict[str, float] | None = None,
        prompts: dict[str, str] | None = None,
    ) -> tuple[Scorekeeper, EventPacker, EventStream, list[Event]]:
        events: list[Event] = []
        stream = EventStream([_record(events)])
        packer = EventPacker()
        config = ScorekeeperConfig(
            experiment_id="exp1",
            system_prompts=prompts or {"a": "be_a", "b": "be_b"},
            weights=weights or {"consistency": 35.0, "contradiction": 30.0},
        )
        keeper = Scorekeeper(config, judges, stream, packer)
        return keeper, packer, stream, events

    def _fighter_response(
        self, packer: EventPacker, fighter: str, content: str, round_number: int
    ) -> Event:
        return packer.pack(
            experiment_id="exp1",
            round_number=round_number,
            source=fighter,
            type="fighter.response",
            data={"fighter": fighter, "content": content},
        )

    def _round_finished(self, packer: EventPacker, round_number: int) -> Event:
        return packer.pack(
            experiment_id="exp1",
            round_number=round_number,
            source="arena",
            type="arena.round_finished",
            data={"round_number": round_number},
        )

    async def test_publishes_judge_and_round_scored(self) -> None:
        judges = [_StubJudge("consistency", 0.8), _StubJudge("contradiction", 0.4)]
        keeper, packer, _, events = self._make(judges)
        keeper(self._fighter_response(packer, "a", "a1", 1))
        keeper(self._fighter_response(packer, "b", "b1", 1))
        keeper(self._round_finished(packer, 1))
        await keeper.await_pending()
        types = [e.type for e in events]
        self.assertEqual(types.count("scorekeeper.judge"), 4)
        self.assertEqual(types.count("scorekeeper.round_scored"), 1)
        self.assertTrue(all(e.source == "scorekeeper" for e in events))

    async def test_lss_aggregation_weighted_normalized(self) -> None:
        judges = [_StubJudge("consistency", 1.0), _StubJudge("contradiction", 0.0)]
        keeper, packer, _, events = self._make(
            judges, weights={"consistency": 35.0, "contradiction": 30.0}
        )
        keeper(self._fighter_response(packer, "a", "a1", 1))
        keeper(self._fighter_response(packer, "b", "b1", 1))
        keeper(self._round_finished(packer, 1))
        await keeper.await_pending()
        scored = next(e for e in events if e.type == "scorekeeper.round_scored")
        lss_a = scored.data["scores"]["a"]["lss"]
        self.assertAlmostEqual(lss_a, 35.0 / 65.0)
        lss_b = scored.data["scores"]["b"]["lss"]
        self.assertAlmostEqual(lss_b, 35.0 / 65.0)

    async def test_context_accumulates_responses_across_rounds(self) -> None:
        record: list = []
        judges = [_StubJudge("consistency", 0.5, record=record)]
        keeper, packer, _, _ = self._make(judges)
        keeper(self._fighter_response(packer, "a", "a1", 1))
        keeper(self._fighter_response(packer, "b", "b1", 1))
        keeper(self._round_finished(packer, 1))
        keeper(self._fighter_response(packer, "a", "a2", 2))
        keeper(self._fighter_response(packer, "b", "b2", 2))
        keeper(self._round_finished(packer, 2))
        await keeper.await_pending()
        consistency_a = [r for r in record if r[0] == "consistency" and r[1] == "a"]
        self.assertEqual(len(consistency_a), 2)
        self.assertEqual(consistency_a[0][2], ["a1"])
        self.assertEqual(consistency_a[1][2], ["a1", "a2"])
        self.assertEqual(consistency_a[1][3], ["b1", "b2"])
        self.assertEqual(consistency_a[1][4], "be_a")
        self.assertEqual(consistency_a[1][5], 2)

    async def test_failed_judge_does_not_break_others(self) -> None:
        judges = [
            _StubJudge("consistency", 0.6),
            _FailJudge("contradiction"),
        ]
        keeper, packer, _, events = self._make(
            judges, weights={"consistency": 35.0, "contradiction": 30.0}
        )
        keeper(self._fighter_response(packer, "a", "a1", 1))
        keeper(self._fighter_response(packer, "b", "b1", 1))
        keeper(self._round_finished(packer, 1))
        await keeper.await_pending()
        judge_events = [e for e in events if e.type == "scorekeeper.judge"]
        failed = [e for e in judge_events if "error" in e.data]
        self.assertEqual(len(failed), 2)
        ok = [e for e in judge_events if "score" in e.data]
        self.assertEqual(len(ok), 2)
        scored = next(e for e in events if e.type == "scorekeeper.round_scored")
        lss_a = scored.data["scores"]["a"]["lss"]
        self.assertAlmostEqual(lss_a, 0.6)

    async def test_round_finished_without_responses_is_noop(self) -> None:
        judges = [_StubJudge("consistency", 0.5)]
        keeper, packer, _, events = self._make(judges)
        keeper(self._round_finished(packer, 1))
        await keeper.await_pending()
        self.assertEqual(events, [])

    async def test_resistance_judge_gets_opponent_responses(self) -> None:
        record: list = []
        judges = [_StubJudge("resistance", 0.7, record=record)]
        keeper, packer, _, _ = self._make(judges, weights={"resistance": 10.0})
        keeper(self._fighter_response(packer, "a", "a1", 1))
        keeper(self._fighter_response(packer, "b", "b1", 1))
        keeper(self._round_finished(packer, 1))
        await keeper.await_pending()
        resistance_b = [r for r in record if r[1] == "b"]
        self.assertEqual(resistance_b[0][3], ["a1"])
