# 大禹·天工

> Docker Compose requires an explicit `ENGINE_COMMIT`. Local development may use
> `DAYU_BUILD_MODE=development` with `ENGINE_COMMIT=development-unverified`; CI and
> release require the actual lowercase 40-character Git SHA. Backend and Workers
> share the resulting `dayu-backend:<ENGINE_COMMIT>` image.

面向河网数字孪生的水利数据治理、水动力计算、闸泵调度、多目标优化与 AI 辅助平台。

## 当前架构状态

自 2026-08-31 起，生产级 Standard 1D 正式采用“Dayu 统一水力模型 → MASCARET Adapter → 外部 MASCARET v9.1.1 → 统一结果”路线；旧自研 1D Solver 已退出生产代码、API、Worker、前端和 CI。HYDRO-DATA-01 的 Network → Branch → Chainage → Cross Section 权威数据结构保持不变。

- [MASCARET 1D Adapter](docs/model/MASCARET-1D-ADAPTER.md)
- [HYDRO-1D-RESET-01 架构迁移](docs/migration/HYDRO-1D-RESET-01.md)
- [当前系统架构](docs/architecture.md)

## 历史发布记录

2026-08-24 的“持续优化 01”已完成文件入口与 Dataset Version 查询边界收敛；其[现状审查](docs/audit/CURRENT_STATE_AUDIT.md)、[执行计划](docs/plan/OPTIMIZATION_EXECUTION_PLAN.md)、[验证报告](docs/verification/OPTIMIZATION_VERIFICATION_REPORT.md)和[发布说明](docs/release/OPTIMIZATION_RELEASE_NOTES.md)是当时基线的归档记录，不代表当前水动力求解路线。

GIS-RESET-01 已将运行架构收敛为一条链路：

