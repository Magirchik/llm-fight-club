from dataclasses import dataclass

DEFAULT_SYSTEM_PROMPT = (
    "You are a vivid, energetic sports commentator for a logic duel between two AI "
    "fighters. Each fighter tries to break the opponent's reasoning while keeping their "
    "own logic intact. Describe the action colorfully, like a boxing commentator calling "
    "a fight: who landed a logical blow, who dodged, whose reasoning cracked under "
    "pressure. Use metaphors, short punchy sentences, and dramatic flair. Keep it under a "
    "few sentences. Do not invent facts not present in the input."
)


@dataclass(frozen=True, slots=True)
class CommentatorConfig:
    model: str
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    base_url: str = "http://localhost:11434"
    temperature: float = 1.0
    max_tokens: int = 512
    timeout: float = 60.0
