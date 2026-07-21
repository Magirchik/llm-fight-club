from typing import Any

from fightclub.core.event import Event
from fightclub.event_stream import EventPacker, EventStream

from .config import RefereeConfig


class Referee:
    """Единственный компонент, принимающий решения.

    Детерминирован: решения основаны на Logic Stability Score бойцов,
    без LLM. Подписывается на scorekeeper.round_scored и arena.finished.
    """

    SOURCE = "referee"

    def __init__(
        self,
        config: RefereeConfig,
        event_stream: EventStream,
        event_packer: EventPacker,
    ) -> None:
        self._config = config
        self._stream = event_stream
        self._packer = event_packer
        self._last_lss: dict[str, float] = {}
        self._last_lss_round: int | None = None
        self._decided = False
        self._fight_finished = False
        self._finish_reason: str | None = None
        self._finish_round: int | None = None

    def __call__(self, event: Event) -> None:
        if event.type == "scorekeeper.round_scored":
            self._on_round_scored(event)
        elif event.type == "arena.finished":
            self._on_arena_finished(event)

    def _on_round_scored(self, event: Event) -> None:
        if self._decided:
            return
        scores = event.data.get("scores", {})
        lss = {fighter: data["lss"] for fighter, data in scores.items()}
        self._last_lss = lss
        self._last_lss_round = event.round_number
        round_number = event.round_number
        if round_number >= self._config.min_rounds and len(lss) == 2:
            a, b = list(lss.keys())
            a_below = lss[a] < self._config.lss_critical_threshold
            b_below = lss[b] < self._config.lss_critical_threshold
            if a_below and b_below:
                self._stop_and_decide(
                    action="double_knockout",
                    winner=None,
                    reason="lss_below_threshold_both",
                    round_number=round_number,
                    lss=lss,
                )
                return
            if a_below:
                self._stop_and_decide(
                    action="technical_knockout",
                    winner=b,
                    reason="lss_below_threshold",
                    round_number=round_number,
                    lss=lss,
                )
                return
            if b_below:
                self._stop_and_decide(
                    action="technical_knockout",
                    winner=a,
                    reason="lss_below_threshold",
                    round_number=round_number,
                    lss=lss,
                )
                return
        if self._fight_finished and self._finish_reason == "completed":
            if self._finish_round is not None and round_number >= self._finish_round:
                self._try_final_decision(round_number)
                return
        self._publish_continue(round_number, lss)

    def _on_arena_finished(self, event: Event) -> None:
        if self._decided:
            return
        self._fight_finished = True
        self._finish_reason = event.data.get("reason")
        self._finish_round = event.round_number
        if self._finish_reason == "completed":
            if (
                self._last_lss_round is not None
                and self._last_lss_round >= self._finish_round
            ):
                self._try_final_decision(self._finish_round)

    def _try_final_decision(self, round_number: int) -> None:
        if self._decided:
            return
        if len(self._last_lss) != 2:
            return
        fighters = list(self._last_lss.keys())
        a, b = fighters
        lss = self._last_lss
        diff = lss[a] - lss[b]
        if abs(diff) < self._config.lss_draw_threshold:
            self._publish_decision(
                action="draw",
                winner=None,
                reason="lss_within_draw_threshold",
                round_number=round_number,
                lss=lss,
            )
        elif diff > 0:
            self._publish_decision(
                action="win",
                winner=a,
                reason="higher_lss",
                round_number=round_number,
                lss=lss,
            )
        else:
            self._publish_decision(
                action="win",
                winner=b,
                reason="higher_lss",
                round_number=round_number,
                lss=lss,
            )

    def _stop_and_decide(
        self,
        *,
        action: str,
        winner: str | None,
        reason: str,
        round_number: int,
        lss: dict[str, float],
    ) -> None:
        self._decided = True
        self._publish(round_number, "referee.stop", {})
        self._publish_decision(
            action=action, winner=winner, reason=reason, round_number=round_number, lss=lss
        )

    def _publish_continue(self, round_number: int, lss: dict[str, float]) -> None:
        if not self._config.publish_continue:
            return
        explain = self._explain_continue(round_number, lss)
        self._publish(
            round_number,
            "referee.continue",
            {"round_number": round_number, "lss": dict(lss), "explain": explain},
        )

    def _publish_decision(
        self,
        *,
        action: str,
        winner: str | None,
        reason: str,
        round_number: int,
        lss: dict[str, float],
    ) -> None:
        self._decided = True
        explain = self._explain_decision(action, winner, reason, round_number, lss)
        self._publish(
            round_number,
            "referee.decision",
            {
                "action": action,
                "winner": winner,
                "reason": reason,
                "explain": explain,
                "round_number": round_number,
                "lss": dict(lss),
            },
        )

    def _explain_continue(self, round_number: int, lss: dict[str, float]) -> str:
        parts = [f"{name}={value:.3f}" for name, value in lss.items()]
        return f"Round {round_number}: continue. LSS: {', '.join(parts)}."

    def _explain_decision(
        self,
        action: str,
        winner: str | None,
        reason: str,
        round_number: int,
        lss: dict[str, float],
    ) -> str:
        parts = [f"{name}={value:.3f}" for name, value in lss.items()]
        lss_str = ", ".join(parts)
        threshold = self._config.lss_critical_threshold
        draw_thr = self._config.lss_draw_threshold
        if action == "technical_knockout":
            loser = next(n for n in lss if n != winner)
            return (
                f"Round {round_number}: {winner} wins by technical knockout. "
                f"{loser} LSS {lss[loser]:.3f} < critical threshold {threshold:.3f}. "
                f"Full LSS: {lss_str}."
            )
        if action == "double_knockout":
            return (
                f"Round {round_number}: draw (double knockout). "
                f"Both fighters LSS below critical threshold {threshold:.3f}. "
                f"Full LSS: {lss_str}."
            )
        if action == "draw":
            return (
                f"Round {round_number}: draw. |ΔLSS| < draw threshold {draw_thr:.3f}. "
                f"Full LSS: {lss_str}."
            )
        if action == "win":
            loser = next(n for n in lss if n != winner)
            return (
                f"Round {round_number}: {winner} wins by higher LSS. "
                f"{winner}={lss[winner]:.3f} vs {loser}={lss[loser]:.3f}. "
                f"Full LSS: {lss_str}."
            )
        return f"Round {round_number}: {action}. Full LSS: {lss_str}."

    def _publish(self, round_number: int, event_type: str, data: dict[str, Any]) -> None:
        event = self._packer.pack(
            experiment_id=self._config.experiment_id,
            round_number=round_number,
            source=self.SOURCE,
            type=event_type,
            data=data,
        )
        self._stream.publish(event)
