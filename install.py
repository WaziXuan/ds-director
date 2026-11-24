"""Install the shared ds-director skill for Claude Code and Codex."""
import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _copy(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_bytes() == source.read_bytes():
            return destination
        shutil.copy2(destination, destination.with_suffix(destination.suffix + ".bak"))
    shutil.copy2(source, destination)
    return destination


def install(claude_home: Path, agents_home: Path, claude: bool = True,
            codex: bool = True) -> list[Path]:
    skill = ROOT / "skill" / "SKILL.md"
    installed = []
    if claude:
        installed.append(_copy(skill, claude_home / "skills" / "ds-director" / "SKILL.md"))
        installed.append(_copy(ROOT / "skill" / "ds.md", claude_home / "commands" / "ds.md"))
    if codex:
        installed.append(_copy(skill, agents_home / "skills" / "ds-director" / "SKILL.md"))
    return installed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--claude", action="store_true", help="install only Claude Code integration")
    ap.add_argument("--codex", action="store_true", help="install only Codex integration")
    ap.add_argument("--claude-home", type=Path,
                    default=Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude"))
    ap.add_argument("--agents-home", type=Path,
                    default=Path(os.environ.get("DSD_AGENTS_HOME") or Path.home() / ".agents"))
    args = ap.parse_args(argv)
    both = not args.claude and not args.codex
    for path in install(args.claude_home, args.agents_home,
                        claude=both or args.claude, codex=both or args.codex):
        print(f"installed: {path}")
    print("Existing files were backed up with a .bak suffix before replacement.")
    if shutil.which("dsd") is None:
        scripts = Path(sys.executable).parent / ("Scripts" if os.name == "nt" else "bin")
        print(f"warning: `dsd` is not on PATH. Add {scripts} to PATH, or run the phases as\n"
              f"         `{sys.executable} -m dsd <command> <task.toml>`, which needs no PATH change.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
