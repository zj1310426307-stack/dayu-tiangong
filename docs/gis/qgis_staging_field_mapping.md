# QGIS 暂存字段映射

## 通用来源字段

| 字段 | 类型/要求 | 来源或默认 | QGIS 编辑 |
|---|---|---|---|
| `id` | integer，数据库主键 | 数据库生成 | 只读 |
| `batch_id` | integer，必填 | 平台创建的同对象类型 batch | 可选填，保存前核对 |
| `source_feature_id` | varchar(128)，批次内唯一 | 原数据稳定 ID；没有时由标准化流程确定 | 可编辑 |
| `operation` | `upsert` / `delete` | 默认 `upsert` | 按批次意图编辑 |
| `quality_status` | `pending` / `passed` / `failed` | 默认 `pending`，治理用途 | 只读 |
| `source_crs` | varchar(64)，必填 | 原数据 CRS | 只读/由导入写入 |
| `target_crs` | 固定 `EPSG:4490` | 数据库默认 | 只读 |
| `source_hash` | 64 位 SHA-256 | 原文件或来源要素规范哈希 | 只读 |
| `operator` | varchar(64)，必填 | 实际作业人/受控服务 | 可编辑 |
| `survey_time` | timestamptz，可空 | 测量/采集时刻 | 可编辑 |
| `source_payload` | JSONB | 未提升为稳定字段的来源扩展 | 只读 |
| `created_at` / `updated_at` | timestamptz | 数据库维护 | 只读 |
| `geometry` | EPSG:4490，非空 | QGIS/GDAL 真正重投影后的几何 | 可编辑 |

一个批次只对应一种 `entity_type`。子对象使用父版本的 `river_code`，不会与同一批次的暂存河道建立虚假的跨类型关系。

## `staging_qgis.river`

| 暂存字段 | 核心字段 | 类型/规则 | 说明 |
|---|---|---|---|
| `code` | `river.code` | varchar(64)，批次内唯一、非空 | 稳定业务键 |
| `name` | `river.name` | varchar(128)，非空 | 河道名称 |
| `length` | `river.length` | float，> 0，单位 m | 来自测量/工程资料；平台会与测地长度做偏差提示 |
| `level` | `river.level` | varchar(32)，非空 | 河道等级/分类 |
| `status` | `river.status` | `active|inactive|planned` | 默认 `active` |
| `description` | `river.description` | text，可空 | 说明 |
| `geometry` | `river.geometry` | LineString, SRID 4490 | 简单、有效、无空几何 |

## `staging_qgis.cross_section`

| 暂存字段 | 核心字段 | 类型/规则 | 说明 |
|---|---|---|---|
| `river_code` | 晋级时解析为 `river_id` | varchar(64)，非空 | 必须存在于父版本 |
| `section_code` | `cross_section.section_code` | varchar(64)，批次内唯一 | 稳定业务键 |
| `section_name` | `section_name` | varchar(128)，非空 | 断面名称 |
| `station` | `station` | float，>= 0，单位 m | 河道桩号，不用经纬度差计算 |
| `points` | `points` | JSONB，至少两个剖面点 | 格式 `{"points": [[offset,elevation], ...]}` |
| `roughness` | `roughness` | float，> 0；QGIS 建议 <= 1 | 曼宁糙率 |
| `elevation_min` | `elevation_min` | float | 单位/高程基准需在批次资料说明 |
| `survey_date` | `survey_date` | date，可空 | 测量日期 |
| `geometry` | `geometry` | Point, SRID 4490 | 断面定位点；本阶段不是断面线对象 |

## `staging_qgis.gate`

| 暂存字段 | 核心字段 | 规则摘要 |
|---|---|---|
| `river_code` | 晋级时解析为 `river_id` | 父版本河道编码，必填 |
| `gate_code` / `name` | 同名 | 稳定编码、名称，必填 |
| `gate_type` | 同名 | 必填 |
| `opening_direction` | 同名 | 必填 |
| `control_mode` | 同名 | 必填 |
| `width` / `height` / `max_flow` | 同名 | 质检要求 > 0 |
| `bottom_elevation` | 同名 | 必填；记录垂直基准 |
| `station` / `crest_elevation` | 同名 | 可空，单位/基准按工程资料 |
| `discharge_coefficient` | 同名 | 可空，需工程参数来源 |
| `minimum_opening` / `maximum_opening` | 同名 | 可空，单位一致且最小不大于最大 |
| `opening_rate_limit` / `minimum_hold_seconds` | 同名 | 可空，非负 |
| `allow_reverse_flow` | 同名 | boolean，默认 false |
| `status` | 同名 | `online|offline|maintenance|fault`，默认 offline |
| `geometry` | 同名 | Point, SRID 4490 |

拓扑节点/河段 ID 不在 QGIS 暂存中填写；晋级后由服务在新版本内生成/解析，避免把父版本的数据库 ID 带入新版本。

## `staging_qgis.pump`

| 暂存字段 | 核心字段 | 规则摘要 |
|---|---|---|
| `river_code` | 晋级时解析为 `river_id` | 父版本河道编码，必填 |
| `pump_code` / `name` | 同名 | 稳定编码、名称，必填 |
| `design_flow` / `head` / `power` | 同名 | 质检要求 > 0 |
| `efficiency_curve` | 同名 | JSONB，至少两个点，例如 `{"points": [[flow,efficiency], ...]}` |
| `head_curve` | 同名 | JSONB，可空 |
| `transfer_type` | 同名 | 可空，按模型约定值域 |
| `unit_count` | 同名 | 可空，正整数 |
| `minimum_running_units` / `maximum_running_units` | 同名 | 可空，最大值不小于最小值 |
| `minimum_run_seconds` / `minimum_stop_seconds` | 同名 | 可空，非负 |
| `maximum_starts_per_run` | 同名 | 可空，非负整数 |
| `minimum_operating_head` / `maximum_operating_head` | 同名 | 可空，最大值不小于最小值 |
| `reverse_flow_protection` | 同名 | boolean，默认 true |
| `control_mode` | 同名 | 必填 |
| `status` | 同名 | `online|offline|maintenance|fault`，默认 offline |
| `geometry` | 同名 | Point, SRID 4490 |

## 映射与删除规则

- 映射逻辑发生变化时递增 `mapping_version`，不要悄悄重解释历史批次。
- 字段缺失、单位不清或 CRS 不明时保留问题并阻断，不用 `source_payload` 隐藏必需业务字段。
- `delete` 行仍需稳定业务编码和来源信息；晋级只从**新版本**删除匹配对象，父版本保留。
- QGIS QML 是桌面生产样式，GeoServer SLD 是 Web 发布样式；只同步分类口径和视觉语义，不做自动双向格式转换。
