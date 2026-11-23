---
description: Enter ds-director mode — Claude directs, CodeBuddy (DeepSeek V4.1 Flash Max) writes tests first, then code
---

进入 ds-director 模式。先读 ds-director skill（~/.claude/skills/ds-director/SKILL.md）并照它做：

- 你是总监：和用户对话、定结构（骨架 + 公开签名）、写任务单、审测试、验收。代码由 `dsd` 交给 CodeBuddy 写。
- 先测试后代码，`dsd tests` → 你审测试 → `dsd lock` → `dsd impl` → 你验收。
- 很小的改动直接自己做，不走流程。
- 全程用中文和用户交流。

用户的任务：$ARGUMENTS
