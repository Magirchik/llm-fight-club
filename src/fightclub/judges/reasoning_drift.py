from .llm_judge import LLMJudge


class ReasoningDriftJudge(LLMJudge):
    """Определяет постепенную деградацию логической цепочки рассуждений."""

    NAME = "reasoning_drift"

    @property
    def name(self) -> str:
        return self.NAME

    def _build_prompt(self, context) -> str:
        answers = "\n\n".join(
            f"[Round {i + 1}] {r}" for i, r in enumerate(context.responses)
        )
        return (
            "You are a strict judge of reasoning drift.\n"
            "Measure the gradual degradation of the fighter's reasoning quality across "
            "rounds. A score of 1.0 means reasoning quality stays stable or improves; "
            "0.0 means severe drift toward incoherence.\n\n"
            f"Fighter system prompt:\n{context.system_prompt}\n\n"
            f"Fighter answers in order:\n{answers}\n\n"
            "Respond with ONLY a JSON object:\n"
            '{"score": <float 0..1, higher = less drift>}\n'
        )
