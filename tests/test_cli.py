import json
import unittest

from dsd import cli
from tests.test_pipeline import TEST, GOOD, make_repo, CHAIN
from tests.test_runner import FakeEnv


class Cli(unittest.TestCase):
    def test_full_flow_prints_summaries_and_exit_codes(self):
        d = make_repo()
        task = str(d / "task.toml")
        with FakeEnv([{"write": {"tests/test_calc.py": TEST}, "result": "| add | 5 |"}, {},
                      {"write": {"calc.py": GOOD}}, {"result": "VERDICT: LGTM"}]):
            self.assertEqual(cli.main(["tests", task], chain=CHAIN), 0)
            self.assertEqual(cli.main(["lock", task], chain=CHAIN), 0)
            self.assertEqual(cli.main(["impl", task], chain=CHAIN), 0)
        last = json.loads((d / ".dsd" / "j1" / "last.json").read_text(encoding="utf-8"))
        self.assertEqual(last["phase"], "impl")
        self.assertEqual(last["status"], "ok")
        self.assertIn("calc.py", last["files"])

    def test_impl_without_lock_exits_nonzero(self):
        d = make_repo()
        self.assertEqual(cli.main(["impl", str(d / "task.toml")], chain=CHAIN), 2)

    def test_needs_director_exit_code(self):
        d = make_repo()
        with FakeEnv([{}] * 5):
            self.assertEqual(cli.main(["tests", str(d / "task.toml")], chain=CHAIN), 3)

    def test_status_lists_sessions(self):
        d = make_repo()
        with FakeEnv([{"write": {"tests/test_calc.py": TEST}}, {}]):
            cli.main(["tests", str(d / "task.toml")], chain=CHAIN)
        self.assertEqual(cli.main(["status", str(d / "task.toml")], chain=CHAIN), 0)


if __name__ == "__main__":
    unittest.main()
