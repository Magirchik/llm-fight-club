import unittest
import asyncio

from fightclub.core.event import Event
from fightclub.event_stream import EventPacker, EventStream
from fightclub.referee import Referee, RefereeConfig


def _record(events: list[Event]):
    def component(event: Event) -> None:
        events.append(event)

    return component


class RefereeTest(unittest.TestCase):
    def _make(
        self, **overrides
    ) -> tuple[Referee, EventPacker, EventStream, list[Event]]:
        events: list[Event] = []
        stream = EventStream([_record(events)])
        packer = EventPacker()
        config = RefereeConfig(experiment_id="exp1", **overrides)
        referee = Referee(config, stream, packer)
        return referee, packer, stream, events

    def _round_scored(
        self, packer: EventPacker, round_number: int, lss: dict[str, float]
    ) -> Event:
        scores = {
            fighter: {"lss": value, "judges": {}} for fighter, value in lss.items()
        }
        return packer.pack(
            experiment_id="exp1",
            round_number=round_number,
            source="scorekeeper",
            type="scorekeeper.round_scored",
            data={"round_number": round_number, "scores": scores},
        )

    def _arena_finished(self, packer: EventPacker, round_number: int, reason: str) -> Event:
        return packer.pack(
            experiment_id="exp1",
            round_number=round_number,
            source="arena",
            type="arena.finished",
            data={"reason": reason},
        )

    def test_continue_when_both_above_threshold(self) -> None:
        referee, packer, _, events = self._make()
        referee(self._round_scored(packer, 1, {"a": 0.8, "b": 0.7}))
        types = [e.type for e in events]
        self.assertEqual(types, ["referee.continue"])
        self.assertEqual(events[0].source, "referee")
        self.assertIn("explain", events[0].data)
        self.assertEqual(events[0].data["lss"], {"a": 0.8, "b": 0.7})

    def test_technical_knockout_when_one_below_threshold(self) -> None:
        referee, packer, _, events = self._make(lss_critical_threshold=0.3)
        referee(self._round_scored(packer, 1, {"a": 0.1, "b": 0.8}))
        types = [e.type for e in events]
        self.assertEqual(types, ["referee.stop", "referee.decision"])
        decision = events[-1]
        self.assertEqual(decision.data["action"], "technical_knockout")
        self.assertEqual(decision.data["winner"], "b")
        self.assertEqual(decision.data["reason"], "lss_below_threshold")
        self.assertIn("a LSS 0.100", decision.data["explain"])

    def test_double_knockout_when_both_below_threshold(self) -> None:
        referee, packer, _, events = self._make(lss_critical_threshold=0.3)
        referee(self._round_scored(packer, 1, {"a": 0.2, "b": 0.1}))
        decision = events[-1]
        self.assertEqual(decision.data["action"], "double_knockout")
        self.assertIsNone(decision.data["winner"])
        self.assertEqual(events[0].type, "referee.stop")

    def test_min_rounds_delays_threshold(self) -> None:
        referee, packer, _, events = self._make(
            lss_critical_threshold=0.3, min_rounds=3
        )
        referee(self._round_scored(packer, 1, {"a": 0.1, "b": 0.8}))
        types = [e.type for e in events]
        self.assertEqual(types, ["referee.continue"])
        referee(self._round_scored(packer, 3, {"a": 0.1, "b": 0.8}))
        types = [e.type for e in events]
        self.assertEqual(types[-1], "referee.decision")
        self.assertEqual(events[-1].data["action"], "technical_knockout")

    def test_publish_continue_disabled(self) -> None:
        referee, packer, _, events = self._make(publish_continue=False)
        referee(self._round_scored(packer, 1, {"a": 0.8, "b": 0.7}))
        self.assertEqual(events, [])

    def test_final_win_by_higher_lss(self) -> None:
        referee, packer, _, events = self._make(lss_draw_threshold=0.05)
        referee(self._round_scored(packer, 1, {"a": 0.6, "b": 0.4}))
        referee(self._arena_finished(packer, 1, "completed"))
        types = [e.type for e in events]
        self.assertEqual(types, ["referee.continue", "referee.decision"])
        decision = events[-1]
        self.assertEqual(decision.data["action"], "win")
        self.assertEqual(decision.data["winner"], "a")
        self.assertEqual(decision.data["reason"], "higher_lss")
        self.assertNotIn("referee.stop", types)

    def test_final_draw_when_lss_close(self) -> None:
        referee, packer, _, events = self._make(lss_draw_threshold=0.05)
        referee(self._round_scored(packer, 1, {"a": 0.61, "b": 0.60}))
        referee(self._arena_finished(packer, 1, "completed"))
        decision = events[-1]
        self.assertEqual(decision.data["action"], "draw")
        self.assertEqual(decision.data["reason"], "lss_within_draw_threshold")
        self.assertIsNone(decision.data["winner"])

    def test_no_final_decision_after_stop(self) -> None:
        referee, packer, _, events = self._make(lss_critical_threshold=0.3)
        referee(self._round_scored(packer, 1, {"a": 0.1, "b": 0.8}))
        n_after_stop = len(events)
        referee(self._arena_finished(packer, 1, "stopped"))
        self.assertEqual(len(events), n_after_stop)

    def test_no_final_decision_on_error_reason(self) -> None:
        referee, packer, _, events = self._make()
        referee(self._round_scored(packer, 1, {"a": 0.6, "b": 0.5}))
        referee(self._arena_finished(packer, 1, "error"))
        types = [e.type for e in events]
        self.assertNotIn("referee.decision", types)

    def test_no_decision_without_scores(self) -> None:
        referee, packer, _, events = self._make()
        referee(self._arena_finished(packer, 0, "completed"))
        self.assertEqual(events, [])

    def test_ignores_round_scored_after_decision(self) -> None:
        referee, packer, _, events = self._make(lss_critical_threshold=0.3)
        referee(self._round_scored(packer, 1, {"a": 0.1, "b": 0.8}))
        n = len(events)
        referee(self._round_scored(packer, 2, {"a": 0.05, "b": 0.05}))
        self.assertEqual(len(events), n)


class RefereeArenaIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_referee_stops_arena_via_event_stream(self) -> None:
        from fightclub.arena import ArenaConfig, ArenaController
        from fightclub.fighters import Fighter, FighterConfig, FighterResponse
        from fightclub.scorekeeper import Scorekeeper, ScorekeeperConfig
        from fightclub.judges import Judge, JudgeContext, JudgeVerdict

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
                await asyncio.sleep(0)
                return FighterResponse(
                    content=self._responses.pop(0), model="m", usage={}, latency_ms=1
                )

        class _StubJudge(Judge):
            def __init__(self, name: str, scores: dict[str, float]) -> None:
                self._name = name
                self._scores = scores

            @property
            def name(self) -> str:
                return self._name

            async def judge(self, context: JudgeContext) -> JudgeVerdict:
                return JudgeVerdict(score=self._scores[context.fighter_name])

        events: list[Event] = []
        components: list = [_record(events)]
        stream = EventStream(components)
        packer = EventPacker()
        a = _StubFighter("a", [f"a{i}" for i in range(1, 21)])
        b = _StubFighter("b", [f"b{i}" for i in range(1, 21)])
        judge = _StubJudge("consistency", {"a": 0.1, "b": 0.9})
        arena_config = ArenaConfig(
            experiment_id="exp1", max_rounds=20, opening_message="opening"
        )
        keeper_config = ScorekeeperConfig(
            experiment_id="exp1",
            system_prompts={"a": "s", "b": "s"},
            weights={"consistency": 1.0},
        )
        referee_config = RefereeConfig(
            experiment_id="exp1", lss_critical_threshold=0.3, publish_continue=False
        )
        keeper = Scorekeeper(keeper_config, [judge], stream, packer)
        referee = Referee(referee_config, stream, packer)
        arena = ArenaController(arena_config, [a, b], stream, packer)
        components.extend([keeper, referee, arena])
        reason = await arena.run()
        await keeper.await_pending()
        self.assertEqual(reason, "stopped")
        decisions = [e for e in events if e.type == "referee.decision"]
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].data["action"], "technical_knockout")
        self.assertEqual(decisions[0].data["winner"], "b")
