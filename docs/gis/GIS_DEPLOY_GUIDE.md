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
2. 0018 `upgrade head` 成功，且 Alembic 只有一个 head。
3. demo seed 连续执行两次保持幂等。
4. `qgis-bootstrap`、`app-bootstrap` 完成。
5. 使用 `database/import_open_reference_data.py` 导入广东开放数据；最低门禁为行政区 20、道路 1000、水系 100，当前验证快照分别为 93、168554、19749。导入器同时写入中文展示字段 `name_zh`，不得覆盖用于溯源的原始 `name`。
6. `geoserver-init` 完成，9 个活动 `publish` 图层可读，WFS 无 Transaction/LockFeature。
7. `gis-catalog-seed` 返回 9 个源、9 项 GeoServer SELECT 权限与 3 个影像底图；Esri 高分辨率层默认可见，2 个 NASA 层默认关闭。
8. backend、worker、frontend 健康。
9. Catalog、WMS、FeatureInfo、广东影像瓦片和 OpenLayers 页面通过。
10. GeoServer 容器内 `fc-list :lang=zh` 可找到 Noto Sans CJK SC；三类参考图层 SLD 均读取 `name_zh`，WFS 返回的非空 `name_zh` 必须包含中文字符。
11. 在同一隔离库演练 `downgrade 20260817_0017 → upgrade head`，再重跑数据导入、seed/bootstrap。
12. 确认地图初始只显示顶部“图层管理/坐标定位”菜单，两面板均收起；验证按钮可展开、再次点击可收起、两个工具互斥打开且收起后状态保留。再分别用经纬度 `113.2644, 23.1291` 和 EPSG:3857 Web XY `12608535.333, 2647638.583` 定位广州，确认两种模式到达同一建筑位置；用 CGCS2000 `X=641444.743`、`Y=2464480.899` 验证中央经线切换与经纬度回显，并检查缺失输入、三套范围限制和“清除”按钮。

## 3. 持久环境迁移

持久迁移会改变数据库结构、活动 Catalog 行、数据库角色密码/授权和 GeoServer 配置，必须在明确授权和维护窗口内执行。

```powershell
docker compose --env-file .env -f docker/docker-compose.yml pull
docker compose --env-file .env -f docker/docker-compose.yml up -d --build
docker compose --env-file .env -f docker/docker-compose.yml ps -a
```

0016 迁移只创建结构与 Catalog 定义，不把百兆级数据写进 Git。迁移后应从项目外层已归档、已校验的数据目录执行导入器，再启动 `geoserver-init` 和 `gis-catalog-seed`。导入器先写临时表、检查最小数量，再在单事务内替换三张 `reference_data` 表；任何失败都会保留原有正式参考数据。

0018 新增 `name_zh`、中文约束和中文优先发布视图。升级前应保留数据库备份；升级后确认行政区 93/93 有中文标注，道路和水系的非空展示值全部含中文。未知外文名称应保持 `name_zh IS NULL`，不能以拼音或来源编号回退显示。

不要输出展开后的完整 Compose 配置，以免把环境密码写入终端日志。

## 4. 验收地址

- `/api/v1/gis/health`
- `/api/v1/gis/geoserver/health`
- `/api/v1/gis/catalog?dataset_version_id=<published-id>`
- `/api/v1/gis/layers?dataset_version_id=<published-id>`
- `/api/v1/gis/ogc/wms?...`
- `/api/v1/gis/feature-info?...`
- `/api/v1/gis/basemaps/nasa_blue_marble/tiles/7/55/104.jpeg`
- `/api/v1/gis/basemaps/esri_world_imagery/tiles/18/113752/213548.jpeg`
- `/gis?datasetVersionId=<published-id>`

页面应只显示 PostGIS、GeoServer、OpenLayers 三项在线状态。浏览器请求不应出现 `/qgis-server/`、`/vector/`、TiTiler 或 Cesium 静态资源。

广州城区 z18 验收瓦片应能清晰分辨建筑、道路和场地。Esri World Imagery 只能在线浏览，必须展示数据提供方署名，不得用本流程批量下载或制作离线影像包。

坐标定位面板支持 EPSG:4326 十进制度（经度、纬度）、EPSG:3857 米制 Web XY，以及 CGCS2000 三度带高斯-克吕格坐标。CGCS2000 采用 `X=东坐标`、`Y=北坐标` 的 GIS 输入约定，必须由资料来源确认中央经线后选择 111°E（EPSG:4546）、114°E（EPSG:4547）或 117°E（EPSG:4548）；系统不会根据数值猜测分带。切换坐标类型会清空输入，切换中央经线会清除旧定位结果但保留 X/Y 供重新定位。该能力只控制当前浏览器地图视图和临时标记，不写入 PostGIS，也不改变 Dataset Version。GCJ-02 和 BD-09 仍不能直接混用。

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
