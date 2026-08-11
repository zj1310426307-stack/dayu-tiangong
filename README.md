# 大禹·天工（Dayu Tiangong）

河网智能调度与数字孪生水利平台。Phase 2 已在 GIS 一张图上贯通版本化 PostGIS 水利数据库、河网拓扑、CRUD、Excel/CSV/GeoJSON 导入、自动校验和 Phase 3 模型输入快照。

## 技术栈

- 前端：React 18、React Router 7、TypeScript、Vite、Ant Design、CesiumJS、ECharts 6
- 后端：FastAPI、Pydantic 2、SQLAlchemy 2、GeoAlchemy2、Psycopg 3、Alembic
- 数据：PostgreSQL 17、PostGIS 3.5，WGS 84 / EPSG:4326
- 部署：Docker Compose、Nginx

## 一键启动

在仓库根目录执行：

```powershell
docker compose -p dayu-tiangong-phase1 -f docker/docker-compose.yml up --build
```

编排会依次等待数据库健康、执行 `0001 → 0002` 迁移、幂等初始化演示数据，再启动 API 和前端。

- 平台首页：`http://127.0.0.1:8080/`
- GIS 一张图：`http://127.0.0.1:8080/gis`
- 河道数据库：`http://127.0.0.1:8080/data-center/rivers`
- 数据导入：`http://127.0.0.1:8080/data-center/imports`
- 数据校验：`http://127.0.0.1:8080/data-center/validation`
- API 文档：`http://127.0.0.1:8001/docs`

默认宿主端口为前端 `8080`、后端 `8001`。容器间后端仍使用 `8000`。如需覆盖，可设置 `BACKEND_PORT` 或 `FRONTEND_PORT`。

## 数据库初始化

Docker 方式：

```powershell
docker compose -p dayu-tiangong-phase1 -f docker/docker-compose.yml up -d database
docker compose -p dayu-tiangong-phase1 -f docker/docker-compose.yml run --rm migrate
docker compose -p dayu-tiangong-phase1 -f docker/docker-compose.yml run --rm seed
```

本机 Python 方式：

```powershell
$env:PYTHONPATH='backend'
backend\.venv\Scripts\python.exe -m alembic -c database\alembic.ini upgrade head
backend\.venv\Scripts\python.exe database\seed\demo_data.py
```

种子脚本幂等生成：1 个版本、3 条河道、20 个横断面、5 座闸门、3 座泵站、8 个节点、7 个河段、1 个模型参数、1 个边界条件和 1 个计算方案。

## Phase 2 API

业务 CRUD：

- `/api/v1/rivers[/{id}]`
- `/api/v1/cross-sections[/{id}]`
- `/api/v1/gates[/{id}]`
- `/api/v1/pumps[/{id}]`
- `POST /api/v1/rivers/topology/generate`
- `GET /api/v1/rivers/topology?dataset_version_id=1`

导入与质量：

- `POST /api/v1/import/excel`
- `POST /api/v1/import/csv`
- `POST /api/v1/import/geojson`
- `GET /api/v1/import/templates/{resource}`
- `POST /api/v1/validation/run`

模型数据：

- `/api/v1/model-data/dataset-versions`
- `/api/v1/model-data/parameters`
- `/api/v1/model-data/boundary-conditions`
- `/api/v1/model-data/simulation-cases`
- `GET /api/v1/model-data/simulation-cases/{id}/input`

Phase 1 `/api/v1/gis/*` 只读 GeoJSON 接口完整保留，泵站响应继续提供兼容属性 `capacity`，同时新增标准字段 `design_flow`。

## Excel 模板

- `docs/templates/phase2_rivers_template.xlsx`
- `docs/templates/phase2_cross_sections_template.xlsx`
- `docs/templates/phase2_gates_template.xlsx`
- `docs/templates/phase2_pumps_template.xlsx`

导入时在页面选择数据版本。模板首行字段名不可修改；删除示例行后填入正式数据。任一行失败时整批不写入。

## OpenAPI 同步

后端启动后执行：

```powershell
cd frontend
npm run openapi:update
```

生成文件 `frontend/src/api/generated/client.ts` 是前端请求唯一入口。页面和组件不得手写 API 包装或自行调用 `fetch`。

## 验证

```powershell
$env:PYTHONPATH='backend;.'
$env:RUN_POSTGIS_TESTS='1'
backend\.venv\Scripts\python.exe -m pytest -q backend\tests tests

cd frontend
npm audit --audit-level=moderate
npm run typecheck
npm run build
```

## 文档

- [项目介绍](docs/project_introduction.md)
- [系统架构](docs/architecture.md)
- [坐标系说明](docs/coordinate_system.md)
- [数据库设计](database/database_design.md)
- [Phase 1 GIS 审查](docs/review/phase1_gis_review.md)
- [Phase 2 数据库审查](docs/review/phase2_database_review.md)

## 阶段边界

Phase 2 只交付静态水利数据库与模型输入准备。水动力求解、实时监测、优化调度、执行控制和 AI 决策不在本阶段实现。
