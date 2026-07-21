import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from fightclub.orchestrator.config import SUPPORTED_LANGUAGES
from fightclub.orchestrator.keys import (
    ENV_VAR_NAMES,
    configured_providers,
    load_secrets,
    save_secrets,
)

from .runner import RunManager

DEFAULT_STATIC_DIR = Path(__file__).parent / "static"


class DashboardServer:
    """HTTP-сервер dashboard: REST API + SSE + static files."""

    def __init__(
        self,
        config_dir: str = "config",
        experiments_dir: str = "experiments",
        static_dir: Path | None = None,
        host: str = "127.0.0.1",
        port: int = 8000,
    ) -> None:
        self.config_dir = Path(config_dir)
        self.experiments_dir = Path(experiments_dir)
        self.static_dir = static_dir or DEFAULT_STATIC_DIR
        self.host = host
        self.port = port
        self.run_manager = RunManager(experiments_dir=experiments_dir)

    def serve(self) -> None:
        server = ThreadingHTTPServer((self.host, self.port), self._make_handler())
        print(f"Dashboard: http://{self.host}:{self.port}")
        server.serve_forever()

    def _make_handler(self):
        config_dir = self.config_dir
        experiments_dir = self.experiments_dir
        static_dir = self.static_dir
        run_manager = self.run_manager

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args) -> None:
                pass

            def _send_json(self, code: int, payload) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_text(self, code: int, text: str, content_type: str = "text/plain; charset=utf-8") -> None:
                body = text.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                path = parsed.path
                if path == "/" or path == "/index.html":
                    self._serve_file(static_dir / "index.html", "text/html; charset=utf-8")
                    return
                if path.startswith("/static/"):
                    self._serve_file(static_dir / path[len("/static/"):])
                    return
                if path == "/api/configs":
                    self._send_json(200, _list_configs(config_dir))
                    return
                if path.startswith("/api/configs/"):
                    name = path[len("/api/configs/"):]
                    p = config_dir / name
                    if not p.is_file():
                        self._send_json(404, {"error": "not found"})
                        return
                    self._send_text(200, p.read_text(encoding="utf-8"), "text/plain; charset=utf-8")
                    return
                if path == "/api/experiments":
                    self._send_json(200, _list_experiments(experiments_dir))
                    return
                if path == "/api/languages":
                    self._send_json(
                        200,
                        [{"code": k, "name": v} for k, v in SUPPORTED_LANGUAGES.items()],
                    )
                    return
                if path == "/api/keys":
                    self._send_json(200, configured_providers())
                    return
                if path.startswith("/api/keys/"):
                    provider = path[len("/api/keys/"):]
                    if self.command == "DELETE":
                        self._delete_key(provider)
                        return
                if path.startswith("/api/experiments/"):
                    exp_id = path[len("/api/experiments/"):]
                    data = _load_experiment(experiments_dir, exp_id)
                    if data is None:
                        self._send_json(404, {"error": "not found"})
                        return
                    self._send_json(200, data)
                    return
                if path == "/api/runs":
                    self._send_json(200, run_manager.list_active())
                    return
                if path.startswith("/api/runs/") and path.endswith("/stream"):
                    run_id = path[len("/api/runs/"):-len("/stream")]
                    self._handle_sse(run_id, run_manager)
                    return
                self._send_json(404, {"error": "not found"})

            def do_POST(self) -> None:
                parsed = urlparse(self.path)
                path = parsed.path
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b""
                if path.startswith("/api/configs/"):
                    name = path[len("/api/configs/"):]
                    body = json.loads(raw) if raw else {}
                    text = body.get("content", "")
                    if not name.endswith(".toml"):
                        name = name + ".toml"
                    p = config_dir / name
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(text, encoding="utf-8")
                    self._send_json(200, {"name": name})
                    return
                if path == "/api/run":
                    body = json.loads(raw) if raw else {}
                    toml_text = body.get("content", "")
                    enable_comm = body.get("commentator", True)
                    language = body.get("language") or None
                    if not toml_text:
                        self._send_json(400, {"error": "content required"})
                        return
                    try:
                        run_id = run_manager.start(
                            toml_text,
                            enable_commentator_flag=enable_comm,
                            language=language,
                        )
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                        return
                    self._send_json(200, {"run_id": run_id})
                    return
                if path == "/api/keys":
                    body = json.loads(raw) if raw else {}
                    self._save_keys(body)
                    return
                self._send_json(404, {"error": "not found"})

            def _save_keys(self, body: dict) -> None:
                secrets = load_secrets()
                for env_var in ENV_VAR_NAMES.values():
                    if env_var in body and body[env_var]:
                        secrets[env_var] = body[env_var]
                save_secrets(secrets)
                self._send_json(200, configured_providers())

            def _delete_key(self, provider: str) -> None:
                env_var = ENV_VAR_NAMES.get(provider)
                if not env_var:
                    self._send_json(404, {"error": "unknown provider"})
                    return
                secrets = load_secrets()
                secrets.pop(env_var, None)
                save_secrets(secrets)
                self._send_json(200, configured_providers())

            def do_DELETE(self) -> None:
                parsed = urlparse(self.path)
                path = parsed.path
                if path.startswith("/api/keys/"):
                    provider = path[len("/api/keys/"):]
                    self._delete_key(provider)
                    return
                self._send_json(404, {"error": "not found"})

            def _serve_file(self, p: Path, content_type: str | None = None) -> None:
                if not p.is_file():
                    self._send_json(404, {"error": "not found"})
                    return
                if content_type is None:
                    content_type = _guess_content_type(p)
                body = p.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store, must-revalidate")
                self.end_headers()
                self.wfile.write(body)

            def _handle_sse(self, run_id: str, manager: RunManager) -> None:
                run = manager.get(run_id)
                if run is None:
                    self._send_json(404, {"error": "run not found"})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                event_offset = 0
                comment_offset = 0
                try:
                    while True:
                        snap = run.snapshot(event_offset, comment_offset)
                        for event in snap["events"]:
                            self._sse_write("event", event)
                            event_offset += 1
                        for comment in snap["comments"]:
                            self._sse_write("comment", {"text": comment})
                            comment_offset += 1
                        if snap["finished"]:
                            self._sse_write("finished", {"reason": snap["reason"]})
                            break
                        time.sleep(0.1)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def _sse_write(self, event_type: str, data) -> None:
                payload = json.dumps(data, ensure_ascii=False)
                self.wfile.write(f"event: {event_type}\n".encode("utf-8"))
                self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()

        return Handler


