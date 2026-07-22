import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fightclub.orchestrator import ConfigError, load_config

_COMMENT_RE = re.compile(r"^\[R\d+\s+\S+\]")


def set_language(toml_text: str, language: str) -> str:
    """Устанавливает language = "<lang>" в тексте TOML (top-level ключ).

    Если ключ есть — заменяет, если нет — добавляет в начало файла (до любых [section]).
    """
    if re.search(r'^\s*language\s*=\s*"', toml_text, re.MULTILINE):
        return re.sub(
            r'^\s*language\s*=\s*"[^"]*"',
            f'language = "{language}"',
            toml_text,
            count=1,
            flags=re.MULTILINE,
        )
    return f'language = "{language}"\n' + toml_text


def enable_commentator(toml_text: str) -> str:
    """Включает commentator в тексте TOML (enabled = true).

    Если [commentator] есть — заменяет/добавляет enabled. Если нет — дописывает секцию.
    """
    if re.search(r"^\[commentator\]", toml_text, re.MULTILINE):
        if re.search(r"^\s*enabled\s*=", toml_text, re.MULTILINE):
            toml_text = re.sub(
                r"(\[commentator\][^\[]*?enabled\s*=\s*)false",
                r"\1true",
                toml_text,
                flags=re.DOTALL,
            )
        else:
            toml_text = re.sub(
                r"(\[commentator\])",
                r"\1\nenabled = true",
                toml_text,
            )
    else:
        toml_text = toml_text.rstrip() + "\n\n[commentator]\nenabled = true\n"
    return toml_text


def set_experiment_id(toml_text: str, experiment_id: str) -> str:
    """Устанавливает experiment_id = "<id>" в тексте TOML (top-level ключ).

    Если ключ есть — заменяет, если нет — добавляет в начало файла (до любых [section]).
    """
    if re.search(r'^\s*experiment_id\s*=\s*"', toml_text, re.MULTILINE):
        return re.sub(
            r'^\s*experiment_id\s*=\s*"[^"]*"',
            f'experiment_id = "{experiment_id}"',
            toml_text,
            count=1,
            flags=re.MULTILINE,
        )
    return f'experiment_id = "{experiment_id}"\n' + toml_text


def set_seeds(toml_text: str, seed: int) -> str:
    """Устанавливает seed = <seed> во всех релевантных секциях TOML.

    Заменяет существующие seed = <int> в каждой [[fighters]], [judge_llm], [commentator].
    Секции без seed — добавляет seed в конец блока. Возвращает новый текст TOML.
    """

    def _process_block(match: re.Match) -> str:
        block = match.group(0)
        if re.search(r"^\s*seed\s*=", block, re.MULTILINE):
            return re.sub(r"(seed\s*=\s*)\d+", rf"\g<1>{seed}", block)
        return block.rstrip() + f"\nseed = {seed}\n"

    text = re.sub(r"\[\[fighters\]\][^\[]*", _process_block, toml_text)
    text = re.sub(r"\[judge_llm\][^\[]*", _process_block, text)
    text = re.sub(r"\[commentator\][^\[]*", _process_block, text)
    return text


def with_run_seeds(toml_text: str, run_index: int) -> str:
    """Присваивает per-run seeds для i-го запуска батча.

    Если в TOML все seed = 0 (default) — ставит seed = run_index (1, 2, ...).
    Если есть ненулевые base seeds — добавляет run_index-1 к каждому (base+i-1).
    Секции без seed получают seed = run_index (добавляется через set_seeds).
    Возвращает новый текст TOML.
    """
    has_nonzero = re.search(r'seed\s*=\s*[1-9]\d*', toml_text) is not None
    if has_nonzero:
        def _bump(m: re.Match) -> str:
            return f"{m.group(1)}{int(m.group(2)) + run_index - 1}"
        return re.sub(r'(seed\s*=\s*)(\d+)', _bump, toml_text)
    return set_seeds(toml_text, run_index)


