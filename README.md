# 大禹·天工（Dayu Tiangong）

面向河网数字孪生的联合水动力、闸泵调度、多目标优化与 AI 辅助解释平台。Phase 6 已形成“模型/优化结果 → 只读工具与 RAG → 来源约束回答/报告 → 人工复核”的可追溯闭环。

> 本仓库内置数据均为 **DEMO DATA**。当前计算未经工程率定，不连接实时监测、PLC/SCADA 或真实控制设备；AI 只解释、检索和生成报告，不修改结果，不替代人工审批。

## 技术栈

- 前端：React 18、React Router、TypeScript、Vite、Ant Design、ECharts、CesiumJS（GIS 路由懒加载）
- 后端：FastAPI、Pydantic 2、SQLAlchemy 2、Alembic
- 数值：一维 Saint-Venant、hydrostatic reconstruction、Rusanov；河网共同水位 + 节点连续性；闸门/泵站内部耦合
- 数据：PostgreSQL 17、PostGIS 3.5，空间坐标统一为 CGCS2000 / EPSG:4490
- 异步：Celery 5.5.3、Redis 7.4
- 优化：种子可复现 PSO、多目标评分、硬约束、Pareto 非支配分层
- AI：本地来源约束生成 / 可选 OpenAI-compatible LLM、离线 RAG、只读工具、安全护栏、Markdown/PDF

## 启动

```powershell
docker compose -p dayu-tiangong-phase1 -f docker/docker-compose.yml up --build
```

编排顺序为 `database + redis → migrate (0001…0007) → seed → backend + worker → frontend`。seed 会复用稳定河网节点并幂等导入五类内置知识。

- 平台：`http://127.0.0.1:8080/`
- GIS：`http://127.0.0.1:8080/gis`
- 调度计划：`http://127.0.0.1:8080/dispatch/plans`
- 调度运行：`http://127.0.0.1:8080/dispatch/runs`
- 水动力任务：`http://127.0.0.1:8080/hydraulic/tasks`
- 多目标优化：`http://127.0.0.1:8080/optimization`
- AI 水利助手：`http://127.0.0.1:8080/ai-assistant`
- OpenAPI：`http://127.0.0.1:8001/docs`

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

本次开启真实 PostGIS 集成后的全量自动测试为 102 passed，Phase 6 专项 11 项通过；Alembic 为 `0007 (head)`；前端类型检查、生产构建和内置浏览器验收通过。AI 页面块 8.68 kB（gzip 3.80 kB）；Cesium、ECharts、Ant Design 仍是独立大块。

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
