# Phase DGIS-Foundation 审查

日期：2026-08-13  
状态：核心 DGIS 开发与在线验收通过；GeoNode datastore 隔离修正待最后一次 profile 重建复验。

> 本阶段内置栅格、时空状态和三维设施均为 DEMO DATA，不得用于真实工程决策。

## 1. DGIS 架构变化

- 保留 `PostGIS -> GeoServer -> Cesium` 和 `FastAPI -> 水动力模型 / 调度 / 分析 / AI` 两条既有主链。
- 在同一 PostgreSQL 17 / PostGIS 3.5 实例内接入 TimescaleDB；没有建立第二套业务空间数据库。
- 引入 Martin 负责 MVT、TiTiler 负责 COG、GeoNode 负责目录/元数据/权限、GDAL/OGR 负责格式转换。
- FastAPI 只提供时空业务契约、版本约束、受控代理和开源服务编排，不重写瓦片、栅格或资产管理引擎。
- React/Cesium 新增目录、图层树、时间回放、栅格、MVT、3D Tiles 和数据转换工作流。

## 2. 开源组件

| 组件 | 版本/来源 | 责任边界 |
| --- | --- | --- |
| GeoNode | `geonode/geonode:5.1.0`，可选 Compose profile | GIS 目录、元数据、用户权限和地图组合 |
| GDAL/OGR | Debian `gdal-bin` | Shapefile/GeoJSON/KML/DXF/GeoTIFF 校验与转换 |
| Martin | `ghcr.io/maplibre/martin:1.11.0` | PostGIS MVT 函数发布 |
| TimescaleDB | PackageCloud PostgreSQL 17 包，实测 2.26.4 | `feature_state` 时序 hypertable |
| TiTiler | `ghcr.io/developmentseed/titiler:2.2.0` | COG 元数据与 PNG 瓦片 |
| CesiumJS | 1.142 | 原生 MVT、影像和 3D Tiles 客户端 |

## 3. PostGIS 与时空设计

- 迁移 `20260813_0010` 创建 `feature_state`、`simulation_layer`、`imports` 和 `tiles` schema。
- `feature_state` 以绝对时间作为 TimescaleDB 分区维度，以 `dataset_version_id`、对象类型/ID、来源和可选任务保存状态来源。
- 状态是追加式事实；闸门/泵站的观测、调度和模拟状态不回写静态设计字段。
- `simulation_layer` 只登记任务、类型、时间范围、服务类型、URL、样式和版本，大型 COG/3D 资产不写入业务表。
- 已实测 Alembic=`20260813_0010`、TimescaleDB=`2.26.4`、`feature_state` hypertable 存在、`tiles` schema 有 5 个 MVT 函数。

## 4. GeoNode 集成

- GeoNode 放入可选 `geonode` profile，核心运行栈不会因其资源占用而被强制启动。
- GeoNode 元数据使用同一 PostgreSQL 服务内的 `dayu_geonode` 逻辑数据库；空间资产使用现有 `dayu_tiangong` 数据库与隔离 schema，避免复制业务空间事实。
- `bootstrap_geonode.py` 幂等创建最小权限账号、数据库和 schema，并连接现有 GeoServer/Redis。
- 官方 5.1 镜像已拉取；元数据库、Django migrations 和共享业务库内的独立 `geonode_assets` schema 已创建。
- 实测发现 GeoNode 的 `datastore` 别名需要把迁移表写入自有 schema；引导脚本已为数据角色设置 `search_path=geonode_assets,public`。
- 官方入口默认打印数据库 URL/密码；本项目薄镜像只对三行诊断输出做脱敏，不修改 GeoNode 应用代码。
- 修正后的 profile 重建、目录首页和权限入口仍列为最终复验项。

## 5. GDAL 能力

- 输入白名单：Shapefile ZIP、GeoJSON、KML、DXF、GeoTIFF；输出：PostGIS、RFC 7946 GeoJSON、COG。
- 上传大小、扩展名、ZIP 路径穿越、解压规模、Shapefile 必需文件、图层名和 SRID 均在 GDAL 前校验。
- 命令使用固定参数数组、超时与 `shell=False`；PostgreSQL 密码仅通过子进程环境变量传入。
- 栅格坐标转换使用 `gdalwarp -t_srs`，不是修改 CRS 标签。
- 真实容器测试已通过 GeoJSON 读取/转换及 GeoTIFF(EPSG:4326) → COG(EPSG:4490)，并确认 `IMAGE_STRUCTURE.LAYOUT=COG`。

