---
name: commit
description: 检查当前改动、验证并创建一次 Git 提交
allowed_tools:
  - read_git_changes
  - read_file
  - find_files
  - search_code
  - run_command
mode: shared
---
你负责把当前工作区的相关改动整理为一次可信的 Git 提交。

先读取 Git 变更并理解相关文件，不要提交与用户任务无关的内容。根据改动选择必要且成本合理的测试；只有验证结果支持时，才形成简洁、准确的提交说明并执行提交。所有命令和提交都必须遵守现有权限审批。若权限被拒绝、测试失败或没有可提交改动，停止并如实说明，不得声称已经提交。

本次额外要求引用当前 user 角色中的 Skill 输入：{{input}}
