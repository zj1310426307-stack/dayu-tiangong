# Phase 1B GIS 业务交互审查

日期：2026-08-12
结论：通过。数据版本、静态图层、动态结果、属性/断面、时间轴、性能监控、容器协议与浏览器门禁全部验收。

## 1. GIS 架构变化

Phase 1B 保持 `PostGIS → GeoServer → WMS/WMTS → Cesium` 静态链路，并增加：

```text
SimulationTask / DispatchRun / PostGIS
                 ↓
FastAPI /api/v1/gis/interaction-frame
                 ↓
Cesium Primitive 水位 / 流速 / 流向 / 闸泵状态
```

PostGIS 仍为唯一业务数据源；GeoServer 负责 6 个静态图层及缓存；FastAPI 负责版本化属性和模型/调度动态帧。前端只通过 OpenAPI 生成客户端访问 FastAPI。

## 2. 数据版本检查

- GIS 统计、4 类 GeoJSON 列表、4 类详情和动态帧均强制 `dataset_version_id`，无版本返回 422。
- 服务查询把版本条件应用到对象、断面数量和详情；响应分页元数据回显版本 ID。
- 任务通过 SimulationCase 追溯版本；调度运行通过 DispatchPlan 追溯版本；跨版本返回 409。
- `task_id + dispatch_run_id` 必须匹配运行的受控任务，禁止同版本不同运行结果拼接。
- WMS/WMTS 请求携带 `CQL_FILTER=dataset_version_id=N`；GeoWebCache regex parameter filter 把规范参数加入缓存身份。
- 版本切换清除 task/run/selected/time，防止浏览器状态跨版本残留。

## 3. 图层管理检查

页面提供 9 类图层：河道、河段、河网节点、横断面、闸门、泵站、水位结果、流速结果、调度状态。每类均支持显示/隐藏和透明度，图例区分正常、警戒、危险、流向与运行/开启状态。静态层继续按相机高度在 WMTS/WMS 间切换。

## 4. 查询功能检查

- GeoServer GetFeatureInfo 只提供稳定业务主键，河道、横断面、闸门和泵站详情继续查询 FastAPI。
- 河道面板包含编码、名称、长度、断面数和数据版本。
- 横断面面板包含桩号、糙率、最低高程、高程点，并由 ECharts 绘制横距—高程图。
- 闸门和泵站静态设计参数与动态模拟状态分开表达，避免把 DEMO 结果称为实时设备状态。

## 5. 模型结果叠加检查

- `/interaction-frame` 原子返回一个时间帧的水位、流量、流速、流向和闸泵状态。
- 水位按 normal/warning/danger 分类；流速按 low/medium/high 分类。
- 流向使用 PostGIS 河道方位角；负流速旋转 180°。
- 闸门展示模拟开度/流量，泵站展示启停、模拟流量与功率；约束标记使用高亮外框。
- `SimulationTimeline` 从权威结果时刻生成；切换时 URL 和动态帧同步刷新。
- 浏览器运行 #24、任务 #155、3600 s 实测：20 个水动力点、2 个闸门状态、1 个泵站状态。

## 6. Cesium 性能测试

- 每次挂载只创建一个 Viewer；版本/reload 变化才销毁并重建，普通时间帧更新只刷新 Primitive。
- 动态水位、流速、流向和调度状态使用 `PointPrimitiveCollection` / `PolylineCollection`，不批量创建 Entity。
- GIS/Cesium 保持路由懒加载。生产构建：5086 modules；GisPage 5.52 kB，CesiumMap 19.10 kB，Cesium vendor 4,174.39 kB 独立块。
- 在线浏览器一轮冷态样本：WMS 346 ms / 5.8 KB，WMTS 328 ms / 4.4 KB，GeoJSON 327 ms / 1.6 KB，JS 堆 32.3 MB。
- 同页热态样本：WMS 47 ms / 5.8 KB，WMTS 47 ms / 4.4 KB，GeoJSON 119 ms / 1.6 KB，JS 堆 43.1 MB。
- 上述是本机单次观测，不作为容量承诺；生产需接入持续采样、分位数与 GeoWebCache 命中率。

## 7. 存在问题

- Cesium vendor 仍约 4.17 MB；已经隔离为 GIS 路由按需块，但首次进入 GIS 仍有下载和解析成本。
- 当前只有 DEMO 数据、简化水动力和单机浏览器性能样本，不能替代真实工程率定、压力测试或生产容量评估。
- 风险阈值在调度计划未配置时使用明确标注的 DEMO 默认值；真实工程必须绑定权威警戒/保证水位标准。
- 动态结果当前以断面点和流向箭头表达；大范围连续水面/流速场仍需专门的时空切片或 3D Tiles 方案。

## 8. Phase 1C 建议

1. 建设可持续观测：GeoServer JVM、WMS/WMTS p50/p95、GeoWebCache 命中率、磁盘配额和浏览器 FPS/内存。
2. 研究动态结果矢量瓦片、3D Tiles 或分级聚合，避免真实大河网一次传输全量断面。
3. 增加空间框选、沿河追踪、断面比较和多时刻对比。
4. 引入真实工程数据后建立版本发布、模型率定、风险阈值审批和专项验收流程。

## 9. 验证摘要

- 真实 PostGIS 全量回归：113 passed。
- 前端 `npm run typecheck`：通过。
- 前端 `npm run build`：通过，5086 modules。
- GeoServer 幂等引导：workspace `dayu`、6 图层、4 缓存层、EPSG:4490。
- 在线协议：版本过滤 WMS/WMTS、Basic WFS、只读角色、FastAPI 同版本查询通过。
- 浏览器：九层控制、时间轴、断面图、性能面板通过；控制台 0 warning / 0 error。
