"""Tie each CodeBuddy session to the Claude Code session that directed it.

The CodeBuddy session id itself starts with the parent's first 8 characters; the full link
goes in a `<sid>.parent.json` sidecar next to the transcript, which session-finder reads.
"""
import json
import os
import re
from pathlib import Path


def projects_root() -> Path:
    return Path(os.environ.get("DSD_CB_PROJECTS") or Path.home() / ".codebuddy" / "projects")


def current_parent() -> str | None:
    return os.environ.get("CLAUDE_CODE_SESSION_ID") or None


def session_id(parent: str | None, job: str, phase: str) -> str:
    job = re.sub(r"[^A-Za-z0-9-]+", "-", job).strip("-")
    return f"ds-{parent[:8] if parent else 'noparent'}-{job}-{phase}"


def write_sidecar(root: Path, sid: str, parent: str | None, agent: str, title: str) -> Path | None:
    if not parent:
        return None
    hits = sorted(Path(root).glob(f"*/{sid}.jsonl"))
    if not hits:
        return None
    p = hits[0].with_name(f"{sid}.parent.json")
    p.write_text(json.dumps({"src": "cl", "id": parent, "agent": agent, "title": title},
                            ensure_ascii=False), encoding="utf-8")
    return p
