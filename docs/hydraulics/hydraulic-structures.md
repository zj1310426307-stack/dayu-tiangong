# 统一水工建筑物模型

更新日期：2026-09-18
适用范围：HYDRO-1D-ENGINEERING-03、MIKE11 水闸数据库优化

## Domain 与持久化

`hydraulic.structure` 表示 Dayu Domain 中的建筑物，不是 MASCARET 私有结构。可建模类型为 `weir`、`culvert`、`bridge`、`gate`、`sluice`、`pump`、`orifice`、`dam`、`storage_link` 和 `compound`；能保存某类型不等于当前 Solver 能安全求解。

核心字段分为：

- 所有权与位置：Dataset Version、Network、Branch、`chainage_m`、CGCS2000 Point；
- 几何：堰顶/底高程、宽度、高度；
- 水力行为：`hydraulic_law_type` 与受控参数；
- 运行规则：`fixed`、`time_series`、`water_level_controlled`、`scenario_specific` 与参数；
- 状态、元数据及旧 Gate/Pump 溯源 ID。

数据库复合外键同时约束 `branch_id + network_id + dataset_version_id`，避免建筑物引用同版本的另一河网。`hydraulic.structure_scenario` 只存工况覆盖参数，并同时外键绑定 Structure/Case 与 Dataset Version；不同工况不复制整张河网或建筑物几何。

结构物默认使用 `Branch + chainage_m` 沿权威中心线线性插值生成 CGCS2000 Point，因此常规录入不再要求重复填写 X/Y。存在可靠实测点时可成对提交 X/Y，后端复用 XY→Branch→Chainage 映射服务，在 Network 的米制 engineering CRS 中校核距离和线定位桩号；默认空间吸附与桩号冲突容差均为 5 m。超出河段、漂浮位置、单轴坐标或 XY/桩号矛盾返回 `STRUCTURE_LOCATION_INVALID`。修改河段或桩号而未提交人工坐标时，Point 会从中心线重新生成。

## API、前端与 GIS

| 操作 | Endpoint |
|---|---|
| 列表/创建 | `GET/POST /api/v1/hydraulic/structures` |
| 详情/编辑/删除 | `GET/PUT/DELETE /api/v1/hydraulic/structures/{id}` |
| 工况覆盖 | `PUT /api/v1/hydraulic/structures/{id}/scenarios/{case_id}` |
| 河网关系 | `GET /api/v1/hydraulic/networks/{network_id}/graph` |

Hydraulic Data 页面在现有管理界面中显示河网关系、建筑物表格和能力状态，并提供创建、编辑、删除。创建弹窗采用渐进式录入：默认仅显示名称、类型、河段、桩号和对应闸/泵核心工况；编码、草稿状态、运行规则、人工坐标、损失系数、性能曲线和控制定义放入高级参数。编码和安全默认值由页面生成，用户仍可展开修改。Bridge/Culvert/Gate/Pump 等未验证或不支持对象仍可作为工程资料保存，但运行按钮前显示 MASCARET 的明确状态与原因。GIS 使用保存后的权威 Point，不另建第二套几何。

### MIKE11 风格水闸资料卡

统一 `gate` 记录新增类型化的 `mike11_gate_configuration`，页面按 MIKE11 Control Structures 的信息组织方式分为：

- Location：沿用统一 Structure 的 Branch、Chainage、ID 和空间坐标；
- Attributes：支持 Overflow、Underflow、Discharge、Radial Gate、Sluice Formula、闸孔数量、Underflow CC；
- Head Loss Factor：正/反向分别保存 Inflow、Outflow、Free Overflow 六个非负系数；
- Control Definitions：保存唯一 Priority、Calculation Mode、Control Type、Target Type、Scaling 和 Value；
- Graphic/限制：保存 Marker 2 水平偏移、图形闸高或开度、Initial/Max Value 和 Max speed。

Branch、Chainage、Width、Sill level 等已有权威字段不在扩展对象中重复。与平台 Gate 计算合同重合的 Underflow CC、最大开度和最大开度变化率必须一致；后端拒绝矛盾值，也禁止通过通用 `hydraulic_parameters` 绕过类型化契约。扩展字段保存在既有 JSONB 中，因此不需要数据库迁移，旧记录读取为 `null` 并保持兼容。

这些字段表示可治理的 MIKE11 风格工程输入，不等于本平台已经获得或实现 MIKE11 求解器。MASCARET Gate 仍为 `UNSUPPORTED`；D-Flow 只接受其能力矩阵已验证的 Gate 子集。Overflow、Discharge、Radial Gate 和 Sluice Formula 等未验证映射会保留资料但在运行前 fail closed。

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
