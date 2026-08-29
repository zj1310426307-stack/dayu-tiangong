# HYDRO-MODEL-02-D3A-RC1 Validation Report

- 日期：2026-08-30
- 本地实现：PASS
- Hosted RC1：PENDING
- PR #12：OPEN / NOT MERGED

## 本地证据

| 门 | 结果 |
| --- | --- |
| runtime-envelope model/backend 专用测试 | PASS（23 cases） |
| 原 D3A-1/2/3 science/native-v4 回归 | PASS |
| FINAL 60/70/80 + fine CFL/2 | PASS，4 个 runtime envelope status 均为 pass |
| MODEL02 + model_engine（排除已独立实跑的长 FINAL） | PASS，0 failures |
| 全量 `tests`（Python 3.12.13） | PASS，698 passed / 37 skipped / 0 failed，497.54 s |
| OpenAPI generated-client drift | 已重新生成 |
| frontend typecheck / production build | PASS |

FINAL 最坏科学 extrema：minimum depth `0.789836 m`、minimum Q `-1.773e-15 m3/s`、maximum Fr `0.054113`、maximum friction number `0.093873`；所有水量相对误差小于 `4e-16`，Gate/Pump 最大残差小于 `1e-10 m`。

## 身份

| identity | SHA-256 |
| --- | --- |
| Registry | `0920e124fa07c764d5086d3d4e2d6723d4f5abfed857a4bb37309eae553029a4` |
| Runtime envelope | `68799777fc9a70f11a8ac27e65a39203f9ba364401c76b4748bf8b590dde9649` |
| D3A-1 solver policy | `19e5fee2043c7891f4e2721f5c0a3fa2d402ea93e899b5b1d31955bb87329af2` |
| D3A-2 solver policy | `29b73142038cf17245c0d726d16a830d969a2b80a6e3a65c5ce544a3c4d588fc` |
| D3A-3 solver policy | `499483625d055e8f4589a24a07d3acc5f227353d00c8a286f7f66d97ec1c0c55` |

## 尚未满足

- 新提交尚未推送并完成 hosted `D3A scientific validation` / `D3A shipping science`；
- `model02`、`hydraulic-platform` 和 D2 shipping/fault/platform checks 尚需在新 head 复验；
- main required checks 尚未加入经成功运行确认的 `D3A shipping science` context。

因此本文不是 merge 授权。Hosted 全绿前 release readiness 保持 NO-GO。
