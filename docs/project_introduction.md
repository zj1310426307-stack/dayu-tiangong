# 大禹·天工项目介绍

“大禹·天工”是面向河网数字孪生的统一水利数据、自动建模、计算调度、GIS 和成果分析平台。平台不以重新实现成熟数值求解器为目标，而是通过统一数据模型、Adapter、独立任务和统一结果层整合成熟开源能力。

## 当前能力

- GIS：PostGIS 权威数据、GeoServer 发布、OpenLayers 展示和 QGIS 受控生产链。
- HYDRO-DATA-01：保留 `Network → Branch → Chainage → Cross Section`，支持断面点、粗糙率、边界、初始条件、方案和导入校验。
- Standard 1D：`Hydraulic1DEngine → MascaretEngine → 官方 MASCARET v9.1.1 → Unified Hydraulic Result`。
- 任务平台：Simulation Case 冻结、输入摘要、构建身份、Celery 生命周期、取消/重试和结果持久化。
- Benchmark：矩形恒定均匀流、粗糙率敏感性、洪水过程、多断面天然河道和上下游边界五类基准。

## 能力边界

默认 Dayu 镜像不捆绑 MASCARET 执行文件；只有在部署方提供并验证官方 v9.1.1 运行时后才可设置 `MASCARET_ENABLED=1`。未安装运行时不等于模拟成功，集成测试必须显式跳过。

当前 Adapter 不支持 Pump，不支持的数据必须显式验证失败，不得降级成其他物理对象。多 Branch、湿干、工程率定、实时遥测、PLC/SCADA 下发、统一 IAM/RBAC 和生产高可用仍待后续建设。

详细架构见 [当前架构](./architecture.md) 和 [MASCARET 1D Adapter](./model/MASCARET-1D-ADAPTER.md)。
