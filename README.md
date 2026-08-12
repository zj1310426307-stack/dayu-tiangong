# 大禹·天工（Dayu Tiangong）

面向河网数字孪生的联合水动力、闸泵调度、多目标优化与 AI 辅助解释平台。Phase 1A 在 Phase 6 业务能力上新增 GeoServer 标准空间服务层，同时保留 FastAPI 动态业务接口。

> 本仓库内置数据均为 **DEMO DATA**。当前计算未经工程率定，不连接实时监测、PLC/SCADA 或真实控制设备；AI 只解释、检索和生成报告，不修改结果，不替代人工审批。

## 技术栈

- 前端：React 18、React Router、TypeScript、Vite、Ant Design、ECharts、CesiumJS（GIS 路由懒加载）
- 后端：FastAPI、Pydantic 2、SQLAlchemy 2、Alembic
- 数值：一维 Saint-Venant、hydrostatic reconstruction、Rusanov；河网共同水位 + 节点连续性；闸门/泵站内部耦合
- 数据：PostgreSQL 17、PostGIS 3.5，空间坐标统一为 CGCS2000 / EPSG:4490
- 空间服务：GeoServer 2.28、WMS、Basic WFS、GeoWebCache/WMTS、6 个 SLD
- 异步：Celery 5.5.3、Redis 7.4
- 优化：种子可复现 PSO、多目标评分、硬约束、Pareto 非支配分层
- AI：本地来源约束生成 / 可选 OpenAI-compatible LLM、离线 RAG、只读工具、安全护栏、Markdown/PDF

## 启动

```powershell
$env:GEOSERVER_ADMIN_PASSWORD="replace-with-local-secret"
$env:GEOSERVER_DB_PASSWORD="replace-with-another-local-secret"
docker compose -p dayu-tiangong-phase1 -f docker/docker-compose.yml up --build
```

也可以把这两个变量写入仓库根目录中被 `.gitignore` 排除的 `.env`。禁止把真实密码提交到版本库。

编排顺序为 `database + redis + geoserver → migrate (0001…0007) → seed → geoserver-init → backend + worker → frontend`。`geoserver-init` 幂等创建只读数据库账号、`dayu` workspace、`dayu_postgis` store、6 个图层/SLD、Basic WFS 和 4 个 WMTS 缓存图层。

- 平台：`http://127.0.0.1:8080/`
- GIS：`http://127.0.0.1:8080/gis`
- 调度计划：`http://127.0.0.1:8080/dispatch/plans`
- 调度运行：`http://127.0.0.1:8080/dispatch/runs`
- 水动力任务：`http://127.0.0.1:8080/hydraulic/tasks`
- 多目标优化：`http://127.0.0.1:8080/optimization`
- AI 水利助手：`http://127.0.0.1:8080/ai-assistant`
- OpenAPI：`http://127.0.0.1:8001/docs`
- GeoServer OGC 入口：`http://127.0.0.1:8081/geoserver/`（仅绑定本机；前端使用同源 `/geoserver/*` 代理）

## Phase 1A 空间服务

- WMS：`/geoserver/dayu/wms`
- WMTS：`/geoserver/gwc/service/wmts`
- Basic WFS：`/geoserver/dayu/ows`，不开放 WFS-T
- 健康检查：`GET /api/v1/gis/geoserver/health`
- 图层清单：`GET /api/v1/gis/geoserver/layers`
- 浏览器安全配置：`GET /api/v1/gis/geoserver/config`

GeoServer 的 PostGIS 登录默认名为 `dayu_geoserver`，只有 `CONNECT`、`USAGE`、`SELECT` 和序列读取权限，并设置 `default_transaction_read_only=on`。`/api/v1/gis/*` 全部保留，用于属性详情、数据版本和模型联动。

## Phase 6 API

- `/api/v1/dispatch/plans`：计划 CRUD、校验、冻结、克隆、归档
- `/api/v1/dispatch/plans/{id}/actions|rules|runs`：动作、规则及异步运行
- `/api/v1/dispatch/runs/{id}`：运行进度、取消、重试、对比、事件、结构物和节点结果
- `/api/v1/model/tasks/{id}/enqueue|cancel|retry|snapshot`：冻结任务生命周期
- `/api/v1/model/results/{id}`：v1/v2 兼容的断面结果与诊断
- `/api/v1/optimization/tasks`：优化任务创建与列表
- `/api/v1/optimization/tasks/{id}/run|cancel`：异步运行与协作取消
- `/api/v1/optimization/tasks/{id}/candidates|pareto|recommendation|explain`：候选、前沿、人工推荐与确定性解释
- `POST /api/v1/ai/chat`：带来源、工具列表和安全状态的 AI 对话
- `GET|POST /api/v1/ai/knowledge/*`：知识检索、文档清单与上传
- `POST /api/v1/ai/report/generate`：生成 Markdown/PDF 调度分析报告
- `GET /api/v1/ai/tools/logs`：工具调用审计

前端请求只使用 `frontend/src/api/generated/client.ts`。后端启动后用 `cd frontend && npm run openapi:update` 同步契约。

## 验证

```powershell
$env:PYTHONPATH="backend;."
$env:RUN_POSTGIS_TESTS="1"
backend\.venv\Scripts\python.exe -m pytest -q

docker compose -p dayu-tiangong-phase1 -f docker/docker-compose.yml build frontend
docker run --rm -v "${PWD}\frontend:/app:ro" -w /app node:22-alpine npm audit --audit-level=moderate
```

Phase 1A 全量回归（含真实 PostGIS）为 105 passed；前端类型检查与生产构建通过，GIS 页面块 2.42 kB、CesiumMap 8.35 kB。Compose 在线验收已覆盖 GeoServer catalog、WMS 图片、WMTS 缓存瓦片、Basic WFS、只读数据库角色、FastAPI 与浏览器 GIS 页面；结果见 `docs/review/phase1A_geoserver_review.md`。

## 文档

- [项目介绍](docs/project_introduction.md)
- [架构](docs/architecture.md)
- [数据库](database/database_design.md)
- [水动力加固](docs/model/phase4_hydraulic_hardening.md)
- [河网耦合](docs/model/phase4_network_coupling.md)
- [闸泵方程](docs/model/phase4_structure_equations.md)
- [调度契约](docs/dispatch/dispatch_contract.md)
- [规则 DSL](docs/dispatch/rule_dsl.md)
- [Worker 生命周期](docs/worker/task_lifecycle.md)
- [数值与性能基准](docs/benchmarks/phase4_benchmarks.md)
- [Phase 4 审查](docs/review/phase4_dispatch_review.md)
- [优化契约](docs/optimization/optimization_contract.md)
- [Phase 5 审查](docs/review/phase5_optimization_review.md)
- [Phase 6 AI 架构](docs/ai/phase6_ai_architecture.md)
- [Phase 6 审查](docs/review/phase6_ai_review.md)
- [Phase 1A GeoServer 审查](docs/review/phase1A_geoserver_review.md)
