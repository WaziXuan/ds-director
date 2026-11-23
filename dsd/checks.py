"""Mechanical gates run after every CodeBuddy turn: test lock, structure lock, anti-mess rules.

All functions are pure or only read the work tree, so the pipeline can call them freely.
"""
import ast
import fnmatch
import hashlib
import re
import subprocess
from pathlib import Path


def file_hashes(root: Path, paths: list[str]) -> dict:
    out = {}
    for p in paths:
        f = Path(root) / p
        out[p] = hashlib.sha256(f.read_bytes()).hexdigest() if f.is_file() else None
    return out


def hash_drift(before: dict, after: dict) -> list[str]:
    return sorted(p for p in before if after.get(p) != before[p])


def changed_files(root: Path) -> list[str]:
    """Modified, added and untracked files relative to HEAD, '/'-separated."""
    r = subprocess.run(["git", "status", "--porcelain", "-uall", "-z"], cwd=root,
                       capture_output=True, text=True, encoding="utf-8", check=True)
    files = []
    entries = r.stdout.split("\0")
    i = 0
    while i < len(entries):
        e = entries[i]
        if len(e) > 3:
            files.append(e[3:].replace("\\", "/"))
            if e[0] in "RC":
                i += 1  # rename: the next entry is the old name
        i += 1
    return sorted(files)


_GENERATED = re.compile(r"(^|/)(\.dsd|__pycache__|\.pytest_cache|node_modules|\.mypy_cache)/|\.py[co]$")


def tree_snapshot(root: Path) -> dict:
    """Hash of every tracked or untracked-but-not-ignored file, minus dsd's folder and caches."""
    r = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=root,
                       capture_output=True, text=True, encoding="utf-8", check=True)
    paths = [p for p in r.stdout.split("\0") if p and not _GENERATED.search(p)]
    return {p: h for p, h in file_hashes(root, paths).items() if h}


def changed_between(before: dict, after: dict) -> list[str]:
    return sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))


def outside_allowed(changed: list[str], allowed: list[str]) -> list[str]:
    return [f for f in changed if not any(fnmatch.fnmatch(f, pat) for pat in allowed)]


def python_signatures(source: str) -> dict:
    """Public top-level functions, classes and their public methods -> signature text."""
    sigs = {}

    def fn_sig(node) -> str:
        ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
        return f"({ast.unparse(node.args)}){ret}"

    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            sigs[node.name] = fn_sig(node)
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            sigs[node.name] = "(" + ", ".join(ast.unparse(b) for b in node.bases) + ")"
            for m in node.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                        (not m.name.startswith("_") or m.name == "__init__"):
                    sigs[f"{node.name}.{m.name}"] = fn_sig(m)
    return sigs


def signature_drift(before: dict, after: dict) -> list[str]:
    out = []
    for name in sorted(set(before) | set(after)):
        if name not in after:
            out.append(f"removed: {name}{before[name]}")
        elif name not in before:
            out.append(f"added: {name}{after[name]}")
        elif before[name] != after[name]:
            out.append(f"changed: {name}{before[name]} -> {after[name]}")
    return out


def size_violations(texts: dict, func_max: int, file_max: int) -> list[str]:
    out = []
    for path, text in texts.items():
        n = len(text.splitlines())
        if n > file_max:
            out.append(f"{path}: file has {n} lines (limit {file_max})")
        if not path.endswith(".py"):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                length = node.end_lineno - node.lineno + 1
                if length > func_max:
                    out.append(f"{path}:{node.lineno}: function {node.name} has {length} lines (limit {func_max})")
    return out


_TRIVIAL = re.compile(r"^[\s()\[\]{},;:]*$|^(pass|return|else:|try:|finally:|\"\"\"|''')$")


def duplicate_blocks(texts: dict, window: int = 6) -> list[str]:
    """Runs of `window` identical meaningful lines appearing in two places."""
    seen: dict = {}
    found, reported = [], set()
    for path, text in texts.items():
        lines = [(i + 1, l.strip()) for i, l in enumerate(text.splitlines())]
        lines = [(n, l) for n, l in lines if l and not _TRIVIAL.match(l) and not l.startswith("#")]
        for k in range(len(lines) - window + 1):
            key = "\n".join(l for _, l in lines[k:k + window])
            here = (path, lines[k][0])
            first = seen.setdefault(key, here)
            if first != here and (first[0], here[0]) not in reported \
                    and not (first[0] == here[0] and abs(first[1] - here[1]) < window):
                reported.add((first[0], here[0]))
                found.append(f"{first[0]}:{first[1]} and {here[0]}:{here[1]}: "
                             f"{window}+ identical lines")
    return found


_DEBUG = re.compile(r"^\s*(breakpoint\(\)|import pdb|pdb\.set_trace\(\)|debugger;|console\.log\()")


def _looks_like_code(comment: str) -> bool:
    c = comment.strip()
    if not c or c[-1] in ".!?" or " " not in c and "(" not in c and "=" not in c:
        return False
    try:
        ast.parse(c)
    except SyntaxError:
        return False
    return bool(re.search(r"[=()\[\]]|^(return|import|from|if|for|while|def|class)\b", c))


def dead_code(texts: dict) -> list[str]:
    out = []
    for path, text in texts.items():
        run = 0
        for n, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            if _DEBUG.match(line):
                out.append(f"{path}:{n}: debug call left in: {s}")
            if s.startswith("#") and _looks_like_code(s[1:]):
                run += 1
                if run == 2:
                    out.append(f"{path}:{n - 1}: commented-out code")
            else:
                run = 0
    return out


_BROKEN = re.compile(r"SyntaxError|IndentationError|ModuleNotFoundError|ImportError|"
                     r"NameError: name '\w+' is not defined|error: unrecognized arguments|"
                     r"Ran 0 tests|NO TESTS RAN|no tests ran|collected 0 items")


def red_problem(returncode: int, output: str) -> str | None:
    """None if a failing run is a proper 'not implemented yet' red; else why it is not."""
    if returncode == 0:
        return "tests pass before the implementation exists"
    m = _BROKEN.search(output)
    if m:
        return f"tests are broken, not red: {m.group(0)}"
    return None
