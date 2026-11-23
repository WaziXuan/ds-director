---
name: ds-director
description: Director mode — Claude plans, writes the skeleton and reviews; CodeBuddy CLI running DeepSeek V4.1 Flash Max writes tests first, then the implementation, through the `dsd` tool (D:\Sandbox\ds-director). Use when the user types /ds, says "ds 模式", "让 DeepSeek 写", "用 codebuddy 执行", or asks to delegate a coding task to CodeBuddy/DeepSeek. Not the default way to code.
---

# ds-director

You are the director. You talk to the user, decide structure, review and accept. CodeBuddy
(DeepSeek V4.1 Flash, effort max; fallback hy4flash → hy4std) writes the code. Tests always
come before code, and the tool enforces it.

```bash
DSD="python D:/Sandbox/ds-director/dsd.py"
$DSD tests  <task.toml> [--feedback "..."]   # phase 1: red tests + one self-check round
$DSD lock   <task.toml>                      # you approve: tests + public signatures frozen
$DSD impl   <task.toml> [--feedback "..."]   # phase 2: green + auto checks + one review session
$DSD status <task.toml>
```
Exit: 0 ok · 2 phase error · 3 needs director · 4 every model failed. Run phases with
`run_in_background: true` (a phase takes minutes); you are notified when it ends.

## When it is worth it

Roughly >100 lines or anything that will need debugging. For a few-line change, just do it
yourself — the fixed overhead (skeleton, two phases, review) costs more than it saves.

## Step 0 — you write the structure (before any test)

1. The work dir must be a git repo with a clean-ish tree. For parallel jobs give each its own
   `git worktree` and split along file boundaries so merges don't conflict.
2. Write the skeleton yourself: file layout, every **public** function/class signature with a
   one-line docstring, body `raise NotImplementedError`. Private helpers are the executor's.
   Public signatures are locked at `lock`; anything public the executor adds or changes is sent back.
3. Write the task file (keep them in `D:/Sandbox/ds-director/jobs/` or the project):

```toml
id = "j1"                       # becomes the CodeBuddy session id ds-<parent8>-j1-<phase>
workdir = "D:/path/to/repo"     # default: the task file's folder
test_cmd = "python -m unittest discover -s tests -t ."
test_paths = ["tests/**"]       # what phase 1 may touch
src_paths = ["pkg/core.py"]     # what phase 2 may touch
goal = "..."                    # one paragraph
structure = "..."               # layout, dependency direction, what is locked, test harness notes
behavior = "..."                # numbered list: normal cases, edges, errors — the acceptance spec
[limits]                        # defaults: func_max 50, file_max 400, dup_window 6, max_fix_rounds 3
```

The behavior list is the contract. Vague behavior → vague tests → wrong code that passes.

## Step 1 — tests

Run `tests`. Then **read the test files yourself** (the executor self-checked, but its blind
spots match its own tests). Check every behavior item is covered, edges and errors included,
assertions are tight, nothing depends on internals. Problems → `tests --feedback "..."`
(same session continues). Satisfied → `lock`.

## Step 2 — implementation

Run `impl`. The tool loops on its own (zero Claude tokens): restores tampered tests, rejects
files outside `src_paths`, signature drift, long functions/files, duplicate blocks, dead code,
red tests — up to `max_fix_rounds`, then a fresh read-only review session, whose
`VERDICT: CHANGES` goes back to the implementation session once.

On exit 0: look at `git diff`, rerun `test_cmd` yourself, check the review section and the
executor's reply for `STRUCTURE-REQUEST:` / `TEST-DISPUTE:`. Decide; if the skeleton or a
test really is wrong, it is your call — fix the skeleton or start a new job id for new tests.
On exit 3: read PROBLEM lines; give `--feedback`, take over, or split the task. Don't loop
more than twice on the same failure.

## Things to keep cheap

- Read the summary `dsd` prints, not the logs. Logs are in `<workdir>/.dsd/<id>/<phase>.log`
  (stream-json); only `grep` them for a specific question.
- Never paste whole files into `--feedback`; point at file:line.

## Sessions

Each CodeBuddy session gets a `<sid>.parent.json` sidecar naming this Claude session
(`CLAUDE_CODE_SESSION_ID`). session-finder lists them as sub-agents under it
(`show <this session>`; `list --subagents`).
