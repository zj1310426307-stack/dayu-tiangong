# REAL-01 数据模型与治理缺口

状态：`IMPLEMENTED_FRAMEWORK / DATA_REQUIRED`。本文记录真实“五河两闸”资料治理所需能力与现有统一水力 Domain 的映射，不记录任何原始工程数值、坐标或文件内容。

## 结论

现有 `DatasetVersion`、`hydraulic.network/node/branch/cross_section/profile/structure`、`BoundaryCondition`、`HydraulicImportJob` 和 `HydraulicObservationSeries` 已能够表达 REAL-01 的权威对象、来源哈希、CRS/高程基准、QA 和版本关系；不新建并行试点库。

REAL-01 新增的是以下治理能力：

1. `GET /api/v1/model-data/dataset-versions/{id}/real-01-readiness`：从已入库对象生成准入状态、缺失清单、假设提示、完整工程图 hash 和就绪度；它不会填补值或更改状态。
2. 版本克隆按完整统一工程图的依赖顺序重建本版本 ID；执行 Task、运行目录、结果产品不复制，必须重新运行。
3. `DatasetVersion.engineering_content_hash`：冻结时保存完整统一工程图 hash，不改变旧 `content_hash` 的四类 GIS 兼容语义。
4. `POST /api/v1/model-data/dataset-versions/{id}/freeze-real-01`：只有资料齐全、已通过统一水力 QA 且仍可编辑的版本才可冻结；操作不启动 MASCARET 或 D-Flow。

## 源数据、QA 与存储边界

| 需求 | 现有权威对象 | REAL-01 规则 |
|---|---|---|
| 原始文件、SHA-256、转换配置 | `hydraulic.import_job` | 原始字节仅存受控数据库/交付归档；Git 仅保存模板、代码和文档。 |
| 水平 CRS 与轴映射 | Network / ImportJob coordinate evidence | 必须明确工程 CRS、中央子午线、轴映射和转换链。 |
| 高程基准 | Network、Profile、Boundary/Observation metadata | 必须明确垂直基准和单位；`unknown` 不可冻结。 |
| 五河河网 | Network / Node / Branch / BranchVertex | 方向、节点、中心线、桩号应在同一 Dataset Version 内。 |
| 横断面 | CrossSection / Profile / Point / RoughnessZone | 原始 Station/Elevation 不可被派生空间线改写。 |
| 两座水闸 | Unified Structure (`gate`) | 位置、桩号、底槛、孔宽/数量、水力参数和来源缺一不可。 |
| 上游 Q(t)、下游 H/H(t) | BoundaryCondition | 值、单位、时间基准和来源均必须留痕。 |
| 观测与外部成果 | ObservationSeries / ExternalResult | 缺失时只能未率定审查，不能宣称率定或独立验证。 |

## 不表达为“默认值”的内容

糙率、初始条件、闸门系数、边界过程、设计水位和观测质量码没有来源证据时均为缺口。平台不会以历史示例、合成数据或运行时默认值补齐真实工程资料。

## 当前真实资料盘点状态

本任务开始时工作区只识别到一条河道的部分中心线与横断面原始文件。它们可作为待治理来源，但不构成“五河两闸”完整工程，也未被写入 Git、模拟测试或真实试点结论。因此当前项目状态仍是 `FRAMEWORK_READY_DATA_REQUIRED`。
