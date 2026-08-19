# HYDRO-MODEL-02-B Benchmark 报告

日期：2026-08-20
测试文件：`tests/model02/test_mvp_benchmarks.py`

## 1. 分级原则

5 个场景不共用“科学验证通过”标签：

- Case 001 是已冻结限定子集的严格静水门。
- Case 002 有一个通过的 MVP 有界性回归，以及一个必须保留的严格科学候选 `xfail`。
- Case 003–005 只是传播因果、结构物质量通量和动态记账行为回归。

测试结果：`5 passed, 1 xfailed`。

## 2. 通用质量门

每个场景都检查：

- 状态、流速、dt 和 CFL 全有限；
- A≥0、depth≥0，干 cell 不携带 Q；
- 接受步时间严格递增并精确到达 end time；
- `maximum_cfl` 不超过配置；
- SSP-RK2 每接受步两个 stage；
- 用初末库容和边界/泵体积独立重算水量账。

## 3. 场景结果

| Case | 等级 | 结果 | 关键证据 | 不能证明 |
|---|---|---|---|---|
| 001 静水保持 | scientific subset | PASS | 同宽矩形变床；max |u| 约 1.25e-15 m/s，最大水位漂移 0，balance 约 2.75e-16 | 一般非棱柱非规则断面 |
| 002 恒定均匀流 | MVP behavior | PASS | Q=50 m³/s；内部最大 Q 相对误差约 3.71%，水深误差约 0.0448 m，未失稳 | Manning 正常水深工程精度 |
| 002 科学候选 | candidate gate | XFAIL | 预登记 Q≤0.1%、depth≤0.01 m 且≤0.1%；当前未达 | 不得用 5% 行为线替代严格门 |
| 003 洪峰传播 | MVP behavior | PASS | 近/远 cell 首次响应约 420/600 s，峰时约 690/840 s，折点 300/600/900 s 精确对齐 | 解析波幅、峰时精度或收敛阶 |
| 004 Gate | MVP behavior | PASS | 首 stage Q 约 1.941897 m³/s，开闸累计内部转输约 141.088 m³，关闸为 0 | 阈值自动开闸、动量/能头强耦合 |
| 005 Pump | MVP behavior | PASS | ON/OFF 外排 150/0 m³，ON 工况泵 cell 水位低于 OFF | Q-H/Q-η 工作点、能耗、阈值启停 |

五个动态场景的归一化水量误差都在约 `1e-16` 量级，但这只证明当前离散质量账闭合，不代表动量、波速或结构物能量闭合已验收。

## 4. 非规则断面附加门

`tests/model02/test_finite_volume_core.py` 另有一个平床、完全相同梯形 Profile 的 lake-at-rest 测试，证明 v4-lite 所允许的“非矩形但棱柱”子集可保持静水。

已知反例显示，变宽或逐断面异形河道在缺少非棱柱几何源项时可产生伪流。因此公开 v4-lite 合同已拒绝该类输入，不把水量平衡误当为静水科学通过。

## 5. 总判定

- 5 个任务书场景的 MVP 行为回归：`PASS`。
- Case 002 科学候选精度：`XFAIL / NO-GO`。
- 湿干溃坝、非棱柱源项、网格收敛、闸泵强耦合、HEC-RAS/MIKE11 和真实率定：`NOT RUN / NO-GO`。
