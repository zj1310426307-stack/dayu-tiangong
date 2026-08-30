# HYDRO-MODEL-02-D3A-RC1 Friction dt Predictor

预测器从当前 accepted state 计算：

```text
k = g*n^2 / (A*R^(4/3))
dt_friction = maximum_mu / (k*abs(Q))
requested_dt = min(existing_dt, 0.8*global_min(dt_friction))
```

`n=0` 或 `Q=0` 的格点不限制步长。D3A manifest 冻结 policy `accepted-state-manning-mu-v1` 和 safety factor `0.8`。原有两个 SSP stage 的 `mu<=0.1` 验证保持不变；预测失准仍通过 `FrictionStabilityError` 重试，不能以预测器替代 stage gate。

## 前后对比

| 指标 | RC1 前 20-section FINAL | RC1 后同场景 |
| --- | ---: | ---: |
| accepted steps | 666 | 488 |
| friction retries | 586 | 2 |
| retry/accepted | 0.8799 | 0.00410 |
| maximum friction number | 0.09749 | 0.09865 |

FINAL 收敛矩阵四层的 friction retry 均为 0，低于 `<0.25` 目标。诊断新增 `friction_predictor_reduction_count` 和 `predicted_minimum_friction_dt`。专用 ON/OFF 科学测试确认质量指标在冻结误差内一致；D1 未启用预测器。
