# 大禹·天工坐标系统说明

## 统一口径

Phase 3 起，全部业务空间表、GeoJSON 接口、导入模板和 GIS 页面统一使用中国大地坐标系 2000（CGCS2000，`EPSG:4490`）。坐标顺序为 `[longitude, latitude]`，即先经度、后纬度。

演示数据范围约为：

- 经度：119.9–120.65°E
- 纬度：30.0–30.55°N

## 存储与交换

- PostGIS：`geometry(LineString, 4490)` 或 `geometry(Point, 4490)`。
- API：标准 GeoJSON；响应 `meta.crs` 明确返回 `EPSG:4490`。
- bbox：`minx,miny,maxx,maxy`，采用 CGCS2000 经纬度。
- OpenLayers：消费 EPSG:4490 业务 GeoJSON，并在 WebGIS 显示层完成投影转换。
- 影像底图：Esri World Imagery 使用其公开瓦片坐标体系；OpenLayers 在显示层完成底图与业务要素叠加，PostGIS 不存储影像瓦片坐标。

## 从 Phase 2 迁移

迁移 `20260812_0003` 对 `river`、`river_node`、`river_segment`、`cross_section`、`gate`、`pump` 六张表执行显式 `ST_Transform(geometry, 4490)`，随后重建 GIST 索引。迁移不删除业务记录，也不通过仅修改 SRID 标签来伪装坐标转换；降级时显式转换回历史 EPSG:4326 类型。

## 水动力计算距离

EPSG:4490 是地理坐标系，角度不能直接作为一维水动力距离。统一模型和 MASCARET Adapter 严格使用：

- `cross_section.station`：沿河桩号，单位 m；
- `river_segment.length`：河段长度，单位 m；
- 横断面 `points`：横距和高程，单位 m。

因此 1D 模型的桩号、断面面积和流速计算均不使用经纬度差值；具体 Solver 文件格式不进入业务数据层。

## 导入检查

真实数据导入前必须核对源坐标系、坐标顺序、区域包络和控制点。若源数据不是 EPSG:4490，应先执行有记录、可复核的坐标转换，禁止只改 SRID 标签。建议抽查 `ST_SRID`、`ST_IsValid`、`ST_Extent` 和已知控制点。