class Run:
    """Один запущенный эксперимент: subprocess + накопленные события/комментарии."""

    def __init__(
        self,
        run_id: str,
        config_path: Path,
        experiment_id: str,
        events_path: Path,
        batch_id: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.config_path = config_path
        self.experiment_id = experiment_id
        self.events_path = events_path
        self.batch_id = batch_id
        self.process: subprocess.Popen | None = None
        self.events: list[dict[str, Any]] = []
        self.comments: list[str] = []
        self.reason: str | None = None
        self.winner: str | None = None
        self.finished = False
        self._lock = threading.Lock()

    def add_event(self, event: dict[str, Any]) -> None:
        with self._lock:
            self.events.append(event)
            if event.get("type") == "referee.decision":
                self.winner = event.get("data", {}).get("winner")

    def add_comment(self, text: str) -> None:
        with self._lock:
            self.comments.append(text)

    def snapshot(self, event_offset: int, comment_offset: int) -> dict[str, Any]:
        with self._lock:
            return {
                "events": self.events[event_offset:],
                "comments": self.comments[comment_offset:],
                "event_total": len(self.events),
                "comment_total": len(self.comments),
                "finished": self.finished,
                "reason": self.reason,
                "winner": self.winner,
            }


class RunManager:
    """Управляет запущенными экспериментами (subprocess) и сбором их вывода."""

    def __init__(self, experiments_dir: str = "experiments") -> None:
        self.experiments_dir = Path(experiments_dir)
        self._runs: dict[str, Run] = {}

    def kill_all(self) -> None:
        """Убивает все незавершённые subprocess'ы и помечает их finished.

        Вызывается перед новым запуском, чтобы побочные процессы прошлых боёв
        не висели и не держали Ollama/JSONL.
        """
        for run in self._runs.values():
            if run.finished or run.process is None:
                continue
            try:
                run.process.kill()
            except Exception:
                pass
            run.finished = True
            if run.reason is None:
                run.reason = "killed"

    def start(
        self,
        toml_text: str,
        *,
        enable_commentator_flag: bool = True,
        language: str | None = None,
    ) -> str:
        self.kill_all()
        run = self._prepare_run(
            toml_text,
            enable_commentator_flag=enable_commentator_flag,
            language=language,
        )
        self._start_run(run)
        return run.run_id

    def start_many(
        self,
        toml_text: str,
        n: int,
        *,
        parallel: bool = False,
        max_parallel: int = 3,
        enable_commentator_flag: bool = True,
        language: str | None = None,
    ) -> tuple[str, list[str]]:
        """Запускает батч из N экспериментов одного конфига.

        Каждому run присваивается уникальный experiment_id («{orig}_{i}»).
        parallel=false — последовательные; parallel=true — до max_parallel одновременно.
        Возвращает (batch_id, [run_id, ...]).
        """
        if n < 1:
            raise ValueError("n must be >= 1")
        self.kill_all()
        base = toml_text
        if language:
            base = set_language(base, language)
        if enable_commentator_flag:
            base = enable_commentator(base)
        tmp_probe = tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False, encoding="utf-8"
        )
        tmp_probe.write(base)
        tmp_probe.close()
        try:
            orig_id = load_config(Path(tmp_probe.name)).experiment_id
        except ConfigError:
            Path(tmp_probe.name).unlink(missing_ok=True)
            raise
        Path(tmp_probe.name).unlink(missing_ok=True)

        batch_id = uuid.uuid4().hex[:12]
        runs: list[Run] = []
        for i in range(1, n + 1):
            run_toml = set_experiment_id(base, f"{orig_id}_{i}" if n > 1 else orig_id)
            if n > 1:
                run_toml = with_run_seeds(run_toml, i)
            run = self._prepare_run(
                run_toml,
                enable_commentator_flag=False,
                language=None,
                batch_id=batch_id,
            )
            runs.append(run)
        worker = threading.Thread(
            target=self._batch_worker,
            args=(runs, parallel, max_parallel),
            daemon=True,
        )
        worker.start()
        return batch_id, [r.run_id for r in runs]

    def _prepare_run(
        self,
        toml_text: str,
        *,
        enable_commentator_flag: bool,
        language: str | None,
        batch_id: str | None = None,
    ) -> Run:
        if language:
            toml_text = set_language(toml_text, language)
        if enable_commentator_flag:
            toml_text = enable_commentator(toml_text)
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False, encoding="utf-8"
        )
        tmp.write(toml_text)
        tmp.close()
        config_path = Path(tmp.name)
        try:
            config = load_config(config_path)
        except ConfigError:
            config_path.unlink(missing_ok=True)
            raise
        run_id = uuid.uuid4().hex[:12]
        events_path = self.experiments_dir / f"{config.experiment_id}.jsonl"
        events_path.unlink(missing_ok=True)
        run = Run(run_id, config_path, config.experiment_id, events_path, batch_id=batch_id)
        self._runs[run_id] = run
        return run

    def _start_run(self, run: Run) -> None:
        cmd = [sys.executable, "-u", "-m", "fightclub", "run", str(run.config_path)]
        run.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={
                **os.environ,
                "PYTHONUNBUFFERED": "1",
                "PYTHONIOENCODING": "utf-8",
            },
        )
        threading.Thread(target=self._read_stdout, args=(run,), daemon=True).start()
        threading.Thread(target=self._read_jsonl, args=(run,), daemon=True).start()
        threading.Thread(target=self._wait_exit, args=(run,), daemon=True).start()

    def _batch_worker(self, runs: list[Run], parallel: bool, max_parallel: int) -> None:
        if parallel:
            queue = list(runs)
            active: list[Run] = []
            while queue or active:
                while queue and len(active) < max_parallel:
                    run = queue.pop(0)
                    self._start_run(run)
                    active.append(run)
                time.sleep(0.2)
                active = [r for r in active if not r.finished]
        else:
            for run in runs:
                self._start_run(run)
                while not run.finished:
                    time.sleep(0.2)

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def list_active(self) -> list[dict[str, Any]]:
        return [
            {
                "run_id": r.run_id,
                "batch_id": r.batch_id,
                "experiment_id": r.experiment_id,
                "finished": r.finished,
                "reason": r.reason,
                "winner": r.winner,
                "events": len(r.events),
                "comments": len(r.comments),
            }
            for r in self._runs.values()
        ]

    def _read_stdout(self, run: Run) -> None:
        assert run.process is not None
        assert run.process.stdout is not None
        stream = run.process.stdout
        while True:
            line = stream.readline()
            if not line:
                break
            text = line.strip()
            if text and _COMMENT_RE.match(text):
                run.add_comment(text)

    def _read_jsonl(self, run: Run) -> None:
        while not run.events_path.exists():
            if run.process and run.process.poll() is not None:
                return
            time.sleep(0.05)
        with open(run.events_path, "r", encoding="utf-8") as f:
            while True:
                line = f.readline()
                if line:
                    try:
                        run.add_event(json.loads(line))
                    except json.JSONDecodeError:
                        pass
                else:
                    if run.process and run.process.poll() is not None:
                        time.sleep(0.1)
                        remaining = f.read()
                        for extra in remaining.strip().split("\n"):
                            if extra:
                                try:
                                    run.add_event(json.loads(extra))
                                except json.JSONDecodeError:
                                    pass
                        break
                    time.sleep(0.05)

    def _wait_exit(self, run: Run) -> None:
        assert run.process is not None
        code = run.process.wait()
        time.sleep(0.2)
        run.finished = True
        if run.reason is None:
            run.reason = _infer_reason(run, code)
        try:
            run.config_path.unlink(missing_ok=True)
        except OSError:
            pass

    def cleanup_finished(self, max_keep: int = 50) -> None:
        finished = [rid for rid, r in self._runs.items() if r.finished]
        for rid in finished[len(finished) - max_keep:]:
            self._runs.pop(rid, None)


def _infer_reason(run: Run, code: int) -> str:
    for event in reversed(run.events):
        if event.get("type") == "arena.finished":
            return event.get("data", {}).get("reason", "unknown")
    if code != 0:
        return "error"
    return "unknown"
