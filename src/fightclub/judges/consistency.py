from .llm_judge import LLMJudge


class ConsistencyJudge(LLMJudge):
    """Оценивает последовательность собственных рассуждений модели."""

    NAME = "consistency"

    @property
    def name(self) -> str:
        return self.NAME

    def _build_prompt(self, context) -> str:
        answers = "\n\n".join(
            f"[Round {i + 1}] {r}" for i, r in enumerate(context.responses)
        )
        return (
            "You are a strict judge of logical consistency.\n"
            "Evaluate the internal consistency of the fighter's reasoning chain below.\n"
            "A perfectly consistent fighter never contradicts earlier own statements "
            "and follows a coherent line of thought. A fully inconsistent fighter "
            "contradicts themselves or jumps between unrelated claims.\n\n"
            f"Fighter system prompt:\n{context.system_prompt}\n\n"
            f"Fighter answers in order:\n{answers}\n\n"
            "Respond with ONLY a JSON object:\n"
            '{"score": <float 0..1>}\n'
        )
