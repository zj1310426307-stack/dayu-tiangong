# 工程图谱克隆与冻结计划

## 目的

把可编辑的 Dataset Version、河网、断面、边界、统一建筑物与闸泵调度计划转换为可复算的水动力输入；不复制或另建第二套业务水力 Domain。

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

## 引擎分流

- 无活动 Gate/Pump 的 Standard 1D：`mascaret/production`，先通过 MASCARET 能力矩阵。
- Gate/Pump 受控子集：仅从冻结调度计划创建 `d-flow-fm/synthetic`；`pilot` 目前只是资料准入合同，执行路径在 REAL-02 前禁用。其能力矩阵、控制合同、runtime provenance 和结果 schema 全部随任务冻结。
- 任何未登记结构、未知 engine、历史无法确证路线或跨引擎回退：拒绝执行并保留原因。

## 冻结核验点

1. 创建任务：解析 engine、执行类别和模型必需能力。
2. Worker 领取：比较任务 provenance 与注册表。
3. 运行前：复验模型能力与运行时 identity。
4. 结果写入：复验引擎、结果 schema 与任务冻结身份。

这使工程图谱可删除运行派生产物后重新生成，而不改写原始河网、断面、边界、建筑物或调度资料。
