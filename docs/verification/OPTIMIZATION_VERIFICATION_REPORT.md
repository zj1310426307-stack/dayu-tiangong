# 持续优化 01 验证报告

日期：2026-08-24

代码提交：`a6ee95b`、`68fc82a`

审查提交：`cd8c12d`

## 1. 自动验证

| 门禁 | 结果 | 说明 |
|---|---|---|
| 全仓 pytest | `637 passed, 71 skipped` | 最终代码树，无失败 |
| 文件基础专项 | 通过 | 有界读取、路径逃逸、原子替换、失败清理、报告事务补偿、容器合同 |
| Dataset Version 专项 | 通过 | 三类 SQL 构造、OpenAPI 参数、旧无参全量合同 |
| 前端类型检查 | 通过 | `npm run typecheck` |
| 前端生产构建 | 通过 | 3927 modules；保留 ECharts/Ant Design 大 chunk 警告 |
| OpenAPI 生成 | 通过 | 从临时真实 FastAPI `/openapi.json` 重新生成客户端 |
| Python 编译 | 通过 | `backend/app` compileall |
| 依赖一致性 | 通过 | `pip check` 无损坏依赖 |
| Alembic | 通过 | 单一 head `20260818_0019`，本轮无迁移 |
| Compose 静态解析 | 通过 | 12 个服务；backend/worker 挂载相同容器存储根 |
| Git 差异格式 | 通过 | `git diff --check` 无错误 |

71 项跳过主要依赖真实 PostGIS、GDAL、QGIS、GeoServer、数据库角色或外部运行环境。本轮没有把跳过项记为通过。

## 2. 文件基础验证

- 四类 `UploadFile` 路由均调用统一 `read_limited_upload`；
- 读取请求精确为 `max_bytes + 1`；
- 绝对路径、`..` 和解析后越界被拒绝；
- 同目录随机临时路径只在生产成功后原子替换；失败临时文件和失败 conversion job 会清理；
- GDAL 生产器使用不存在的临时目标名，避免提前暴露半成品；
- AI Markdown/PDF 在数据库提交失败时回滚并删除；
- 新报告使用存储根相对 object key，历史仓库相对路径仍可解析；
- 默认 Compose 中 backend/worker 共用 `/app/backend/storage`，backend 端口仅绑定 `127.0.0.1`；
- Nginx 102 MiB 和应用 10/20/100 MB 精确门同时保留。

未验证：真实代理大文件上下界、chunked 超限、非默认宿主挂载的容器运行、病毒/MIME magic 扫描、配额、保留、分布式共享和备份恢复。

## 3. 任务监控版本边界

- 水动力列表经 `SimulationCase.dataset_version_id` JOIN 过滤；
- 优化列表按 `OptimizationTask.dataset_version_id` 过滤；
- 调度运行经 `DispatchPlan.dataset_version_id` JOIN 过滤，items 与 total 使用同一条件；
- 不传参数时 SQL 保持全量列表；
- 前端水动力、优化、调度监控均传当前 Dataset Version；
- request sequence/取消标记阻止切版后的旧响应覆盖新状态；
- 生成客户端保留旧 baseUrl 调用并支持新查询对象。

上述证据是 SQL 构造和契约单测，不是生产权限隔离。真实 PostGIS 两版本数据验证、详情/结果/取消/重试 ID 授权未执行。

## 4. 内置浏览器验收

按要求仅使用 Codex 内置浏览器，基于实时 `HydraulicEngine` 24 小时验收夹具完成：

- `/hydraulic/results?taskId=1002`：任务 1002、真实断面时序与 Dataset Version 正常，无加载/跨版本错误；
- `/dispatch/runs/1`：运行详情、已发布版本、闸门/泵站结果正常；
- 两页最后一次加载均为控制台 `0 warning / 0 error`；
- 修复了 React StrictMode 下异步 ECharts 重复初始化和卸载后监听残留；
- 验收夹具是实时引擎软件证据，不是 PostGIS/API 集成、真实工程率定或设备执行证据。

## 5. 未执行门禁

- 当前环境无 Docker CLI：未构建镜像、未运行 Compose、未验证容器模板下载；
- 未执行真实 IAM、RBAC、tenant/project、可信 actor 或安全审计测试；
- 未执行真实 PostGIS 多版本数据、GeoServer、QGIS、GDAL 二进制与外部模型对比；
- 未执行负载、HA、灾备、TLS、密钥托管和恶意文件测试。

结论：本轮两个限定软件闭环为 `PASS`；统一 IAM、完整文件管理、权限隔离和生产部署继续 `NO-GO`。

## 6. GitHub 发布与 main 合并

- 发布前重跑全仓：`637 passed, 71 skipped in 136.28s`；
- 前端 `npm run typecheck` 与 `npm run build` 通过，构建仍保留既有大 chunk 提示；
- 高置信凭据与本机绝对路径公开发布扫描：0 命中；
- 远端功能分支 HEAD：`608d4a653990ed17eefb42ec71f5d28e1fb06e15`；
- 普通双亲合并提交：`b58207ba9195e001c8e535b990dc0d2c563a12a5`；
- 合并两父：`07948e663fedc220d8ca6cdbdb34fd3fb4e2beee`、`608d4a653990ed17eefb42ec71f5d28e1fb06e15`；
- 合并 Tree：`544d71e531a7c4f46e2734b60cff2ef7d863b993`，与功能分支一致；
- 未强推、未删除功能分支、未把外部项目治理文档混入代码仓库。

GitHub 默认 HTTPS Git 节点连续超时或重置，SSH 主机指纹虽与官方一致但本机无可用公钥。最终使用项目历史已验证的 Git Credential Manager + GitHub 官方 Git Data API 通道，令牌仅在进程内存使用；逐 Blob、Tree、Commit 交叉校验后才创建分支和非强制更新 `main`。
