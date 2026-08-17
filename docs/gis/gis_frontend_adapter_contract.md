# OpenLayers WebGIS 合同

状态：GIS-RESET-01 当前合同（取代 GIS-OPT-2 多 adapter 合同）

## 唯一渲染端

`frontend/src/gis/MapView.tsx` 是唯一 WebGIS 地图生命周期入口，使用 OpenLayers `Map`、`View` 和 `TileWMS`。前端不存在 QGIS WMS、Martin、TiTiler、Cesium Dynamic 或 3D adapter 选择矩阵。

## 依赖边界

```text
MapView
  → generated getGISCatalog
  → generated getGISFeatureInfo
  → /api/v1/gis/ogc/wms TileWMS
```

地图组件不得直接 `fetch`、不得保存服务内部 URL、不得构造 SQL/CQL，也不得自带河道/断面/闸泵业务清单。所有业务图层来自 Catalog。

## 视图能力

- 投影固定 `EPSG:3857`；
- 行政区参考层作为最小底图；
- Catalog 图层开关；
- 透明度调整；
- 上移/下移改变 z-index；
- 单击按顶层可见图层顺序调用 FeatureInfo；
- 属性弹窗只展示 FastAPI 清洗后的字段；
- 坐标栏明确显示 Web CRS。

浏览器不提供编辑能力。QGIS Desktop 和治理链负责生产，GeoServer SLD 负责权威制图，`StyleManager.ts` 只提供图层面板的 UI 色点，不定义业务地图样式。

## 资源生命周期

版本切换时销毁旧 MapView，重新读取 Catalog 和 WMS source。组件卸载必须解除 OpenLayers target；图层透明度、可见性与顺序只保存在当前页面状态，不写回数据库。

## 验收

- TypeScript typecheck 和生产 build 通过；
- generated client 包含 Catalog/layers/FeatureInfo，且不含 QGIS Server helper；
- 页面网络请求不出现 Cesium 静态资源、`/qgis-server/`、`/vector/` 或任意外部底图 URL；
- 新增 Catalog 层无需修改 MapView、GisPage 或 LayerManager 的业务 key 列表。
