# HYDRO-MODEL-02 v3→v4 迁移与回退设计报告

- 文档状态：`MIGRATION PLAN / NO MIGRATION EXECUTED`
- 当前数据库迁移：无
- 当前 API 变更：无
- 当前默认求解器变更：无

## 1. 结论

v4 必须是加法、显式且可审计的原生输入版本。不能修改 v3 的含义，也不能让 v4 继续走
`v3 -> v2 -> continuity-Manning`。回退通过 solver selector 和应用版本完成，不通过破坏性
删除 v4 快照或有损改写历史结果完成。

## 2. 兼容矩阵

| 输入 | 路由 | 结果 | 策略 |
|---|---|---|---|
| v1 | legacy single-river FV | result v1 | 只维护兼容回归 |
| v2 | legacy network continuity-Manning | result v2 | 保留 |
| v3 | v3→v2 adapter→legacy network | result v2 | 保持业务字段/serializer/结果语义；固定 provenance 时字节稳定 |
| v4 | native Saint-Venant FV | planned result v3 | 新增，初期禁用/shadow |

禁止用同一个 solver ID 表示不同算法。

## 3. 纯迁移函数

未来 `migrate_v3_to_v4` 只复制可证明事实：

- Dataset Version、Network、Node、Branch、Reach；
- Profile、profile hash、processing ID/version；
- CRS、单位和垂向基准；
- 常值/series 边界；
- Gate/Pump 静态参数、位置和 provenance；
- compatibility mapping 仅作为旧系统证据。

现有 compatibility bridge 只覆盖 node、segment→Branch 和 cross-section。Gate/Pump 仍使用
public 资产 ID；A1 必须先决定 v4 canonical structure identity 是继续使用
`(structure_type, public_asset_id)`，还是新增 hydraulic structure identity，迁移器不得按整数
相等自动改写。

必须生成：

- `source_v3_hash`；
- `target_v4_hash`；
- `migration_version`；
- copied/defaulted/blocked 字段清单；
- 每项 warning、assumption 和 loss；
- readiness 状态。

原 v3 快照永不覆盖。

## 4. 不允许自动推断的项目

- single default n 不能自动宣称为 Left/Main/Right 三区；
- 全局 active Profile 不能自动成为所有未来工况的选择；
- 无结构桩号/Reach 时不能从 GIS 最近距离猜测；
- null Gate/Pump 初始态不能自动视为关闭/停止；
- 一个全网初始水位/流量不能自动视为生产初态；
- 缺失边界覆盖不能自动延拓；
- v3 的参考 CFL 不能转写成已验证 v4 最大时间步；
- public ID 不能按整数相等当作 hydraulic ID。

上述任一项影响可计算性时，迁移结果为 `not_ready`。

## 5. v4 双读发布顺序

### M0：文档和合同

- 当前状态：本报告完成；
- 不改 runtime。

### M1：schema/validator/migrator

- 先让所有在役 API/Worker 对未知 input schema fail closed，禁止未知版本落入 v1 路由；
- 增加 `ModelInputV4`；
- 只允许生成/校验，不允许普通用户执行；
- 保存 migration manifest 和双 hash；
- v3 契约测试必须原样通过。

### M2：原生 solver selector

- 注册 v4 原生路由；
- feature flag 默认关闭；
- v4 使用独立 queue/Worker capability 标识，legacy Worker 不领取 v4；
- benchmark 环境可显式启用；
- 未注册 solver/scheme fail closed。

### M3：shadow tasks

- 同一冻结业务事实创建独立 v3 legacy 与 v4 shadow task；
- 两份结果都保存 input hash、solver ID、engine commit；
- 绝不覆盖或混合结果；
- 对比是诊断，不把 legacy 当真值。

### M4：opt-in

- 仅在科学 Benchmark、外部对比和性能门通过后，对获准案例开放；
- UI 明确显示 solver family；
- 旧任务仍按其冻结版本重放。

### M5：default cutover

- 专家签字；
- 真实工程率定；
- 回退演练；
- 生产监控和失败策略完成；
- 默认变化写入版本发布说明。

## 6. 数据库策略

现有 `SimulationTask` 已保存 input schema、snapshot/hash、engine version/commit；现有
SimulationResult/JunctionResult/StructureResult 也已有时序形态。第一步先评估增量增加：

- canonical hydraulic entity ID；
- result schema 与 solver ID；
- mesh hash、validation policy/hash；
- cell/diagnostic artifact 引用；
- 索引和分页所需字段。

`JunctionResult.node_id` 当前为非空 public `RiverNode` FK，无法保存没有 legacy 映射的纯
hydraulic 节点；仅添加 `hydraulic_node_id` 仍不够。M3 前必须二选一：新增 v4 junction 表，
或 additive 增列并将旧 node FK 改为 nullable，同时增加“legacy 或 hydraulic 恰有一个”的
条件约束与对应唯一索引。`StructureResult.structure_id` 当前是裸整数，也必须与 canonical
structure identity 决策一起改为无歧义合同。

