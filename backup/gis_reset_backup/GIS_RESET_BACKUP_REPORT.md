# GIS-RESET-01 旧 GIS 架构备份报告

- 备份时间：2026-08-17
- 恢复基线提交：`0eb6027cfdb32905569b9d8e812eda3b70488b85`
- 工作分支：`agent/gis-reset-01`
- Git 完整历史包：`project-003-大禹天工/99_临时文件/GIS_RESET-01_pre_reset_0eb6027.bundle`
- 旧 GIS 源码归档：`project-003-大禹天工/99_临时文件/GIS_RESET-01_legacy_gis_0eb6027.zip`

## 已备份范围

- `qgis/`：QGIS Desktop 工程、插件、样式、启动脚本及旧 QGIS Server 生成链。
- `geoserver/`：GeoServer 初始化、校验与 SLD。
- `backend/app/qgis_server/`、`backend/app/gis_catalog/`：旧双服务 Catalog 与 Gateway。
- `frontend/src/gis/`、`frontend/src/components/gis/`：Cesium、多协议 adapter 与地图组件。
- `docker/`、`database/seed/gis_registry.py`、`docs/`：旧编排、Registry 播种与架构资料。

两个归档均由 Git 对已跟踪内容生成；完整历史包已经过 `git bundle verify`。用户原有、未跟踪的 `docs/review/Phase1_GIS_Base_Audit_Report.md` 不属于本次修改，也未被纳入归档。

## 重构后的保留内容

- 单一 PostGIS 数据库、`publish` 发布边界、Dataset Version 与 QGIS 受控暂存/审核/晋级链。
- QGIS Desktop、工程模板、QML 样式和 Bridge 插件。
- GeoServer `dayu` workspace、只读 PostGIS datastore、WMS/WMTS/WFS Basic 和 SLD。
- FastAPI 业务属性、空间查询、水动力、调度、优化和 AI 能力。

## 计划移除的运行时重复项

- QGIS Server 容器、Gateway、manifest/builder/隔离证据和专用登录角色初始化。
- 浏览器端 QGIS/GeoServer/Martin/TiTiler/Cesium 多协议 adapter 选择层。
- Martin、TiTiler、GeoNode 与 3D Tiles 在默认 GIS 运行链中的编排。
- QGIS Project 参与 Web 运行时 Catalog 合并的逻辑。

## 恢复方式

最小恢复可直接切回基线提交；完整仓库恢复可从 `.bundle` 克隆：

```powershell
git clone "..\..\99_临时文件\GIS_RESET-01_pre_reset_0eb6027.bundle" restored-dayu-tiangong
```

归档位于项目目录内，不包含密码、令牌或本机 `.env`。