## 6. Vector Tile

- `tiles.river`、`tiles.road`、`tiles.administrative_area`、`tiles.place_name`、`tiles.engineering_facility` 五个函数由 Martin 自动发现。
- 函数按 `dataset_version_id` 过滤，使用 `ST_TileEnvelope`、`ST_AsMVTGeom` 和 `ST_AsMVT`。
- Martin 使用只读、无继承账号，只可连接数据库、使用相关 schema、读取六张源表并执行瓦片函数。
- Nginx 对外统一暴露 `/vector/`，Cesium 使用原生 `MVTDataProvider`。
- Martin `/health`、`/catalog` 与实际 `tiles.river` MVT 均返回 200；代理瓦片为 `application/x-protobuf`、275 B。

## 7. 栅格与三维能力

- `dgis-assets` 幂等生成水深、流速、洪水风险三张有效 COG，TiTiler 只读挂载资产卷。
- FastAPI 栅格代理只接受 `simulation_layer` 中登记的 `/data/` 资产，禁止任意 URL 获取。
- 3D Tiles 1.1 DEMO 清单与 GLB 写入只读前端卷，通过 `/3d/` 暴露；Cesium 使用 `Cesium3DTileset.fromUrl`。
- 资产初始化与 TiTiler 健康检查通过；前端代理 COG PNG（883 B）、3D Tiles JSON（586 B）和 GLB（468 B）均返回 200。

## 8. API 与前端

- 新增健康、目录、时空状态写入/查询/回放、模型图层、3D Tiles、栅格瓦片和 GDAL 转换 API。
- OpenAPI 已同步到 `frontend/src/api/generated/client.ts`；DGIS 组件没有直接手写 `fetch`。
- 新增 `Catalog`、`LayerTree`、`TimeController`、`RasterLayer`、`VectorTileLayer`、`ThreeDViewer`、`DataManager`。
- 前端生产构建通过：Vite 转换 5100 modules；Cesium 仍是较大的独立懒加载 vendor chunk。

## 9. 测试与性能

- 数据卷升级前已停机克隆备份：源卷和备份卷均为 PostgreSQL 17、2245 个文件。
- 迁移第一次真实执行暴露 JSON 冒号被 SQLAlchemy 解析为 bind 的问题；事务自动回滚，改为 DBAPI driver SQL 后迁移通过。
- 后端现有离线回归无失败；连接真实 PostGIS/TimescaleDB/Martin/TiTiler 的 DGIS 专项为 `5 passed`。
- 前端 TypeScript + Vite 生产构建通过；npm audit 为 0 vulnerabilities（构建日志）。
- 性能脚本执行一次预热和 10 次顺序请求。中位延迟：GeoJSON 5.733 ms、WMS 18.213 ms、WMTS 6.575 ms、MVT 2.283 ms；响应大小分别为 1627 B、5454 B、4531 B、275 B。
- 该结果只代表本机 DEMO DATA 热缓存基准；真实工程数据仍需按要素规模、缩放级别和并发量单独压测。

## 10. 后续建议

1. 生产环境为 GeoNode 补齐 SSO、对象存储、反向代理、邮件和异步 worker，不复用本地开发口令。
2. 为真实模型任务建立 COG/3D Tiles 资产生命周期、校验和、对象存储 URL 和过期清理策略。
3. 对千万级河网使用真实数据执行 MVT 压测，并按缩放级别简化几何和裁剪属性。
4. 为 TimescaleDB 增加保留/压缩策略前，应先确认监管留存和回放精度要求。
5. DEMO 验收完成后再接入真实监测、BIM 或设备数据；当前平台仍不具备真实控制下发权限。

## 验收清单

- [x] TimescaleDB 接入、hypertable 与时空模型
- [x] GDAL 真实 GeoJSON/COG 转换和坐标转换
- [x] 五类 MVT 数据库函数与最小权限角色
- [x] TiTiler COG 和 3D Tiles 资产初始化
- [x] OpenAPI 生成客户端与七个 DGIS 前端组件
- [x] 前后端生产构建与离线回归
- [x] 修正后的 Martin 在线健康、目录与实际 MVT 瓦片
- [ ] GeoNode profile 在线目录、元数据与权限入口
- [x] 前端代理 COG/3D Tiles 与协议性能实测
