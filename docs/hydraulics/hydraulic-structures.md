# 统一水工建筑物模型

更新日期：2026-09-02
适用范围：HYDRO-1D-ENGINEERING-03

## Domain 与持久化

`hydraulic.structure` 表示 Dayu Domain 中的建筑物，不是 MASCARET 私有结构。可建模类型为 `weir`、`culvert`、`bridge`、`gate`、`sluice`、`pump`、`orifice`、`dam`、`storage_link` 和 `compound`；能保存某类型不等于当前 Solver 能安全求解。

核心字段分为：

- 所有权与位置：Dataset Version、Network、Branch、`chainage_m`、CGCS2000 Point；
- 几何：堰顶/底高程、宽度、高度；
- 水力行为：`hydraulic_law_type` 与受控参数；
- 运行规则：`fixed`、`time_series`、`water_level_controlled`、`scenario_specific` 与参数；
- 状态、元数据及旧 Gate/Pump 溯源 ID。

数据库复合外键同时约束 `branch_id + network_id + dataset_version_id`，避免建筑物引用同版本的另一河网。`hydraulic.structure_scenario` 只存工况覆盖参数，并同时外键绑定 Structure/Case 与 Dataset Version；不同工况不复制整张河网或建筑物几何。

结构物写入复用 XY→Branch→Chainage 映射服务：在 Network 的米制 engineering CRS 中计算到 Branch 的距离和线定位桩号，默认空间吸附与桩号冲突容差均为 5 m。超出河段、漂浮位置或 XY/桩号矛盾返回 `STRUCTURE_LOCATION_INVALID`。

## API、前端与 GIS

| 操作 | Endpoint |
|---|---|
| 列表/创建 | `GET/POST /api/v1/hydraulic/structures` |
| 详情/编辑/删除 | `GET/PUT/DELETE /api/v1/hydraulic/structures/{id}` |
| 工况覆盖 | `PUT /api/v1/hydraulic/structures/{id}/scenarios/{case_id}` |
| 河网关系 | `GET /api/v1/hydraulic/networks/{network_id}/graph` |

Hydraulic Data 页面在现有管理界面中显示河网关系、建筑物表格和能力状态，并提供创建、编辑、删除。Bridge/Culvert/Gate/Pump 等未验证或不支持对象仍可作为工程资料保存，但运行按钮前显示 MASCARET 的明确状态与原因。GIS 使用权威 Point，不从桩号反猜一套第二几何。

提交计算时，Model Builder 合并 Structure 基础参数和当前 Simulation Case 覆盖；仅 `active` 结构形成 required capability。`MODEL_ENGINE_INCOMPATIBLE` 会列出 feature、structure ID、engine/version 和理由，并在外部进程启动前失败。Adapter 禁止跳过任何 active 的未兼容结构。

## Migration 0025

`20260901_0025_hydraulic_engineering_core.py` 是加法迁移：

1. 扩展 Node 角色约束并建立统一 Structure/Scenario 表；
2. 保留所有旧 `public.gate`、`public.pump` 及历史 Hydraulic Result；
3. 对可解析旧 Gate/Pump 创建带 `legacy_*_id` 的统一副本，位置投影到权威 Branch，并将能力标记为 `UNSUPPORTED`；
4. downgrade 只删除 Engineering-03 副本，先把新增 Node 角色映射回旧约束允许值；原始 Gate/Pump 不删除。

CI 对 fresh upgrade、downgrade `-1`、再次 upgrade、单一 Alembic head、复合外键、旧对象回填完整性和 Structure 不漂浮进行真实 PostGIS 验证。

## 已验证范围

本阶段只有固定几何宽顶堰升级为 `VERIFIED_NATIVE`。S01 采用 MASCARET REZO 原生 geometric seuil：结构运行和无结构基线使用同一河道/边界，结构使上游峰值水位增加 `0.350 m`，最终下游流量 `8.000 m³/s`，断面积分质量残差 `0.469375%`，在预先固定的 `0.5%` 门内。

S01 只证明当前固定 broad-crested geometric weir 参数范围；不外推到淹没堰、活动闸门、溃坝或通用控制算法。Gate/Pump 继续 `UNSUPPORTED`；Bridge/Culvert/Orifice/Dam/Storage Link/Compound 继续 `UNVERIFIED`。
