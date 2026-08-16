# GIS Unified Catalog Contract

- Contract status：Frozen for GIS-OPT-2 implementation
- Contract version：`gis-catalog/v1alpha1`
- Date：2026-08-15
- Decision baseline：远端 `main` / `f72b675e4681823e35cf74219a0721825dca8082`
- Runtime status：NOT IMPLEMENTED

## 1. Purpose

统一 Catalog 是后端生成、前端只读消费的安全 DTO。它把 Registry、QGIS project manifest、运行健康和 Dataset Version 合并为一个稳定合同，消除主地图中的业务图层硬编码。

本合同不替代 `/api/v1/dgis/catalog` 的资产登记职责，也不授权任意数据源、URL、MAP、FILTER、SQL 或文件路径。

## 2. Endpoint

未来入口：

```http
GET /api/v1/gis/catalog?dataset_version_id={positive_integer}
```

首期规则：

- `dataset_version_id` 必填；
- 只返回 `status=published` 且 `content_hash` 非空的版本；
- draft/approved/rejected 返回 `409 DATASET_VERSION_NOT_PUBLIC`；
- retired 返回 `410 DATASET_VERSION_RETIRED`；
- 未知版本返回 `404 DATASET_VERSION_NOT_FOUND`；
- 服务端根据 Registry active allowlist、manifest revision 和运行健康裁剪能力；
- 不接受 layer、schema、relation、endpoint 或 project 参数。

错误沿用平台结构化形状：

```json
{
  "detail": {
    "code": "DATASET_VERSION_NOT_PUBLIC",
    "message": "Dataset version is not publicly available.",
    "context": {"dataset_version_id": 12, "status": "approved"}
  }
}
```

## 3. Top-level DTO

```json
{
  "schema_version": "gis-catalog/v1alpha1",
  "catalog_revision": "sha256:...",
  "generated_at": "2026-08-15T08:00:00Z",
  "project": {},
  "dataset": {},
  "capabilities": {},
  "services": [],
  "groups": [],
  "layers": [],
  "basemaps": []
}
```

所有未声明字段对客户端均视为不可依赖。服务端可以追加兼容字段，删除/改义必升 `schema_version`。

## 4. Project DTO

| 字段 | 类型 | 语义 |
|---|---|---|
| `project_key` | string | 固定项目身份，如 `dayu_tiangong` |
| `title` | string | 项目显示标题 |
| `crs` | string | 规范 CRS，当前 `EPSG:4490` |
| `project_revision` | string | canonical server manifest revision |
| `qgis_project_hash` | string/null | canonical QGIS deployment project hash；legacy-only 时可空 |
| `qgis_version` | string/null | 当前受控 Server 版本；legacy-only 时可空 |
| `extent` | `[west,south,east,north]`/null | 可空的安全初始范围 |

不得返回源工程绝对路径、内部容器路径、数据库 service、authcfg 或 QGIS layer id。

## 5. Dataset DTO

| 字段 | 类型 | 语义 |
|---|---|---|
| `dataset_version_id` | integer | 本次目录绑定版本 |
| `version` | string | 人类可读版本名 |
| `name` | string | Dataset Version 展示名称 |
| `status` | `published` | 公开 Catalog 首期固定值 |
| `content_hash` | string | canonical core hash |
| `published_at` | ISO-8601 string | 发布时间 |
| `change_summary` | string/null | 经治理审核的摘要 |

`approved_by`、内部 batch id、审计 actor 等不进入公开 DTO，除非后续数据分级明确允许。

## 6. Capabilities DTO

顶层能力只表示“本版本、当前运行 revision、当前调用者”实际可用的交集：

```json
{
  "identify": true,
  "legend": true,
  "print": false,
  "measure": true,
  "version_switch": true,
  "external_basemap_registration": false,
  "editing": false
}
```

前端不得因为 adapter 存在就推断能力。

## 7. Service DTO

`services[]` 是以 `service_key` 为判别的安全端点登记。公开 endpoint 必须同源或属于构建期 allowlist；绝不返回内部服务地址。

公共字段：

| 字段 | 类型 |
|---|---|
| `service_key` | stable string |
| `service_mode` | 固定枚举 |
| `endpoint` | same-origin path 或已审核公开地址 |
| `healthy` | boolean |
| `revision` | string/null |

按模式允许的扩展字段：

| service_mode | 允许字段 |
|---|---|
| `QGIS_WMS` | `wms_version`, `gateway_contract_version` |
| `GEOSERVER_WMS_LEGACY` | `wms_version`, `wmts_endpoint` |
| `MARTIN_MVT` | `tile_template`, `min_zoom`, `max_zoom` |
| `TITILER` | `tile_template`, `asset_key`, `min_zoom`, `max_zoom` |
| `FASTAPI` | `endpoint_key` |
| `CESIUM_DYNAMIC` | `endpoint_key` |
| `THREE_D_TILES` | `tileset_path` |

