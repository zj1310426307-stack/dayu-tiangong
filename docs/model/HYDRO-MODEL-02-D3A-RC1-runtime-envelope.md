# HYDRO-MODEL-02-D3A-RC1 Runtime Envelope

## 权威策略

D3A-1/2/3 共同绑定 `fully-wet-forward-fr08-v1`：

| 字段 | 冻结值 |
| --- | ---: |
| schema | `dayu.runtime-envelope.v1` |
| minimum water depth | `0.001 m`，与当前 D3A `dry_depth` 一致 |
| reverse-flow tolerance | `1e-12 m3/s` |
| maximum Froude | `0.8` |
| require fully wet / forward | `true / true` |

manifest hash：`68799777fc9a70f11a8ac27e65a39203f9ba364401c76b4748bf8b590dde9649`。

每格按 `c=sqrt(gA/T)`、`Fr=abs(Q/A)/c` 计算；A、T、depth、Q、Fr 必须有限。容差只吸收舍入量，不把真实负 Q 改成零。

## 检查点与失败语义

检查覆盖 initial state、SSP-RK2 第一 Euler stage、第二 Euler stage、RK2 blended candidate、accepted state 和 final result。stage 违反由 `RuntimeEnvelopeStabilityError` 分类，`dt*=0.5` 重试并累加 `runtime_envelope_retry_count`；缩到 `minimum_dt` 仍失败则返回稳定的 D3A runtime-envelope failure。Backend 在持久化成功结果前再次验证 extrema、status 和 provenance。

成功结果必须保存：

- `minimum_water_depth_m`；
- `minimum_discharge_m3s`；
- `maximum_froude_number`；
- `runtime_envelope_retry_count`；
- `runtime_envelope_status=pass`。

Registry hash 为 `0920e124fa07c764d5086d3d4e2d6723d4f5abfed857a4bb37309eae553029a4`。D1 capability 没有 `runtime_envelope_id`，因此不受新增 stage gate 影响。
