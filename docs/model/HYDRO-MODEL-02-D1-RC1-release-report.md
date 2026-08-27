# HYDRO-MODEL-02-D1-RC1 发布报告

- 日期：2026-08-28
- `main` 基线：`c00a05fa508f3f186e87f05dd26b67ea88cfc0fc`
- D1 RC1 基线：`9002f10b584ac8c95439e9e161027897f7e3d803`
- RC1 候选 SHA：`6175ab2`
- 分支：`feature/HYDRO-MODEL-02-D1-pump-strong-coupling`
- 发布状态：`PENDING HOSTED CI`
- 合并状态：`NOT MERGED`

## 1. 提交链

1. `bd48bf3` audit(hydraulic): freeze D1 pump coupling baseline
2. `5a65c5b` feat(hydraulic): solve Pump Q-H operating points
3. `b9c04a5` feat(hydraulic): add accepted-state Pump control
4. `84c7ecb` feat(hydraulic): integrate Gate Pump strong coupling
5. `0c05bf3` test(hydraulic): freeze D1 Gate Pump benchmark
6. `dfc25e6` fix(hydraulic): enforce strict D1 balance gate
7. `9002f10` docs(hydraulic): publish D1 evidence and limits
8. `6175ab2` fix(hydraulic): stabilize D1 cross-platform RC1

## 2. GitHub Actions 历史

首次运行：[`33097599382`](https://github.com/zj1310426307-stack/dayu-tiangong/actions/runs/33097599382)，结论 `failure`。

- Ubuntu MODEL-02：FAIL，机器误差精确冻结与动态 fixture hash 两项；
- Windows MODEL-02：首次工作流尚无 Windows job；
- legacy：前序失败后被跳过；
- frontend：PASS。

RC1 hosted CI run id、Ubuntu、Windows、legacy 和 frontend 结果将在候选推送并真实运行后补录。未全绿前不创建 PR。

## 3. 身份迁移

- canonicalization id：`dayu-canonical-json-v1`；
- 旧 Windows 动态 hash：`96eb4e4d...bec1`；
- 旧 Linux 动态 hash：`313964ba...53ba`；
- 新 authoritative fixture hash：`96eb4e4d...bec1`；
- 新 runtime projection policy：`dayu.v4-lite.runtime-projection.v1`；
- mesh policy：保持 `dayu.finite-volume-mesh.v1/v2`；
- validation policy：`dayu.v4-lite.validation-policy.v1`；
- solver policy：保持 `dayu.solver-policy.v1-v5`。

哈希值选择不是把 Linux 值改回 Windows expected，而是把原本意图冻结的受控输入落为仓库 JSON，并对 parse 后 canonical bytes 计算权威身份。

## 4. 水量测试变化

公共 MVP 示例不再精确比较约 `1e-16` 的浮点残差，而是断言：

```text
finite(relative_error)
result tolerance == frozen tolerance
relative_error <= frozen tolerance
status == pass
```

该变化只修复测试合同。D1 的严格 `1e-10` 水量门、Pump/Gate 残差门和 benchmark 均未降低。

## 5. 本地验证

| 验证 | 结果 |
|---|---|
| compileall | PASS |
| MODEL-02 | 355 passed |
| 根目录 tests | 521 passed, 1 skipped |
| backend 聚合 | 680 passed, 71 skipped |
| Node 24 `npm ci/typecheck/build` | PASS |
| D1 6 h benchmark | PASS，事件 2940/7740/12540 s，381 步 |
| `git diff --check` | PASS |

## 6. Benchmark 与兼容性

D1 benchmark 保持：相对水量误差 `4.748482309112566e-16`、Pump 外排 `22.023440130973746 m³`、输入能量 `0.12252120603722051 kWh`。v1/v2/v3、v4-lite-1～7、legacy OnOffPump/Gate、C1/C2/C3b/C3c 由回归覆盖，未修改 D1 物理方程或工况。

## 7. NO-GO 与下一阶段

一般河网、湿干、倒流、internal Pump、真实泵站率定、HEC-RAS/MIKE11 等价和生产水利决策仍为 `NO-GO`。只有 RC1 hosted CI 全绿并完成审查后，D2 才可进入 v4 原生任务链和 Gate/Pump 平台接入。