```text
QGIS Desktop → staging_qgis → 质检/审核/版本晋级 → publish
                                                       ↓
OpenLayers → FastAPI 安全边界 → GeoServer → PostGIS
          └→ FastAPI 影像代理 → Esri World Imagery / NASA GIBS
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
| PostGIS / TimescaleDB | 权威 GIS、水动力交换语义、治理、模型和时序数据 |
| GeoServer | 6 个版本化业务层与 3 个广东开放参考层的 WMS、WMTS、Basic WFS 与样式发布 |
| FastAPI | Catalog、版本门禁、WMS/FeatureInfo、白名单在线影像瓦片安全代理和业务 API |
| OpenLayers | EPSG:3857 Web 地图、图层控制和属性点选 |
| QGIS Desktop | EPSG:4490 暂存编辑、拓扑检查和专业生产 |
| Redis / Worker | 模型、调度和后台任务；Standard 1D 任务进入独立 `hydraulic-1d` 队列 |
| MASCARET v9.1.1 | 外部一维水动力运行时；由 Adapter 通过官方 CLI/独立进程调用，不复制到 Dayu 代码库 |
| Nginx | 前端静态资源、SPA 回退和同源 API 代理 |

## 本地启动

1. 从 `.env.example` 复制本机 `.env`，填写 GeoServer、QGIS 编辑/复核和后端运行账号的口令。
2. 启动 Docker Desktop。
3. 在仓库根目录运行：

```powershell
docker compose --env-file .env -f docker/docker-compose.yml up -d --build
```

核心初始化顺序为 `database → migrate → seed → qgis-bootstrap → app-bootstrap → geoserver-init → gis-catalog-seed → backend/worker/hydraulic-worker → frontend`。后端使用非 owner 的 `dayu_backend` 登录，并继承 NOLOGIN `dayu_publisher` 发布组；数据库 owner 只用于迁移和初始化。默认镜像只包含 MASCARET Adapter，不捆绑 MASCARET 本体；未配置官方运行时时 `MASCARET_ENABLED=0`。

## GIS API

- `GET /api/v1/gis/health`
- `GET /api/v1/gis/catalog?dataset_version_id=...`
- `GET /api/v1/gis/layers?dataset_version_id=...`
- `GET /api/v1/gis/ogc/wms`（受控 GeoServer GetMap）
- `GET /api/v1/gis/feature-info`（受控 GeoServer GetFeatureInfo）
- `GET /api/v1/gis/basemaps/{key}/tiles/{z}/{y}/{x}.jpeg`（受控高分辨率/后备影像瓦片）
- `GET /api/v1/gis/rivers|cross_sections|gates|pumps`
- `POST /api/v1/gis-governance/batches/...`（暂存、质检、审核、晋级）
- `POST /api/v1/gis-governance/versions/{id}/publish|retire`

前端调用必须来自 `frontend/src/api/generated/client.ts`，该文件由 `npm run openapi:update` 从当前 FastAPI OpenAPI 生成。

## 水动力数据交换

`/data-center/hydraulic` 将 Network–Node–Branch–Reach–Chainage、断面多地形版本、糙率分区、水力查算、导入审计、校核与 MIKE11 交换能力收敛到一个管理页。导入使用“预览校验 → 配置 hash 确认提交”两阶段流程，并在同一数据库事务内写入 `hydraulic` 权威语义和现有 GIS 兼容投影。显示几何统一为 CGCS2000 `EPSG:4490`；拓扑、长度和桩号只能使用明确确认的米制 engineering CRS。

- `POST /api/v1/hydraulic/imports/preview|commit`
- `GET /api/v1/hydraulic/networks|cross-sections/{section_id}|imports`
- `POST /api/v1/hydraulic/networks/{network_id}/topology`
- `POST /api/v1/hydraulic/branches/{branch_id}/reverse|recalculate-chainage`
- `POST /api/v1/hydraulic/cross-sections/{section_id}/locate`
- `POST /api/v1/hydraulic/profiles/{profile_id}/process|process-batch`
- `POST /api/v1/hydraulic/validation/run`
- `GET /api/v1/hydraulic/validation/{run_code}`
- `GET /api/v1/hydraulic/exports/network.nwk11|cross-sections.xns11`
- `GET /api/v1/hydraulic/templates/river-network|cross-section`
- Simulation Case 转统一 Hydraulic 1D Model 由服务端 Model Builder 完成，前端不接触 MASCARET 私有文件。

内置 `.nwk11`/`.xns11` 支持是 HYDRO-DATA-01 的确定性交换子集，能力状态固定标识为 `ROUNDTRIP_VALIDATED_ONLY`，不宣称已通过 DHI 商业软件原生验收。常驻后端不加载 DHI/mikeio 运行时；原生 NWK11/XNS11 读取、转换和验收属于授权外部适配环境。

## 水动力求解器能力边界

当前正式一维技术路线是：

```text
HYDRO-DATA-01 (Network → Branch → Chainage → Cross Section)
  → Dayu Unified Hydraulic Model
  → MASCARET Adapter
  → 经身份校验的官方 MASCARET v9.1.1 外部进程 / 容器
  → Opthyca Result Parser
  → Dayu Unified Hydraulic Result
