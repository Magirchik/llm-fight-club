from .llm_judge import LLMJudge


class MemoryJudge(LLMJudge):
    """Проверяет сохранение собственных определений, выводов и аргументов."""

    NAME = "memory"

    @property
    def name(self) -> str:
        return self.NAME

    def _build_prompt(self, context) -> str:
        answers = "\n\n".join(
            f"[Round {i + 1}] {r}" for i, r in enumerate(context.responses)
        )
        return (
            "You are a strict judge of memory retention.\n"
            "Check whether the fighter preserves its own earlier definitions, "
            "conclusions and arguments across rounds. A score of 1.0 means the fighter "
            "consistently reuses and builds on prior claims; 0.0 means the fighter "
            "forgets or reverses earlier commitments.\n\n"
            f"Fighter system prompt:\n{context.system_prompt}\n\n"
            f"Fighter answers in order:\n{answers}\n\n"
            "Respond with ONLY a JSON object:\n"
            '{"score": <float 0..1>}\n'
        )
