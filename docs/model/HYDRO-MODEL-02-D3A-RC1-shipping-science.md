# HYDRO-MODEL-02-D3A-RC1 Shipping Science

> **FIX1 更新：** 下列 `8da24aa` Hosted runs 仅为 pre-FIX1 历史基线。当前工作流
> 已切换到 `final-convergence-fix1.json` 和 v2 collector；新的 Hosted 证据必须在
> FIX1 head 推送后重新产生，不能复用旧 run。

FIX1 evidence head `d0aa74860471acfeb92a6cccaae5385059702cd9` 已重新产生 Hosted
证据：model02 push `33272555233`、PR `33272557735` 均 SUCCESS。push/PR shipping
jobs 均为 49/49 tests；push artifact id `9721109268` 精确记录 evidence head，PR
artifact id `9721041489` 记录 GitHub merge ref。两者 v2 completion gates 全部为 true。

新增 hosted check 的精确名称为 `D3A shipping science`。它使用 `docker/backend.Dockerfile` 构建真实 Python 3.12 发布镜像，并注入 `ENGINE_COMMIT=${{ github.sha }}`、`DAYU_BUILD_MODE=ci`；不使用 setup-python 伪装发布运行时。

Job 运行 D3A Manning、Slope、non-prismatic、runtime envelope、FINAL convergence 和 native-v4 Backend 测试。artifact `d3a-shipping-science` 包含：

- JUnit 与 summary；
- `final-convergence-fix1.json`（`dayu.d3a-final-convergence.v2`）；
- `runtime-envelope-summary.json`；
- `runtime-build-identity.json` 与 `python-version.json`；
- `solver-registry-identity.json`（Registry、solver policy、validation policy 和 envelope hash）。

原 `D3A scientific validation` 继续使用 Ubuntu Python 3.11；MODEL02 继续覆盖 Ubuntu/Windows Python 3.11；D2 shipping runtime 继续独立负责平台 E2E。FIX1 后两项 D3A science job 显式运行 `test_d3a_final_convergence_fix1.py`；旧 `test_d3a_final_convergence.py` 只保留为 pre-FIX1 历史 smoke。长 FINAL test 继续使用 `d3a_shipping_science` marker，从普通 MODEL02/D1 smoke 排除。

FIX1 collector 只接受 `dayu.d3a-final-convergence.v2`、四层、`status=pass` 且全部
`completion_gates=true` 的 artifact。旧 v1 artifact 即使文件存在，也不能使发布镜像
科学门通过。

Hosted push run [33266346178](https://github.com/zj1310426307-stack/dayu-tiangong/actions/runs/33266346178) 与 PR run [33266347597](https://github.com/zj1310426307-stack/dayu-tiangong/actions/runs/33266347597) 均为 SUCCESS。Push artifact 证明发布镜像为 CPython `3.12.14`、`ENGINE_COMMIT=8da24aa12f05f9e13731c85b69ed864961c748dd`、47 tests / 0 failures / 0 errors / 0 skipped；运行包络、Registry 和 policy identities 均通过核对。

首次成功后已将精确 context `D3A shipping science` 追加到 main required checks；原 10 项未删除，当前 11 项，strict 为 true，禁止强推/删除等既有保护未变。
