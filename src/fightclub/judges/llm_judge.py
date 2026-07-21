import json
import re

from fightclub.fighters import Fighter, FighterError

from .base import Judge, JudgeContext, JudgeVerdict


class LLMJudge(Judge):
    """Базовая реализация Judge через LLM (интерфейс Fighter).

    Конкретный Judge задаёт системный промпт оценщика и метод parse_verdict.
    Модель должна вернуть JSON со строковым полем «score» (0..1) и опциональными
    дополнительными полями.
    """

    def __init__(self, fighter: Fighter) -> None:
        self._fighter = fighter

    @property
    def name(self) -> str:
        raise NotImplementedError

    async def judge(self, context: JudgeContext) -> JudgeVerdict:
        prompt = self._build_prompt(context)
        try:
            response = await self._fighter.generate(prompt)
        except FighterError as exc:
            raise JudgeError(f"{self.name} failed: {exc}") from exc
        return self.parse_verdict(response.content)

    def _build_prompt(self, context: JudgeContext) -> str:
        raise NotImplementedError

    def parse_verdict(self, content: str) -> JudgeVerdict:
        payload = _extract_json(content)
        if payload is None:
            raise JudgeError(f"{self.name}: no JSON in response")
        try:
            score = float(payload["score"])
        except (KeyError, TypeError, ValueError) as exc:
            raise JudgeError(f"{self.name}: invalid score: {exc}") from exc
        if not 0.0 <= score <= 1.0:
            raise JudgeError(f"{self.name}: score out of [0,1]: {score}")
        details = {k: v for k, v in payload.items() if k != "score"}
        return JudgeVerdict(score=score, details=details)


class JudgeError(Exception):
    """Ошибка оценки Judge."""


def _extract_json(text: str) -> dict | None:
    candidates = _JSON_BLOCK_RE.findall(text)
    if not candidates:
        candidates = [text]
    for candidate in candidates:
        obj = _try_loads(candidate)
        if isinstance(obj, dict):
            return obj
    return None


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _try_loads(text: str) -> object | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
