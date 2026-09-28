# 工程图谱克隆与冻结计划

## 目的

把可编辑的 Dataset Version、河网、断面、边界、统一建筑物与闸泵调度计划转换为可复算的水动力输入；不复制或另建第二套业务水力 Domain。

当前实现已由 `app.dataset.engineering_graph.clone_unified_engineering_graph` 执行克隆。它依次重映射 ImportJob、网络、节点、河段、顶点、Reach、断面、剖面、点、糙率区、处理表、结构、边界、方案、结构方案、观测和外部成果。`legacy_*` 仅是旧 GIS 投影，跨版本克隆时清空，避免形成指向父版本的外键；统一水力图保持权威。

## 克隆顺序

```text
Raw Engineering Data
  → Import / Manual Entry → QA → Dataset Version
  → River Network / Node / Branch / Cross Section / Boundary / Structure / Dispatch Plan
  → Approved or Frozen Engineering Graph
  → Canonical Hydraulic Model + source hashes
  → Capability Resolution
  → SimulationTask (object IDs, versions, hashes, engine_id, execution_class, capability evidence)
  → isolated runtime workspace → Solver → Unified Result
```

每一步只读取权威对象，并把对象 ID、版本、内容 hash 和映射规则写入不可变 snapshot。运行时绝不回读可编辑表；修改资料必须建立或选择新的 Dataset Version 后重新冻结。

完整工程图 hash 由 `app.hydraulic.snapshot.engineering_graph_content_hash` 计算，覆盖统一工程输入和来源证据，排除数据库主键、时间戳、原始文件字节与执行派生物。它写入 `DatasetVersion.engineering_content_hash`；旧 `content_hash` 仍保留给 GIS 四类对象兼容用途。

## 引擎分流

- 无活动 Gate/Pump 的 Standard 1D：`mascaret/production`，先通过 MASCARET 能力矩阵。
- Gate/Pump 受控子集：仅从冻结调度计划创建 `d-flow-fm/synthetic`；`pilot` 目前只是资料准入合同，执行路径在 REAL-02 前禁用。其能力矩阵、控制合同、runtime provenance 和结果 schema 全部随任务冻结。
- 任何未登记结构、未知 engine、历史无法确证路线或跨引擎回退：拒绝执行并保留原因。

## 冻结核验点

1. 创建任务：解析 engine、执行类别和模型必需能力。
2. Worker 领取：比较任务 provenance 与注册表。
3. 运行前：复验模型能力与运行时 identity。
4. 结果写入：复验引擎、结果 schema 与任务冻结身份。

这使工程图谱可删除运行派生产物后重新生成，而不改写原始河网、断面、边界、建筑物或调度资料。克隆明确不复制 SimulationTask、运行时目录、结果产品、生产运行、率定运行和验证结论；这些必须由克隆后的版本重新产生，不能把旧执行证据伪装成新版本结果。
