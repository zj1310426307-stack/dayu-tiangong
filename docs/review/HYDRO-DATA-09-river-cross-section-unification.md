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
- 中心线点与断面组统一采用上游到下游的表格语义：中心线桩号严格递增，断面里程按 Branch 非递减；预览对倒序断面返回 `SECTION_CHAINAGE_ORDER_INVALID`。
- Branch 增加 `centerline_role`，可明确标识实测中心线或纵向深泓线；河道数据库、OpenAPI 和生成客户端使用同一字段。
- 六列断面表在未显式给 marker 时自动标记最低高程深泓点；同高最低点全部保留并提示复核。纵向深泓线与横向断面测线严格分离，后者缺失时方向仍为 `pending`。
- 导入页不再硬编码“1985 国家高程基准”，未明确高程基准时不能预检。
- `hydraulic.cross_section/profile/point` 现有规范化结构已能无损承载该合同，因此本次不新增无意义数据库列或 Alembic 迁移；`public.river/cross_section` 保持同事务兼容投影。

## 数据边界

用户工作簿只作为字段与版式参考，未写入仓库、未提交其工程数据，也未导入正式数据库。仓库模板使用明确的合成示例。六列文件不包含断面轴线或测点 XY，系统不会伪造这些证据。

用户后续提供的 `gaominghe` 中心线截图已逐点整理为项目参考工作簿：21 点、桩号 `0–5432.1266 m`、几何折线累计长度约 `5432.1761 m`，最大累计差 `0.11285 m`。其 Branch 编码与断面表 `river_name=gaominghe` 一致。用户已确认中央经线 114°、中心线与断面均按上游到下游依次输入、所给中心线代表各断面最低点组成的纵向深泓线，并进一步明确断面高程采用 1985 国家高程基准。当前 v05 联合导入文件使用 `EPSG:4547`、`flow_direction=forward`、`centerline_role=thalweg`、`vertical_datum=1985_NATIONAL_HEIGHT_DATUM` 和 MIKE11 `Datum=0.000 m`；原始高程不平移，权威 `bed_elevation_m` 仍保持未确认，未执行正式数据库提交。

v03 从 DM1–DM20 的 383 个 Profile 点提取 21 个深泓候选点。20 个断面全部覆盖；DM8 在偏移 `25.8 m` 与 `30.0 m` 处均为最低高程 `31.65 m`，两点都保留并等待人工复核。工作簿另有“深泓线 Thalweg”证据表；其中 alignment XY 只是在用户给定纵向深泓线上按断面里程插值的位置，不冒充缺失的横向断面测线实测 XY。

用户提供了三组特征边界值：P=5% 为 `Q=405.43 m³/s、H=29.721 m`，P=10% 为 `Q=343.74 m³/s、H=29.415 m`，枯水期20%为 `Q=56.16 m³/s、H=27.253 m`。v05 增加“边界 Boundary”表并保留来源、常值诊断解释和 QA 状态。由于资料未指明边界断面/桩号且没有 Q(t)/H(t) 完整过程线，平台不得把这些特征值自动升级为正式工程边界。

断面范围联检发现 `DM21=5432.5237 m`（超出约 `0.3971 m`）和 `DM22=5725.8932 m`（超出约 `293.7666 m`）。在中心线终点或断面里程得到确认前，正式预览应返回越界错误，不能提交。

## 验证摘要

- v05 工作簿反读：`hydraulic-xlsx-v2`；1 个 `thalweg` Branch、21 个中心线点、20 个 Profile、383 个断面点、21 个深泓候选点；错误 0，DM8 并列最低点警告 1 个，横向断面测线缺失警告 20 个。新增边界 QA 表不改变河网/断面解析结果。
- v05 文件 SHA-256：`1EC84DAD014729BD297D2E95BFA7BB98AC0D6CE61ADBD0BF64F90E98B6B49644`；五张表均已渲染检查，公式错误 0。
- MASCARET v9.1.1 诊断：锁定提交 `1fe3b514...`，原生程序 SHA-256 `63296729...`。P=5% 与 P=10% 将 Q 映射到 DM1、H 映射到 DM20 后均因“upstream node negative water depth” fail closed；枯水期 H 比 DM20 河床低 `1.657 m`，在运行前拒绝。该结果证明边界定位/基准或断面覆盖仍需补充，不构成率定模拟。
- 用户原始工作簿反读：22 个 Profile，424 个断面点，1 个 Branch 标识；解析配置 `hydraulic-xlsx-v2`。
- 模板结构/公式/视觉：两个正式模板 SHA-256 一致；六列表头与分组空白行正确；公式错误 0；渲染通过。
- 后端：Excel/HYDRO 交换与导入安全测试 16 项通过；Phase 2、兼容性和工程 API 组合测试 10 项通过、6 项按环境标志跳过；启用真实 PostGIS 标志后工程集成 1 项通过。
- 静态/API：Ruff 通过；OpenAPI 客户端重新生成；TypeScript 类型检查通过。
- 前端：本机与 Docker 两次生产构建通过，仅保留既有 antd/ECharts 大分块提示。
- 运行态：Docker 后端健康；`/api/v1/health` healthy；`/api/v1/gis/health` 返回数据库 `dayu_tiangong`、SRID 4490；模板下载 200。
- 浏览器：河道库、横断面库、数据导入中心三页视觉与链接验收通过。

## 未扩大声明

本次验证覆盖数据合同、数据库/API 查询、模板、导入解析、边界 QA 和 MASCARET fail-closed 诊断，不代表用户工作簿已经作为正式工程数据提交，也不新增 MIKE11 原生运行能力声明。三组边界在明确位置、过程线和率定参数前均不得用于生产结论。
