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


class Run:
    """Один запущенный эксперимент: subprocess + накопленные события/комментарии."""

    def __init__(self, run_id: str, config_path: Path, experiment_id: str, events_path: Path) -> None:
        self.run_id = run_id
        self.config_path = config_path
        self.experiment_id = experiment_id
        self.events_path = events_path
        self.process: subprocess.Popen | None = None
        self.events: list[dict[str, Any]] = []
        self.comments: list[str] = []
        self.reason: str | None = None
        self.finished = False
        self._lock = threading.Lock()

    def add_event(self, event: dict[str, Any]) -> None:
        with self._lock:
            self.events.append(event)

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
            }


class RunManager:
    """Управляет запущенными экспериментами (subprocess) и сбором их вывода."""

    def __init__(self, experiments_dir: str = "experiments") -> None:
        self.experiments_dir = Path(experiments_dir)
        self._runs: dict[str, Run] = {}

    def start(
        self,
        toml_text: str,
        *,
        enable_commentator_flag: bool = True,
        language: str | None = None,
    ) -> str:
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
        run = Run(run_id, config_path, config.experiment_id, events_path)
        self._runs[run_id] = run
        cmd = [sys.executable, "-u", "-m", "fightclub", "run", str(config_path)]
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
        return run_id

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def list_active(self) -> list[dict[str, Any]]:
        return [
            {
                "run_id": r.run_id,
                "experiment_id": r.experiment_id,
                "finished": r.finished,
                "reason": r.reason,
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
