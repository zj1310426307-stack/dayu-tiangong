# HYDRO-MODEL-02-D2-RC1 基线审计

## 审计边界

- 日期：2026-08-28
- 分支：`feature/HYDRO-MODEL-02-D2-v4-task-platform`
- RC1 基线 SHA：`d06dd77c47d004f519f352eabd7fbaf0101805ca`
- D1 RC1 基线 SHA：`cc6936d9d48d64c46a78ba85bed77c473e20cff3`
- D1 标签：`hydro-model-02-d1-rc1`
- 工作项：现有 PR #11，保持 OPEN，不合并
- 数据库基线 head：`20260828_0020`

RC1 仅整改任务状态、执行 attempt/lease、重试语义、冻结证据、结果/文件发布一致性和恢复工具；不扩大 D1/D2 科学作用域。

## GitHub 基线

PR #11 在基线 SHA 上为 `OPEN` 且 `MERGEABLE`。已有 8 个 main required-check context 保持不变：

1. `MODEL02 Ubuntu Python 3.11`
2. `MODEL02 Windows Python 3.11`
3. `Legacy hydraulic`
4. `Frontend contract`
5. `Backend v4 contract`
6. `PostGIS migration`
7. `Worker integration`
8. `Frontend OpenAPI`

分支保护同时要求管理员遵守、对话解决，并禁止 force-push 与删除。`D2 fault recovery` 只能在 Hosted 环境真实成功一次后再追加，不得替换现有 context。

## 基线验证

| 项目 | 结果 |
| --- | --- |
| `tests/model02` | 355 passed |
| `tests/model_engine` | 44 passed, 2 skipped |
| Python compileall | 提权后 PASS |
| 本地/远程分支对齐 | PASS，均为 `d06dd77` |
| 基线工作树 | clean |

首次 compileall 在已存在的 `__pycache__` 目录上遇到 Windows ACL `PermissionError`；以允许写缓存的相同代码重跑后通过。该问题不是 Python 语法或测试失败。

## 独立审计结论

基线状态为 `NO-GO`，原因是以下独立一致性缺口尚未关闭：

- Celery `autoretry_for` 与已 commit 的 `queued -> running` 认领冲突。
- lifecycle retry 与数值 rejected-step retry 共用 `retry_count`。
- v1/v2/v3 任务可保存客户端传入的 solver 来源。
- Dispatch Plan 只检查 hash 长度，不重算冻结快照。
- Case 可覆盖 Registry 定义的能力限制。
- Artifact rename 后的 success 为普通 ORM commit，没有 token/cancel CAS。
- Gate/Pump/Branch/Event 结果缺少完整 Dataset Version 复合身份约束。
- Profile、Boundary 和 Case Gate/Pump 选择存在静默取“最新/第一个/数据集唯一个”的歧义。
- phase heartbeat 会把已有 simulation time/CFL 写为 NULL。
- stale finalization、retry eligibility 与 Artifact reconciliation 没有可执行闭环。
- v4 暴露未实现的非 `full` storage level。
- Shadow Pair 为 group/v3/v4 三次 commit，失败可留孤儿行。

这些结论构成 RC1 的固定整改基线；数值方程、D1 基准和科学能力不在变更范围内。
