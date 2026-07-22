import io
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard.runner import (
    Run,
    RunManager,
    _COMMENT_RE,
    enable_commentator,
    set_experiment_id,
    set_language,
    set_seeds,
    with_run_seeds,
)


class _FakeProc:
    def __init__(self) -> None:
        self.stdout = io.StringIO("")
        self.stderr = io.StringIO("")
        self.killed = False

    def poll(self) -> int:
        return 0

    def wait(self) -> int:
        return 0

    def kill(self) -> None:
        self.killed = True


def _fake_start_run(run: Run) -> None:
    run.process = _FakeProc()
    run.finished = True
    run.reason = "completed"


def _live_start_run(run: Run) -> None:
    run.process = _FakeProc()
    run.finished = False


class EnableCommentatorTest(unittest.TestCase):
    def test_adds_section_when_absent(self) -> None:
        text = 'experiment_id = "e1"\nmax_rounds = 1\n'
        out = enable_commentator(text)
        self.assertIn("[commentator]", out)
        self.assertIn("enabled = true", out)

    def test_replaces_false_with_true(self) -> None:
        text = (
            'experiment_id = "e1"\nmax_rounds = 1\n\n'
            "[commentator]\nenabled = false\nmodel = \"m\"\n"
        )
        out = enable_commentator(text)
        self.assertIn("enabled = true", out)
        self.assertNotIn("enabled = false", out)
        self.assertIn('model = "m"', out)

    def test_adds_enabled_when_section_exists_without_it(self) -> None:
        text = 'experiment_id = "e1"\n\n[commentator]\nmodel = "m"\n'
        out = enable_commentator(text)
        self.assertIn("enabled = true", out)
        self.assertIn('model = "m"', out)

    def test_idempotent_when_already_true(self) -> None:
        text = "[commentator]\nenabled = true\n"
        out = enable_commentator(text)
        self.assertEqual(out.count("enabled = true"), 1)

    def test_preserves_rest_of_file(self) -> None:
        text = (
            'experiment_id = "e1"\nmax_rounds = 5\nopening_message = "hi"\n\n'
            "[[fighters]]\nname = \"a\"\nprovider = \"ollama\"\nmodel = \"m\"\n"
        )
        out = enable_commentator(text)
        self.assertIn('experiment_id = "e1"', out)
        self.assertIn('name = "a"', out)
        self.assertIn("[commentator]", out)


class StdoutFilterTest(unittest.TestCase):
    def test_only_commentator_lines_become_comments(self) -> None:
        run = Run("rid", Path("x.toml"), "exp", Path("x.jsonl"))
        lines = [
            "[R1 alice] Sharp opening! She attacks the premise.\n",
            "[sample_003] finished: reason=completed, winner=bob\n",
            "  events: experiments\\sample_003.jsonl\n",
            "[R2 bob] Bob dodges and counters.\n",
            "random noise without prefix\n",
        ]
        for line in lines:
            text = line.strip()
            if text and _COMMENT_RE.match(text):
                run.add_comment(text)
        self.assertEqual(len(run.comments), 2)
        self.assertTrue(run.comments[0].startswith("[R1 alice]"))
        self.assertTrue(run.comments[1].startswith("[R2 bob]"))


class SetLanguageTest(unittest.TestCase):
    def test_adds_language_when_absent(self) -> None:
        out = set_language('experiment_id = "e1"\nmax_rounds = 1\n', "ru")
        self.assertIn('language = "ru"', out)
        self.assertTrue(out.startswith('language = "ru"'))

    def test_replaces_existing_language(self) -> None:
        text = 'language = "en"\nexperiment_id = "e1"\n'
        out = set_language(text, "ru")
        self.assertIn('language = "ru"', out)
        self.assertNotIn('language = "en"', out)

    def test_preserves_rest_of_file(self) -> None:
        text = 'experiment_id = "e1"\nmax_rounds = 5\n\n[[fighters]]\nname = "a"\n'
        out = set_language(text, "ru")
        self.assertIn('experiment_id = "e1"', out)
        self.assertIn('name = "a"', out)
        self.assertIn('language = "ru"', out)


