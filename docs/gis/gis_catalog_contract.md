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
- `layers`：9 个活动图层，其中 6 个为版本化水利业务层，3 个为广东开放参考层；
- `basemaps`：1 个默认高分辨率 Esri World Imagery 与 2 个 NASA 后备影像，只返回同源 FastAPI 瓦片模板；
- `catalog_revision`：排除生成时间后的规范 SHA-256。

`GET /api/v1/gis/layers` 返回同一 Catalog 的 layer 数组，不创建第二份目录。

## 活动图层约束

每一行必须满足：

```text
active = true
source_schema = publish
service_mode = GEOSERVER_WMS
render_mode = RASTER_WMS
dataset_filter_field = dataset_version_id  # 版本化业务层
dataset_filter_field = NULL                # 全局开放参考层
```

当前 9 层：`river`、`river_segment`、`river_node`、`cross_section`、`gate`、`pump`、`administrative_area`、`road`、`waterway`。行政区、道路和水系分别读取 `publish.administrative_area_open|road_open|waterway_open`，不附加 `dataset_version_id` 过滤。

三类开放参考层的标签和 FeatureInfo 名称字段统一为 `name_zh`。`name` 仅作为来源审计字段保留，不允许前端或 SLD 在 `name_zh` 为空时回退显示拼音、未知外文或来源编号。所有非空 `name_zh` 必须通过数据库中文字符约束。

## 安全

- 只接受已发布且未退役、具有 content hash 的版本。
- Catalog 不返回数据库 schema、内部 URL、DSN、凭据或项目文件路径。
- 浏览器只使用 `layer_key`，不能提交任意 GeoServer qualified layer name。
- 影像瓦片只接受 Catalog 中预注册的 Esri/NASA endpoint key、合法层级与瓦片坐标；不接受任意上游 URL，也不跟随重定向。
- inactive 历史多渲染行不返回浏览器。
- GeoServer health 失败时 layer render/identify 能力收窄，而不是伪报在线。

## 变更规则

新增活动层必须同时具备 `publish` 视图、GeoServer layer/style、Catalog seed 行、GeoServer SELECT 权限和测试。不得只改 React 数组或只改 GeoServer 配置。

attribution 必须保留：行政边界为 geoBoundaries/PDDL，路网与水系为 OpenStreetMap contributors/ODbL，NASA 影像为对应 GIBS 产品署名；Esri World Imagery 还必须显示 Esri、Vantor、Earthstar Geographics 和 GIS User Community。Esri 高分辨率影像仅在线浏览，不作为开放数据归档或离线导出。
