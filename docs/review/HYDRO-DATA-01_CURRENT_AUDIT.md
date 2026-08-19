# HYDRO-DATA-01 当前基线审计

日期：2026-08-18
基线：`main@cfd2b02`

## 已存在能力

| 目标概念 | 当前实现 | 结论 |
|---|---|---|
| 数据版本 | `dataset_version` 与生命周期门禁 | 直接复用 |
| 河道 | `public.river`，EPSG:4490 LineString | 不能另建孤立副本 |
| 河网拓扑 | `river_node`、`river_segment`、`river_connection` | 可作为网络检查依据 |
| 横断面 | `public.cross_section`，含 station、points、roughness | 保持现有 API |
| 标准断面点 | `cross_section_point`，含 point_order、offset、elevation | 迁移时保真映射 |
| 断面空间扩展 | location、axis、profile 四张加法表 | 避免重复建模 |
| 导入 | Excel/CSV/GeoJSON 原子导入；GDAL 支持 SHP ZIP/DXF 检查与原始落区 | 在其上增加水动力标准化 |
| 坐标 | 权威 EPSG:4490；Web EPSG:3857；显式 CGCS2000 三度带 | 不允许无 CRS 入库 |
| 前端 | 河道库、断面库、导入、校验、模型和水动力任务页 | 新增聚合管理页，不复制 API 层 |

## 主要缺口

- 没有 network/branch/chainage 的 MIKE11 语义和稳定映射。
- 旧断面 JSON 与标准点表并存，但没有面向 MIKE11 的统一交换 DTO。
- 没有 MIKE11 文件适配器、专用导入任务状态、导出状态和水动力质量结果持久化。
- SHP/DXF 当前只进入不可变 raw landing，尚未标准化为 branch/section/point。
- 前端没有一处同时查看 network tree、横断面曲线、导入状态和导出能力。

## 迁移风险

- 新旧双模型若无映射会产生数据漂移，因此必须保留 `legacy_river_id`、`legacy_cross_section_id` 并在单事务导入。
- EPSG:4490 是地理坐标，原始米制 X/Y 不能直接写入 4490 geometry；必须显式转换并保留 source SRID。
- `.nwk11`/`.xns11` 存在版本与编辑器差异；没有真实样例和 DHI 运行时时只能证明交换子集往返，不能证明商业软件原生兼容。
- 现有已发布版本不可写，新导入只能写 draft。

## 实施方案

1. 新增迁移 0019 和 `app.hydraulic` 模块。
2. 回填默认 network、branch、chainage、cross section 和 points 映射。
3. 增加解析器、标准化器、验证器、导出器和 API。
4. 同步 OpenAPI 生成客户端与聚合管理页。
5. 以解析往返、迁移、真实 PostGIS、前端构建和浏览器证据分层验收。