禁止字段：`internal_url`、`dsn`、`MAP`、`FILTER`、`source_table`、`project_path`、credential 和任意请求 header。

## 8. Group DTO

```json
{
  "group_key": "hydraulic_core",
  "title": "水利核心对象",
  "order": 100,
  "collapsed": false
}
```

- `group_key` 是稳定状态 key；
- `title/order/collapsed` 可来自 QGIS manifest，但不能新增 Registry 未登记图层；
- layer 的 group 必须在 `groups[]` 中存在。

## 9. Layer DTO

每个 layer 必须包含：

| 字段 | 类型 | 来源/约束 |
|---|---|---|
| `key` | string | Registry `layer_key` 的公开稳定业务身份 |
| `title` | string | Registry 稳定业务标题 |
| `display_title` | string | manifest 展示标题，缺失回退 title |
| `group_key` | string | Registry |
| `group_title` | string | 当前 Catalog 的分组展示标题 |
| `order` | integer | manifest；无 manifest 时 Registry seed |
| `z_index` | integer | 确定性绘制顺序；与 order 一致性受测试约束 |
| `geometry_type` | enum | Registry 安全枚举 |
| `service_key` | string | 指向 services[] |
| `service_mode` | enum | 必须与 service 一致 |
| `render_mode` | enum | 合法组合矩阵 |
| `dataset_version_id` | integer | 与顶层 dataset 一致 |
| `dataset_filter_field` | string/null | QGIS_WMS 首期固定 `dataset_version_id` |
| `default_visible` | boolean | 初始 UI 状态，不是持久业务事实 |
| `default_opacity` | number | 0..1 初始值 |
| `min_scale` | number/null | manifest |
| `max_scale` | number/null | manifest |
| `identify_enabled` | boolean | Registry 默认与运行能力交集 |
| `legend_enabled` | boolean | Registry 默认与运行能力交集 |
| `search_enabled` | boolean | Registry 默认与安全搜索 API 交集 |
| `qgis_short_name` | string/null | QGIS_WMS 发布名；其他模式可空 |
| `model_entity_type` | string/null | 受控实体类型，不推断数据库表 |
| `service` | object | 只含本 render mode 需要的 browser-safe 字段 |
| `legend` | object/null | 受控 legend descriptor |
| `identify` | object | 受控 identify descriptor |
| `cache_mode` | enum | Registry |
| `capabilities` | object | 当前可用交集 |

`legend` 只允许：

```json
{"mode":"WMS_LEGEND","endpoint":"/qgis-server/wms","layer_key":"river"}
```

或受控静态 legend key。不得含上游 FILTER/MAP。

`identify` 只允许：

```json
{
  "mode": "FEATURE_INFO",
  "identity_fields": ["feature_id", "dataset_version_id"],
  "detail_route_key": "river_detail"
}
```

`service` 例如：

```json
{"kind":"QGIS_WMS","endpoint":"/qgis-server/wms","layer_key":"river"}
```

不得返回 internal QGIS URL、MAP path、relation 或 FILTER template。

标准化选择身份始终为：

```text
{ layer_key, feature_id, dataset_version_id }
```

## 10. Basemap DTO

```json
{
  "basemap_key": "world_imagery",
  "title": "影像底图",
  "type": "XYZ",
  "endpoint": "/api/v1/gis/basemaps/world_imagery/{z}/{x}/{y}",
  "credit": "...",
  "crs": "EPSG:3857",
  "visible": true,
  "opacity": 1.0
}
```

首期 Catalog 只输出部署时已登记的底图；不接受用户 URL。公开地址必须经过 SSRF、凭据和许可证审查，或通过同源代理。

## 11. Service / Render Enums

```text
service_mode:
  QGIS_WMS | GEOSERVER_WMS_LEGACY | MARTIN_MVT | TITILER |
  FASTAPI | CESIUM_DYNAMIC | THREE_D_TILES

render_mode:
  RASTER_WMS | VECTOR_TILE | RASTER_TILE |
  DYNAMIC_PRIMITIVE | THREE_D

cache_mode:
  NONE | CLIENT_PRIVATE | VERSIONED_PUBLIC
```

服务端必须拒绝 ADR-0013 未声明的组合；客户端对未知 enum 显示“不支持”，不得回退到任意 URL 加载。

## 12. Catalog Merge Pipeline

```text
Registry active rows
  → schema/relation/capability allowlist validation
  → optional QGIS canonical manifest join by layer_key/qgis_short_name
  → runtime endpoint + health + revision join
  → published Dataset Version gate
  → capability intersection
  → DTO allowlist serializer
  → ETag/cache
```

合并优先级遵循 ADR-0013。manifest 缺层、重复 short name、revision 不一致或健康失败时，对应 layer `capabilities` 必须收窄；QGIS_WMS 无安全版本字段时必须整层剔除。

建议 ETag 输入至少包含：contract version、Registry revision、project revision、Dataset Version id/content hash、runtime endpoint revision 和调用者授权范围。不得只以 Dataset Version id 缓存。

