# 大禹·天工（Dayu Tiangong）

面向河网数字孪生的联合水动力、闸泵调度与多目标优化仿真平台。Phase 5 已形成“版本化数据 → 候选调度 → Phase 4 水动力仿真 → 多目标评价 → Pareto → 人工复核”的可追溯闭环。

> 本仓库内置数据均为 **DEMO DATA**。当前计算未经工程率定，不连接实时监测和真实控制设备；优化结果仅用于仿真与人工复核，不包含 AI 自主决策。

## 技术栈

- 前端：React 18、React Router、TypeScript、Vite、Ant Design、ECharts、CesiumJS（GIS 路由懒加载）
- 后端：FastAPI、Pydantic 2、SQLAlchemy 2、Alembic
- 数值：一维 Saint-Venant、hydrostatic reconstruction、Rusanov；河网共同水位 + 节点连续性；闸门/泵站内部耦合
- 数据：PostgreSQL 17、PostGIS 3.5，空间坐标统一为 CGCS2000 / EPSG:4490
- 异步：Celery 5.5.3、Redis 7.4
- 优化：种子可复现 PSO、多目标评分、硬约束、Pareto 非支配分层

## 启动

```powershell
docker compose -p dayu-tiangong-phase1 -f docker/docker-compose.yml up --build
```

编排顺序为 `database + redis → migrate (0001…0006) → seed → backend + worker → frontend`。seed 已避免在存在历史结果时重建稳定的河网节点身份。

- 平台：`http://127.0.0.1:8080/`
- GIS：`http://127.0.0.1:8080/gis`
- 调度计划：`http://127.0.0.1:8080/dispatch/plans`
- 调度运行：`http://127.0.0.1:8080/dispatch/runs`
- 水动力任务：`http://127.0.0.1:8080/hydraulic/tasks`
- 多目标优化：`http://127.0.0.1:8080/optimization`
- OpenAPI：`http://127.0.0.1:8001/docs`

## Phase 5 API

- `/api/v1/dispatch/plans`：计划 CRUD、校验、冻结、克隆、归档
- `/api/v1/dispatch/plans/{id}/actions|rules|runs`：动作、规则及异步运行
- `/api/v1/dispatch/runs/{id}`：运行进度、取消、重试、对比、事件、结构物和节点结果
- `/api/v1/model/tasks/{id}/enqueue|cancel|retry|snapshot`：冻结任务生命周期
- `/api/v1/model/results/{id}`：v1/v2 兼容的断面结果与诊断
- `/api/v1/optimization/tasks`：优化任务创建与列表
- `/api/v1/optimization/tasks/{id}/run|cancel`：异步运行与协作取消
- `/api/v1/optimization/tasks/{id}/candidates|pareto|recommendation|explain`：候选、前沿、人工推荐与确定性解释

前端请求只使用 `frontend/src/api/generated/client.ts`。后端启动后用 `cd frontend && npm run openapi:update` 同步契约。

## 验证

```powershell
$env:PYTHONPATH="backend;."
$env:RUN_POSTGIS_TESTS="1"
backend\.venv\Scripts\python.exe -m pytest -q

docker compose -p dayu-tiangong-phase1 -f docker/docker-compose.yml build frontend
docker run --rm -v "${PWD}\frontend:/app:ro" -w /app node:22-alpine npm audit --audit-level=moderate
```

本次开启真实 PostGIS 集成后的全量自动测试为 91 passed，其中 Phase 5 新增 8 项专项测试通过；真实 PostgreSQL 迁移与 2 候选端到端优化通过；前端类型检查、生产构建和内置浏览器验收通过。npm audit 本次因 registry endpoint 不可用未返回新结果；Cesium、ECharts、Ant Design 仍是独立大块。

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
