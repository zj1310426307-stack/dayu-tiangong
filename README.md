# 大禹·天工（Dayu Tiangong）

面向河网数字孪生的联合水动力、闸泵调度、多目标优化与 AI 辅助解释平台。GIS-OPT-1 建立 QGIS 受控数据生产链；GIS-OPT-2 进一步建立由 Desktop 专业工程生成 Server 工程、只读 QGIS Server、图层 Registry、统一 Catalog、Cesium adapter 和薄 Bridge 插件组成的单源 GIS 架构。

> 本仓库内置数据均为 **DEMO DATA**。当前计算未经工程率定，不连接实时监测、PLC/SCADA 或真实控制设备；AI 只解释、检索和生成报告，不修改结果，不替代人工审批。

## 技术栈

- 前端：React 18、React Router、TypeScript、Vite、Ant Design、ECharts、CesiumJS（GIS 路由懒加载）
- 后端：FastAPI、Pydantic 2、SQLAlchemy 2、Alembic
- 数值：一维 Saint-Venant、hydrostatic reconstruction、Rusanov；河网共同水位 + 节点连续性；闸门/泵站内部耦合
- 桌面生产：QGIS 3.44 LTR，仅编辑 `staging_qgis`，通过 PostgreSQL service / QGIS Authentication Manager 管理本机凭据
- 专业二维发布：QGIS Server 3.44 LTR，仅加载确定性生成的 Server QGZ，由 FastAPI Safe WMS Gateway 隔离浏览器与私有服务
- 数据：PostgreSQL 17、PostGIS 3.5、TimescaleDB，空间坐标统一为 CGCS2000 / EPSG:4490
- 数据转换：GDAL/OGR，原始导入按批次写入不可变 `imports` 表
- 空间服务：GeoServer 2.28、WMS、Basic WFS、GeoWebCache/WMTS、12 个图层、12 个 SLD 与 `dayu_basemap` 图层组
- 异步：Celery 5.5.3、Redis 7.4
- 优化：种子可复现 PSO、多目标评分、硬约束、Pareto 非支配分层
- AI：本地来源约束生成 / 可选 OpenAI-compatible LLM、离线 RAG、只读工具、安全护栏、Markdown/PDF

## 启动

```powershell
$env:GEOSERVER_ADMIN_PASSWORD="replace-with-local-secret"
$env:GEOSERVER_DB_PASSWORD="replace-with-another-local-secret"
$env:MARTIN_DB_PASSWORD="replace-with-martin-readonly-secret"
$env:QGIS_EDITOR_DB_PASSWORD="replace-with-editor-secret"
$env:QGIS_REVIEWER_DB_PASSWORD="replace-with-reviewer-secret"
$env:QGIS_SERVER_DB_PASSWORD="replace-with-qgis-server-secret"
$env:BACKEND_DB_PASSWORD="replace-with-non-owner-runtime-secret"
docker compose -p dayu-tiangong-phase1 -f docker/docker-compose.yml up --build
```

也可以把这些变量写入仓库根目录中被 `.gitignore` 排除的 `.env`。禁止把真实密码写入 Git、Markdown、QGIS 工程或前端；QGIS 桌面连接使用用户级 `.pg_service.conf`、QGIS Authentication Manager 或受控凭据设施。

编排顺序为 `database + redis + geoserver → migrate (0001…0014) → seed → qgis-bootstrap/app-bootstrap → gis-registry-seed → QGIS Server/GeoServer/Martin/TiTiler → backend + worker → frontend`。`qgis-bootstrap` 额外创建 `dayu_qgis_server` 独立只读账号；Registry seed 会校验所有源对象存在，并验证该账号对 QGIS allowlist 视图的 SELECT 权限。

