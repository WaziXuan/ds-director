"""The two-phase TDD job: tests (red) -> director lock -> implementation (green) -> review."""
import fnmatch
import json
import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from string import Template

from . import checks, links, runner

PROMPTS = Path(__file__).resolve().parent / "prompts"
DEFAULT_CHAIN = [runner.Model("deepseek-v4.1-flash", "max", 600),
                 runner.Model("hy4flash", None, 300), runner.Model("hy4std", None, 300)]
GIT_READ = ["git diff", "git status", "git log", "git show"]
EDIT_TOOLS = ["Read", "Glob", "Grep", "Edit", "MultiEdit", "Write", "Task", "Agent"]
READ_TOOLS = ["Read", "Glob", "Grep"]


def shell_rules(prefixes: list) -> list:
    """CodeBuddy on Windows runs commands through PowerShell or Bash; allow both."""
    return [f"{shell}({p}:*)" for p in prefixes for shell in ("Bash", "PowerShell")]
LIMITS = {"func_max": 50, "file_max": 400, "dup_window": 6, "max_fix_rounds": 3, "max_turns": 80}


class PhaseError(Exception):
    pass


class Escalation(Exception):
    """The executor raised TEST-DISPUTE / STRUCTURE-REQUEST: only the director may decide,
    so the fix loop must stop rather than push it to satisfy the disputed contract."""

    def __init__(self, phase: str, reply: str):
        super().__init__(reply)
        self.phase, self.reply = phase, reply


_ESCALATION = re.compile(r"^[\s>*-]*(TEST-DISPUTE|STRUCTURE-REQUEST)\**\s*[:：]")


def escalation_lines(reply: str) -> list:
    """Lines that open with a marker ("**TEST-DISPUTE**: ..."), not ones merely naming it."""
    return [l.strip() for l in reply.splitlines() if _ESCALATION.match(l)]


@dataclass
class Outcome:
    status: str  # ok | needs_director | model_failed
    problems: list = field(default_factory=list)
    files: list = field(default_factory=list)
    test_output: str = ""
    reply: str = ""
    review: str = ""
    notes: list = field(default_factory=list)


def prompt(name: str, **values) -> str:
    return Template((PROMPTS / f"{name}.md").read_text(encoding="utf-8")).safe_substitute(values)


def _tail(text: str, n: int = 40) -> str:
    return "\n".join(text.strip().splitlines()[-n:])


