# REAL-01 试点资料准入合同

状态：`DATA_REQUIRED`。本合同定义 HYDRO-DATA-REAL-01 允许接收什么资料、如何记录缺口以及何时拒绝冻结；它不是数据库迁移、数据导入器或真实工程运行授权。

## 资料域与状态

每一域必须记录 `AVAILABLE`、`PARTIAL`、`MISSING`、`NOT_APPLICABLE`、`NEEDS_CONFIRMATION` 或 `REJECTED`，不得用默认值把 `MISSING` 伪装成可运行数据。

| 数据域 | 统一 Domain 入口 | REAL-01 初始要求 | 缺失处理 |
|---|---|---|---|
| PROJECT / DATASET_VERSION | Project、Dataset Version | 工程身份、用途、责任人、来源版本 | BLOCKER |
| CRS / VERTICAL_DATUM | Dataset Version metadata | 水平 CRS、投影带、垂直基准、单位 | BLOCKER |
| RIVER_NETWORK / NODE / BRANCH | Network、Node、Branch | 拓扑、流向、Chainage、中心线 | BLOCKER |
| CROSS_SECTION / POINT | CrossSection、CrossSectionPoint | Branch/Chainage、Station/Elevation、单位 | BLOCKER |
| ROUGHNESS | profile / roughness parameters | 分区值、来源与适用范围 | 模型使用时 BLOCKER，否则 WARNING |
| GATE | Unified Structure / Gate | 2 座 Gate 的 Branch/Chainage、底槛、孔宽/数量、几何与控制来源 | BLOCKER |
| PUMP | Unified Structure / Pump | 当前无真实资料，显式 `NOT_AVAILABLE` | 不阻断 MASCARET baseline；阻断 Pump pilot |
| BOUNDARY / INITIAL_CONDITION | Boundary、Simulation Case | 上游 Q(t)、下游 H 或 H(t)、时间基准、单位 | BLOCKER |
| OBSERVATION | Observation series | 率定/独立验证用 H/Q、仪器与质量码 | REAL-01 导入可 WARNING；率定/验证为 BLOCKER |
| SCENARIO / DISPATCH_PLAN | Simulation Case、Dispatch Plan | 工况来源及冻结控制证据 | 需要调度模拟时 BLOCKER |
| SOURCE_EVIDENCE / QUALITY_STATUS | 既有 source hash、import job、QA 记录 | 来源、责任、审核与可复算证据 | BLOCKER |

## 必填元数据

每一条原始资料或人工录入均须在其已有的来源/导入/版本字段中保留：`source`、`source_file`、`source_version`、`source_date`、`unit`、`horizontal_crs`、`vertical_datum`、`data_owner`、`responsible_person`、`quality_status`、`review_status`、`evidence_reference`、`missing_reason`、`assumption_flag`。本合同不新建平行数据库字段；字段由现有导入元数据、Dataset Version、结构参数、Boundary、Observation 与 QA 记录承接。

## 阻断规则

以下任一条件不满足时，`real_01_ready=false`：河网拓扑不确定；断面无法映射到 Branch/Chainage；Station/Elevation 单位不明；CRS 或高程基准不明；上游或下游边界缺失；边界时间基准不明；Gate 的 Branch/Chainage、底槛或孔宽/数量缺失；资料来源不可追溯。粗糙率、初始条件和观测的阻断级别必须按拟运行类型显式记录，不能无依据填值。

## 原始资料到统一 Domain 映射

| 原始资料 | 统一 Domain | 当前入口 |
|---|---|---|
| CAD 河道中心线 | Branch geometry | MANUAL / 已有河网导入 |
| SHP 河网 | RiverNetwork / Node / Branch | MANUAL / 已有河网导入 |
| 测量横断面 Excel | CrossSection / CrossSectionPoint | 已有断面导入 |
| 水闸设计资料 | Structure / Gate | MANUAL / 已有统一建筑物录入 |
| 泵站设计与曲线资料 | Structure / Pump | MANUAL；当前无真实资料 |
| 洪水过程 | Boundary Q(t) | MANUAL / 已有 Boundary 入口 |
| 下游设计水位 | Boundary H / H(t) | MANUAL / 已有 Boundary 入口 |
| 调度规程 | DispatchPlan source evidence | MANUAL；规则执行未实现 |
| 实测 H/Q 与 MIKE11 导出 | Observation / external result | 已有资料入口；需按 QA 复核 |

“MANUAL”或“PLANNED”不代表自动 importer 已实现；`NOT_IMPLEMENTED` 的入口不得作为 READY 依据。

## 准入与执行边界

REAL-01 只在真实工程资料进入统一 Domain、完成 QA 并冻结 Dataset Version 后建立真实 SimulationCase。它不运行 D-Flow Pilot。D-Flow 的 Pilot Contract 已定义，但 `pilot_execution_enabled=false`；真实 D-Flow Pilot 是后续 REAL-02 的独立任务，且不会由一次试跑获得 production eligibility。

空白可填模板见 [templates/real-engineering-pilot-manifest.yaml](templates/real-engineering-pilot-manifest.yaml)。
