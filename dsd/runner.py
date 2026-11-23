"""One CodeBuddy turn: run `codebuddy -p`, falling back down the model chain on timeout/failure."""
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Model:
    name: str
    effort: str | None
    timeout: int  # seconds


@dataclass
class TurnResult:
    ok: bool
    model: str = ""
    text: str = ""
    turns: int = 0
    denials: list = field(default_factory=list)
    fallbacks: list = field(default_factory=list)


def codebuddy_exe() -> list[str]:
    """argv prefix for the CLI. Calls node directly: the npm .cmd shim mangles '(' and '*'."""
    override = os.environ.get("DSD_CODEBUDDY")
    if override:
        return [sys.executable, override] if override.endswith(".py") else [override]
    shim = shutil.which("codebuddy")
    if shim:
        js = Path(shim).parent / "node_modules" / "@tencent-ai" / "codebuddy-code" / "bin" / "codebuddy"
        node = shutil.which("node")
        if js.is_file() and node:
            return [node, str(js)]
        return [shim]
    raise RuntimeError("codebuddy CLI not found on PATH")


def cb_args(model: Model, sid: str, first: bool, tools: list[str], append: str,
            max_turns: int) -> list[str]:
    args = ["-p", "--output-format", "stream-json", "--verbose", "--model", model.name]
    if model.effort:
        args += ["--effort", model.effort]
    args += ["--session-id", sid] if first else ["--resume", sid, "--resume-create-missing"]
    args += ["--permission-mode", "acceptEdits", "--max-turns", str(max_turns)]
    if append:
        args += ["--append-system-prompt", append]
    return args + ["--allowedTools", *tools]


def _kill_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        proc.kill()
    proc.wait()


def _call(argv: list[str], prompt: str, cwd: Path, timeout: int, log: Path) -> tuple[str, dict | None]:
    """-> (problem or '', result event)."""
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as out:  # streamed, so a running turn can be watched
        out.write((json.dumps({"dsd": "call", "argv": argv[-40:], "at": time.time()}) + "\n").encode())
        out.flush()
        start = out.tell()
        proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=out, stderr=subprocess.STDOUT)
        try:
            proc.communicate(prompt.encode("utf-8"), timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            return f"timeout after {timeout}s", None
    with open(log, "rb") as f:
        f.seek(start)
        stdout = f.read().decode("utf-8", errors="replace")
    result = None
    for line in stdout.splitlines():
        if line.startswith("{") and '"type"' in line:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") == "result":
                result = ev
    if result is None:
        tail = " ".join(stdout.split()[-30:])
        return f"exit {proc.returncode}, no result: {tail[:300]}", None
    if result.get("is_error"):
        return f"error result: {str(result.get('result'))[:300]}", result
    return "", result


def run_turn(sid: str, prompt: str, cwd: Path, first: bool, chain: list[Model],
             tools: list[str], append: str, log: Path, max_turns: int = 80) -> TurnResult:
    res = TurnResult(ok=False)
    exe = codebuddy_exe()
    for i, model in enumerate(chain):
        argv = exe + cb_args(model, sid, first and i == 0, tools, append, max_turns)
        problem, ev = _call(argv, prompt, Path(cwd), model.timeout, Path(log))
        if problem:
            res.fallbacks.append(f"{model.name}: {problem}")
            continue
        res.ok, res.model = True, model.name
        res.text = str(ev.get("result") or "")
        res.turns = ev.get("num_turns") or 0
        res.denials = [d.get("tool_name", "?") if isinstance(d, dict) else str(d)
                       for d in ev.get("permission_denials") or []]
        return res
    return res
