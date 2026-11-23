import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from dsd import checks


def git_repo() -> Path:
    d = Path(tempfile.mkdtemp())
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                    "--allow-empty", "-qm", "init"], cwd=d, check=True)
    return d


class Hashes(unittest.TestCase):
    def test_same_content_same_hash_and_missing_file_is_none(self):
        d = Path(tempfile.mkdtemp())
        (d / "a.py").write_text("x = 1\n", encoding="utf-8")
        h = checks.file_hashes(d, ["a.py", "gone.py"])
        self.assertEqual(len(h["a.py"]), 64)
        self.assertIsNone(h["gone.py"])
        self.assertEqual(h, checks.file_hashes(d, ["a.py", "gone.py"]))

    def test_hash_drift_lists_changed_and_deleted_files(self):
        before = {"t/a.py": "1", "t/b.py": "2", "t/c.py": "3"}
        after = {"t/a.py": "1", "t/b.py": "X", "t/c.py": None}
        self.assertEqual(checks.hash_drift(before, after), ["t/b.py", "t/c.py"])


class ChangedFiles(unittest.TestCase):
    def test_reports_modified_and_untracked_files_with_forward_slashes(self):
        d = git_repo()
        (d / "pkg").mkdir()
        (d / "pkg" / "new.py").write_text("", encoding="utf-8")
        self.assertEqual(checks.changed_files(d), ["pkg/new.py"])

    def test_outside_allowed_uses_glob_patterns(self):
        changed = ["tests/test_a.py", "src/a.py", "tests/sub/test_b.py"]
        self.assertEqual(checks.outside_allowed(changed, ["tests/**"]), ["src/a.py"])
        self.assertEqual(checks.outside_allowed(changed, ["src/a.py", "tests/**"]), [])


class Signatures(unittest.TestCase):
    SRC = textwrap.dedent('''
        def parse(text: str, *, strict: bool = False) -> dict:
            raise NotImplementedError
        def _helper(x):
            return x
        class Store:
            def get(self, key: str) -> str | None:
                raise NotImplementedError
            def _cache(self):
                pass
    ''')

    def test_only_public_names_are_collected(self):
        sigs = checks.python_signatures(self.SRC)
        self.assertEqual(set(sigs), {"parse", "Store", "Store.get"})
        self.assertIn("strict", sigs["parse"])

    def test_drift_flags_changed_removed_and_added_public_names(self):
        before = checks.python_signatures(self.SRC)
        after_src = self.SRC.replace("strict: bool = False", "strict: bool = True") \
                            .replace("def get(self", "def fetch(self")
        after_src += "\ndef extra():\n    pass\n"
        drift = checks.signature_drift(before, checks.python_signatures(after_src))
        self.assertEqual(sorted(d.split(":")[0] for d in drift),
                         ["added", "added", "changed", "removed"])
        joined = "\n".join(drift)
        self.assertIn("parse", joined)
        self.assertIn("Store.get", joined)
        self.assertIn("Store.fetch", joined)
        self.assertIn("extra", joined)

    def test_private_helpers_may_change_freely(self):
        before = checks.python_signatures(self.SRC)
        after = checks.python_signatures(self.SRC + "\ndef _new(a, b):\n    pass\n")
        self.assertEqual(checks.signature_drift(before, after), [])


class Size(unittest.TestCase):
    def test_long_function_and_long_file_are_reported(self):
        body = "\n".join(f"    x{i} = {i}" for i in range(60))
        src = f"def big():\n{body}\n\ndef small():\n    return 1\n"
        v = checks.size_violations({"m.py": src}, func_max=50, file_max=40)
        self.assertEqual(len(v), 2)
        self.assertTrue(any("big" in x and "m.py" in x for x in v))
        self.assertTrue(any("file" in x for x in v))

    def test_non_python_files_only_get_the_file_limit(self):
        self.assertEqual(checks.size_violations({"a.js": "x\n" * 10}, 5, 400), [])
        self.assertEqual(len(checks.size_violations({"a.js": "x\n" * 10}, 5, 9)), 1)


