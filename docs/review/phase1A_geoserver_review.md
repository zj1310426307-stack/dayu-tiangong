# Phase 1A GeoServer 空间服务底座审查

日期：2026-08-12
结论：通过。完整 Compose、真实 OGC 服务、PostGIS 只读账号、FastAPI 和 GIS 浏览器页面均已验收。

## 1. 架构变化

静态制图链路升级为 `PostGIS → GeoServer → WMS/WMTS → Cesium`。FastAPI `/api/v1/gis/*` 继续承担属性详情、版本数据和模型/调度联动。PostGIS 仍是唯一数据源；GeoServer 数据卷只保存 catalog、样式和瓦片缓存。

## 2. Docker 与安全

- `geoserver` 使用 `docker.osgeo.org/geoserver:2.28.0`，数据卷为 `dayu_geoserver_data`，管理端口只绑定 `127.0.0.1:8081`。
- `geoserver-init` 在迁移、种子与 GeoServer 健康后幂等创建 catalog；实际输出为 workspace `dayu`、6 个图层、4 个缓存层、EPSG:4490。
- Nginx 只代理公开 OGC 路径，拒绝 `/rest`、`/web` 与 `/gwc/rest`。
- 管理密码、GeoServer 数据库密码仅通过环境变量提供，未写入源代码、文档或 Git。
- 后端镜像补齐既有 `optimization` 包，API 与 Celery Worker 均通过容器健康检查。

## 3. PostGIS 只读验证

`dayu_geoserver` 只获得数据库 `CONNECT`、schema `USAGE`、表/序列读取权限，并设置 `default_transaction_read_only=on`。在线脚本已实际完成 `SELECT`，同时证明 `DELETE FROM river WHERE false` 被 PostgreSQL 以 `ReadOnlySqlTransaction` 拒绝。GeoServer store 使用现有 `dayu_tiangong.public`，未创建第二数据库。

## 4. 图层发布

| 图层 | 类型 | SLD | WMS | WMTS |
|---|---|---|---|---|
| `dayu:river` | LineString | `river.sld` | 通过 | 通过 |
| `dayu:river_segment` | LineString | `river_segment.sld` | 通过 | 通过 |
| `dayu:river_node` | Point | `river_node.sld` | 通过 | 不缓存 |
| `dayu:cross_section` | Point | `cross_section.sld` | 通过 | 不缓存 |
| `dayu:gate` | Point | `gate.sld` | 通过 | 通过 |
| `dayu:pump` | Point | `pump.sld` | 通过 | 通过 |

6 个 SLD 均通过 XML 解析、GeoServer 上传和真实地图渲染。

## 5. OGC 与 API 在线验收

- WMS 1.3.0 capabilities 包含 6 个图层；GetMap 返回 `image/png`，尺寸为 512×384。
- WMTS capabilities 包含 4 个缓存层；`dayu:river` GetTile 返回 256×256 PNG，并带 `geowebcache-gridset: EPSG:900913`。
- WFS 2.0 capabilities 实际操作集合不含 `Transaction` 与 `LockFeature`，保持 Basic 查询级别。
- `/api/v1/gis/geoserver/health` 返回 healthy、6 个图层、4 个缓存层；图层清单与原 `/api/v1/gis/rivers` 同时可用。

## 6. Cesium 联动与浏览器验收

小比例尺使用 WMTS，大比例尺切换 WMS；WMS GetFeatureInfo 只提取业务主键，详情继续走 FastAPI 生成客户端。浏览器实测 PostGIS、GeoServer、Cesium 均显示在线，影像、河网、闸门与泵站样式成功渲染，当前视图显示“小比例尺 · WMTS”，控制台 0 warning / 0 error。截图归档在项目 `06_验证记录/2026-08-12_Phase1A-GIS页面验收.png`。

## 7. 自动化结果

- 后端全量测试（`RUN_POSTGIS_TESTS=1`）：105 passed。
- 前端 `npm run typecheck`：通过。
- 前端 `npm run build`：通过；5082 modules，GIS 页面 2.42 kB（gzip 1.36 kB），CesiumMap 8.35 kB（gzip 3.76 kB）。
- Cesium 独立 vendor 块约 4.17 MB，仍是后续性能优化项；GIS 路由和页面组件已按需加载。

## 8. 后续建议

- Phase 1B 补充 GeoJSON 与 WMTS 的冷/热加载时间、传输字节、浏览器内存对比，再制定预热层级与磁盘配额。
- 增加 GeoServer JVM、请求时延、GeoWebCache 命中率与磁盘配额监控。
- 生产环境改用 Docker secrets 或外部密钥管理，并取消 GeoServer 8081 主机映射，只保留反向代理。
- 当前仍为 DEMO DATA；真实工程使用前必须完成数据导入、率定与专项验证。
