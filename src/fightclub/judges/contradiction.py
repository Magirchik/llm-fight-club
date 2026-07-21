from .llm_judge import LLMJudge


class ContradictionJudge(LLMJudge):
    """Находит внутренние логические противоречия."""

    NAME = "contradiction"

    @property
    def name(self) -> str:
        return self.NAME

    def _build_prompt(self, context) -> str:
        answers = "\n\n".join(
            f"[Round {i + 1}] {r}" for i, r in enumerate(context.responses)
        )
        return (
            "You are a strict judge of logical contradictions.\n"
            "Find internal logical contradictions in the fighter's answers below.\n"
            "A contradiction is a pair of statements that cannot both be true.\n\n"
            f"Fighter system prompt:\n{context.system_prompt}\n\n"
            f"Fighter answers in order:\n{answers}\n\n"
            "Respond with ONLY a JSON object:\n"
            '{"score": <float 0..1, higher = fewer contradictions>, '
            '"contradiction_count": <int>, '
            '"contradiction_severity": <float 0..1>}\n'
        )
