import asyncio
from typing import Any

from fightclub.core.event import Event
from fightclub.event_stream import EventPacker, EventStream
from fightclub.judges import Judge, JudgeContext, JudgeVerdict

from .config import ScorekeeperConfig


class Scorekeeper:
    """Главный вычислительный модуль.

    Компонент Event Stream: накапливает ответы бойцов и после каждого раунда
    запускает Judges, агрегирует Logic Stability Score и публикует события.
    Не принимает решений и не хранит долгосрочной истории.
    """

    SOURCE = "scorekeeper"

    def __init__(
        self,
        config: ScorekeeperConfig,
        judges: list[Judge],
        event_stream: EventStream,
        event_packer: EventPacker,
    ) -> None:
        self._config = config
        self._judges = judges
        self._stream = event_stream
        self._packer = event_packer
        self._round_answers: dict[int, dict[str, str]] = {}
        self._pending: set[asyncio.Task] = set()

    def __call__(self, event: Event) -> None:
        if event.type == "fighter.response":
            self._round_answers.setdefault(event.round_number, {})[
                event.source
            ] = event.data["content"]
        elif event.type == "arena.round_finished":
            task = asyncio.create_task(self._score_round(event.round_number))
            self._pending.add(task)
            task.add_done_callback(self._pending.discard)

    async def await_pending(self) -> None:
        """Дождаться завершения всех запланированных оценок раундов."""
        if not self._pending:
            return
        await asyncio.gather(*self._pending, return_exceptions=True)

    async def _score_round(self, round_number: int) -> None:
        round_data = self._round_answers.get(round_number, {})
        fighters = list(round_data.keys())
        if len(fighters) != 2:
            return
        opponent = {fighters[0]: fighters[1], fighters[1]: fighters[0]}
        per_fighter: dict[str, dict[str, Any]] = {}
        for fighter in fighters:
            responses = self._collect(fighter, round_number)
            opponent_responses = self._collect(opponent[fighter], round_number)
            system_prompt = self._config.system_prompts.get(fighter, "")
            context = JudgeContext(
                fighter_name=fighter,
                system_prompt=system_prompt,
                responses=responses,
                opponent_responses=opponent_responses,
                round_number=round_number,
            )
            verdicts = await self._run_judges(context)
            lss = self._aggregate(verdicts)
            judge_results: dict[str, Any] = {}
            for judge, verdict in zip(self._judges, verdicts):
                if isinstance(verdict, JudgeVerdict):
                    judge_results[judge.name] = {
                        "score": verdict.score,
                        "details": verdict.details,
                    }
                    self._publish(
                        round_number,
                        "scorekeeper.judge",
                        {
                            "fighter": fighter,
                            "judge": judge.name,
                            "score": verdict.score,
                            "details": verdict.details,
                        },
                    )
                else:
                    judge_results[judge.name] = {
                        "error": str(verdict),
                    }
                    self._publish(
                        round_number,
                        "scorekeeper.judge",
                        {
                            "fighter": fighter,
                            "judge": judge.name,
                            "error": str(verdict),
                        },
                    )
            per_fighter[fighter] = {"judges": judge_results, "lss": lss}
        self._publish(
            round_number,
            "scorekeeper.round_scored",
            {"round_number": round_number, "scores": per_fighter},
        )

    async def _run_judges(self, context: JudgeContext) -> list[JudgeVerdict | BaseException]:
        return await asyncio.gather(
            *(judge.judge(context) for judge in self._judges),
            return_exceptions=True,
        )

    def _aggregate(self, verdicts: list[JudgeVerdict | BaseException]) -> float:
        total_weight = 0.0
        weighted = 0.0
        for judge, verdict in zip(self._judges, verdicts):
            if isinstance(verdict, JudgeVerdict):
                weight = self._config.weights.get(judge.name, 0.0)
                weighted += weight * verdict.score
                total_weight += weight
        if total_weight == 0:
            return 0.0
        return weighted / total_weight

    def _collect(self, fighter: str, up_to_round: int) -> list[str]:
        out: list[str] = []
        for rn in range(1, up_to_round + 1):
            answers = self._round_answers.get(rn, {})
            if fighter in answers:
                out.append(answers[fighter])
        return out

    def _publish(self, round_number: int, event_type: str, data: dict[str, Any]) -> None:
        event = self._packer.pack(
            experiment_id=self._config.experiment_id,
            round_number=round_number,
            source=self.SOURCE,
            type=event_type,
            data=data,
        )
        self._stream.publish(event)
