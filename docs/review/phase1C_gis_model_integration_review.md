# Phase 1C GIS 与模型融合审查

日期：2026-08-13
结论：代码、本地运行与 Docker Compose 在线验收全部通过；`map_annotation` 已作为第 7 个 GeoServer 图层发布。

## 1. 架构与数据

- PostGIS 仍是唯一 GIS/模型数据源，没有建立第二套空间数据库。
- 迁移 `20260813_0008` 新增版本化 `map_annotation`，几何固定为 `Point/4490`，并由约束保证经纬度、几何、比例尺和类型一致。
- 演示库迁移及播种成功：31 条基础注记，SRID 全部为 4490。
- GeoServer 目录、SLD、发布脚本和验证脚本已扩展至 7 个图层；`map_annotation` 已在线发布且不进入 GeoWebCache，避免高频编辑造成缓存失效复杂化。
- FastAPI 新增 `/api/v1/gis-analysis`，路由只处理 HTTP 边界，业务逻辑位于 `service.py` 与 `annotation.py`。

## 2. 专业 GIS 能力

- 注记支持 CRUD、类型、颜色、字号、旋转、比例尺、版本、关联对象和动态显示文本。
- 横断面标签可叠加所选时刻水位/流速；闸泵标签可叠加开度、流量、功率；调度事件使用瞬态高位 ID，不污染基础注记表。
- 沿河追踪使用 `river_connection` 有向拓扑；框选使用当前 Cesium 视域；缓冲和最近设施使用 PostGIS geography 米制计算。
- 水位风险、流速/流向、闸泵状态继续通过同一原子时间帧叠加。
- A/B 方案按断面 ID 和结构类型/ID 对齐，限制在同一数据版本，响应明确 `execution_authorized=false`。
- PostGIS MVT 端点使用 `ST_TileEnvelope`、`ST_AsMVTGeom` 和 `ST_AsMVT`，查询参数强制携带数据版本。

## 3. Cesium 与性能

- 新增 `LayerManager`、`AnnotationLayer`、`SpatialAnalysis`、`TimelineController`、`ResultRenderer`。
- 注记使用一个 `LabelCollection`；模型、空间分析和比较使用 `PointPrimitiveCollection` / `PolylineCollection`，未批量创建 Entity。
- 1001 条注记接口专项测试通过；前端超过 500 条时按相机比例尺进行地理网格聚合。
- 页面显示 FPS、JS 堆内存、图层数、标注数和 WMS/WMTS/GeoJSON 请求时延/体积。
- 浏览器实测样本：36 FPS、JS 堆 71.2 MB、13 层、3 条当前视域注记；WMS 331 ms / 5.8 KB，WMTS 327 ms / 4.4 KB，GeoJSON 329 ms / 1.6 KB。该样本只代表本机单次观测。

## 4. 专题图

- 后端使用 ReportLab 输出 A4 横版 PDF。
- 地图包含版本化河网、水位风险点、图例、比例尺、指北针、坐标格网、模拟时间、任务、数据版本、作者和 DEMO/无执行权声明。
- 验收样本已渲染成 PNG 逐页检查，河网与水动力点关系清晰，无裁切和重叠。
- 验收证据：`06_验证记录/phase1c_gis_model_integration_acceptance.pdf` 与同名 PNG。

## 5. 验证结果

- Alembic：`20260812_0007 -> 20260813_0008` 成功。
- 真实 PostGIS 全量回归：`52 passed`。
- Phase 1C + GeoServer 专项：`7 passed`。
- OpenAPI：从本次 FastAPI 实例重建生成客户端成功。
- 前端：`npm run typecheck` 通过；`npm run build` 通过（5091 modules）。
- 浏览器：Cesium 加载、动态图层、视域框选、空间结果渲染、时间轴、性能面板通过；最终回归最近 15 秒控制台 0 warning / 0 error。
- PDF：A4 横版、1 页，已用 Poppler 150 DPI 渲染并视觉检查。
- Docker Compose：Docker Desktop 4.84.0 / Engine 29.6.2 / Compose 5.3.1；迁移、播种、GeoServer 初始化均以退出码 0 完成，数据库、Redis、GeoServer、后端与 Worker 健康，前端正常运行。
- GeoServer 在线门禁：7 层目录、`map_annotation` WFS、版本过滤 WMS/WMTS、只读数据库角色和 FastAPI 均通过。

## 6. 已知边界与运维动作

- 当前仍为 DEMO 数据和简化水动力结果，不可替代工程率定、生产容量测试或真实遥测。
- 当前 Compose 栈已在本机完成 Phase 1C 增量部署。后续代码或图层配置变化时复用同一项目名执行：

```powershell
docker compose -p dayu-tiangong-phase1 -f docker/docker-compose.yml up -d --build --wait migrate seed geoserver-init backend worker frontend
python geoserver/verify.py
```

- Cesium vendor 块约 4.17 MB，已独立分块和路由懒加载；首次进入 GIS 仍有下载与解析成本。
- MVT 已提供服务端能力；当前 Cesium 主视图仍以 WMS/WMTS + Primitive 为主，生产大规模连续场建议进一步评估 3D Tiles/时空瓦片。
