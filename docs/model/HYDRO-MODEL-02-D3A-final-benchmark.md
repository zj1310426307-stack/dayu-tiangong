# HYDRO-MODEL-02-D3A FINAL 综合基准

## 冻结工况

- 时长：6 h；20 个 tabulated Sections；单 Branch；
- 几何：12% 平滑渐缩—渐扩，断面均不相同，显式微坡河床；
- 摩阻：有效 Manning `n > 0`；
- 结构：1 个 completed-interface Gate，1 个 external Q-H/Q-η Pump；
- 流态：全湿、正向、严格亚临界；
- 路径：authoritative native-v4 → `v4-to-d3a-3-v1` → 既有有限体积求解器。

测试入口为 `tests/model_engine/test_v4_d3a_3_execution.py`，冻结示例为 `examples/hydraulic/gate-pump-engineering-profiles/case.py`。

## 综合结果

| 证据 | 实测值 | 判定 |
| --- | ---: | --- |
| 接受步数 | 666 | 完成 21,600 s |
| 总 retry / 摩阻 retry | 586 / 586 | 受控缩步，无丢弃 trial 证据泄漏 |
| 最小接受步长 | 3.75 s | 有限且为正 |
| 最大 CFL | 0.689672676 | 稳定门内 |
| 最大摩阻数 | 0.0974940005 | `<= 0.1` |
| 水量残差 | `-2.94449e-11 m³` | PASS |
| 相对水量误差 | `1.60389e-15` | `<= 1e-10` |
| Gate 转移体积 | `3882.87916 m³` | 正值 |
| Gate 最大能量残差 | `9.61186e-11 m` | `<= 1e-10 m` |
| Pump 外排体积 | `54.4935866 m³` | 正值 |
| Pump 最大扬程闭合残差 | `9.45835e-11 m` | `<= 1e-10 m` |
| Pump 输入能量 | `0.324649864 kWh` | 正值 |

## 事件与断面耦合

- Gate 在 `2966.25 s` 由保守括区重放定位为 open；定位容差 5 s，4 次细化。
- Pump 在 `4020 s` 触发 start；结果采样从 `4500 s` 起显示 on。
- Gate 每次 stage evaluation 分别保存上下游实际 A、T、I1，已观测到三者左右侧均不同。
- Pump 源水位在运行期间变化，Q-H 工作点、效率、功率、累计能量和外排体积均来自 accepted-state evidence。

## 性能说明

一次本地直接执行观测为约 `28.7 s`。该值仅用于确认 6 h synthetic benchmark 可在开发环境完成，不是吞吐量承诺或生产 SLA。

## 结论

综合案例证明已解锁范围内的质量、事件、能量、水量、重试和结构几何证据闭合。它不证明真实工程率定、生产预报或一般河网能力。
