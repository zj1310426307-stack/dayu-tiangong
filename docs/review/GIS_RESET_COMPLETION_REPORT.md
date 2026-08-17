# GIS-RESET-01 完成报告

日期：2026-08-17
状态：实现完成，隔离运行验收通过；持久环境未部署

## 完成范围

- 迁移前 Git bundle 和旧 GIS 资产 ZIP 已生成并验证。
- PostGIS 保持唯一数据中心，未创建第二套 GIS 数据库。
- 新增 Alembic 0015，将活动目录收敛为 12 个 `publish` GeoServer WMS 图层。
- 新增 PostGIS Catalog seed 和 GeoServer SELECT 权限验证。
- 移除 QGIS Server 运行模块、工程生成器、清单和 Compose 服务。
- 从核心 Compose 移除 Martin、TiTiler、GeoNode 和 3D 资产链。
- 前端删除 Cesium 与多协议 adapter，改为 OpenLayers 唯一 WebGIS。
- 新 WebGIS 支持底图、河道、断面、闸、泵、图层开关、透明度、顺序和属性点选。
- WMS 与 FeatureInfo 通过 FastAPI allow-list，浏览器不直接构造 GeoServer 数据源或 CQL。
- OpenAPI 生成器和 generated client 已同步。
- QGIS Desktop 暂存生产、治理、Dataset Version、发布和退役流程保留。

## 已删除但可恢复

- `backend/app/qgis_server/`
- `qgis/server/`
- `database/seed/gis_registry.py`
- QGIS Server / GeoNode bootstrap 与 Dockerfile
- Cesium GIS 组件和 `frontend/src/gis` 多服务适配层

恢复来源：

- `99_临时文件/GIS_RESET-01_pre_reset_0eb6027.bundle`
- `99_临时文件/GIS_RESET-01_legacy_gis_0eb6027.zip`

## 当前验证证据

- 后端/仓库离线测试：`192 passed, 69 skipped`。
- OpenAPI generated client：由本次 FastAPI 实例重新生成。
- 前端 TypeScript：通过。
- 前端生产构建：通过；OpenLayers 独立分块约 191 kB，未再输出 Cesium 分块。
- Compose 静态配置：主配置与隔离 override 均通过。
- 隔离全新卷：0015 从空库升级成功；seed、QGIS/App bootstrap、GeoServer init 和 Catalog seed 均退出码 0。
- 隔离迁移回退：`0015 → 0014 → 0015` 成功，重跑初始化保持幂等。
- 真实 PostGIS 专项：`24 passed`；降级再升级后复跑仍为 `24 passed`。
- GeoServer 在线验证：12 层、7 个缓存层、注记 WFS、版本过滤 WMS/WMTS、Basic WFS 无 Transaction/LockFeature、只读账号与 FastAPI 联动均通过。
- API 实测：单一 `GEOSERVER_WMS` 服务、12 层、WMS PNG 10,306 bytes；河道 FeatureInfo 返回 2 个要素。
- 浏览器实测：`http://127.0.0.1:8085/gis` 正常，PostGIS/GeoServer/OpenLayers 在线，5/12 默认可见，河网/闸泵渲染和图层面板正常。
- 持久环境：未迁移、未轮换角色、未替换当前运行栈。
- 隔离环境：验收完成后已删除临时容器、网络和三只测试卷；持久 `dayu-tiangong-phase1` 未操作。

## 明确不在本阶段

- 第二 GIS 数据库、WFS-T、Web GIS 编辑器。
- QGIS Server、三维和栅格服务回迁。
- 统一 IAM、真实模型率定、PLC/SCADA、生产高可用。

## 判定

代码、隔离数据库、GeoServer 与浏览器已经证明 PostGIS → GeoServer → OpenLayers 单一链路成立。持久环境部署仍需单独授权、备份和维护窗口。