- 平台：`http://127.0.0.1:8080/`
- GIS：`http://127.0.0.1:8080/gis`
- 调度计划：`http://127.0.0.1:8080/dispatch/plans`
- 调度运行：`http://127.0.0.1:8080/dispatch/runs`
- 水动力任务：`http://127.0.0.1:8080/hydraulic/tasks`
- 多目标优化：`http://127.0.0.1:8080/optimization`
- AI 水利助手：`http://127.0.0.1:8080/ai-assistant`
- OpenAPI：`http://127.0.0.1:8001/docs`
- GeoServer OGC 入口：`http://127.0.0.1:8081/geoserver/`（仅绑定本机；前端使用同源 `/geoserver/*` 代理）
- Unified GIS Catalog：`GET /api/v1/gis/catalog?dataset_version_id={id}`
- QGIS Server 证据健康：`GET /api/v1/gis/qgis-server/health`
- QGIS WMS 安全网关：`/qgis-server/wms`（浏览器不能提交 `MAP/FILTER/SQL`）

## Phase 1D GIS 空间工作台

- WMS：`/geoserver/dayu/wms`
- WMTS：`/geoserver/gwc/service/wmts`
- Basic WFS：`/geoserver/dayu/ows`，不开放 WFS-T
- 健康检查：`GET /api/v1/gis/geoserver/health`
- 图层清单：`GET /api/v1/gis/geoserver/layers`
- 浏览器安全配置：`GET /api/v1/gis/geoserver/config`
- 底图图层组：`dayu:dayu_basemap`
- 坐标/地名/道路/POI 定位：`GET /api/v1/gis-analysis/search`
- 注记、追踪、框选、缓冲、最近设施、A/B 对比和 PDF：`/api/v1/gis-analysis/*`

GeoServer 的 PostGIS 登录默认名为 `dayu_geoserver`，只有 `CONNECT`、`USAGE`、`SELECT` 和序列读取权限，并设置 `default_transaction_read_only=on`。`/api/v1/gis/*` 全部保留，用于属性详情、数据版本和模型联动。

## GIS-OPT-1 QGIS 受控生产链

```text
CAD / SHP / GPKG / GeoJSON / 测量资料
→ QGIS 3.44 LTR 或 GDAL/OGR
→ imports/raw → staging_qgis
→ FastAPI 质检 → 人工审核
→ 原子创建新 dataset_version → publish
→ GeoServer / Martin / TiTiler → Cesium / 模型 / 调度 / AI
```

- `dayu_tiangong` 仍是唯一业务空间数据库；没有新建第二套 GIS 数据库。
- QGIS 编辑者只写 `staging_qgis.river|cross_section|gate|pump`，不能修改核心表；审阅者只读；`dayu_backend` 是非 owner 运行账号并继承 `dayu_publisher` 发布组，后端和 Worker 已不再使用数据库 owner。
- 批次状态、质检运行、问题、审核决定和发布清单分别持久化，彼此不混用。质检通过与人工批准都是晋级前置条件，晋级始终创建新版本并计算稳定 SHA-256。
- `publish` 中的 12 个兼容视图只暴露 `published` 版本；GeoServer store 已切换到该 schema，并通过 WMS、WMTS、Basic WFS、GetFeatureInfo、缓存和 Cesium 兼容回归。GeoServer 账号不再读取 `public` 核心表。
- WFS 保持 `BASIC`；不开放 WFS-T，不把 QGIS 桌面账号交给 GeoServer。
- 平台 mutation API 已保留 actor/reviewer/publisher 字段，但统一 OIDC/IAM 尚未完成；当前只能用于受控开发与验收环境，不能宣称生产身份安全已闭环。

QGIS 工程模板位于 `qgis/projects/dayu_tiangong_ltr.qgs`，项目 CRS 为 EPSG:4490，并包含 `01_REFERENCE_READONLY`、`02_EDIT_STAGING`、`03_PUBLISH_READONLY` 三个职责分组。Windows 本机请双击 `qgis/Start_Dayu_QGIS.cmd`，由启动器用短英文盘符规避中文安装路径导致的 SIP/PyQt 模块加载故障。完整操作与治理说明见 [QGIS 生产流程](docs/gis/qgis_production_workflow.md) 和 [GIS 数据治理](docs/gis/gis_data_governance.md)。

治理 API 前缀为 `/api/v1/gis-governance`：

- `POST|GET /batches`、`GET /batches/{id}`：登记和查询来源批次；
- `POST /batches/{id}/stage|validate|submit-review|review|promote`：受控状态流；
- `GET /batches/{id}/validation|issues|diff`：质检证据和父版本差异；
- `GET /publications`、`POST /versions/{id}/publish|retire`：发布审计、只读发布视图激活与版本退役。

