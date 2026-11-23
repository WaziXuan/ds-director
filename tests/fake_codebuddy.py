"""Stand-in for the CodeBuddy CLI in tests.

Each call pops the next step from the JSON plan at $DSD_FAKE_PLAN and logs its argv and
stdin prompt to $DSD_FAKE_LOG. A step may write files (relative to cwd), sleep, or fail.
"""
import json
import os
import sys
import time
from pathlib import Path

plan_path = Path(os.environ["DSD_FAKE_PLAN"])
plan = json.loads(plan_path.read_text(encoding="utf-8"))
step = plan.pop(0) if plan else {}
plan_path.write_text(json.dumps(plan), encoding="utf-8")

argv = sys.argv[1:]
prompt = sys.stdin.buffer.read().decode("utf-8")
with open(os.environ["DSD_FAKE_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": argv, "prompt": prompt}) + "\n")

sid = None
for flag in ("--session-id", "--resume"):
    if flag in argv:
        sid = argv[argv.index(flag) + 1]
if sid:
    d = Path(os.environ["DSD_CB_PROJECTS"]) / "fake-proj"
    d.mkdir(parents=True, exist_ok=True)
    with open(d / f"{sid}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"role": "user", "content": prompt[:50]}) + "\n")

time.sleep(step.get("sleep", 0))
for rel, text in step.get("write", {}).items():
    p = Path.cwd() / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
for rel in step.get("delete", []):
    (Path.cwd() / rel).unlink()

if step.get("crash"):
    print("boom", file=sys.stderr)
    sys.exit(2)
print(json.dumps({"type": "system", "subtype": "init", "session_id": sid}))
print(json.dumps({"type": "result", "subtype": "success", "is_error": bool(step.get("error")),
                  "result": step.get("result", "done"), "session_id": sid,
                  "num_turns": 3, "permission_denials": step.get("denials", [])}))
