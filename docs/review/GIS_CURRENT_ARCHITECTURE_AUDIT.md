# GIS-RESET-01 当前 GIS 架构审查

审查日期：2026-08-17
审查基线：`0eb6027`
任务性质：重构前只读盘点

## 结论

当前底座的数据治理部分已经成熟：PostGIS 是唯一业务空间数据库，QGIS 只能写 `staging_qgis`，发布数据通过 `publish` 只读视图进入 GeoServer，Dataset Version 提供不可变版本边界。因此无需另建 `dayu_gis` 第二数据库，也不应推翻 GIS-OPT-1。

需要重构的是运行与展示层。现状同时存在 QGIS Server、GeoServer、Martin、TiTiler、FastAPI 动态图元、Cesium 3D Tiles 和自定义 Registry/manifest 合并，浏览器需要八类 adapter 才能展示 Catalog。这个结构增加了部署、健康判断、版本隔离和故障定位成本，不适合作为最小稳定 WebGIS 核心。

## QGIS

### 保留

- `qgis/projects/dayu_tiangong_ltr.qgs`：三组职责、EPSG:4490、暂存编辑和发布只读工程。
- `qgis/plugins/dayu_tiangong_bridge/`：批次、质检、审核和发布操作入口。
- `qgis/styles/`、`qgis/docs/`、桌面启动脚本。

### 移出平台运行核心

- `qgis/server/` 的 server project builder、manifest、Gateway 配置与运行证据。
- Docker `qgis-server` 容器和 `dayu_qgis_server` 登录角色。
- FastAPI `/qgis-server/wms` 与 `/api/v1/gis/qgis-server/health`。

QGIS 的最终职责是工程数据生产、质检辅助和人工审核，不承担 Web 地图发布。

## GeoServer

现有 `dayu` workspace、`dayu_postgis` datastore、12 个 `publish` 图层、7 个缓存层、12 份 SLD 和 Basic WFS 均可复用。GeoServer 已通过只读数据库角色访问已发布版本，并明确禁用 WFS-T，适合成为唯一 WebGIS 地图服务。

需增加 FastAPI 受控 OGC Gateway，使浏览器地图请求统一进入 `/api/v1/gis/ogc/*`，由后端验证图层、数据版本、请求尺寸和参数后再访问内部 GeoServer。

## Backend GIS

### 已有能力

- `/api/v1/gis/rivers|cross_sections|gates|pumps`：版本隔离 GeoJSON 和属性详情。
- `/api/v1/gis/geoserver/*`：GeoServer 健康、图层和公开配置。
- `gis_layer_registry`：位于 PostGIS 的图层 allow-list。
- GIS Governance：QGIS 暂存、质检、审核、晋级、发布和退役。

### 重复与耦合

- `gis_catalog.service` 同时合并数据库 Registry、QGIS manifest、QGIS health、GeoServer、Martin、TiTiler 和 Cesium 能力。
- `qgis_server` Gateway 与 GeoServer 已有 OGC 服务职责重叠。
- Registry 中混合数据身份、QGIS renderer、Martin/TiTiler、动态图元和 3D 运行模式。

重构后，PostGIS Catalog 只描述 GeoServer 发布图层及安全字段；FastAPI 只负责目录、OGC 参数门禁和业务属性，不再选择多个地图服务。

## Frontend GIS

当前 GIS 页面使用 Cesium，并通过 adapter registry 支持 QGIS WMS、GeoServer WMS/WMTS、Martin MVT、TiTiler、FastAPI primitives 和 3D Tiles。地图业务层与三维运行时耦合，GPU/WebGL 故障会扩大为整个 GIS 模块故障。

重构目标是 `frontend/src/gis/` 下的单一 OpenLayers 2D 工作台：

- `MapView.tsx`：地图生命周期和 GeoServer WMS。
- `LayerManager.tsx`：图层开关、透明度、同组顺序。
- `Popup.tsx`：受控 FeatureInfo 属性。
- `StyleManager.ts`：选中/状态样式约定。
- `Coordinate.ts`：EPSG:3857 显示坐标格式。

前端不再维护业务图层枚举，也不再直接连接 QGIS Server、Martin、TiTiler 或 3D Tiles。

## 数据模型与坐标

现有 `river`、`cross_section`、`gate`、`pump` 比共享建议中的最小字段更完整，并已进入水动力模型与版本治理，不应降级为第二组简化表。`publish` 视图作为 GeoServer 来源继续保留。

- 权威存储：CGCS2000 / EPSG:4490。
- Web 地图：EPSG:3857。
- 地图重投影：由 GeoServer WMS 完成；浏览器不转换权威业务几何。

DEM、影像和洪水结果将在 GIS-RESET-02 以 GeoServer coverage/时态发布方式接入，本轮不保留 TiTiler/3D Tiles 作为默认运行依赖。

## 删除与保留矩阵

| 能力 | 决策 | 原因 |
|---|---|---|
| PostGIS、publish views、版本治理 | KEEP | 唯一事实源与发布边界已经成立 |
| GeoServer、SLD、WMS/WMTS/Basic WFS | KEEP/PRIMARY | 唯一地图服务出口 |
| QGIS Desktop、Plugin、Project、QML | KEEP/PRODUCTION | 专业数据生产端 |
| QGIS Server、manifest、Gateway | REMOVE | 与 GeoServer 发布职责重复 |
| 自定义多协议 Registry 运行合并 | REPLACE | 改为 PostGIS GeoServer Catalog |
| Cesium WebGIS | REMOVE FROM CORE | 最小 WebGIS 改用 OpenLayers |
| Martin、TiTiler、3D Tiles、GeoNode 默认编排 | REMOVE FROM CORE | 不再作为 GIS-RESET-01 运行依赖 |
| FastAPI GIS GeoJSON/属性/治理 | KEEP | 业务服务和安全门禁 |

## 风险与回滚点

- 旧 QGIS Server 与 Cesium 代码均有 Git/ZIP 备份，可按 `0eb6027` 恢复。
- 现有 Docker 卷不会因 Compose 文件删除服务定义而自动删除。
- 迁移必须在隔离数据库先执行 upgrade/downgrade/upgrade，持久数据库迁移需另行记录。
- 洪水栅格、3D 和高性能 MVT 不在最小闭环中；在 GIS-RESET-02 重新以统一 GeoServer 服务合同接入。