只有性能/实体完整性评估证明复用合理时才扩展现表，否则新增结果表。所有数据库迁移必须
additive：先双写、再切读，不删除旧列/旧 API。

现有结果表引用 public 兼容实体，v4 应以 hydraulic ID 为权威；有映射时再生成 legacy 投影。
历史 v3 只能依据各任务冻结的 compatibility mapping 回填，禁止按当前数据库或整数巧合回填。

## 7. API/OpenAPI 策略

未来 API 变化顺序：

1. 新增后端强类型 Pydantic DTO；
2. 更新并校验 `/openapi.json`；
3. 重新生成 `frontend/src/api/generated/client.ts`；
4. 更新 required paths 和后端/前端契约测试；
5. 前端只通过生成客户端访问；
6. 保留旧任务、单断面结果和 dispatch API。

节点、结构物和 task result manifest 应获得正式分页/降采样 DTO，不继续以通用
`list[dict]` 作为长期合同。

## 8. 冻结一致性整改

在 v4 可执行前：

- 锁定 approved/published Dataset，或使用一致性事务快照；
- 同一边界锁定 Plan/Action/Rule；
- create-run 和 Worker claim 前分别复算 `snapshot_hash(plan.frozen_snapshot)`，与
  `plan.frozen_snapshot_hash` 比对；不得通过重新生成 task hash 掩盖 Plan 已失配；
- validation run 绑定 Dataset content hash、Profile hashes 和 validator version；
- Worker 执行前用现行
  `SHA-256(UTF-8(canonical_json(snapshot)))` 重算 input snapshot hash；`canonical_json` 的当前合同
  是键排序、紧凑分隔符、UTF-8 直出、日期/UTC 时间规范化、`-0.0 -> 0.0` 且拒绝非有限值；
- v4/migration manifest 保存 `canonicalization_id=dayu-canonical-json-v1`、`hash_algorithm=sha256`
  和 `hash_domain`；snapshot domain 是含 provenance 的完整冻结快照，mesh/validation 各用独立
  domain；manifest 自身 hash 排除 `manifest_hash` 字段或以 detached hash 保存，禁止自引用；
- Worker claim 必须校验
  `task.input_schema_version == snapshot.schema_version == snapshot.provenance.input_schema_version`、
  `task.engine_version == snapshot.provenance.engine_version`、
  `task.engine_commit == snapshot.provenance.engine_commit`，并核验注册的 schema/solver 组合；
- mesh 生成后保存 mesh hash；
- engine version 由单一提供器生成；
- result schema 绑定对应质量门；
- 未知 schema 不能绕过 finite/balance 检查。
- Worker 对未知 input schema 必须在进入引擎前返回 unsupported/failed，禁止落入 v1 fallback。

## 9. 回退

应用回退步骤：

1. 首次创建 v4 前已部署“未知 schema fail closed”兼容底座，并使用独立 v4 queue；
2. 暂停创建和领取新的 v4 task；
3. 等待正在运行的 v4 task 安全结束或协作取消，对仍排队任务可靠 revoke/purge 并留审计；
4. 确认 legacy Worker 不会领取 v4 后，将创建入口切回原 v3 legacy selector；
5. 保留全部 v4 snapshot/result/manifest；
6. 旧版本只读无法解释 v4 时应显示 unsupported，而不是伪装 v3；
7. 恢复新版后继续读取或重跑 v4。

不提供一般性的 v4→v3 降级，因为分区粗糙率、精确查算、结构初态和数值配置不能无损表达。
只有完全落在 v3 可表达子集时才允许导出，并附 loss report。

数据库 downgrade 若遇到 v4-only 数据必须 BLOCK 或先归档；不能删除数据后称“无损回退”。

## 10. 验收清单

- [ ] 固定 provenance 下 v3 canonical bytes 稳定，业务/legacy 结果语义不变；
- [ ] 每个 v3/v4 task 的 stored snapshot 与 stored hash 自洽；
- [ ] task 行 schema/engine 元数据与 snapshot provenance 全部一致；
- [ ] snapshot/mesh/validation/migration manifest 的 canonicalization 与 hash domain 明确且不自引用；
- [ ] v4 缺信息 fail closed；
- [ ] migration manifest 可复现；
- [ ] v4 不经过 v2 adapter；
- [ ] v3/v4 结果按 schema/solver/hash 隔离；
- [ ] canonical hydraulic ID 可持久化；
- [ ] Plan frozen hash 与 Worker task hash 均在各自边界复核；
- [ ] 未知 input schema fail closed，v4 queue 与 legacy Worker 隔离；
- [ ] OpenAPI/生成客户端同步；
- [ ] shadow/opt-in/default 三阶段开关独立；
- [ ] 回退演练不删除 v4 历史。

当前上述项目均为计划，未执行迁移，也未改变默认运行行为。
