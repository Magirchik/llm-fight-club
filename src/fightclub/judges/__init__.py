from .base import Judge, JudgeContext, JudgeVerdict
from .consistency import ConsistencyJudge
from .contradiction import ContradictionJudge
from .llm_judge import JudgeError, LLMJudge
from .memory import MemoryJudge
from .reasoning_drift import ReasoningDriftJudge
from .resistance import ResistanceJudge

DEFAULT_WEIGHTS: dict[str, float] = {
    ConsistencyJudge.NAME: 35.0,
    ContradictionJudge.NAME: 30.0,
    ReasoningDriftJudge.NAME: 20.0,
    ResistanceJudge.NAME: 10.0,
    MemoryJudge.NAME: 5.0,
}

__all__ = [
    "Judge",
    "JudgeContext",
    "JudgeVerdict",
    "JudgeError",
    "LLMJudge",
    "ConsistencyJudge",
    "ContradictionJudge",
    "ReasoningDriftJudge",
    "ResistanceJudge",
    "MemoryJudge",
    "DEFAULT_WEIGHTS",
]