class KillAllTest(unittest.TestCase):
    def test_kills_unfinished_and_marks_finished(self) -> None:
        manager = RunManager(experiments_dir=".")
        run1 = Run("r1", Path("a.toml"), "e1", Path("a.jsonl"))
        run1.process = _FakeProc()
        run1.finished = False
        run2 = Run("r2", Path("b.toml"), "e2", Path("b.jsonl"))
        run2.process = _FakeProc()
        run2.finished = True
        run2.reason = "completed"
        manager._runs = {"r1": run1, "r2": run2}
        manager.kill_all()
        self.assertTrue(run1.process.killed)
        self.assertTrue(run1.finished)
        self.assertEqual(run1.reason, "killed")
        self.assertFalse(run2.process.killed)

    def test_kill_all_no_error_on_none_process(self) -> None:
        manager = RunManager(experiments_dir=".")
        run = Run("r", Path("a.toml"), "e", Path("a.jsonl"))
        run.process = None
        run.finished = False
        manager._runs = {"r": run}
        manager.kill_all()
        self.assertFalse(run.finished)


class RunManagerStartTest(unittest.TestCase):
    _TOML = (
        'experiment_id = "rmt"\nmax_rounds = 1\nopening_message = "hi"\n\n'
        '[[fighters]]\nname = "a"\nprovider = "ollama"\nmodel = "m"\nsystem_prompt = "s"\n\n'
        '[[fighters]]\nname = "b"\nprovider = "ollama"\nmodel = "m"\nsystem_prompt = "s"\n\n'
        '[judge_llm]\nprovider = "ollama"\nmodel = "m"\n'
    )

    def test_deletes_existing_jsonl_before_spawn(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        exp_dir = Path(tmp.name)
        events_path = exp_dir / "rmt.jsonl"
        events_path.write_text('{"old": "stale event"}\n', encoding="utf-8")
        manager = RunManager(experiments_dir=str(exp_dir))
        manager._start_run = _fake_start_run
        manager.start(self._TOML, enable_commentator_flag=False)
        self.assertFalse(events_path.exists())

    def test_start_no_error_when_jsonl_absent(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        manager = RunManager(experiments_dir=str(tmp.name))
        manager._start_run = _fake_start_run
        manager.start(self._TOML, enable_commentator_flag=False)


class SetExperimentIdTest(unittest.TestCase):
    def test_replaces_existing(self) -> None:
        out = set_experiment_id('experiment_id = "orig"\nmax_rounds = 1\n', "new_id")
        self.assertIn('experiment_id = "new_id"', out)
        self.assertNotIn('"orig"', out)

    def test_adds_when_absent(self) -> None:
        out = set_experiment_id('max_rounds = 1\n', "added")
        self.assertIn('experiment_id = "added"', out)
        self.assertTrue(out.startswith('experiment_id = "added"'))


class SetSeedsTest(unittest.TestCase):
    _TOML_WITH_SEEDS = (
        'experiment_id = "e"\nmax_rounds = 1\n\n'
        '[[fighters]]\nname = "a"\nseed = 0\n\n'
        '[[fighters]]\nname = "b"\nseed = 0\n\n'
        '[judge_llm]\nseed = 0\n\n'
        '[commentator]\nseed = 0\n'
    )

    def test_set_seeds_replaces_all(self) -> None:
        out = set_seeds(self._TOML_WITH_SEEDS, 7)
        self.assertEqual(out.count("seed = 7"), 4)
        self.assertNotIn("seed = 0", out)

    def test_set_seeds_adds_to_sections_without_seed(self) -> None:
        toml = (
            'experiment_id = "e"\nmax_rounds = 1\n\n'
            '[[fighters]]\nname = "a"\nsystem_prompt = "s"\n\n'
            '[judge_llm]\nmodel = "m"\n'
        )
        out = set_seeds(toml, 5)
        self.assertIn("seed = 5", out)

    def test_with_run_seeds_default_zero(self) -> None:
        out = with_run_seeds(self._TOML_WITH_SEEDS, 3)
        self.assertEqual(out.count("seed = 3"), 4)

    def test_with_run_seeds_nonzero_base_adds_index(self) -> None:
        toml = self._TOML_WITH_SEEDS.replace("seed = 0", "seed = 42")
        out = with_run_seeds(toml, 2)
        self.assertEqual(out.count("seed = 43"), 4)

    def test_with_run_seeds_run1_keeps_base(self) -> None:
        toml = self._TOML_WITH_SEEDS.replace("seed = 0", "seed = 10")
        out = with_run_seeds(toml, 1)
        self.assertEqual(out.count("seed = 10"), 4)


class StartManyTest(unittest.TestCase):
    _TOML = (
        'experiment_id = "rmt"\nmax_rounds = 1\nopening_message = "hi"\n\n'
        '[[fighters]]\nname = "a"\nprovider = "ollama"\nmodel = "m"\nsystem_prompt = "s"\n\n'
        '[[fighters]]\nname = "b"\nprovider = "ollama"\nmodel = "m"\nsystem_prompt = "s"\n\n'
        '[judge_llm]\nprovider = "ollama"\nmodel = "m"\n'
    )

    def _wait_for_runs(self, manager: RunManager, n: int, timeout: float = 5.0) -> list:
        deadline = time.time() + timeout
        while time.time() < deadline:
            active = manager.list_active()
            if len(active) >= n:
                return active
            time.sleep(0.05)
        return manager.list_active()

    def _make_manager(self, experiments_dir: str) -> RunManager:
        manager = RunManager(experiments_dir=experiments_dir)
        manager._start_run = _fake_start_run
        return manager

    def test_sequential_creates_n_runs_with_unique_ids(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        manager = self._make_manager(str(tmp.name))
        batch_id, run_ids = manager.start_many(
            self._TOML, 3, parallel=False, enable_commentator_flag=False
        )
        self.assertEqual(len(run_ids), 3)
        self.assertIsNotNone(batch_id)
        active = self._wait_for_runs(manager, 3)
        self.assertEqual(len(active), 3)
        exp_ids = {r["experiment_id"] for r in active}
        self.assertEqual(exp_ids, {"rmt_1", "rmt_2", "rmt_3"})
        for r in active:
            self.assertEqual(r["batch_id"], batch_id)

    def test_parallel_creates_n_runs(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        manager = self._make_manager(str(tmp.name))
        batch_id, run_ids = manager.start_many(
            self._TOML, 4, parallel=True, max_parallel=2, enable_commentator_flag=False
        )
        self.assertEqual(len(run_ids), 4)
        active = self._wait_for_runs(manager, 4)
        self.assertEqual(len(active), 4)
        for r in active:
            self.assertEqual(r["batch_id"], batch_id)

    def test_single_run_keeps_original_id(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        manager = self._make_manager(str(tmp.name))
        batch_id, run_ids = manager.start_many(
            self._TOML, 1, parallel=False, enable_commentator_flag=False
        )
        active = self._wait_for_runs(manager, 1)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["experiment_id"], "rmt")

    def test_per_run_seeds_are_sequential(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        manager = self._make_manager(str(tmp.name))
        batch_id, run_ids = manager.start_many(
            self._TOML, 3, parallel=False, enable_commentator_flag=False
        )
        self._wait_for_runs(manager, 3)
        from fightclub.orchestrator import load_config

        seeds = []
        for run_id in run_ids:
            run = manager.get(run_id)
            cfg = load_config(run.config_path)
            seeds.append([f.seed for f in cfg.fighters])
        self.assertEqual(seeds[0], [1, 1])
        self.assertEqual(seeds[1], [2, 2])
        self.assertEqual(seeds[2], [3, 3])

    def test_per_run_seeds_nonzero_base(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        toml = self._TOML.replace(
            'name = "a"\nprovider = "ollama"\nmodel = "m"\nsystem_prompt = "s"',
            'name = "a"\nprovider = "ollama"\nmodel = "m"\nsystem_prompt = "s"\nseed = 50',
        ).replace(
            'name = "b"\nprovider = "ollama"\nmodel = "m"\nsystem_prompt = "s"',
            'name = "b"\nprovider = "ollama"\nmodel = "m"\nsystem_prompt = "s"\nseed = 50',
        )
        manager = self._make_manager(str(tmp.name))
        batch_id, run_ids = manager.start_many(
            toml, 2, parallel=False, enable_commentator_flag=False
        )
        self._wait_for_runs(manager, 2)
        from fightclub.orchestrator import load_config

        cfg1 = load_config(manager.get(run_ids[0]).config_path)
        cfg2 = load_config(manager.get(run_ids[1]).config_path)
        self.assertEqual([f.seed for f in cfg1.fighters], [50, 50])
        self.assertEqual([f.seed for f in cfg2.fighters], [51, 51])

    def test_single_run_does_not_change_seed(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        manager = self._make_manager(str(tmp.name))
        batch_id, run_ids = manager.start_many(
            self._TOML, 1, parallel=False, enable_commentator_flag=False
        )
        self._wait_for_runs(manager, 1)
        from fightclub.orchestrator import load_config

        cfg = load_config(manager.get(run_ids[0]).config_path)
        self.assertEqual([f.seed for f in cfg.fighters], [0, 0])

    def test_invalid_toml_raises(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        manager = self._make_manager(str(tmp.name))
        with self.assertRaises(Exception):
            manager.start_many("not valid toml {{{", 2, enable_commentator_flag=False)
