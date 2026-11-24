# ds-director

Claude Code 或 Codex 当总监，CodeBuddy CLI（DeepSeek）当执行者：总监先定骨架和公开接口，执行者先写红测试，总监审测试并锁定，再让执行者实现、自动检查和独立审查。适合较大、可用自动测试验收的改动；小改动不必走这套流程。

## 安装

前置条件：Python 3.11+、git、已安装并登录 CodeBuddy CLI。

```bash
git clone https://github.com/WaziXuan/ds-director.git
cd ds-director
python -m pip install -e .
python install.py
```

安装器默认同时安装：

- Claude Code：`~/.claude/skills/ds-director/SKILL.md` 和 `~/.claude/commands/ds.md`
- Codex：`~/.agents/skills/ds-director/SKILL.md`

已有文件在替换前会保存为同目录的 `.bak`。也可执行 `python install.py --claude` 或 `python install.py --codex` 只装一端。

## 怎么用

- Claude Code：新开或重启会话，输入 `/ds 你的任务`。
- Codex：输入 `$ds-director 你的任务`，或通过 `/skills` 选择它；也可用「ds 模式」自然语言触发。

总监在目标项目里按 `examples/task.toml` 写任务单，核心命令是：

```bash
dsd tests task.toml
dsd lock task.toml
dsd impl task.toml
dsd status task.toml
```

退出码：0 成功；2 阶段/用法错误；3 需要总监裁决；4 所有执行模型失败。状态、锁定的测试和流式日志位于目标项目的 `.dsd/<任务id>/`，该目录会自动加入 git 的本地排除规则。

## 怎么看运行状态

```bash
dsd status task.toml
```

日志在 `<目标项目>/.dsd/<任务id>/<phase>.log`。Windows 可实时查看执行者发言和工具调用：

```powershell
pwsh ./watch.ps1 <目标项目>/.dsd/<任务id>/tests.log
```

不给日志路径时，脚本从当前目录查找最新的 `.dsd` 日志。`Ctrl+C` 只停止查看，不停止任务。

自测与安装检查：

```bash
python -m unittest discover -s tests
dsd --help
codebuddy --version
python install.py --claude-home ./tmp/claude --agents-home ./tmp/agents
```

最后一条安装到当前目录的临时目录，用于验证，不改真实客户端配置。

## 会话关联与环境变量

Claude Code 自动读取 `CLAUDE_CODE_SESSION_ID`；Codex 在客户端提供时读取 `CODEX_THREAD_ID` 或 `CODEX_SESSION_ID`。session-finder 通过 sidecar 把 CodeBuddy 会话挂到 `cl` 或 `cx` 父会话下。

可选覆盖：`DSD_CODEBUDDY`（CodeBuddy 入口）、`DSD_CB_PROJECTS`（会话目录）、`DSD_PARENT_SESSION` 和 `DSD_PARENT_SOURCE=cl|cx`（父会话）。不要在任务单、日志或提交里写入 API key。

## 怎么回滚

1. 执行 `python -m pip uninstall ds-director` 移除 `dsd` 命令。
2. 删除上面「安装」列出的三个已复制文件；若安装前存在 `.bak`，先把对应备份恢复回去。
3. 删除目标项目的 `.dsd/<任务id>/` 只会清除该任务的运行状态和日志，不影响源码；已锁定的测试副本也在其中，删除前先确认不再需要。
4. 源码回退用普通 git 操作；不要把整个目标项目重置到 ds-director 的提交。

## 边界

- 公开签名锁目前只理解 Python；其他语言仍受文件范围、行数、重复代码和测试检查。
- 并行任务需要总监为每个任务准备独立 git worktree。
- 执行者仍需要本机可用的 CodeBuddy CLI 和对应模型额度；安装 skill 本身不会安装或登录 CodeBuddy。