## GIS-OPT-2 QGIS × 平台深度融合

```text
QGIS Desktop 主工程 → 确定性 Builder → 只读 Server QGZ
→ 私有 QGIS Server → FastAPI Safe WMS Gateway
→ Registry + Manifest + Runtime + Dataset Version 统一 Catalog
→ Cesium 协议 Adapter Runtime
```

- `gis_layer_registry` 登记 22 个逻辑/服务图层，`basemap_registry` 只登记受控 endpoint key，不存 URL/SQL/DSN/凭据。
- 首批 `river/cross_section/gate/pump` 由 QGIS WMS 提供专业二维制图；其余 8 个静态层保留 GeoServer 过渡路径，Martin/TiTiler/动态 Primitive/3D 继续各司其职。
- `CesiumMap.tsx`、`GisPage.tsx`、`LayerManager.tsx` 不再保存业务图层清单；adapter 只按 `service_mode + render_mode` 选择。QGIS GetFeatureInfo 经生成客户端只调用平台网关。
- Bridge 只调用治理 API，在 QGIS 内显示 validation/review/publish，以 Private memory layer 加载最新问题并定位 staging 源要素；无 IAM 时生产 mutation fail closed。
- 横断面空间扩展采用 ADD ONLY：新增 location/axis/point/profile，保留旧 Point geometry、`points` JSON 和 `station`。
- GetPrint 仍禁用。只有真实双 published version 的 GetMap/FeatureInfo 隔离证据与打印内容安全检查通过后才可启用。
- 离线、独立 Docker 全栈、持久库 0013/0014 迁移与权限、持久双版本 QGIS WMS/FeatureInfo、QGIS 3.44.13 GUI 和 `qgis_process` 门禁已全部通过，QGIS health 为 `healthy`。GIS-OPT-2 结论为 COMPLETE；GeoServer KEEP，GetPrint 仍 PRINT_NOT_READY。详见 [GIS-OPT-2 Final Review](docs/review/GIS-OPT-2_Final_Review.md)。

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

backend\.venv\Scripts\python.exe -m pytest -q tests/test_qgis_project_contract.py
cd frontend
npm run openapi:update
npm run typecheck
npm run build
cd ..
docker compose -p dayu-tiangong-phase1 -f docker/docker-compose.yml build frontend
docker run --rm -v "${PWD}\frontend:/app:ro" -w /app node:22-alpine npm audit --audit-level=moderate
```

Phase 1D 历史回归（含真实 PostGIS）为 124 passed；其在线验收覆盖 12 图层目录、`dayu_basemap` GetMap、版本过滤 WMS/WMTS、Basic WFS、只读数据库角色、FastAPI 搜索与专题图 PDF。该数字不是 GIS-OPT-1 的本轮结果；GIS-OPT-1 已完成离线、隔离 PostGIS、持久全栈和 QGIS GUI 验收，具体数量、命令和生产外部输入边界以 [阶段审查报告](docs/review/phase_gis_opt1_qgis_governance_review.md) 为准。

## 文档

- [项目介绍](docs/project_introduction.md)
- [架构](docs/architecture.md)
- [数据库](database/database_design.md)
- [QGIS 生产流程](docs/gis/qgis_production_workflow.md)
- [GIS 数据治理](docs/gis/gis_data_governance.md)
- [GIS 角色矩阵](docs/gis/gis_role_matrix.md)
- [GIS 坐标标准](docs/gis/gis_crs_standard.md)
- [QGIS 暂存字段映射](docs/gis/qgis_staging_field_mapping.md)
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
- [Phase 1B GIS 交互审查](docs/review/phase1B_gis_interaction_review.md)
- [Phase 1C GIS 模型融合审查](docs/review/phase1C_gis_model_integration_review.md)
- [Phase 1D GIS 空间分析审查](docs/review/phase1D_gis_spatial_review.md)
- [GIS-OPT-1 QGIS 治理审查](docs/review/phase_gis_opt1_qgis_governance_review.md)
- [GIS-OPT-2 最终审查](docs/review/GIS-OPT-2_Final_Review.md)
