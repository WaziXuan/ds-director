"""Tie each CodeBuddy session to the Claude Code or Codex session that directed it.

The CodeBuddy session id starts with the parent's first 8 characters; the full link goes
in a `<sid>.parent.json` sidecar next to the transcript, which session-finder reads.
"""
import json
import os
import re
from pathlib import Path


def projects_root() -> Path:
    return Path(os.environ.get("DSD_CB_PROJECTS") or Path.home() / ".codebuddy" / "projects")


def current_parent() -> str | None:
    """Return the directing session id, with an explicit override for other hosts."""
    return (os.environ.get("DSD_PARENT_SESSION")
            or os.environ.get("CLAUDE_CODE_SESSION_ID")
            or os.environ.get("CODEX_THREAD_ID")
            or os.environ.get("CODEX_SESSION_ID") or None)


def current_parent_source() -> str:
    """session-finder source: cl for Claude Code, cx for Codex."""
    explicit = os.environ.get("DSD_PARENT_SOURCE")
    if explicit in {"cl", "cx"}:
        return explicit
    if os.environ.get("CLAUDE_CODE_SESSION_ID"):
        return "cl"
    if os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SESSION_ID"):
        return "cx"
    return "cl"


def session_id(parent: str | None, job: str, phase: str) -> str:
    job = re.sub(r"[^A-Za-z0-9-]+", "-", job).strip("-")
    return f"ds-{parent[:8] if parent else 'noparent'}-{job}-{phase}"


def write_sidecar(root: Path, sid: str, parent: str | None, agent: str, title: str,
                  source: str = "cl") -> Path | None:
    if not parent:
        return None
    if source not in {"cl", "cx"}:
        raise ValueError("parent source must be 'cl' or 'cx'")
    hits = sorted(Path(root).glob(f"*/{sid}.jsonl"))
    if not hits:
        return None
    p = hits[0].with_name(f"{sid}.parent.json")
    p.write_text(json.dumps({"src": source, "id": parent, "agent": agent, "title": title},
                            ensure_ascii=False), encoding="utf-8")
    return p
