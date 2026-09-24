# HYDRO-CORE-06 最终审查

- 审查日期：2026-09-24
- 分支：`refactor/hydro-core-06-engine-routing`
- 基线：`main@8d2d432d77c37ecf4896b776b80d965d38d19800`
- 当前结论：`PARTIAL`（代码与本地回归已收敛；持久 PostGIS 迁移演练及 Docker runtime 验证受本机 Docker Linux Engine 不可用阻断）

## 已实现

1. `SimulationTask` 新增不可为空的 `engine_id`、`execution_class`，并用迁移 `20260924_0036` 对可证明的历史 MASCARET/D-Flow 任务进行确定性回填；不可证明的历史任务明确标为 `legacy-unresolved/legacy`，不会重跑。
2. 引入统一 `routing.py`：注册表解析、production/pilot/synthetic 门禁、能力检查与冻结 provenance 检查均走同一 fail-closed 规则。
3. 标准 API、同步执行、Worker、受控闸泵创建和生命周期均只从已冻结 `engine_id` 建立引擎。生产路径不存在无参 factory 调用；factory 默认值只保留给旧测试/命令行兼容。
4. MASCARET 仍是唯一 production eligible 引擎；D-Flow FM 只允许 pilot/synthetic，Gate/Pump 仅走冻结调度合同，未扩大 PLC/SCADA、优化、第二 Domain 或原生文件业务边界。
5. 新增 `/api/v1/model/engines`；OpenAPI 生成客户端与水动力页面显示引擎目录、生产资格和 Task 的冻结引擎/执行类别。

## 验证结果

| 检查 | 结果 |
|---|---|
| 显式路由、registry、task/result/dispatch 定向回归 | PASS，34 项 |
| MASCARET + D-Flow FM 引擎/benchmark 分组 | PASS，195 passed，13 skipped（受运行时标记/外部条件控制） |
| 后端分组 | PASS，运行至 100%；跳过项均由既有环境标记控制 |
| 根目录 GIS/契约分组 | PASS，35 项 |
| 末段前端/仓库/优化/QGIS 契约分组 | PASS，43 passed，1 skipped |
| Ruff（backend/model/tests/新增迁移） | PASS |
| 前端 TypeScript | PASS |
| 前端生产构建 | PASS，本地 `dist/index.html` 已更新 |
| OpenAPI 漂移检查 | PASS |
| Alembic head | PASS，`20260924_0036` |
| Alembic 全链离线 SQL | PARTIAL：历史 `20260813_0010` 使用 `MockConnection` 不支持的 `exec_driver_sql`，在抵达本迁移前中断 |
| 持久 PostGIS upgrade/downgrade | BLOCKED：Docker Desktop Linux Engine 管道不可连接 |
| MASCARET/D-Flow 外部 runtime 实跑 | NOT RUN：本机 Docker runtime 不可用；未伪造成功 |

## 兼容性与风险

- 旧 API 请求中的 `engine` 仍由 schema alias 接受，响应统一输出 `engine_id`。
- 旧 Task 只要 migration 可证明引擎身份即可被保留；不可证明的 Task 是可读不可重跑的安全状态。
- `engine_version` 未被重定义：MASCARET 继续保存既有 build identity，D-Flow 保存其已登记运行时版本；新增 `engine_id` 解决语义歧义。
- 迁移在线演练、真实工程资料包、真实运行时与 D-Flow pilot 仍需在 Docker Linux Engine 恢复后按独立 Compose 项目执行。

## 合并前要求

1. 启动 Docker Desktop Linux Engine；在独立 Compose 项目/新卷中执行 migration upgrade/downgrade，并保留日志。
2. 运行容器化 MASCARET 与 D-Flow acceptance 集，确保 runtime identity 与 registry 一致。
3. 在审查通过后创建 PR；本任务不直接合并 `main`。
