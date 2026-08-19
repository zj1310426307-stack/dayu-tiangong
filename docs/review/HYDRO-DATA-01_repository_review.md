# HYDRO-DATA-01 仓库差距审计

日期：2026-08-18
当前分支：`feature/HYDRO-DATA-01`
基线：`main@cfd2b02`
代码迁移头：`20260818_0019`
持久库当前修订：`20260817_0018`

## 1. 安全策略

工作区已有未提交 HYDRO-DATA-01 修改，因此不切换或重命名分支，不覆盖现有文件。附件中的 `agent/hydro-data-01` 和“执行结束后提交”只作为参考；本轮没有获得 Git 提交、推送、持久迁移或合并授权。

## 2. 当前实体关系

- `public.dataset_version` 是 GIS、模型、调度和优化的共同版本身份。
- `public.river` 和 `public.cross_section` 仍为旧 API 与 GIS 的核心对象；断面同时存在 `points JSON`、`cross_section_point` 和 `cross_section_profile.profile JSONB` 三种表达。
- 0019 初稿已增加 `hydraulic.network|branch|chainage|cross_section|cross_section_point`，但缺少 node、reach、多测次 profile、糙率分区、查算缓存和统一坐标溯源。
- `public.river_node|river_segment|river_connection` 有拓扑对象，但外键主要是单列 ID，未全面防止跨 Dataset Version 引用。

## 3. 当前 API 与前端

- 旧 API 提供 River/CrossSection CRUD、数据导入、拓扑生成、Dataset Version 和模型任务。
- 0019 初稿提供 `/api/v1/hydraulic/*` 河网树、导入预览/提交、校核、模板与交换导出。
- 新前端页面能浏览 Network–Branch–Section、剖面曲线和导入审计，但还没有 Reach/节点、反向、米制拓扑、profile 切换、糙率分区和查算表工作流。
- 前端水动力调用已经只经 OpenAPI 生成客户端，这一边界应保留。

## 4. 导入链差距

- 现有 GIS Import Batch、staging、validation、review、promotion 和 publish 链完整，但 0019 初稿另建了 `hydraulic.import_job|validation_*`，尚未与 `gis_import_batch` 关联。
- Excel/SHP/DXF 可解析，但缺少强类型 CoordinateReferenceSpec、显式轴序、垂向基准门禁、转换管线/版本、源目标包络和样点证据。
- preview 和 commit 已分离，但 commit 只依赖保存的 payload，缺少预览配置 hash 二次校验。
- `.nwk11/.xns11` 子集仍和核心 importer 同目录，需迁到隔离 adapter 边界。

## 5. 模型输入链

- `dayu.model-input.v1` 是独立河道兼容输入，`v2` 增加节点、连接和表格化断面并驱动当前有向河网求解器。
- 当前模型快照直接读旧 River/CrossSection 投影，没有 network/reach/profile/roughness/processing/coordinate provenance。
- 需要新增 v3 中立快照和 v3→v2 适配层，不重写 Saint-Venant 求解器。

## 6. 严重正确性问题

1. `river.service.generate_topology` 用经纬度量化容差、对所有形状顶点建节点，并以 `math.hypot(delta_lon, delta_lat)` 分配长度，不符合米制水动力拓扑。
2. `flow_direction='forward'` 在旧数据回填中被默认当作已确认，应改为 `inferred`或 `unknown`。
3. 断面 axis 缺失时需记录待验证，不得推测并标记 confirmed。
4. 新表虽有部分复合外键，但完整 Network–Node–Branch–Reach–Profile 关系尚未存在；现有拓扑表也存在跨版本漏洞。

## 7. 兼容与回退边界

- 新 `hydraulic` 模型成为水动力权威语义；旧 API 通过同事务兼容投影继续工作。
- 0019 仍未进入持久库，可在本分支直接扩展为完整结构，避免为未部署草案再叠加一个修补迁移。
- downgrade 只移除加法 `hydraulic` schema 及本迁移为旧表增加的约束；生产恢复依赖升级前备份。
- 持久库仍保持 0018，全部 upgrade/downgrade/upgrade 只能先在一次性库验证。
