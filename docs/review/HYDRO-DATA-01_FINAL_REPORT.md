# HYDRO-DATA-01 生产级优化实施报告

> **历史基线（2026-08-18）：** Network–Branch–Chainage–Cross Section 数据成果继续有效，但本文中 v3→v2 旧求解器边界已由 [HYDRO-1D-RESET-01](../migration/HYDRO-1D-RESET-01.md) 取代。当前计算路线为 Unified Hydraulic Model + MASCARET Adapter。

日期：2026-08-18
分支：`feature/HYDRO-DATA-01`
基线：`main@cfd2b02`
状态：本地代码、离线门禁与隔离 PostGIS 运行验收完成；浏览器数据闭环和持久迁移待补

## 交付结论

HYDRO-DATA-01 已从文件交换层扩展为 Network–Node–Branch–Reach–Chainage、断面多地形版本、糙率分区、水力查算缓存和 `dayu.model-input.v3` 数据链。实现继续使用同一 PostGIS 和 Dataset Version，以 `hydraulic` schema 作为水动力权威语义，以现有 `public.river|cross_section|river_node|river_segment|river_connection` 作为兼容投影，没有创建第二数据库。

## 已完成

- 完整 0019 加法迁移：复合版本外键、几何/范围/唯一性约束、旧数据回填、适配视图和可逆 downgrade。
- 强类型坐标声明：source/display/engineering CRS、轴序、单位、垂向基准、中央经线和分带；预览保存源文件 SHA-256、配置 hash、PostGIS/PROJ 变换证据。
- 导入链：Excel、CSV、GeoJSON/SHP ZIP/DXF 和文档化 NWK11/XNS11 交换子集；preview 与 commit 分离，commit 必须匹配预览配置 hash。
- 米制拓扑：端点/交点吸附、Node/Reach 生成、重叠/短 Reach/自环/重复边/断连 QA、流向反转和桩号重算；正式拓扑同步投影到现有 GIS 拓扑表。
- 断面链：同一断面的多个 Topography ID/Profile、有序测点、标志点、糙率分区、实测轴线定位、人工覆盖审计、按 profile hash 缓存的水力查算表。
- 模型链：生成 `dayu.model-input.v3`，在求解器边界确定性适配为现有 v2 河网输入，并在结果中保留源 schema provenance。
- API/OpenAPI/前端：节点与 Reach 浏览、坐标配置、拓扑、反向、桩号重算、断面定位、多 Profile、批量查算和 v3 输入接口；前端只调用生成客户端。
- 两份正式 Excel 模板已重做并完成逐页渲染检查和解析器反读。

## 本轮实际验收证据

| 门禁 | 结果 |
|---|---|
| HYDRO-DATA-01 解析、模板、坐标、OpenAPI | 纳入后端回归并通过 |
| HYDRO 定向复核 | `13 passed`，覆盖交换链与 v3 适配器 |
| 全仓测试 | `215 passed, 71 skipped, 0 failed`；跳过项均为显式外部环境门 |
| FastAPI 装载 | 成功，175 条路由 |
| Alembic 静态门禁 | `20260817_0018 -> 20260818_0019` SQL 成功生成 |
| 隔离数据库迁移 | PostgreSQL 17/PostGIS 3.5 + TimescaleDB：`upgrade 0019 -> downgrade 0018 -> upgrade 0019` 成功；升级后 16 张 `hydraulic` 表，降级后 schema 完整移除 |
| 真实 PostGIS 双写/拓扑 | `backend/tests/test_hydraulic_postgis.py`：`1 passed`；覆盖 hydraulic/旧 GIS 双向兼容、拓扑、SRID 4490 与导出 |
| TypeScript | `tsc -b` 通过 |
| 前端生产构建 | Vite 通过；水动力页产物约 15.95 kB |
| Excel 模板 | 4 个工作表逐页渲染通过；两份 XLSX 解析反读、0 公式错误 |

## 尚未完成的运行验收

- 隔离数据库已完成 0019 升降级与真实双写/拓扑门禁，但尚未完成浏览器导入、拓扑、Profile、查算和 v3 输入的数据闭环；不把静态构建或 API 测试冒充浏览器验收。
- 持久数据库仍应视为 0018；本轮没有迁移或写入持久业务数据。
- 本轮隔离镜像是仓库部署基线 PostgreSQL 17/PostGIS 3.5 + TimescaleDB，不等同于 HYDRO-DATA-02 另行指定的 PostgreSQL 16 验收矩阵。
- 没有真实工程 `.nwk11/.xns11` 样例和授权 DHI 运行环境，能力仍为 `ROUNDTRIP_VALIDATED_ONLY`，不声称原生兼容。

## 操作边界

- 本阶段成果在 `feature/HYDRO-DATA-01` 分支封存；未推送、未创建 PR。
- 持久升级必须另行获得备份与维护窗口授权。
- 真实工程使用仍需要坐标资料确认、实测断面、模型率定和专项验证。

## 关键位置

- 代码：`backend/app/hydraulic/`、`backend/app/hydraulic_adapters/`、`model/adapters/`、`frontend/src/pages/hydraulic-data/`
- 迁移：`database/migrations/versions/20260818_0019_hydraulic_exchange_schema.py`
- 模板：`outputs/HYDRO-DATA-01-20260818/`
- 迁移验证器：`tools/verify_hydraulic_migration.py`
- 决策与审计：`docs/adr/ADR-HYDRO-*.md`、`docs/review/HYDRO-DATA-01_repository_review.md`
