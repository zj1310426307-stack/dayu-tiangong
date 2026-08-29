# HYDRO-MODEL-02-D3A-RC1 Validation Report

- 日期：2026-08-30
- 本地实现：PASS
- Hosted RC1：PASS（implementation head `8da24aa12f05f9e13731c85b69ed864961c748dd`）
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

## Hosted 证据

| 事件 | model02 | hydraulic-platform |
| --- | --- | --- |
| push | [33266346178](https://github.com/zj1310426307-stack/dayu-tiangong/actions/runs/33266346178) SUCCESS | [33266346170](https://github.com/zj1310426307-stack/dayu-tiangong/actions/runs/33266346170) SUCCESS |
| PR | [33266347597](https://github.com/zj1310426307-stack/dayu-tiangong/actions/runs/33266347597) SUCCESS | [33266347599](https://github.com/zj1310426307-stack/dayu-tiangong/actions/runs/33266347599) SUCCESS |

Push `d3a-shipping-science` artifact 在 CPython `3.12.14` 发布镜像中运行 `47/47` tests，0 failures / 0 errors / 0 skipped；`ENGINE_COMMIT` 精确为上述 implementation head。artifact 中 Registry、RuntimeEnvelope、solver/validation policy 身份均与冻结值一致，包络 summary 为 `pass`，最坏 minimum Q `-1.7729e-15 m3/s`、minimum depth `0.789836 m`、maximum Fr `0.054113`。

`D3A shipping science` 已在首次 hosted SUCCESS 并确认实际 context 后追加到 main required checks；原 10 项完整保留，当前共 11 项，strict 仍为 true。

机器门已闭合，可进入独立审查；本文仍不是 merge 授权，PR #12 保持 OPEN / NOT MERGED，D3A tag 未创建。