```

- Dayu 保留统一数据、自动建模、任务生命周期、GIS 和结果体系，不再开发或提供自研生产级 1D 数值求解器。
- MASCARET 源码不复制到本仓库；可重复构建从官方 `v9.1.1`、提交 `1fe3b514` 和固定的规范化源码树哈希生成原生运行时。
- External 模式核对二进制 SHA-256、官方资源摘要、tag、commit 和构建时间；Container 模式只接受不可变镜像 digest，并核对 OCI version/revision/created 标签。
- 默认发布镜像不捆绑 MASCARET，因此默认 `MASCARET_ENABLED=0`。未发现可用运行时的集成测试必须明确记录 `SKIPPED_MASCARET_RUNTIME_NOT_AVAILABLE`，不允许伪造成功运算。
- 闸门与泵站当前均不进入生产 Adapter；在完整业务语义、官方文件合同和真实运行时 benchmark 全部验证前必须 fail closed，不得伪装成横向流量或猜测奇异建筑物参数。
- 五组真实数值算例、官方示例、生命周期和平台验收见 [MASCARET 正式验证](docs/hydraulics/mascaret-validation.md)；现行映射见 [MASCARET 1D Adapter](docs/model/MASCARET-1D-ADAPTER.md)。
- 旧 `HYDRO-MODEL-02` 阶段文档、审查过程和失效工作计划已从当前树清理；仅保留一份最终 D3A RC1 发布索引，完整历史由 Git 标签保存，不能作为现行产品说明。

## 广东开放参考数据

- 行政区：geoBoundaries 中国 ADM1/ADM2，经广东范围筛选后导入 `reference_data.administrative_area`。
- 道路、水系：OpenStreetMap 广东快照，经广东边界裁剪后导入 `reference_data.road|waterway`。
- 地图标注统一读取审核后的 `name_zh`：93 个行政区全部使用中文名；道路和水系只显示可确认的中文名或标准中文路线编号，未知外文名与“未命名”占位符不进入地图。原始 `name` 保留用于来源追溯。
- GeoServer 镜像内置 Noto Sans CJK SC，避免服务端 WMS 标注出现方框、乱码或缺字。
- 高分辨率影像：Esri World Imagery 作为默认底图，支持放大到建筑可辨的层级；NASA Blue Marble/VIIRS 作为后备，默认关闭。
- 浏览器只访问同源 FastAPI 代理。Esri World Imagery 是在线授权服务而非开放数据，不做离线导出；页面必须保留 Esri 及其数据提供方署名。
- 三类参考数据不绑定 Dataset Version；六类水利核心层继续按已发布版本过滤。

来源、许可、快照哈希和处理结果见项目外层 `03_参考资料/2026-08-17_GIS开放数据/manifests/SOURCE_MANIFEST.md`。

## 地图坐标定位

GIS 一张图顶部提供“图层管理”和“坐标定位”两个工具菜单，默认均收起；点击按钮展开，再次点击收起，切换工具时始终只打开一个面板。面板只隐藏而不卸载，因此图层开关、坐标输入和定位结果都会保留。坐标工具提供三种模式：EPSG:4326 十进制度的“经度、纬度”、当前 WebGIS 投影 EPSG:3857 米制的“Web XY”，以及 CGCS2000 三度带高斯-克吕格坐标。CGCS2000 模式按常用 GIS 顺序输入 `X=东坐标`、`Y=北坐标`，并要求明确选择 111°E（EPSG:4546）、114°E（EPSG:4547）或 117°E（EPSG:4548）中央经线；定位后同时显示转换得到的经纬度。地图会平滑放大到 17 级并显示临时红色标记；点击“清除”只移除标记，不修改发布图层或权威数据。地图左下角随鼠标同时显示经纬度和 Web XY。

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

## 历史自研 Solver 发布证据（已归档）

自研 `v4-lite` / D1 / D3A 求解路线已由 HYDRO-1D-RESET-01 废止；旧示例、运行工具
和阶段性报告不再随当前生产代码分发。其最终发布事实见
`docs/release/HYDRO-MODEL-02-D3A-RC1-release.md`，完整实现与验证证据由 Git 历史及
`hydro-model-02-d1-rc1`、`hydro-model-02-d2-rc2`、`hydro-model-02-d3a-rc1` 标签保存。
这些历史材料不得作为重新启用自研生产 Solver 的依据。

## 当前边界

这是工程原型和受控本地部署基线，不是生产高可用系统。统一 IAM、真实模型率定、PLC/SCADA 接入、生产 TLS/密钥托管、审计归档、备份恢复演练和集群高可用仍需后续建设。新发布 GIS 版本也不会自动成为已率定的水动力模型版本。
