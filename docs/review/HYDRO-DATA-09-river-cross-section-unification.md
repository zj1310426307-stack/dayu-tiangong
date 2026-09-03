# HYDRO-DATA-09 河道与横断面数据链统一报告

日期：2026-09-03
分支：`feature/hydro-data-river-cross-section-unification-09`

## 结果

- 河道数据库页面改为读取 `/api/v1/hydraulic/networks` 的 Network → Branch 权威数据，展示河网/河段身份、流向、来源修订、桩号范围、长度、河网点、断面数和工程 CRS。
- 横断面数据库页面改为读取同一接口中的 Section 摘要，并通过 `/api/v1/hydraulic/cross-sections/{id}` 获取 Profile / Point 详情和曲线。
- 通用导入中心不再允许河网或断面绕过坐标声明与预览哈希；两类数据统一进入 `/api/v1/hydraulic/imports/preview|commit`。
- `HydraulicBranchRecord` 增加 `flow_direction`、`source_revision`、`vertex_count`，OpenAPI 生成客户端已同步。
- 横断面 XLSX 合同改为六列：`ID、TOPOID、里程、偏移、高程、river_name`。解析器兼容组内空白身份行，按 `(ID, TOPOID)` 分组，仍对未知 Branch 和整批错误 fail closed。
- 断面单独导入现在会读取目标数据库 Branch 的起止桩号；修复了旧逻辑只校验 Branch 编码、随后把越界断面夹到河端点的风险。
- `hydraulic.cross_section/profile/point` 现有规范化结构已能无损承载该合同，因此本次不新增无意义数据库列或 Alembic 迁移；`public.river/cross_section` 保持同事务兼容投影。

## 数据边界

用户工作簿只作为字段与版式参考，未写入仓库、未提交其工程数据，也未导入正式数据库。仓库模板使用明确的合成示例。六列文件不包含断面轴线或测点 XY，系统不会伪造这些证据。

用户后续提供的 `gaominghe` 中心线截图已逐点整理为项目参考工作簿：21 点、桩号 `0–5432.1266 m`、几何折线累计长度约 `5432.1761 m`，最大累计差 `0.11285 m`。其 Branch 编码与断面表 `river_name=gaominghe` 一致。该资料只声明“CGCS2000”，未声明具体 3°/6°投影带/EPSG，因此未写入数据库；工作簿明确标记为“待确认 EPSG”。

断面范围联检发现 `DM21=5432.5237 m`（超出约 `0.3971 m`）和 `DM22=5725.8932 m`（超出约 `293.7666 m`）。在中心线终点或断面里程得到确认前，正式预览应返回越界错误，不能提交。

## 验证摘要

- 用户工作簿反读：22 个 Profile，424 个断面点，1 个 Branch 标识；解析配置 `hydraulic-xlsx-v2`。
- 模板结构/公式/视觉：两个正式模板 SHA-256 一致；六列表头与分组空白行正确；公式错误 0；渲染通过。
- 后端：Excel/HYDRO 交换与导入安全测试 16 项通过；Phase 2、兼容性和工程 API 组合测试 10 项通过、6 项按环境标志跳过；启用真实 PostGIS 标志后工程集成 1 项通过。
- 静态/API：Ruff 通过；OpenAPI 客户端重新生成；TypeScript 类型检查通过。
- 前端：本机与 Docker 两次生产构建通过，仅保留既有 antd/ECharts 大分块提示。
- 运行态：Docker 后端健康；`/api/v1/health` healthy；`/api/v1/gis/health` 返回数据库 `dayu_tiangong`、SRID 4490；模板下载 200。
- 浏览器：河道库、横断面库、数据导入中心三页视觉与链接验收通过。

## 未扩大声明

本次验证覆盖数据合同、数据库/API 查询、模板、导入解析和浏览器工作流，不代表用户工作簿已经作为正式工程数据提交，也不新增 MIKE11 原生运行能力声明。
