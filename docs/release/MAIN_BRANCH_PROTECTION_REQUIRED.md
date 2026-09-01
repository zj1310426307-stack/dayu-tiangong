# main 分支保护 required checks

更新日期：2026-08-31

下列规则是 D3A RC1 发布时已验证的保护基线及 HYDRO-1D-RESET-01 必须保留的稳定 check names。实际 GitHub 设置仍应由管理员在受控会话中回读确认：

1. 要求 Pull Request 后才能合并；
2. 禁止 force push 与删除；
3. 要求分支合并前保持最新；
4. 保留以下 11 个精确 check display names：
   - `MODEL02 Ubuntu Python 3.11`
   - `MODEL02 Windows Python 3.11`
   - `Legacy hydraulic`
   - `Frontend contract`
   - `Backend v4 contract`
   - `PostGIS migration`
   - `Worker integration`
   - `Frontend OpenAPI`
   - `D2 fault recovery`
   - `D2 shipping runtime`
   - `D3A shipping science`
5. 至少要求一名审查者，并在需要时要求 code owner 审查；
6. 不允许管理员绕过上述发布门，除非执行有记录的紧急回滚。

上述名称中的 `Legacy`、`v4`、`D1/D2/D3A` 是已发布分支保护的稳定外部标识，
不是当前 Solver 语义。HYDRO-1D-RESET-01 保留 display name 以避免 required context
消失，但工作流内容已切换为 MASCARET Adapter、架构隔离、统一 Benchmark、
迁移、OpenAPI 与发布镜像门。后续如需改名，必须先让新 context 在默认分支/目标
PR 成功生成，再原子更新 branch protection，不得先删除旧 required context。
