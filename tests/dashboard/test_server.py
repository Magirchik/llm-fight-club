import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path

from dashboard.server import DashboardServer


def _sample_toml(exp_id: str = "dash_test") -> str:
    return (
        f'experiment_id = "{exp_id}"\nmax_rounds = 1\nopening_message = "hi"\n\n'
        '[[fighters]]\nname = "a"\nprovider = "ollama"\nmodel = "m"\nsystem_prompt = "s"\n\n'
        '[[fighters]]\nname = "b"\nprovider = "ollama"\nmodel = "m"\nsystem_prompt = "s"\n\n'
        '[judge_llm]\nprovider = "ollama"\nmodel = "m"\n'
    )


class ServerApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._config_tmp = tempfile.TemporaryDirectory()
        cls._exp_tmp = tempfile.TemporaryDirectory()
        cls.config_dir = Path(cls._config_tmp.name)
        cls.exp_dir = Path(cls._exp_tmp.name)
        (cls.config_dir / "sample.toml").write_text(_sample_toml(), encoding="utf-8")
        cls.server = DashboardServer(
            config_dir=str(cls.config_dir),
            experiments_dir=str(cls.exp_dir),
            host="127.0.0.1",
            port=0,
        )
        from http.server import ThreadingHTTPServer

        cls._httpd = ThreadingHTTPServer(("127.0.0.1", 0), cls.server._make_handler())
        cls.port = cls._httpd.server_address[1]
        cls._thread = threading.Thread(target=cls._httpd.serve_forever, daemon=True)
        cls._thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._httpd.shutdown()
        cls._config_tmp.cleanup()
        cls._exp_tmp.cleanup()

    def _conn(self) -> HTTPConnection:
        return HTTPConnection("127.0.0.1", self.port, timeout=5)

    def _get(self, path: str):
        conn = self._conn()
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
        return resp.status, body

    def _post(self, path: str, payload: dict):
        conn = self._conn()
        conn.request("POST", path, json.dumps(payload), {"Content-Type": "application/json"})
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
        return resp.status, body

    def test_serves_index(self) -> None:
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("LLM Fight Club", body)

    def test_serves_static_css(self) -> None:
        status, body = self._get("/static/style.css")
        self.assertEqual(status, 200)
        self.assertIn("font-family", body)

    def test_list_configs(self) -> None:
        status, body = self._get("/api/configs")
        self.assertEqual(status, 200)
        data = json.loads(body)
        names = [c["name"] for c in data]
        self.assertIn("sample.toml", names)

    def test_get_config_content(self) -> None:
        status, body = self._get("/api/configs/sample.toml")
        self.assertEqual(status, 200)
        self.assertIn("experiment_id", body)

    def test_get_config_not_found(self) -> None:
        status, body = self._get("/api/configs/missing.toml")
        self.assertEqual(status, 404)

    def test_save_new_config(self) -> None:
        status, body = self._post("/api/configs/newfight", {"content": _sample_toml("new")})
        self.assertEqual(status, 200)
        self.assertTrue((self.config_dir / "newfight.toml").exists())

    def test_list_experiments_empty(self) -> None:
        status, body = self._get("/api/experiments")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), [])

    def test_experiment_not_found(self) -> None:
        status, body = self._get("/api/experiments/nope")
        self.assertEqual(status, 404)

    def test_load_experiment_with_meta_and_events(self) -> None:
        import json as _json

        exp_id = "exp_view"
        meta = {
            "experiment_id": exp_id,
            "max_rounds": 2,
            "opening_message": "hi",
            "fighters": [{"name": "a", "model": "m"}, {"name": "b", "model": "m"}],
            "judge_llm": {"model": "m"},
            "commentator": {"enabled": False},
            "referee": {"lss_critical_threshold": 0.3},
        }
        (self.exp_dir / f"{exp_id}.meta.json").write_text(
            _json.dumps(meta), encoding="utf-8"
        )
        events = [
            {"id": 0, "type": "arena.started", "source": "arena", "round_number": 0, "data": {}},
            {"id": 1, "type": "referee.decision", "source": "referee", "round_number": 2,
             "data": {"action": "win", "winner": "a", "explain": "a wins"}},
        ]
        with open(self.exp_dir / f"{exp_id}.jsonl", "w", encoding="utf-8") as f:
            for e in events:
                f.write(_json.dumps(e) + "\n")
        status, body = self._get("/api/experiments/" + exp_id)
        self.assertEqual(status, 200)
        data = _json.loads(body)
        self.assertEqual(data["winner"], "a")
        self.assertEqual(data["decision"]["action"], "win")
        self.assertEqual(data["event_count"], 2)
        self.assertEqual(data["meta"]["fighters"][0]["name"], "a")
        self.assertFalse(data["meta"]["commentator"]["enabled"])

    def test_run_endpoint_validates_config(self) -> None:
        status, body = self._post("/api/run", {"content": "invalid toml {{{"})
        self.assertEqual(status, 400)

    def test_run_endpoint_missing_content(self) -> None:
        status, body = self._post("/api/run", {})
        self.assertEqual(status, 400)

    def test_list_experiments_shows_meta_fields(self) -> None:
        import json as _json

        exp_id = "exp_list"
        meta = {
            "experiment_id": exp_id,
            "max_rounds": 3,
            "fighters": [{"name": "x"}, {"name": "y"}],
            "judge_llm": {"model": "qwen"},
            "commentator": {"enabled": True},
        }
        (self.exp_dir / f"{exp_id}.meta.json").write_text(
            _json.dumps(meta), encoding="utf-8"
        )
        status, body = self._get("/api/experiments")
        self.assertEqual(status, 200)
        data = _json.loads(body)
        found = [e for e in data if e["experiment_id"] == exp_id]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["fighters"], ["x", "y"])
        self.assertEqual(found[0]["judge_llm"], "qwen")
        self.assertTrue(found[0]["commentator_enabled"])

    def test_unknown_path_404(self) -> None:
        status, body = self._get("/api/unknown")
        self.assertEqual(status, 404)

    def test_languages_endpoint(self) -> None:
        status, body = self._get("/api/languages")
        self.assertEqual(status, 200)
        data = json.loads(body)
        codes = [d["code"] for d in data]
        self.assertIn("en", codes)
        self.assertIn("ru", codes)

    def test_run_with_language_validates(self) -> None:
        status, body = self._post("/api/run", {"content": _sample_toml(), "language": "fr"})
        self.assertEqual(status, 400)

    def test_keys_endpoint_returns_status(self) -> None:
        status, body = self._get("/api/keys")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn("openai", data)
        self.assertIn("anthropic", data)
        self.assertFalse(data["openai"])

    def test_save_and_delete_keys(self) -> None:
        import tempfile
        from pathlib import Path
        import fightclub.orchestrator.keys as keys_mod

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        secrets_path = Path(tmp.name) / "secrets.json"
        orig = keys_mod.SECRETS_FILE
        keys_mod.SECRETS_FILE = secrets_path
        self.addCleanup(setattr, keys_mod, "SECRETS_FILE", orig)
        status, body = self._post("/api/keys", {"OPENAI_API_KEY": "sk-test123"})
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["openai"])
        status, body = self._get("/api/keys")
        self.assertTrue(json.loads(body)["openai"])
        conn = self._conn()
        conn.request("DELETE", "/api/keys/openai")
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertFalse(json.loads(body)["openai"])
