# HYDRO-MODEL-02 Audit 交付索引

- 阶段：HYDRO-MODEL-02-A
- 状态：**审查完成；升级路线 GO；生产模型 NO-GO**
- 代码行为变更：无

## 权威文档

1. 当前求解器事实与整改清单：
   [`HYDRO-MODEL-02-current-solver-audit.md`](HYDRO-MODEL-02-current-solver-audit.md)
2. 目标架构与阶段路线：
   [`../model/HYDRO-MODEL-02-design.md`](../model/HYDRO-MODEL-02-design.md)
3. 数学方程与数值决策：
   [`../model/HYDRO-MODEL-02-equation.md`](../model/HYDRO-MODEL-02-equation.md)
4. 科学验证与生产门禁：
   [`../model/HYDRO-MODEL-02-validation.md`](../model/HYDRO-MODEL-02-validation.md)
5. v3→v4 迁移与回退计划：
   [`../model/HYDRO-MODEL-02-migration-report.md`](../model/HYDRO-MODEL-02-migration-report.md)

## 核心结论

- 仓库已有 v1 单河 Rusanov/Saint-Venant 原型；
- 正式 v3 仍走 v2 continuity-Manning 河网路径，不含动量和动态蓄量；
- 分区粗糙率和 `K(h)` 已生成/冻结，但未进入当前求解；
- 现有 Gate/Pump 和控制状态可以复用，但没有逐 FV stage 强耦合；
- 不删除现有求解器，不建 `model/solver2`；在现有 `model/solver/` 内建设 v4 原生有限体积路径；
- v4 先 shadow、再 opt-in，科学 Benchmark、外部结果级对比和性能门通过后才讨论默认切换。

本索引不重复维护技术事实；若有冲突，以 current-solver-audit 和对应 model 设计文档为准。
