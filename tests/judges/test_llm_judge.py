import unittest

from fightclub.fighters import Fighter, FighterConfig, FighterResponse
from fightclub.judges import (
    ConsistencyJudge,
    ContradictionJudge,
    JudgeContext,
    JudgeError,
    LLMJudge,
    MemoryJudge,
    ReasoningDriftJudge,
    ResistanceJudge,
)


def _fighter(responses: list[str]) -> Fighter:
    class _Stub(Fighter):
        def __init__(self) -> None:
            self._config = FighterConfig(
                name="judge_llm", provider="stub", model="m", system_prompt="s"
            )
            self._responses = list(responses)

        @property
        def config(self) -> FighterConfig:
            return self._config

        async def generate(self, message: str) -> FighterResponse:
            return FighterResponse(
                content=self._responses.pop(0),
                model="m",
                usage={},
                latency_ms=1,
            )

    return _Stub()


def _ctx() -> JudgeContext:
    return JudgeContext(
        fighter_name="a",
        system_prompt="be logical",
        responses=["first claim", "second claim"],
        opponent_responses=["opponent presses here", "opponent presses again"],
        round_number=2,
    )


class LLMJudgeParsingTest(unittest.IsolatedAsyncioTestCase):
    async def test_consistency_parses_score(self) -> None:
        judge = ConsistencyJudge(_fighter(['{"score": 0.8}']))
        verdict = await judge.judge(_ctx())
        self.assertEqual(verdict.score, 0.8)
        self.assertEqual(verdict.details, {})
        self.assertEqual(judge.name, "consistency")

    async def test_contradiction_parses_details(self) -> None:
        judge = ContradictionJudge(
            _fighter(
                ['{"score": 0.5, "contradiction_count": 2, "contradiction_severity": 0.7}']
            )
        )
        verdict = await judge.judge(_ctx())
        self.assertEqual(verdict.score, 0.5)
        self.assertEqual(verdict.details["contradiction_count"], 2)
        self.assertEqual(verdict.details["contradiction_severity"], 0.7)
        self.assertEqual(judge.name, "contradiction")

    async def test_json_in_code_block(self) -> None:
        judge = ReasoningDriftJudge(_fighter(['```json\n{"score": 0.3}\n```']))
        verdict = await judge.judge(_ctx())
        self.assertEqual(verdict.score, 0.3)
        self.assertEqual(judge.name, "reasoning_drift")

    async def test_json_embedded_in_text(self) -> None:
        judge = MemoryJudge(_fighter(['Here is my verdict: {"score": 0.9} done.']))
        verdict = await judge.judge(_ctx())
        self.assertEqual(verdict.score, 0.9)
        self.assertEqual(judge.name, "memory")

    async def test_resistance_prompt_includes_opponent(self) -> None:
        captured: list[str] = []

        class _Capture(ConsistencyJudge):
            async def judge(self, context: JudgeContext):
                captured.append(self._build_prompt(context))
                from fightclub.judges import JudgeVerdict

                return JudgeVerdict(score=0.5)

        ResistanceJudge  # noqa: F841
        judge = ResistanceJudge(_fighter(['{"score": 0.5}']))
        prompt = judge._build_prompt(_ctx())
        self.assertIn("opponent presses here", prompt)
        self.assertIn("be logical", prompt)
        self.assertEqual(judge.name, "resistance")

    async def test_invalid_json_raises(self) -> None:
        judge = ConsistencyJudge(_fighter(["no json here"]))
        with self.assertRaises(JudgeError):
            await judge.judge(_ctx())

    async def test_score_out_of_range_raises(self) -> None:
        judge = ConsistencyJudge(_fighter(['{"score": 1.5}']))
        with self.assertRaises(JudgeError):
            await judge.judge(_ctx())

    async def test_fighter_error_wrapped_as_judge_error(self) -> None:
        from fightclub.fighters import FighterError

        class _ErrFighter(Fighter):
            def __init__(self) -> None:
                self._config = FighterConfig(
                    name="judge_llm", provider="stub", model="m", system_prompt="s"
                )

            @property
            def config(self) -> FighterConfig:
                return self._config

            async def generate(self, message: str) -> FighterResponse:
                raise FighterError("llm down")

        judge = ConsistencyJudge(_ErrFighter())
        with self.assertRaises(JudgeError):
            await judge.judge(_ctx())
