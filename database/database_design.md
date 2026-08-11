# 大禹·天工 Phase 2 数据库设计

## 设计目标

Phase 2 在 Phase 1 四张空间表上无损升级，形成可供一维水动力模型直接读取的版本化静态数据库。物理坐标统一使用 WGS 84（EPSG:4326），运行时通过 PostGIS 负责几何类型、SRID、有效性与空间索引。

## 领域边界

| 聚合 | 主表 | 职责 |
|---|---|---|
| 数据版本 | `dataset_version` | 隔离不可混用的河网、断面、建筑物与参数 |
| 河网 | `river`、`river_node`、`river_segment`、`river_connection` | 表达河道空间线、可计算河段和有向拓扑 |
| 横断面 | `cross_section` | 保存桩号、有序横距—高程点、糙率与测量信息 |
| 水工建筑物 | `gate`、`pump` | 保存静态设计参数、控制方式和空间位置 |
| 模型配置 | `model_parameter`、`boundary_condition`、`simulation_case` | 组织 Phase 3 模型参数、边界和可追溯计算方案 |

## 核心关系

- 一个 `dataset_version` 拥有多条河道、断面、闸门、泵站、节点、河段、参数和边界条件。
- `river_segment` 通过 `upstream_node_id`、`downstream_node_id` 明确水流方向；`river_connection` 提供轻量有向边读取。
- `cross_section.station` 在同一版本、同一河道内唯一，并受非负约束。
- 闸门和泵站引用所属河道；河道有建筑物时禁止误删。
- `simulation_case` 固定引用一个数据版本和同版本边界条件；读取接口会生成 `dayu.model-input.v1` 快照，不写入计算结果。

## 空间与索引

| 表 | 几何类型 | SRID | GIST 索引 |
|---|---|---:|---|
| `river` | LineString | 4326 | `ix_river_geometry_gist` |
| `river_node` | Point | 4326 | `ix_river_node_geometry_gist` |
| `river_segment` | LineString | 4326 | `ix_river_segment_geometry_gist` |
| `cross_section` | Point | 4326 | `ix_cross_section_geometry_gist` |
| `gate` | Point | 4326 | `ix_gate_geometry_gist` |
| `pump` | Point | 4326 | `ix_pump_geometry_gist` |

## 迁移和初始化

- `20260811_0001`：Phase 1 GIS 基线。
- `20260811_0002`：字段无损扩展、版本化、拓扑和模型配置表。
- `database/seed/demo_data.py`：幂等初始化 1 个版本、3 条河道、20 个断面、5 座闸门、3 座泵站、8 个节点、7 个河段及 1 个计算方案。

数据库变更只允许通过 Alembic 迁移；`schema.sql` 用于结构审阅和新环境核对，不替代迁移历史。
