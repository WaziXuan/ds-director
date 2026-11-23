import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from dsd import pipeline, runner
from tests.test_runner import FakeEnv

STUB = textwrap.dedent('''\
    def add(a: int, b: int) -> int:
        """Sum of two ints."""
        raise NotImplementedError
''')
GOOD = 'def add(a: int, b: int) -> int:\n    """Sum of two ints."""\n    return a + b\n'
TEST = textwrap.dedent('''\
    import unittest
    from calc import add

    class T(unittest.TestCase):
        def test_add(self):
            self.assertEqual(add(2, 3), 5)
''')
PASSING_TEST = "import unittest\n\nclass T(unittest.TestCase):\n    def test_x(self):\n        pass\n"
TASK = textwrap.dedent('''\
    id = "j1"
    goal = "Implement add()."
    behavior = "add(2, 3) == 5"
    test_cmd = "python -m unittest discover -s tests -t ."
    test_paths = ["tests/**"]
    src_paths = ["calc.py"]
    [limits]
    max_fix_rounds = 2
''')
CHAIN = [runner.Model("deepseek-v4.1-flash", "max", 30)]


def make_repo() -> Path:
    d = Path(tempfile.mkdtemp())
    (d / "calc.py").write_text(STUB, encoding="utf-8")
    (d / "tests").mkdir()
    (d / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (d / "task.toml").write_text(TASK, encoding="utf-8")
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "stub"]):
        subprocess.run(cmd, cwd=d, check=True)
    return d


def load(d: Path):
    return pipeline.Job.load(d / "task.toml", chain=CHAIN)


class TestsPhase(unittest.TestCase):
    def test_happy_path_writes_red_tests_then_self_checks_in_same_session(self):
        d = make_repo()
        with FakeEnv([{"write": {"tests/test_calc.py": TEST}, "result": "| add(2,3) | 5 |"},
                      {"result": "self-check: nothing missing"}]) as fe:
            out = load(d).run_tests_phase()
        self.assertEqual(out.status, "ok", out.problems)
        calls = fe.calls()
        self.assertEqual(len(calls), 2)
        self.assertIn("Implement add()", calls[0]["prompt"])
        self.assertIn("add(2, 3) == 5", calls[0]["prompt"])
        self.assertIn("tests/**", calls[0]["prompt"])
        sid = calls[0]["argv"][calls[0]["argv"].index("--session-id") + 1]
        self.assertTrue(sid.startswith("ds-") and sid.endswith("-j1-tests"))
        self.assertEqual(calls[1]["argv"][calls[1]["argv"].index("--resume") + 1], sid)
        self.assertIn("self-check", calls[1]["prompt"].lower())
        self.assertIn("tests/test_calc.py", out.files)
        self.assertIn("NotImplementedError", out.test_output)
        tools = calls[0]["argv"][calls[0]["argv"].index("--allowedTools") + 1:]
        for shell in ("Bash", "PowerShell"):  # CodeBuddy on Windows uses either
            self.assertIn(f"{shell}(python -m unittest:*)", tools)
            self.assertIn(f"{shell}(git diff:*)", tools)

    def test_test_tool_prefix_can_be_set_in_the_task(self):
        d = make_repo()
        with open(d / "task.toml", "a", encoding="utf-8") as f:
            f.write('\n')
        text = (d / "task.toml").read_text(encoding="utf-8").replace(
            'test_paths =', 'test_tool_prefix = "python -m unittest discover"\ntest_paths =')
        (d / "task.toml").write_text(text, encoding="utf-8")
        with FakeEnv([{"write": {"tests/test_calc.py": TEST}}, {}]) as fe:
            load(d).run_tests_phase()
        tools = fe.calls()[0]["argv"]
        self.assertIn("PowerShell(python -m unittest discover:*)", tools)
        self.assertNotIn("PowerShell(python -m unittest:*)", tools)

    def test_touching_source_in_tests_phase_is_sent_back(self):
        d = make_repo()
        with FakeEnv([{"write": {"tests/test_calc.py": TEST, "calc.py": GOOD}},
                      {"write": {"calc.py": STUB}},
                      {"result": "self-check done"}]) as fe:
            out = load(d).run_tests_phase()
        self.assertEqual(out.status, "ok", out.problems)
        self.assertIn("calc.py", fe.calls()[1]["prompt"])

    def test_tests_that_already_pass_end_with_needs_director(self):
        d = make_repo()
        with FakeEnv([{"write": {"tests/test_calc.py": PASSING_TEST}}] + [{}] * 5) as fe:
            out = load(d).run_tests_phase()
        self.assertEqual(out.status, "needs_director")
        self.assertTrue(any("pass" in p for p in out.problems))
        self.assertIn("pass", fe.calls()[1]["prompt"])
        self.assertLessEqual(len(fe.calls()), 1 + 2)  # first turn + max_fix_rounds

    def test_director_feedback_resumes_the_tests_session(self):
        d = make_repo()
        with FakeEnv([{"write": {"tests/test_calc.py": TEST}}, {}, {}]) as fe:
            load(d).run_tests_phase()
            load(d).run_tests_phase(feedback="also cover negatives")
        last = fe.calls()[-1]
        self.assertIn("--resume", last["argv"])
        self.assertIn("also cover negatives", fe.calls()[2]["prompt"])


