# 当前水动力数据结构报告

> **2026-08-18 基线归档：** 本文的数据表审查仍有历史价值，但其中 v1/v2/v3 自研 Solver 链不再是当前架构。现行 1D 数据与计算边界见 [HYDRO-1D-RESET-01](../migration/HYDRO-1D-RESET-01.md)。

日期：2026-08-18
代码迁移头：`20260818_0019`
持久库口径：仍按 `20260817_0018` 管理，本轮未迁移

## 1. 权威边界

`public.dataset_version` 继续是 GIS、模型和水动力数据的共同版本身份。`hydraulic` schema 保存生产级水动力语义；现有 `public.river|cross_section|river_node|river_segment|river_connection` 保留旧 API、GIS 发布与 v1/v2 兼容投影。两侧在同一数据库事务内同步，不创建第二权威库。

## 2. 0019 对象

| 对象 | 职责 |
|---|---|
| `hydraulic.network` | 河网身份、工程 CRS、单位和垂向基准 |
| `hydraulic.node` | 正式拓扑边界/汇分流/构筑物节点 |
| `hydraulic.branch` | 有向河段、首尾节点、桩号范围、工程长度和旧 River 映射 |
| `hydraulic.branch_vertex` | 有序源点、桩号、原始 XYZ、轴序与变换管线 |
| `hydraulic.reach` | 两拓扑节点间的求解分段 |
| `hydraulic.cross_section` | 空间断面位置、轴线、桩号来源和方向状态 |
| `hydraulic.cross_section_profile` | Topography ID、测量日期/方法、垂向基准、profile hash 和活动版本 |
| `hydraulic.cross_section_point` | 有序 offset/elevation、测点 XYZ 和标志点 |
| `hydraulic.cross_section_roughness_zone` | 不重叠的 Manning 区间 |
| `hydraulic.cross_section_processing` | profile hash + 处理器版本 + 步长的缓存身份 |
| `hydraulic.cross_section_hydraulic_row` | 水位—面积—顶宽—湿周—水力半径—输水能力查算表 |
| `hydraulic.import_job` | 不可变源文件、坐标/解析配置、变换证据、预览与提交状态 |
| `hydraulic.validation_run/result` | 持久化校核批次和问题证据 |
| `hydraulic.gis_*_adapter` | 只读旧 GIS 适配视图 |

## 3. 一致性与坐标

- 主要跨实体引用使用 `(id, dataset_version_id)` 复合外键，阻止跨版本拼接。
- source CRS 只允许 4326、4490、4546–4549；engineering CRS 必须是受控的米制 4546–4549，不能把 4490 经纬度用于吸附、距离或桩号计算。
- 源 XYZ、轴序、中央经线、分带、单位、垂向基准、配置 hash 和变换样点均保留；不根据数值大小猜测坐标系。
- 权威显示几何保存为 EPSG:4490；距离、拓扑和 chainage 运算在已确认 engineering CRS 中执行。

## 4. 数据与模型链

文件先解析为中立 DTO，再经坐标证据与规则校核进入原子 commit。正式断面由“空间位置 + 多个测量 Profile”组成，粗糙度和水力查算结果依附 Profile。`dayu.model-input.v3` 读取正式 Network/Node/Branch/Reach/Profile/Roughness/Processing；求解器边界通过纯适配器转为现有 v2 契约。

## 5. 当前验证边界

SQL 离线生成、模型装载、解析/适配测试和前端构建已通过。一次性 PostgreSQL 17/PostGIS 3.5 + TimescaleDB 隔离库也已完成真实 0019 升降级、双向兼容写入、空间拓扑、SRID 4490 与导出门禁。浏览器数据闭环和持久数据库迁移仍未执行，不能把隔离数据库通过写成持久部署或浏览器验收。
