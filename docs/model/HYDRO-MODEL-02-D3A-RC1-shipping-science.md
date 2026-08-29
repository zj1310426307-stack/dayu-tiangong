# HYDRO-MODEL-02-D3A-RC1 Shipping Science

新增 hosted check 的精确名称为 `D3A shipping science`。它使用 `docker/backend.Dockerfile` 构建真实 Python 3.12 发布镜像，并注入 `ENGINE_COMMIT=${{ github.sha }}`、`DAYU_BUILD_MODE=ci`；不使用 setup-python 伪装发布运行时。

Job 运行 D3A Manning、Slope、non-prismatic、runtime envelope、FINAL convergence 和 native-v4 Backend 测试。artifact `d3a-shipping-science` 包含：

- JUnit 与 summary；
- `final-convergence.json`；
- `runtime-envelope-summary.json`；
- `runtime-build-identity.json` 与 `python-version.json`；
- `solver-registry-identity.json`（Registry、solver policy、validation policy 和 envelope hash）。

原 `D3A scientific validation` 继续使用 Ubuntu Python 3.11；MODEL02 继续覆盖 Ubuntu/Windows Python 3.11；D2 shipping runtime 继续独立负责平台 E2E。长 FINAL test 使用 `d3a_shipping_science` marker，从普通 MODEL02/D1 smoke 排除，但在两项 D3A science job 中显式执行。

Hosted push run [33266346178](https://github.com/zj1310426307-stack/dayu-tiangong/actions/runs/33266346178) 与 PR run [33266347597](https://github.com/zj1310426307-stack/dayu-tiangong/actions/runs/33266347597) 均为 SUCCESS。Push artifact 证明发布镜像为 CPython `3.12.14`、`ENGINE_COMMIT=8da24aa12f05f9e13731c85b69ed864961c748dd`、47 tests / 0 failures / 0 errors / 0 skipped；运行包络、Registry 和 policy identities 均通过核对。

首次成功后已将精确 context `D3A shipping science` 追加到 main required checks；原 10 项未删除，当前 11 项，strict 为 true，禁止强推/删除等既有保护未变。
