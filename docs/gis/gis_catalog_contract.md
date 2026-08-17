# GIS Catalog 合同

合同版本：`gis-catalog/v1`

## 目的

Catalog 是 WebGIS 业务图层、顺序、默认可见性、透明度和能力的唯一目录。数据存储在 PostGIS `gis_layer_registry` 历史物理表中，活动行只能描述 GeoServer 读取 `publish` 的 WMS 图层。

## API

`GET /api/v1/gis/catalog?dataset_version_id=<published-id>` 返回：

- `project`：项目名、权威 CRS `EPSG:4490`、Web CRS `EPSG:3857`；
- `dataset`：不可变已发布 Dataset Version、content hash、发布时间；
- `services`：有且仅有 `geoserver_ogc`；
- `groups`：展示分组和顺序；
- `layers`：12 个活动图层；
- `basemaps`：以 GeoServer `administrative_area` 作为本地参考底图；
- `catalog_revision`：排除生成时间后的规范 SHA-256。

`GET /api/v1/gis/layers` 返回同一 Catalog 的 layer 数组，不创建第二份目录。

## 活动图层约束

每一行必须满足：

```text
active = true
source_schema = publish
service_mode = GEOSERVER_WMS
render_mode = RASTER_WMS
dataset_filter_field = dataset_version_id
```

当前 12 层：`river`、`river_segment`、`river_node`、`cross_section`、`gate`、`pump`、`map_annotation`、`administrative_area`、`road`、`place_name`、`water_name`、`poi`。

## 安全

- 只接受已发布且未退役、具有 content hash 的版本。
- Catalog 不返回数据库 schema、内部 URL、DSN、凭据或项目文件路径。
- 浏览器只使用 `layer_key`，不能提交任意 GeoServer qualified layer name。
- inactive 历史多渲染行不返回浏览器。
- GeoServer health 失败时 layer render/identify 能力收窄，而不是伪报在线。

## 变更规则

新增活动层必须同时具备 `publish` 视图、GeoServer layer/style、Catalog seed 行、GeoServer SELECT 权限和测试。不得只改 React 数组或只改 GeoServer 配置。
