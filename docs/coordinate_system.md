# Phase 1 坐标系说明

## 统一坐标系

Phase 1 所有空间表、GeoJSON 接口、演示底图和 Cesium 数据源统一使用 WGS 84（`EPSG:4326`）。坐标顺序为 `[longitude, latitude]`，即先经度、后纬度。

演示数据范围约为：

- 经度：119.9–120.65°E
- 纬度：30.0–30.55°N

## 存储与交换

- PostGIS：`geometry(LineString, 4326)` 或 `geometry(Point, 4326)`。
- API：标准 GeoJSON，不写入已废弃的顶层 `crs` 成员；响应 `meta.crs` 明确声明数据口径。
- bbox：`minx,miny,maxx,maxy`，对应 `min_lon,min_lat,max_lon,max_lat`。
- CesiumJS：直接消费经纬度 GeoJSON，由引擎转换到地心坐标进行渲染。
- 影像底图：Esri World Imagery 使用 Web Mercator 瓦片；Cesium 负责与 EPSG:4326 业务要素对齐，PostGIS 中不存储或伪装影像坐标。

## 计算限制

EPSG:4326 的单位是角度，不能直接用于米制长度、面积、缓冲区或水动力网格计算。需要工程量计算时，应在服务或离线处理流程中显式转换到适合项目区域的投影坐标系，并记录源 SRID、目标 SRID、转换方法与精度验证。本阶段不引入未经确认的工程投影。

## 数据导入检查

后续导入真实数据必须检查坐标顺序、SRID、有效性和区域包络；禁止仅修改 SRID 标签来冒充坐标转换。建议至少执行 `ST_SRID`、`ST_IsValid`、`ST_Extent` 和已知控制点抽检。
