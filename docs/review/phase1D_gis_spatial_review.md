# Phase 1D GIS 空间分析底座审查

日期：2026-08-13
结论：Phase 1D 开发、真实 PostGIS 回归、Docker Compose 增量部署与 OGC 在线验收全部通过。

## 1. GIS 架构变化

- 继续保持 PostGIS 为唯一 GIS/模型数据源，没有新建第二套空间数据库。
- 静态底图与工程图层使用 `PostGIS -> GeoServer -> WMS/WMTS -> Cesium`。
- 水动力、调度、空间分析和对比结果使用 `PostGIS -> FastAPI -> Cesium Primitive`。
- 迁移 `20260813_0009` 新增 `administrative_area`、`road`、`place_name`、`water_name`、`poi` 五张版本化表。
- OpenAPI 已同步，前端仅通过生成客户端访问 Phase 1D 搜索与分析 API。

## 2. GeoServer 检查

- 已发布 12 个静态图层，新增 5 个底图图层与 `dayu_basemap` 命名图层组。
- 道路、地名、水名进入 GeoWebCache，总计 7 个 WMTS 缓存图层。
- 5 个新 SLD 均含比例尺阈值；行政区、道路、地名、水名与 POI 样式已在源码中固化。
- 在线验收已验证 `dayu_basemap` 实际 GetMap PNG，且 CQL 强制 `dataset_version_id=1`。
- WFS 保持 Basic 只读，GeoServer 数据库角色 `default_transaction_read_only=on`，实际 DML 被拒绝。

## 3. 注记检查

- 延用 Phase 1C `map_annotation`，支持河道、闸门、泵站、水文站、调度事件和参数标注。
- 后端按比例尺和当前视域返回注记，模型/调度文本按同一时刻动态更新。
- Cesium 继续使用单一 `LabelCollection`，1001 条注记专项测试通过。

## 4. 定位检查

- `GET /api/v1/gis-analysis/search` 支持 EPSG:4490 经纬度严格解析，越界坐标返回稳定 409。
- 文本搜索仅查询本地 PostGIS，支持广州市、广州市天河区天寿路、道路、水名与 POI。
- 坐标 `113.3238,23.1356` 已在真实 API 返回坐标解析结果；点击结果后 Cesium 飞行定位、加入 Primitive 标记并更新坐标栏。

## 5. 图层管理检查

- `LayerManager` 已按基础地图、水利工程、分析结果、调度状态分组；分析组拆分水位/流速/风险，调度组拆分闸门/泵站。
- 每个图层支持显隐、透明度、组内顺序调整，图例覆盖正常/警戒/危险、流向、运行/停止。
- 中小比例尺使用 WMS，大范围自动切换 WMTS；数据版本作为 CQL/瓦片维度。

## 6. 空间分析检查

- 沿河追踪使用 `river_connection` 有向拓扑，返回上下游河道、断面、闸门和泵站。
- 框选基于 Cesium 当前视域；缓冲和最近设施使用 PostGIS geography 米制计算。
- 结果使用 `PointPrimitiveCollection` / `PolylineCollection` 渲染，未批量创建 Entity。

## 7. 水动力融合检查

- 水位按 `normal/warning/danger` 分级；流速同时表达大小、方向和等级。
- 时间轴使用同一 `interaction-frame` 同步水位、流速、风险和调度状态。
- A/B 空间对比以断面 ID 和结构物 ID 对齐，禁止跨数据版本对比。

## 8. 闸泵联动检查

- 闸门可视化模拟开度、流量、状态；泵站可视化启停、流量和功率。
- 约束标志使用高亮轮廓，调度事件包含时间、动作、原因与约束。
- 所有结果均标明 DEMO，前后端明确 `execution_authorized=false`，不具备真实设备执行权限。

## 9. Cesium 性能与验证

- 保留 Primitive、Vector Tile、分级加载与注记聚合，页面显示 FPS、JS 堆内存、请求耗时/体积和图层数。
- 真实 PostGIS 全量后端测试：124 passed。
- 前端：`npm run typecheck` 和 `npm run build` 通过，Vite 转换 5093 modules。
- Docker：数据库、Redis、GeoServer、Backend、Worker、Frontend 全部健康；迁移、播种、GeoServer 初始化正常退出。
- 专题图：A4 横版单页 PDF，已渲染检查，图例、比例尺、指北针、坐标、时间、数据/模型版本完整，无裁切或重叠。

## 10. 存在问题

- 当前基础地图、水动力和调度数据均为 DEMO，不能代替工程率定、生产容量测试或实时遥测。
- 由于 Codex 桌面应用安全策略拒绝浏览器自动化访问本机 `127.0.0.1`，本次未重复 Phase 1C 的 UI 点击回归；以生产构建、真实 API/OGC 验收与 PDF 视觉验收覆盖。
- Cesium vendor 块约 4.17 MB，已路由懒加载和独立分块；首次进入 GIS 仍有下载与解析成本。
- MVT 已提供服务端能力，当前主视图仍以 WMS/WMTS + Primitive 为主，生产超大规模连续场可进一步评估 3D Tiles/时空瓦片。
