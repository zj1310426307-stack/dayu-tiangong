# ADR-0014：GIS 运行底座统一为 PostGIS + GeoServer + OpenLayers

- 状态：Accepted
- 日期：2026-08-17

## 背景

GIS-OPT-2 同时引入 QGIS Server、GeoServer、Martin、TiTiler、Cesium 和数据库 Registry/manifest 合并。该结构能够覆盖多种协议，但对当前“稳定、统一、可扩展的最小 WebGIS”目标过度复杂。

## 决策

1. 继续使用现有单一 PostGIS 数据库，不创建第二个 GIS 数据库。
2. `publish` 视图仍是 Web 发布唯一数据边界，Dataset Version 仍是数据事实代次。
3. GeoServer 是唯一地图发布服务，提供 WMS、WMTS 与只读 Basic WFS。
4. FastAPI 提供 PostGIS Catalog、受控 OGC Gateway、业务属性与治理接口；不再合并 QGIS manifest 或选择多种 renderer。
5. WebGIS 使用 OpenLayers，所有地图图层从 Catalog 获取，通过 FastAPI Gateway 访问 GeoServer。
6. QGIS Desktop、Plugin、Project 和 QML 保留为专业数据生产工具；QGIS Server 从平台运行链移除。
7. Martin、TiTiler、3D Tiles 与 GeoNode 不再是默认 Compose 依赖。相关数据能力在后续阶段按 GeoServer 统一合同重新接入。

## 结果

主链路变为：

```text
QGIS Desktop → staging_qgis → validation/review/promotion → publish
                                                        ↓
OpenLayers → FastAPI GIS Gateway → GeoServer → PostGIS publish
```

正向结果是服务职责、健康状态、版本过滤和前端 adapter 大幅收敛。代价是本阶段暂时不提供 Cesium 三维、TiTiler COG 和 Martin MVT 展示；这些能力只有在不破坏统一出口时才会重新引入。
