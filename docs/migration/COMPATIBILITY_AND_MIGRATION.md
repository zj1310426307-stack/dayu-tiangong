# 持续优化 01 兼容与迁移说明

> **ARCHIVED (2026-08-31):** 本文仅保留 CONTINUOUS-OPT-01 当时的兼容事实。
> 其中对 v1/v2/v3/v4-lite 的描述不再是现行 1D 产品路线；当前迁移见
> [HYDRO-1D-RESET-01](./HYDRO-1D-RESET-01.md)。

日期：2026-08-24

分支：`feature/continuous-optimization-01`

基线：`main@07948e663fedc220d8ca6cdbdb34fd3fb4e2beee`

## 1. 兼容结论

本轮是加法变更，没有数据库迁移，不修改 Dataset Version、任务状态、v1/v2/v3/v4-lite 模型输入或历史结果语义。旧 HTTP 客户端不传新增查询参数时仍返回原全量任务列表。

本轮没有实现 OIDC/JWT、RBAC、tenant/project 或可信 actor。任务列表过滤是工作区查询边界，不是安全授权；所有生产 mutation 继续 `NO-GO`。

## 2. API 变化

以下 GET 接口新增可选 `dataset_version_id`：

- `/api/v1/model/tasks`
- `/api/v1/optimization/tasks`
- `/api/v1/dispatch/runs`

携带参数时，水动力任务经 `SimulationCase`、调度运行经 `DispatchPlan`、优化任务经自身字段在 SQL 层过滤。不携带参数时保持全量列表。详情、结果、取消、重试、候选等 ID 接口没有新增版本授权。

生成客户端同时支持：

```ts
listHydraulicTasks()
listHydraulicTasks('https://legacy-base-url')
listHydraulicTasks({ dataset_version_id: 17 }, 'https://base-url')
```

后端 API、`frontend/scripts/update-openapi.mjs` 与生成的 `frontend/src/api/generated/client.ts` 必须同步发布或同步回滚。

## 3. 文件路径与容器配置

本地运行使用：

```dotenv
DAYU_STORAGE_ROOT=backend/storage
```

相对路径以仓库根解析。Compose 内的 `DAYU_STORAGE_ROOT` 固定为 `/app/backend/storage`；宿主机路径由下列变量控制：

```dotenv
DAYU_STORAGE_HOST_PATH=../backend/storage
```

backend 与 worker 必须挂载同一个宿主目录。多节点部署不能使用当前本地 bind mount 作为共享存储或高可用方案。

AI 新报告使用 `ai-reports/<filename>` 的存储根相对 key；历史仓库相对路径仍可读取。修改存储根前必须：

1. 停止 backend 与 worker 写入；
2. 完整复制 `imports`、`conversions`、`ai-reports`；
3. 校验数量、大小与哈希；
4. 更新宿主挂载并验证历史报告下载；
5. 失败时保留旧目录并回滚配置。

历史自定义根中保存的绝对报告路径若已离开当前允许根，不会被放宽读取；必须先迁移。水动力原件 BLOB、知识文档原件和既有业务文件没有在本轮迁移。

## 4. 上传兼容性

- AI、普通导入、DGIS 转换、水动力导入统一只读取各自上限加一字节；
- 原有 413/415/422 状态和业务提示保持不变；
- Nginx 总门为 102 MiB，可能先于应用返回 413，响应格式可能不同；
- backend 只发布到宿主 `127.0.0.1`，但本机直连仍会绕过 Nginx；
- multipart 解析前的 ASGI 全请求体限制尚未完成。

## 5. 发布步骤

1. 备份当前 `.env` 与 `backend/storage`；
2. 同步后端、生成客户端、Nginx、Dockerfile 和 Compose；
3. 检查 `DAYU_STORAGE_HOST_PATH` 对 backend/worker 可写且一致；
4. 重新构建 backend、worker、frontend；
5. 验证 OpenAPI 三个新增参数、四类上传边界、模板下载和历史 AI 报告；
6. 在真实 PostGIS 中验证至少两个 Dataset Version 的列表过滤；
7. IAM 未完成时不得开放公网 mutation。

## 6. 回滚

按逻辑提交反向回滚，不使用破坏性重置：

```powershell
git revert 68fc82a
git revert a6ee95b
```

若只回滚一项，仍需保证后端与生成客户端版本匹配。回滚文件基础前先备份自定义存储根和本轮生成文件；旧代码不会自动删除孤儿文件。Nginx、Dockerfile、Compose 可独立恢复，但必须重新验证上传与模板。没有数据库 migration，因此没有 downgrade 命令。
