import unittest
from pathlib import Path

from dashboard.runner import Run, _COMMENT_RE, enable_commentator, set_language


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