class Duplicates(unittest.TestCase):
    BLOCK = "".join(f"    total = total + values[{i}] * weight\n" for i in range(7))

    def test_same_block_in_two_files_is_reported_once(self):
        a = "def f(values, weight):\n    total = 0\n" + self.BLOCK
        b = "def g(values, weight):\n    total = 1\n" + self.BLOCK
        dups = checks.duplicate_blocks({"a.py": a, "b.py": b}, window=6)
        self.assertEqual(len(dups), 1)
        self.assertIn("a.py", dups[0])
        self.assertIn("b.py", dups[0])

    def test_blank_lines_and_brackets_do_not_count_as_duplicates(self):
        filler = "\n\n)\n]\n}\n\n" * 5
        self.assertEqual(checks.duplicate_blocks({"a.py": filler, "b.py": filler}, 6), [])


class DeadCode(unittest.TestCase):
    def test_commented_out_code_and_debug_calls_are_found(self):
        src = textwrap.dedent('''
            def f(x):
                # old = compute(x)
                # return old * 2
                breakpoint()
                return x
        ''')
        found = checks.dead_code({"m.py": src})
        self.assertTrue(any("commented-out" in f for f in found))
        self.assertTrue(any("breakpoint" in f for f in found))

    def test_prose_comments_are_fine(self):
        src = "# Parse the header first, then the body.\n# See RFC 822 for details\nx = 1\n"
        self.assertEqual(checks.dead_code({"m.py": src}), [])


class RedCheck(unittest.TestCase):
    def test_not_implemented_failures_are_a_valid_red(self):
        out = "FAILED (errors=3)\nNotImplementedError"
        self.assertEqual(checks.red_problem(1, out), None)

    def test_passing_tests_are_not_red(self):
        self.assertIn("pass", checks.red_problem(0, "OK"))

    def test_syntax_and_import_errors_are_not_a_valid_red(self):
        self.assertIsNotNone(checks.red_problem(1, "SyntaxError: invalid syntax"))
        self.assertIsNotNone(checks.red_problem(1, "ModuleNotFoundError: No module named 'x'"))
        self.assertIsNotNone(checks.red_problem(1, "ImportError: cannot import name 'parse'"))

    def test_no_tests_at_all_is_not_red(self):
        self.assertIsNotNone(checks.red_problem(5, "Ran 0 tests in 0.000s\n\nNO TESTS RAN"))
        self.assertIsNotNone(checks.red_problem(5, "collected 0 items\nno tests ran in 0.01s"))

    def test_assertion_failures_are_a_valid_red_when_changing_existing_code(self):
        self.assertIsNone(checks.red_problem(1, "AssertionError: 1 != 2\nFAILED (failures=1)"))


class Snapshot(unittest.TestCase):
    def test_changed_between_finds_edits_new_and_deleted_files_but_ignores_dsd_dir(self):
        d = git_repo()
        (d / "keep.py").write_text("a", encoding="utf-8")
        (d / "edit.py").write_text("a", encoding="utf-8")
        (d / "gone.py").write_text("a", encoding="utf-8")
        before = checks.tree_snapshot(d)
        (d / "edit.py").write_text("b", encoding="utf-8")
        (d / "gone.py").unlink()
        (d / "new.py").write_text("n", encoding="utf-8")
        (d / ".dsd").mkdir()
        (d / ".dsd" / "state.json").write_text("{}", encoding="utf-8")
        (d / "__pycache__").mkdir()
        (d / "__pycache__" / "m.cpython-312.pyc").write_bytes(b"x")
        (d / "node_modules").mkdir()
        (d / "node_modules" / "x.js").write_text("x", encoding="utf-8")
        self.assertEqual(checks.changed_between(before, checks.tree_snapshot(d)),
                         ["edit.py", "gone.py", "new.py"])


if __name__ == "__main__":
    unittest.main()
