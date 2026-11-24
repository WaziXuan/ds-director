"""dsd — Claude Code or Codex directs, CodeBuddy executes, tests first.

  dsd tests  <task.toml> [--feedback TEXT]   write red tests (+ one self-check round)
  dsd lock   <task.toml>                     director approves: freeze tests + public signatures
  dsd impl   <task.toml> [--feedback TEXT]   implement until green, auto-checks, one review
  dsd status <task.toml>                     sessions and last outcome

Exit codes: 0 ok, 2 usage/phase error, 3 needs director, 4 every model failed.
"""
import argparse
import json
import sys
from dataclasses import asdict

from .pipeline import Job, PhaseError

EXIT = {"ok": 0, "needs_director": 3, "model_failed": 4}


def _print_outcome(phase: str, out) -> None:
    print(f"## dsd {phase}: {out.status}")
    if out.files:
        print("files: " + ", ".join(out.files))
    for p in out.problems:
        print(f"PROBLEM: {p}")
    for n in out.notes:
        print(f"note: {n}")
    if out.review:
        print(f"\n### review\n{out.review.strip()}")
    print(f"\n### executor's last reply\n{out.reply.strip()[:4000]}")
    print(f"\n### test output (tail)\n{out.test_output}")


def _run_phase(job: Job, phase: str, feedback) -> int:
    out = job.run_tests_phase(feedback) if phase == "tests" else job.run_impl_phase(feedback)
    job.dir.mkdir(parents=True, exist_ok=True)
    (job.dir / "last.json").write_text(json.dumps({"phase": phase, **asdict(out)}, ensure_ascii=False,
                                                  indent=1), encoding="utf-8")
    _print_outcome(phase, out)
    return EXIT[out.status]


def _status(job: Job) -> int:
    print(f"job {job.id} in {job.root}")
    parent = job.state.get("parent")
    source = job.state.get("parent_src", "cl")
    print(f"parent session: {source}|{parent}" if parent else "parent session: None")
    for phase, sid in job.state.get("sessions", {}).items():
        print(f"  {phase:7s} cb|{sid}")
    print(f"locked: {'yes' if 'locked' in job.state else 'no'}")
    last = job.dir / "last.json"
    if last.exists():
        d = json.loads(last.read_text(encoding="utf-8"))
        print(f"last: {d['phase']} -> {d['status']}")
    return 0


def main(argv=None, chain=None) -> int:
    ap = argparse.ArgumentParser(prog="dsd", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["tests", "lock", "impl", "status"])
    ap.add_argument("task")
    ap.add_argument("--feedback")
    a = ap.parse_args(argv)
    job = Job.load(a.task, chain=chain)
    try:
        if a.command == "lock":
            locked = job.lock()
            print(f"locked {len(locked['tests'])} test file(s): {', '.join(locked['tests'])}")
            print(f"locked signatures in: {', '.join(locked['signatures']) or '(none)'}")
            return 0
        if a.command == "status":
            return _status(job)
        return _run_phase(job, a.command, a.feedback)
    except PhaseError as e:
        print(f"dsd: {e}", file=sys.stderr)
        return 2
