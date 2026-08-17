# GIS-RESET-01 部署指南

## 1. 部署前检查

1. 备份数据库、GeoServer data dir 和当前 Git 提交。
2. 确认 `.env` 未被 Git 跟踪，并填写：
   - `POSTGRES_PASSWORD`
   - `GEOSERVER_ADMIN_PASSWORD`
   - `GEOSERVER_DB_PASSWORD`
   - `QGIS_EDITOR_DB_PASSWORD`
   - `QGIS_REVIEWER_DB_PASSWORD`
   - `BACKEND_DB_PASSWORD`
3. 确认 5432、8001、8080、8081 不被其他项目占用。
4. 先在独立 Compose project 和新卷完成迁移与验收。

## 2. 隔离验收

为隔离项目设置不同的 project name、宿主端口和具名卷。不得复用 `dayu_postgres_data`、`dayu_geoserver_data` 或当前持久容器。

验收顺序：

1. `database` 健康。
2. 0015 `upgrade head` 成功，且 Alembic 只有一个 head。
3. demo seed 连续执行两次保持幂等。
4. `qgis-bootstrap`、`app-bootstrap` 完成。
5. `geoserver-init` 完成，12 个 `publish` 图层可读，WFS 无 Transaction/LockFeature。
6. `gis-catalog-seed` 返回 12 个源与 12 项 GeoServer SELECT 权限。
7. backend、worker、frontend 健康。
8. Catalog、WMS、FeatureInfo、OpenLayers 页面通过。
9. 在同一隔离库演练 `downgrade 20260815_0014 → upgrade head`，再重跑 seed/bootstrap。

## 3. 持久环境迁移

持久迁移会改变数据库结构、活动 Catalog 行、数据库角色密码/授权和 GeoServer 配置，必须在明确授权和维护窗口内执行。

```powershell
docker compose --env-file .env -f docker/docker-compose.yml pull
docker compose --env-file .env -f docker/docker-compose.yml up -d --build
docker compose --env-file .env -f docker/docker-compose.yml ps -a
```

不要输出展开后的完整 Compose 配置，以免把环境密码写入终端日志。

## 4. 验收地址

- `/api/v1/gis/health`
- `/api/v1/gis/geoserver/health`
- `/api/v1/gis/catalog?dataset_version_id=<published-id>`
- `/api/v1/gis/layers?dataset_version_id=<published-id>`
- `/api/v1/gis/ogc/wms?...`
- `/api/v1/gis/feature-info?...`
- `/gis?datasetVersionId=<published-id>`

页面应只显示 PostGIS、GeoServer、OpenLayers 三项在线状态。浏览器请求不应出现 `/qgis-server/`、`/vector/`、TiTiler 或 Cesium 静态资源。

## 5. QGIS Desktop

QGIS 不在 Docker 中运行。Windows 操作者双击 `qgis/Start_Dayu_QGIS.cmd`，通过 `dayu_qgis` service 和本机凭据连接数据库。

验收至少包含：

- 工程正常打开，无 SIP/Python 错误。
- 3 个顶层组、4 个暂存可编辑层和只读参考/发布层正确。
- 编辑者可插入暂存业务字段，来源字段由触发器回填。
- 审核状态后暂存写入被数据库拒绝。
- 核心表和 publish 不能被编辑者写入。

## 6. 回退

应用回退优先使用上一个已验证 Git 提交和数据库备份。Alembic downgrade 仅用于一次性验证库；它不是生产恢复机制。QGIS Server 等已删除资产可从 `99_临时文件/GIS_RESET-01_legacy_gis_0eb6027.zip` 或 Git bundle 恢复审计，不应在故障时临时拼回生产链。
