# HYDRO-1D-RESET-01 架构迁移

日期：2026-08-31
决策：废止 Dayu 自研生产级 1D Solver，Standard 1D 切换到 MASCARET v9.1.1 Adapter。

## 不变的权威边界

HYDRO-DATA-01 继续使用 Dayu 自身的 `Network → Branch → Chainage → Cross Section` 数据结构。Node、Reach、Profile、Point、Roughness、Boundary Condition、Initial Condition、Structure、Scenario、Simulation 和 GIS 映射都是平台权威语义，不改建为 MASCARET 文件表。

已发布 Dataset Version、历史 Simulation Task、历史结果和 Alembic 迁移不删除、不改写。历史自研 Solver 任务可供审计读取，但不能被新建、重试或重放。

## 生产路径变更

```text
旧：API/Worker → Dayu custom Solver / v4-lite → solver-specific result
新：API/Worker → Hydraulic1DModel → MascaretEngine → MASCARET → unified result
```

- 新任务的 engine 固定为 `mascaret`，版本固定为 `v9.1.1`。
- 任务冻结 solver-neutral input，业务服务与前端不依赖 `.xcas/.geo/.loi/.lig/.opt`。
- Worker 队列收敛为 `hydraulic-1d`，每个 job 使用独立 workspace。
- 结果写入既有 `hydraulic_task_section_result`，并增加 depth、area、hydraulic radius、top width 和 Froude 等 solver-neutral 可选字段。
- 新 `simulation_case.hydraulic_1d_configuration` 保存平台配置，不保存 MASCARET 私有文件作为数据库事实源。

## 部署变更

Dayu 官方镜像只包含 Adapter，默认 `MASCARET_ENABLED=0`。部署方必须先按官方来源提供 MASCARET v9.1.1 CLI 或已审查独立镜像，确认许可证、可执行路径、工作目录写权限和超时后，再显式启用。

回退不得重启已删除的自研 Solver。如果外部运行时不可用，正确状态是任务 fail closed，并在 CI 集成测试中记录 `SKIPPED_MASCARET_RUNTIME_NOT_AVAILABLE`。

## 文档与审计

HYDRO-MODEL-02 B/C/D1/D2/D3A 的重复阶段报告、审查过程和已失效工作计划已从
当前生产树清理；Git 历史与 `hydro-model-02-d3a-rc1` 冻结标签保留原始内容。
当前树仅保留一份最终 D3A RC1 发布索引，用于记录 PR、merge commit、tag、
11 项保护检查和 `13.99%` 已知局限事实。索引见 `docs/model/README.md`。
