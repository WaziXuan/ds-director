# 阶段：写实现

## 目标
$goal

## 要求的行为
$behavior

## 结构说明
$structure

## 本阶段
- 只能修改匹配这些模式的文件：$src_paths
- 这些测试已由总监锁定，只读，目标是让它们全部通过：$test_files
- 测试命令：`$test_cmd`
- 公开签名已锁定：$signatures

先读测试弄清楚期望，再实现。全部通过后自己看一遍 diff，删掉多余和调试的东西再结束。
