# 大禹·天工

面向河网数字孪生的水利数据治理、水动力计算、闸泵调度、多目标优化与 AI 辅助平台。

GIS-RESET-01 已将运行架构收敛为一条链路：

```text
QGIS Desktop → staging_qgis → 质检/审核/版本晋级 → publish
                                                       ↓
OpenLayers → FastAPI 安全边界 → GeoServer → PostGIS
```

## GIS 核心结论

- PostGIS 是唯一空间数据中心，不建立第二套 GIS 数据库。
- GeoServer 是唯一在线 GIS 服务，读取 `publish` 只读视图。
- OpenLayers 是唯一 WebGIS 渲染端，网页不保存第二份业务图层清单。
- QGIS Desktop 3.44 LTR 只用于专业数据生产，只能编辑 `staging_qgis`。
- 不开放 WFS-T，不允许 QGIS 直接修改核心表。
- Dataset Version、质检、人工审核、晋级、发布和退役链继续保留。
- QGIS Server、Martin、TiTiler、Cesium 多适配层和 GeoNode 不再属于核心运行编排。

## 核心运行组件

| 组件 | 职责 |
|---|---|
| PostGIS / TimescaleDB | 权威 GIS、治理、模型和时序数据 |
| GeoServer | 12 个 `publish` 图层的 WMS、WMTS、Basic WFS 与样式发布 |
| FastAPI | Catalog、版本门禁、WMS/FeatureInfo 安全代理和业务 API |
| OpenLayers | EPSG:3857 Web 地图、图层控制和属性点选 |
| QGIS Desktop | EPSG:4490 暂存编辑、拓扑检查和专业生产 |
| Redis / Worker | 模型、调度和后台任务 |
| Nginx | 前端静态资源、SPA 回退和同源 API 代理 |

## 本地启动

1. 从 `.env.example` 复制本机 `.env`，填写 GeoServer、QGIS 编辑/复核和后端运行账号的口令。
2. 启动 Docker Desktop。
3. 在仓库根目录运行：

```powershell
docker compose --env-file .env -f docker/docker-compose.yml up -d --build
```

默认入口：

- 应用：`http://127.0.0.1:8080/`
- 后端：`http://127.0.0.1:8001/`
- OpenAPI：`http://127.0.0.1:8001/docs`
- GeoServer：`http://127.0.0.1:8081/geoserver/`

核心初始化顺序为 `database → migrate → seed → qgis-bootstrap → app-bootstrap → geoserver-init → gis-catalog-seed → backend/worker → frontend`。后端使用非 owner 的 `dayu_backend` 登录，并继承 NOLOGIN `dayu_publisher` 发布组；数据库 owner 只用于迁移和初始化。

## GIS API

- `GET /api/v1/gis/health`
- `GET /api/v1/gis/catalog?dataset_version_id=...`
- `GET /api/v1/gis/layers?dataset_version_id=...`
- `GET /api/v1/gis/ogc/wms`（受控 GeoServer GetMap）
- `GET /api/v1/gis/feature-info`（受控 GeoServer GetFeatureInfo）
- `GET /api/v1/gis/rivers|cross_sections|gates|pumps`
- `POST /api/v1/gis-governance/batches/...`（暂存、质检、审核、晋级）
- `POST /api/v1/gis-governance/versions/{id}/publish|retire`

前端调用必须来自 `frontend/src/api/generated/client.ts`，该文件由 `npm run openapi:update` 从当前 FastAPI OpenAPI 生成。

## QGIS 生产端

双击 `qgis/Start_Dayu_QGIS.cmd` 可用短英文盘符启动仓库内的 QGIS 3.44 LTR 工程，规避 Windows 中文安装路径导致的 Python/SIP 加载问题。连接名固定为 `dayu_qgis`，真实密码只放在被忽略的 `.env`、本机凭据文件或 QGIS Authentication Manager。

详细流程见：

- `qgis/README.md`
- `docs/gis/qgis_production_workflow.md`
- `docs/gis/GIS_DEPLOY_GUIDE.md`
- `docs/architecture.md`

## 验证

```powershell
$env:PYTHONPATH='backend;.'
backend\.venv\Scripts\python.exe -m pytest -q
cd frontend
npm.cmd run openapi:update
npm.cmd run typecheck
npm.cmd run build
```

涉及数据库迁移、角色轮换或 GeoServer 配置的验证，应先在独立 Compose 项目和新卷中执行。不得把隔离验证结果冒充现有持久环境部署结果。

## 当前边界

这是工程原型和受控本地部署基线，不是生产高可用系统。统一 IAM、真实模型率定、PLC/SCADA 接入、生产 TLS/密钥托管、审计归档、备份恢复演练和集群高可用仍需后续建设。新发布 GIS 版本也不会自动成为已率定的水动力模型版本。