class LockAndImpl(unittest.TestCase):
    def ready(self) -> Path:
        d = make_repo()
        with FakeEnv([{"write": {"tests/test_calc.py": TEST}}, {}]):
            load(d).run_tests_phase()
        load(d).lock()
        return d

    def test_impl_before_lock_is_refused(self):
        d = make_repo()
        with self.assertRaises(pipeline.PhaseError):
            load(d).run_impl_phase()

    def test_happy_path_goes_green_then_fresh_review_session(self):
        d = self.ready()
        with FakeEnv([{"write": {"calc.py": GOOD}},
                      {"result": "Looks fine.\nVERDICT: LGTM"}]) as fe:
            out = load(d).run_impl_phase()
        self.assertEqual(out.status, "ok", out.problems)
        review = fe.calls()[1]["argv"]
        self.assertTrue(review[review.index("--session-id") + 1].endswith("-j1-review"))
        tools = review[review.index("--allowedTools") + 1:]
        self.assertNotIn("Edit", tools)
        self.assertNotIn("Write", tools)
        self.assertNotIn("PowerShell(python -m unittest:*)", tools)
        self.assertIn("PowerShell(git diff:*)", tools)
        self.assertIn("calc.py", fe.calls()[1]["prompt"])

    def test_edited_tests_are_restored_and_it_is_told(self):
        d = self.ready()
        with FakeEnv([{"write": {"calc.py": GOOD, "tests/test_calc.py": PASSING_TEST}},
                      {}, {"result": "VERDICT: LGTM"}]) as fe:
            out = load(d).run_impl_phase()
        self.assertEqual(out.status, "ok", out.problems)
        self.assertEqual((d / "tests" / "test_calc.py").read_text(encoding="utf-8"), TEST)
        self.assertIn("tests/test_calc.py", fe.calls()[1]["prompt"])

    def test_signature_change_is_sent_back(self):
        d = self.ready()
        bad = GOOD.replace("b: int)", "b: int, c: int = 0)")
        with FakeEnv([{"write": {"calc.py": bad}}, {"write": {"calc.py": GOOD}},
                      {"result": "VERDICT: LGTM"}]) as fe:
            out = load(d).run_impl_phase()
        self.assertEqual(out.status, "ok", out.problems)
        self.assertIn("add", fe.calls()[1]["prompt"])
        self.assertIn("signature", fe.calls()[1]["prompt"].lower())

    def test_overlong_function_is_sent_back(self):
        d = self.ready()
        body = "".join(f"    x{i} = {i}\n" for i in range(60))
        long_ = f'def add(a: int, b: int) -> int:\n    """Sum of two ints."""\n{body}    return a + b\n'
        with FakeEnv([{"write": {"calc.py": long_}}, {"write": {"calc.py": GOOD}},
                      {"result": "VERDICT: LGTM"}]) as fe:
            out = load(d).run_impl_phase()
        self.assertEqual(out.status, "ok", out.problems)
        self.assertIn("lines", fe.calls()[1]["prompt"])

    def test_still_red_after_max_rounds_needs_director(self):
        d = self.ready()
        with FakeEnv([{}] * 4) as fe:
            out = load(d).run_impl_phase()
        self.assertEqual(out.status, "needs_director")
        self.assertEqual(len(fe.calls()), 3)  # first + 2 fix rounds, no review

    def test_review_issues_go_back_to_impl_session_once(self):
        d = self.ready()
        with FakeEnv([{"write": {"calc.py": GOOD}},
                      {"result": "1. docstring vague\nVERDICT: CHANGES"},
                      {"result": "fixed"}]) as fe:
            out = load(d).run_impl_phase()
        self.assertEqual(out.status, "ok", out.problems)
        calls = fe.calls()
        self.assertEqual(len(calls), 3)
        self.assertTrue(calls[2]["argv"][calls[2]["argv"].index("--resume") + 1].endswith("-j1-impl"))
        self.assertIn("docstring vague", calls[2]["prompt"])
        self.assertEqual(out.review, "1. docstring vague\nVERDICT: CHANGES")


class Linking(unittest.TestCase):
    def test_sessions_get_parent_sidecars_and_a_links_log(self):
        d = make_repo()
        os.environ["CLAUDE_CODE_SESSION_ID"] = "feedbeef-0000-1111-2222-333344445555"
        try:
            with FakeEnv([{"write": {"tests/test_calc.py": TEST}}, {}]) as fe:
                load(d).run_tests_phase()
                side = list(fe.projects.glob("*/ds-feedbeef-j1-tests.parent.json"))
        finally:
            del os.environ["CLAUDE_CODE_SESSION_ID"]
        self.assertEqual(len(side), 1)
        meta = json.loads(side[0].read_text(encoding="utf-8"))
        self.assertEqual(meta["id"], "feedbeef-0000-1111-2222-333344445555")
        self.assertEqual(meta["agent"], "ds:tests")
        state = json.loads((d / ".dsd" / "j1" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["sessions"]["tests"], "ds-feedbeef-j1-tests")


if __name__ == "__main__":
    unittest.main()
