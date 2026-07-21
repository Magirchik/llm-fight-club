import asyncio

from fightclub.core.event import Event
from fightclub.fighters import Fighter, FighterError


class Commentator:
    """Вспомогательный компонент Event Stream, пишущий красочное описание боя в stdout.

    Не влияет на систему: не публикует событий, не требуется для воспроизводимости.
    LLM-вызов асинхронный, fire-and-forget — не замедляет бой. Использует интерфейс
    Fighter (передаётся в конструктор) — поддерживает любого провайдера (Ollama,
    OpenAI, Anthropic).
    """

    def __init__(self, fighter: Fighter) -> None:
        self._fighter = fighter
        self._pending: set[asyncio.Task] = set()

    def __call__(self, event: Event) -> None:
        if event.type != "fighter.response":
            return
        task = asyncio.create_task(self._comment(event))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def await_pending(self) -> None:
        """Дождаться завершения всех запланированных комментариев."""
        if not self._pending:
            return
        await asyncio.gather(*self._pending, return_exceptions=True)

    async def _comment(self, event: Event) -> None:
        fighter = event.data.get("fighter") or event.source
        content = event.data.get("content", "")
        round_number = event.round_number
        user_prompt = (
            f"Round {round_number}. Fighter '{fighter}' just responded:\n\n"
            f"{content}\n\n"
            "Comment on this move in a few vivid sentences."
        )
        try:
            response = await self._fighter.generate(user_prompt)
        except FighterError:
            return
        text = response.content
        if not text or not text.strip():
            return
        self._emit(round_number, fighter, text)

    def _emit(self, round_number: int, fighter: str, text: str) -> None:
        prefix = f"[R{round_number} {fighter}] "
        for line in text.strip().splitlines():
            print(prefix + line)
