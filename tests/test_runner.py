import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from dsd import links, runner

FAKE = str(Path(__file__).with_name("fake_codebuddy.py"))


class FakeEnv:
    """Points dsd at fake_codebuddy.py with a scripted plan."""

    def __init__(self, plan):
        self.dir = Path(tempfile.mkdtemp())
        self.plan, self.log = self.dir / "plan.json", self.dir / "log.jsonl"
        self.projects = self.dir / "projects"
        self.plan.write_text(json.dumps(plan), encoding="utf-8")
        self.env = {"DSD_CODEBUDDY": FAKE, "DSD_FAKE_PLAN": str(self.plan),
                    "DSD_FAKE_LOG": str(self.log), "DSD_CB_PROJECTS": str(self.projects)}

    def __enter__(self):
        self.old = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        return self

    def __exit__(self, *exc):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(l) for l in self.log.read_text(encoding="utf-8").splitlines()]


CHAIN = [runner.Model("deepseek-v4.1-flash", "max", 5), runner.Model("hy4flash", None, 5),
         runner.Model("hy4std", None, 5)]


class Command(unittest.TestCase):
    def test_first_call_sets_session_id_model_effort_and_tools(self):
        cmd = runner.cb_args(CHAIN[0], "ds-abc-j1-tests", first=True,
                             tools=["Read", "Bash(python -m unittest:*)"], append="RULES", max_turns=40)
        self.assertEqual(cmd[cmd.index("--session-id") + 1], "ds-abc-j1-tests")
        self.assertNotIn("--resume", cmd)
        self.assertEqual(cmd[cmd.index("--model") + 1], "deepseek-v4.1-flash")
        self.assertEqual(cmd[cmd.index("--effort") + 1], "max")
        self.assertIn("-p", cmd)
        self.assertNotIn("-y", cmd)
        self.assertNotIn("--dangerously-skip-permissions", cmd)
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "acceptEdits")
        i = cmd.index("--allowedTools")
        self.assertEqual(cmd[i + 1:i + 3], ["Read", "Bash(python -m unittest:*)"])
        self.assertEqual(cmd[cmd.index("--append-system-prompt") + 1], "RULES")
        self.assertEqual(cmd[cmd.index("--output-format") + 1], "stream-json")

    def test_later_calls_resume_and_models_without_effort_omit_it(self):
        cmd = runner.cb_args(CHAIN[1], "ds-abc-j1-tests", first=False, tools=["Read"],
                             append="", max_turns=40)
        self.assertEqual(cmd[cmd.index("--resume") + 1], "ds-abc-j1-tests")
        self.assertIn("--resume-create-missing", cmd)
        self.assertNotIn("--session-id", cmd)
        self.assertNotIn("--effort", cmd)


class Turn(unittest.TestCase):
    def run_turn(self, first=True, chain=CHAIN):
        cwd = Path(tempfile.mkdtemp())
        return runner.run_turn("ds-p-j1-impl", "do the thing", cwd, first=first, chain=chain,
                               tools=["Read"], append="", log=cwd / "turns.jsonl"), cwd

    def test_success_returns_text_model_and_passes_prompt_on_stdin(self):
        with FakeEnv([{"result": "all good", "write": {"x.txt": "hi"}}]) as fe:
            res, cwd = self.run_turn()
        self.assertTrue(res.ok)
        self.assertEqual(res.text, "all good")
        self.assertEqual(res.model, "deepseek-v4.1-flash")
        self.assertEqual((cwd / "x.txt").read_text(), "hi")
        self.assertEqual(fe.calls()[0]["prompt"], "do the thing")
        self.assertTrue((cwd / "turns.jsonl").exists())

    def test_timeout_falls_back_to_next_model_resuming_same_session(self):
        chain = [runner.Model("deepseek-v4.1-flash", "max", 1), runner.Model("hy4flash", None, 5)]
        with FakeEnv([{"sleep": 4}, {"result": "from hy"}]) as fe:
            res, _ = self.run_turn(chain=chain)
        self.assertTrue(res.ok)
        self.assertEqual(res.model, "hy4flash")
        self.assertEqual(res.fallbacks, ["deepseek-v4.1-flash: timeout after 1s"])
        second = fe.calls()[1]["argv"]
        self.assertEqual(second[second.index("--resume") + 1], "ds-p-j1-impl")

    def test_crash_and_error_result_also_fall_back(self):
        with FakeEnv([{"crash": True}, {"error": True, "result": "overloaded"}, {"result": "ok"}]):
            res, _ = self.run_turn()
        self.assertTrue(res.ok)
        self.assertEqual(res.model, "hy4std")
        self.assertEqual(len(res.fallbacks), 2)

    def test_all_models_failing_is_not_ok(self):
        with FakeEnv([{"crash": True}] * 3):
            res, _ = self.run_turn()
        self.assertFalse(res.ok)
        self.assertEqual(len(res.fallbacks), 3)

    def test_permission_denials_are_reported(self):
        with FakeEnv([{"denials": [{"tool_name": "Bash"}]}]):
            res, _ = self.run_turn()
        self.assertEqual(res.denials, ["Bash"])


class Links(unittest.TestCase):
    def test_session_id_carries_parent_prefix_and_is_sanitised(self):
        sid = links.session_id("db444e85-f5d6-5a72-a39b-8cb176c40190", "j 01/x", "tests")
        self.assertEqual(sid, "ds-db444e85-j-01-x-tests")
        self.assertEqual(links.session_id(None, "j1", "impl"), "ds-noparent-j1-impl")

    def test_sidecar_is_written_next_to_the_session_file(self):
        root = Path(tempfile.mkdtemp())
        (root / "d-Work").mkdir()
        (root / "d-Work" / "ds-aa-j1-tests.jsonl").write_text("{}\n")
        p = links.write_sidecar(root, "ds-aa-j1-tests", "aa-full-id", "ds:tests", "j1 · tests")
        self.assertEqual(p, root / "d-Work" / "ds-aa-j1-tests.parent.json")
        data = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(data, {"src": "cl", "id": "aa-full-id", "agent": "ds:tests",
                                "title": "j1 · tests"})

    def test_no_sidecar_without_parent_or_session_file(self):
        root = Path(tempfile.mkdtemp())
        self.assertIsNone(links.write_sidecar(root, "ds-x", "pid", "ds:tests", "t"))
        (root / "p").mkdir()
        (root / "p" / "ds-x.jsonl").write_text("{}\n")
        self.assertIsNone(links.write_sidecar(root, "ds-x", None, "ds:tests", "t"))

    def test_parent_comes_from_claude_env(self):
        os.environ["CLAUDE_CODE_SESSION_ID"] = "abc-123"
        try:
            self.assertEqual(links.current_parent(), "abc-123")
        finally:
            del os.environ["CLAUDE_CODE_SESSION_ID"]
        self.assertIsNone(links.current_parent())


if __name__ == "__main__":
    unittest.main()