class Job:
    def __init__(self, task_path: Path, task: dict, chain: list):
        self.task, self.chain = task, chain
        self.id = task["id"]
        self.root = Path(task.get("workdir") or task_path.parent).resolve()
        self.dir = self.root / ".dsd" / self.id
        self.limits = {**LIMITS, **task.get("limits", {})}
        self.state_file = self.dir / "state.json"
        self.state = json.loads(self.state_file.read_text(encoding="utf-8")) \
            if self.state_file.exists() else {"sessions": {}}
        self.notes: list = []
        prefix = task.get("test_tool_prefix") or " ".join(task["test_cmd"].split()[:3])
        self.edit_tools = EDIT_TOOLS + shell_rules([prefix] + GIT_READ)
        self.read_tools = READ_TOOLS + shell_rules(GIT_READ)

    @classmethod
    def load(cls, task_path, chain=None) -> "Job":
        task_path = Path(task_path)
        with open(task_path, "rb") as f:
            return cls(task_path, tomllib.load(f), chain or DEFAULT_CHAIN)

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        exclude = self.root / ".git" / "info" / "exclude"
        if exclude.parent.is_dir() and ".dsd/" not in (exclude.read_text() if exclude.exists() else ""):
            with open(exclude, "a", encoding="utf-8") as f:
                f.write("\n.dsd/\n")
        self.state_file.write_text(json.dumps(self.state, ensure_ascii=False, indent=1), encoding="utf-8")

    # --- plumbing -------------------------------------------------------------------

    def _values(self) -> dict:
        t = self.task
        return {"goal": t.get("goal", ""), "behavior": t.get("behavior", "（见目标）"),
                "structure": t.get("structure", "（无额外说明）"), "test_cmd": t["test_cmd"],
                "test_paths": ", ".join(t["test_paths"]), "src_paths": ", ".join(t["src_paths"]),
                **{k: str(v) for k, v in self.limits.items()}}

    def _turn(self, phase: str, text: str, tools: list) -> runner.TurnResult:
        parent = self.state.setdefault("parent", links.current_parent())
        parent_src = self.state.setdefault("parent_src", links.current_parent_source())
        sid = self.state["sessions"].get(phase)
        first = sid is None
        if first:
            sid = self.state["sessions"][phase] = links.session_id(parent, self.id, phase)
            self.save()
        res = runner.run_turn(sid, text, self.root, first=first, chain=self.chain, tools=tools,
                              append=prompt("rules", **self._values()), log=self.dir / f"{phase}.log",
                              max_turns=self.limits["max_turns"])
        title = f"{self.id} · {phase} · {self.task.get('goal', '').strip().splitlines()[0][:40]}"
        links.write_sidecar(links.projects_root(), sid, parent, f"ds:{phase}", title,
                            source=parent_src)
        self.notes += [f"{phase}: fell back from {f}" for f in res.fallbacks]
        if res.denials:
            self.notes.append(f"{phase}: permission denied for {', '.join(res.denials)}")
        if not res.ok:
            raise PhaseError(f"every model failed on {phase}: " + "; ".join(res.fallbacks))
        if phase != "review" and escalation_lines(res.text):
            raise Escalation(phase, res.text)
        return res

    def _run_tests(self) -> tuple[int, str]:
        r = subprocess.run(self.task["test_cmd"], cwd=self.root, shell=True, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=900)
        return r.returncode, _tail(r.stdout + "\n" + r.stderr)

    def _fix_loop(self, phase: str, check, tools: list) -> list:
        rounds = self.limits["max_fix_rounds"]
        for n in range(1, rounds + 1):
            problems = check()
            if not problems:
                return []
            self._turn(phase, prompt("fix", round=n, max=rounds, test_cmd=self.task["test_cmd"],
                                     problems="\n".join(f"- {p}" for p in problems)), tools)
        return check()

    def _matching(self, patterns_key: str) -> list:
        snap = checks.tree_snapshot(self.root)
        return sorted(p for p in snap if any(fnmatch.fnmatch(p, g) for g in self.task[patterns_key]))

    def _escalated(self, e: Escalation, patterns_key: str) -> Outcome:
        self.save()
        return self._outcome(escalation_lines(e.reply), self._changed(patterns_key), e.reply)

    def _changed(self, patterns_key: str) -> list:
        if patterns_key == "src_paths" and "impl_base" in self.state:
            return checks.changed_between(self.state["impl_base"], checks.tree_snapshot(self.root))
        return self._matching(patterns_key)

    def _outcome(self, problems: list, files: list, reply: str, review: str = "") -> Outcome:
        _, out = self._run_tests()
        return Outcome("needs_director" if problems else "ok", problems, files, out, reply,
                       review, self.notes)

    # --- phase 1: tests ---------------------------------------------------------------

    def _check_tests(self) -> list:
        changed = checks.changed_between(self.state["tests_base"], checks.tree_snapshot(self.root))
        problems = [f"{p}: outside this phase's files ({', '.join(self.task['test_paths'])}); "
                    f"put it back" for p in checks.outside_allowed(changed, self.task["test_paths"])]
        rc, out = self._run_tests()
        red = checks.red_problem(rc, out)
        if red:
            problems.append(f"{red}\n  test output (tail):\n{_tail(out, 15)}")
        return problems

    def run_tests_phase(self, feedback: str | None = None) -> Outcome:
        try:
            return self._tests_phase(feedback)
        except Escalation as e:
            return self._escalated(e, "test_paths")
        except PhaseError as e:
            return Outcome("model_failed", [str(e)], notes=self.notes)

    def _tests_phase(self, feedback):
        if "locked" in self.state:
            raise PhaseError("tests are locked; start a new job to change them")
        self.state.setdefault("tests_base", checks.tree_snapshot(self.root))
        fresh = "tests" not in self.state["sessions"]
        text = prompt("tests", **self._values()) if fresh else f"总监的意见：\n{feedback or '请继续。'}"
        res = self._turn("tests", text, self.edit_tools)
        problems = self._fix_loop("tests", self._check_tests, self.edit_tools)
        if not problems:
            res = self._turn("tests", prompt("selfcheck_tests"), self.edit_tools)
            problems = self._fix_loop("tests", self._check_tests, self.edit_tools)
        self.save()
        return self._outcome(problems, self._matching("test_paths"), res.text)

    # --- director lock ----------------------------------------------------------------

    def lock(self) -> dict:
        locked_dir = self.dir / "locked"
        tests = self._matching("test_paths")
        for p in tests:
            (locked_dir / p).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.root / p, locked_dir / p)
        sigs = {p: checks.python_signatures((self.root / p).read_text(encoding="utf-8"))
                for p in self._matching("src_paths") if p.endswith(".py")}
        self.state["locked"] = {"tests": checks.file_hashes(self.root, tests), "signatures": sigs}
        self.state["impl_base"] = checks.tree_snapshot(self.root)
        self.save()
        return self.state["locked"]

    # --- phase 2: implementation ------------------------------------------------------

    def _restore_tests(self) -> list:
        locked = self.state["locked"]["tests"]
        drift = checks.hash_drift(locked, checks.file_hashes(self.root, list(locked)))
        for p in drift:
            shutil.copyfile(self.dir / "locked" / p, self.root / p)
        return [f"{p}: locked test was modified — restored. Tests are read-only; "
                f"use TEST-DISPUTE if you think one is wrong" for p in drift]

    def _src_texts(self, changed: list) -> dict:
        return {p: (self.root / p).read_text(encoding="utf-8", errors="replace")
                for p in changed if (self.root / p).is_file()}

    def _check_impl(self) -> list:
        problems = self._restore_tests()
        changed = checks.changed_between(self.state["impl_base"], checks.tree_snapshot(self.root))
        problems += [f"{p}: outside this phase's files ({', '.join(self.task['src_paths'])}); put it back"
                     for p in checks.outside_allowed(changed, self.task["src_paths"])]
        texts = self._src_texts([p for p in changed if p not in problems])
        for p, before in self.state["locked"]["signatures"].items():
            if p in texts:
                try:
                    after = checks.python_signatures(texts[p])
                except SyntaxError as e:
                    problems.append(f"{p}: syntax error: {e}")
                    continue
                problems += [f"{p}: public signature locked — {d}" for d in checks.signature_drift(before, after)]
        lim = self.limits
        problems += checks.size_violations(texts, lim["func_max"], lim["file_max"])
        problems += checks.duplicate_blocks(texts, lim["dup_window"])
        problems += checks.dead_code(texts)
        rc, out = self._run_tests()
        if rc != 0:
            problems.append(f"tests are not all passing:\n{_tail(out, 25)}")
        return problems

    def _diff(self, files: list) -> str:
        parts = []
        for p in files:
            tracked = subprocess.run(["git", "ls-files", "--error-unmatch", p], cwd=self.root,
                                     capture_output=True).returncode == 0
            if tracked:
                parts.append(subprocess.run(["git", "diff", "HEAD", "--", p], cwd=self.root, capture_output=True,
                                            text=True, encoding="utf-8", errors="replace").stdout)
            else:
                body = (self.root / p).read_text(encoding="utf-8", errors="replace")
                parts.append(f"+++ new file {p}\n" + "".join(f"+{l}\n" for l in body.splitlines()))
        return "\n".join(parts)[:60000]

    def _review(self, files: list) -> str:
        text = prompt("review", **self._values(), files="\n".join(files), diff=self._diff(files))
        return self._turn("review", text, self.read_tools).text

    def run_impl_phase(self, feedback: str | None = None) -> Outcome:
        if "locked" not in self.state:
            raise PhaseError("tests are not locked yet: run the tests phase and `lock` first")
        try:
            return self._impl_phase(feedback)
        except Escalation as e:
            return self._escalated(e, "src_paths")
        except PhaseError as e:
            return Outcome("model_failed", [str(e)], notes=self.notes)

    def _impl_phase(self, feedback):
        fresh = "impl" not in self.state["sessions"]
        locked = self.state["locked"]
        text = prompt("impl", **self._values(), test_files=", ".join(locked["tests"]),
                      signatures=json.dumps(locked["signatures"], ensure_ascii=False)) \
            if fresh else f"总监的意见：\n{feedback or '请继续。'}"
        res = self._turn("impl", text, self.edit_tools)
        problems = self._fix_loop("impl", self._check_impl, self.edit_tools)
        changed = self._changed("src_paths")
        review = ""
        if not problems and "review" not in self.state["sessions"]:
            review = self._review(changed)
            if "VERDICT: CHANGES" in review:
                res = self._turn("impl", "审查者的意见（不同意的条目请说明理由，不必照改）：\n" + review, self.edit_tools)
                problems = self._fix_loop("impl", self._check_impl, self.edit_tools)
        self.save()
        return self._outcome(problems, changed, res.text, review)