## 13. Complete Example

```json
{
  "schema_version": "gis-catalog/v1alpha1",
  "catalog_revision": "sha256:example",
  "generated_at": "2026-08-15T08:00:00Z",
  "project": {
    "project_key": "dayu_tiangong",
    "title": "大禹天工",
    "crs": "EPSG:4490",
    "project_revision": "sha256:project-example",
    "qgis_project_hash": "sha256:qgz-example",
    "qgis_version": "3.44.13",
    "extent": null
  },
  "dataset": {
    "dataset_version_id": 7,
    "version": "V1.2",
    "name": "V1.2 发布版",
    "status": "published",
    "content_hash": "sha256:content-example",
    "published_at": "2026-08-15T07:30:00Z",
    "change_summary": "河道与断面更新"
  },
  "capabilities": {
    "identify": true,
    "legend": true,
    "print": false,
    "measure": true,
    "version_switch": true,
    "external_basemap_registration": false,
    "editing": false
  },
  "services": [{
    "service_key": "qgis_wms_primary",
    "service_mode": "QGIS_WMS",
    "endpoint": "/qgis-server/wms",
    "healthy": true,
    "revision": "sha256:project-example",
    "wms_version": "1.3.0",
    "gateway_contract_version": "qgis-wms-gateway/v1alpha1"
  }],
  "groups": [{
    "group_key": "hydraulic_core",
    "title": "水利核心对象",
    "order": 100,
    "collapsed": false
  }],
  "layers": [{
    "key": "river",
    "title": "河道",
    "display_title": "河道",
    "group_key": "hydraulic_core",
    "group_title": "水利核心对象",
    "order": 10,
    "z_index": 10,
    "geometry_type": "LINESTRING",
    "service_key": "qgis_wms_primary",
    "service_mode": "QGIS_WMS",
    "render_mode": "RASTER_WMS",
    "dataset_version_id": 7,
    "dataset_filter_field": "dataset_version_id",
    "default_visible": true,
    "default_opacity": 1.0,
    "min_scale": null,
    "max_scale": null,
    "identify_enabled": true,
    "legend_enabled": true,
    "search_enabled": true,
    "qgis_short_name": "river",
    "model_entity_type": "river",
    "service": {"kind":"QGIS_WMS","endpoint":"/qgis-server/wms","layer_key":"river"},
    "legend": {"mode":"WMS_LEGEND","endpoint":"/qgis-server/wms","layer_key":"river"},
    "identify": {"mode":"FEATURE_INFO","identity_fields":["feature_id","dataset_version_id"],"detail_route_key":"river_detail"},
    "cache_mode": "CLIENT_PRIVATE",
    "capabilities": {"render":true,"identify":true,"legend":true,"print":false}
  }],
  "basemaps": []
}
```

示例中的 hash 是占位符，不是运行证据。

## 14. Compatibility and Rollback

1. `legacy`：主地图完全使用现有静态配置；新 Catalog 可离线构建。
2. `shadow`：浏览器仍渲染 legacy，后台比较 layer identity、服务、显隐、顺序和能力差异。
3. `catalog`：LayerManager 与 adapter 使用本合同；旧 API 保留回滚窗口。
4. 失败时 feature flag 切回 `legacy`，不删除 Registry、旧 API 或 GeoServer 配置。

`/api/v1/dgis/catalog` 的资源可由后端 adapter 合并进入本合同，但旧响应在弃用窗口内保持不变。

## 15. Contract Tests Required Before Cutover

- OpenAPI/JSON Schema 对 required、enum、范围和结构化错误的合同测试；
- 每种合法/非法 service/render 组合测试；
- 所有 layer 的 service/group 引用完整性测试；
- Catalog 不含 internal URL、schema/relation、MAP/FILTER/path/secret 的静态与运行测试；
- 同一输入的 canonical JSON/ETag 稳定，revision 或 content hash 改变则 ETag 改变；
- published/retired/draft/rejected 状态矩阵；
- QGIS manifest short name 缺失、重复、revision 漂移时 fail-closed；
- legacy 与 shadow 差异快照；
- generated TypeScript 客户端必须由 OpenAPI 生成，禁止手工漂移。

## 16. Explicit Non-goals

- 本文不创建 Registry 表、迁移、API 或前端 adapter；
- 不把现有 GeoServer 12 层切到 QGIS Server；
- 不开放 Web GIS 编辑、WFS-T、任意外部底图登记或 QGIS project 上传；
- 不改变断面 `Point + points JSON + station` 现有模型合同。后续扩展只能添加可空字段/关联并保持旧读写与模型测试通过。

横断面后续迁移固定为 ADD ONLY：保留 `cross_section.geometry=Point`、`points` JSON profile 和 `station`；未来可增加 `cross_section_location`、`cross_section_axis`、`cross_section_point`、`cross_section_profile`、`vertical_datum`、`left_bank`、`right_bank`。在模型 adapter 完成前，水动力模型继续读取旧合同。
