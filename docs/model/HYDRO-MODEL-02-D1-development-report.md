# HYDRO-MODEL-02-D1 开发报告

- 日期：2026-08-26
- 基线：`c00a05fa508f3f186e87f05dd26b67ea88cfc0fc`
- 分支：`feature/HYDRO-MODEL-02-D1-pump-strong-coupling`
- 结论：限定能力完成；生产与一般网络仍为 `NO-GO`

## 1. 完成内容

新增 `v4-lite-7` 显式能力，不改变旧版默认行为：

- 纯 Python Q-H/Q-η、同型并联、系统损失和确定性二分工作点；
- accepted-state Pump 滞回、最小运行/停机时间和最大启动次数；
- 每个 SSP-RK2 stage 重新读取 source/outlet stage 并重新求工作点；
- external mass sink 与 local advective momentum sink 共用同一 stage Q；
- completed-interface Gate 与 hydraulic Pump 在同一 Branch 联算；
- accepted-stage 水量、功率、能量和控制事件证据；
- v7 结果增加 section control-volume、Pump 水力序列和强耦合证据；
- 20 断面、6 小时 Gate open → Pump start → Pump stop 冻结示例；
- MODEL-02 GitHub Actions 最小工作流。

## 2. 主要代码边界

| 层 | 文件 | 职责 |
|---|---|---|
| 能力注册 | `model/solver/finite_volume/capabilities.py` | v7 policy manifest 与限定作用域 |
| 数学层 | `pump_curve.py` | 曲线、并联、系统扬程、工作点、功率证据 |
| 控制/设备 | `pump.py` | accepted-state 滞回与逐 stage Pump 求解 |
| FV 推进 | `integrator.py` | 每 stage Gate/Pump 求解、质量/动量源项、能量积分 |
| 编排 | `solver.py` | 原子控制提交、事件重放、接受步累计和限定 preflight |
| 输入 | `model/api/v4_lite.py` | v7 严格合同与显式 policy 门 |
| 结果 | `model/result/mvp.py` | 可独立复算的 Pump/Gate/水量/能量证据 |
| 适配 | `model/adapters/v4_lite.py` | 输入到纯 runtime、runtime 到结果 DTO |

FastAPI 路由和 OpenAPI 没有变化，因此未生成前端 API 客户端。

## 3. 作用域收敛

v7 preflight 固定为：单 Branch、20～50 断面可用、全湿、正向严格亚临界、平床同断面、
零 Manning 系数、1 个 completed-interface Gate、1 个不与 Gate face 重叠的 external
hydraulic Pump。上游过程线必须全程正流；下游水位过程必须保持湿润且不高于末断面初始水位。
水量容差必须 `<=1e-10`。

Gate 继续使用已验证的关闭/一次开启/淹没孔流子集，没有重写为一般闸门。

## 4. 兼容策略

- v1～v6 不接受 D1 Pump policy 字段；
- legacy `OnOffPump` 仍使用 `design_flow`，不会自动升级；
- 旧 Gate 不会自动进入 completed-interface；
- pre-v7 结果序列不增加 `volume_m3` 或 Pump coupling 字段，序列化字节形状保持；
- solver policy hash 仅为 v7 升级到 `dayu.solver-policy.v5`；
- 所有无根、超域、干源、冲突、retry/event/balance 耗尽均失败关闭。

## 5. 实现中修正的既有缺陷

平缓越过 Gate 阈值时，旧事件细化计数会跨已接受步累积。D1 长算例暴露该问题后，计数改为
每个候选接受步局部所有；最终事件 evidence 仍记录本次右括端重放的真实细分次数。v6 冻结事件
时刻、哈希和结果回归保持通过。

长时结果还将固定 `1e-12` 时钟比较改为基于 float ULP 的绝对容差，避免 6 小时时标下把
相同 SSP 边界误判为不连续；水力残差容差未放宽。

## 6. 逻辑提交

1. `bd48bf3` audit(hydraulic): freeze D1 pump coupling baseline
2. `5a65c5b` feat(hydraulic): solve Pump Q-H operating points
3. `b9c04a5` feat(hydraulic): add accepted-state Pump control
4. `84c7ecb` feat(hydraulic): integrate Gate Pump strong coupling
5. `0c05bf3` test(hydraulic): freeze D1 Gate Pump benchmark
6. `dfc25e6` fix(hydraulic): enforce strict D1 balance gate

原 D1 阶段未合并 `main`。分支后续已上传并由 RC1 完成 Windows/Linux CI 收口；
`main` 仍未合并，详见 `HYDRO-MODEL-02-D1-RC1-release-report.md`。