def _list_configs(config_dir: Path) -> list[dict]:
    if not config_dir.is_dir():
        return []
    return [
        {"name": p.name, "size": p.stat().st_size}
        for p in sorted(config_dir.glob("*.toml"))
    ]


def _list_experiments(experiments_dir: Path) -> list[dict]:
    if not experiments_dir.is_dir():
        return []
    out = []
    for meta in sorted(experiments_dir.glob("*.meta.json"), reverse=True):
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        out.append({
            "experiment_id": data.get("experiment_id"),
            "max_rounds": data.get("max_rounds"),
            "fighters": [f.get("name") for f in data.get("fighters", [])],
            "judge_llm": data.get("judge_llm", {}).get("model"),
            "commentator_enabled": data.get("commentator", {}).get("enabled"),
            "meta_file": meta.name,
        })
    return out


def _load_experiment(experiments_dir: Path, exp_id: str) -> dict | None:
    meta_path = experiments_dir / f"{exp_id}.meta.json"
    events_path = experiments_dir / f"{exp_id}.jsonl"
    if not meta_path.is_file():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    events: list[dict] = []
    if events_path.is_file():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    decision = None
    winner = None
    for event in reversed(events):
        if event.get("type") == "referee.decision":
            decision = event.get("data")
            winner = decision.get("winner")
            break
    return {
        "meta": meta,
        "events": events,
        "decision": decision,
        "winner": winner,
        "event_count": len(events),
    }


def _guess_content_type(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8",
    }.get(ext, "application/octet-stream")
