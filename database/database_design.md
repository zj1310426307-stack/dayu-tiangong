# 数据库设计基线

更新日期：2026-08-18
权威迁移头：`20260818_0019`

## 单库原则

`dayu_tiangong` 是唯一业务 PostgreSQL/PostGIS 数据库。不同职责用 schema、视图、事务和最小权限角色隔离，不创建 `dayu_gis` 或其他第二权威库。

| schema / 范围 | 用途 |
|---|---|
| `public` | Dataset Version、河道、断面、闸、泵、模型、治理、调度和 AI 元数据 |
| `imports` | 原始 GDAL 落地区，每批次不可变物理表 |
| `staging_qgis` | QGIS 可编辑的四张强类型暂存表 |
| `reference_data` | 与 Dataset Version 解耦的广东开放行政区、道路和水系快照 |
| `hydraulic` | Network/Node/Branch/Reach/Vertex、断面 Profile/糙率/查算语义、导入审计与校核证据 |
| `publish` | GeoServer 和 QGIS 复核读取的版本过滤只读视图 |
| TimescaleDB hypertable | 观测、仿真和调度动态状态 |

Alembic 是部署结构的唯一权威来源。`database/schema.sql` 与 `database/gis/schema.sql` 仅用于阅读和设计参考，不能替代迁移。

## 关键对象

### Dataset Version

`dataset_version` 保存状态、父版本、来源批次、内容哈希、审核和发布时间。发布或退役版本不可由核心 CRUD 原地修改。`source_batch_id` 唯一约束保证同批次晋级幂等。

### 核心 GIS

- `river`
- `river_node`
- `river_segment`
- `cross_section`
- `gate`
- `pump`
- `map_annotation`
- 基础参考对象

所有版本化对象携带 `dataset_version_id`。权威几何 SRID 为 4490，GiST 索引用于空间过滤。

### 治理

- `gis_import_batch`
- `gis_validation_run`
- `gis_validation_issue`
- `gis_review`
- `gis_batch_event`
- `gis_publication`

审核与事件为追加式记录。晋级在一个数据库事务内锁定批次，复核当前暂存哈希，写入新版本并执行最终一致性检查；异常必须整体回滚。

### QGIS 暂存

`staging_qgis.river|cross_section|gate|pump` 保留强类型业务字段、几何、批次身份、操作类型和权威来源字段。编辑者只有列级业务写权限；`source_crs`、`source_hash`、`operator`、质量状态和审计时间由批次溯源触发器维护。

### 广东开放参考数据

`reference_data.administrative_area|road|waterway` 保存来源、来源对象 ID、快照 SHA-256、原始名称 `name`、中文展示名 `name_zh`、类型、原始属性 JSON 和 EPSG:4490 几何。行政区为 `MULTIPOLYGON`，道路/水系为 `MULTILINESTRING`，均有来源唯一约束和 GiST 索引。行政区 `name_zh` 必填，道路/水系允许为空；数据库约束保证每个非空展示名至少含一个中文字符。导入器使用临时表、数量门禁和单事务替换，避免失败时留下半批数据。

### 发布视图

Catalog 激活的 9 个 `publish` 视图包括 6 个显式暴露 `dataset_version_id`、只读取 `dataset_version.status='published'` 的业务视图，以及 3 个不绑定版本的广东开放参考视图。GeoServer 的 `dayu_postgis` store 使用该 schema，并通过 `dayu_geoserver` 只读账号访问。

### PostGIS Catalog

历史物理表 `gis_layer_registry` 为避免复制而保留，但运行模型名为 `GISCatalogLayer`。迁移 0016 激活 9 个 `publish` / `GEOSERVER_WMS` / `RASTER_WMS` 行；迁移 0017 在 `basemap_registry` 增加默认可见的 Esri World Imagery 高分辨率 endpoint，并把 2 个 NASA GIBS endpoint 调整为默认关闭的后备；迁移 0018 将三类参考层的 FeatureInfo 展示字段切换为 `name_zh`。其他历史渲染行保持 inactive，只服务于可逆 downgrade。

### 水动力交换语义

迁移 0019 新增 `hydraulic.network|node|branch|branch_vertex|reach`、`cross_section|cross_section_profile|cross_section_point|cross_section_roughness_zone|cross_section_processing|cross_section_hydraulic_row`、导入/校核对象及 GIS 适配视图。`legacy_river_id` 与 `legacy_cross_section_id` 将正式水动力对象稳定映射到现有核心表；正式拓扑也投影到现有 Node/Segment/Connection。新导入和原有 CRUD 在同一业务事务内保持兼容，不把语义 schema 变成第二权威空间库。

空间输入必须声明完整坐标契约；source 受控为 4326、4490 或 4546–4549，engineering CRS 必须为米制 4546–4549，标准化显示 geometry 固定为 4490。已发布/已退役版本不接受导入，文件预览不触发业务实体写入。

## 角色矩阵

| 角色 | 登录 | 主要权限 |
|---|---:|---|
| 数据库 owner | 是 | 迁移、seed、角色 bootstrap |
| `dayu_backend` | 是 | API/Worker 所需业务 DML，继承 `dayu_publisher` |
| `dayu_publisher` | 否 | 受控晋级与发布所需核心权限 |
| `dayu_geoserver` | 是 | `publish` USAGE/SELECT，默认只读 |
| `dayu_qgis_editor` | 是 | 暂存列级写、必要参考读 |
| `dayu_qgis_reviewer` | 是 | 暂存/治理/核心/发布只读 |

角色密码不进入迁移、QGS、Markdown 或版本库。bootstrap 会轮换密码并重置权限/成员关系；因此只能由授权管理员在维护窗口执行。

## 迁移与回退

- 新环境：`alembic upgrade head`，然后运行 demo seed、广东开放参考数据导入、QGIS/App bootstrap、GeoServer bootstrap 和 Catalog seed。
- 升级前必须备份数据库并盘点历史版本状态/content_hash。
- downgrade 会删除该迁移新增或接管的结构/状态，不能作为生产数据恢复方案。
- upgrade/downgrade/upgrade 只能先在一次性空库或恢复副本上演练。
