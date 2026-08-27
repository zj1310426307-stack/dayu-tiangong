# main 分支保护建议

本仓库未由 RC1 自动修改 GitHub 管理设置。建议管理员在 GitHub `Settings → Branches` 或 Rulesets 中为 `main` 配置：

1. 要求 Pull Request 后才能合并；
2. 禁止 force push 与删除；
3. 要求分支合并前保持最新；
4. 将以下检查设为 required：
   - `MODEL02 Ubuntu Python 3.11`
   - `MODEL02 Windows Python 3.11`
   - `Legacy hydraulic`
   - `Frontend contract`
5. 至少要求一名审查者，并在需要时要求 code owner 审查；
6. 不允许管理员绕过上述发布门，除非执行有记录的紧急回滚。

首次启用 required checks 前，应先确认 RC1 工作流已经在默认分支或目标 PR 上生成完全一致的 check names。
