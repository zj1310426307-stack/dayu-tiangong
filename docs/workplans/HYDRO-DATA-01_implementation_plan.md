# HYDRO-DATA-01 生产级优化计划

> **历史计划 / Solver 部分已废止（2026-08-31）：** HYDRO-DATA-01 数据体系继续有效，但本文关于自研 Saint-Venant、v1/v2/v3 输入适配的求解路线已由 [HYDRO-1D-RESET-01](../migration/HYDRO-1D-RESET-01.md) 取代。

日期：2026-08-18
状态：本地代码、离线门禁与隔离 PostGIS 运行验收完成；浏览器闭环和持久迁移待补

## 目标

将已完成的 HYDRO-DATA-01 交换层升级为可驱动自研一维 Saint-Venant 求解器的生产级数据底座，保持 PostGIS 单库、Dataset Version 治理、现有 API 兼容和 OpenLayers 运行链。

## 执行顺序

1. 扩展 0019：Network/Node/Branch/Vertex/Reach、Section/Profile/Point/Roughness/Processing、复合外键与审计字段。
2. 实现 CoordinateReferenceSpec、预览配置 hash、变换证据和显式轴序；迁移 `.nwk11/.xns11` 到隔离 adapter。
3. 以米制 engineering CRS 重写正式拓扑，增加 Network 定向、反向、重算桩号和 QA。
4. 完成断面 locate/process/batch-process、profile hash、糙率分区和水力查算缓存。
5. 生成 `dayu.model-input.v3`，用适配层转为当前 v2 求解器内部契约，并保留 v1/v2。
6. 扩展 OpenAPI 和前端河网/断面/导入工作流，只使用生成客户端。
7. 已完成 compileall、专项/全量测试、静态迁移 SQL、类型检查、生产构建、模板渲染和报告；一次性 PostgreSQL 17/PostGIS 3.5 + TimescaleDB 已完成 upgrade–downgrade–upgrade 及真实双写/拓扑门禁，浏览器数据闭环和持久迁移按验证记录待补。

## 完成口径

以实际验证为准，不将未执行的 DHI 实机兼容、持久数据库迁移、真实工程率定或前端高并发性能写为已完成。
