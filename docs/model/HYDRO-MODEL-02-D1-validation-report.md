# HYDRO-MODEL-02-D1 验证报告

- 日期：2026-08-26
- 结论：D1 限定能力 `PASS`；生产/一般网络 `NO-GO`

## 1. 实际命令与结果

| 验证 | 结果 |
|---|---|
| `python -m compileall -q model backend/app` | PASS |
| `pytest ... tests/model02` | `350 passed` |
| `pytest ... tests -ra` | `516 passed, 1 skipped` |
| backend 聚合 `pytest -ra` | `675 passed, 71 skipped` |
| D1 short + long post-gate targeted | `20 passed` |
| `npm run typecheck` | PASS |
| `npm run build` | PASS，3927 modules；仅既有大 chunk 警告 |
| `git diff --check` | PASS（Windows LF/CRLF 提示不属于 whitespace error） |
| 首次 GitHub hosted Actions | Run `33097599382`：FAIL，暴露 2 个跨平台测试/身份合同问题；frontend PASS |

唯一根测试 skip 是本机没有 `qgis_process`。后端 71 项 skip 来自未启动的
PostGIS/TimescaleDB、未安装 GDAL/QGIS 或显式外部服务门，未计为模型科学通过。

本阶段没有修改 FastAPI/OpenAPI，因此按方案执行 typecheck/build，没有运行
`openapi:update`。

## 1.1 RC1 跨平台收口（2026-08-28）

RC1 测试候选 `e85c95c` 本地结果：MODEL-02 `355 passed`；根目录 `521 passed,
1 skipped`；backend 聚合 `680 passed, 71 skipped`；Node 24 typecheck/build PASS；
D1 benchmark 未漂移。GitHub run `33102252587` 的 Ubuntu/Windows MODEL-02、legacy 和
frontend 全部通过，三个测试 artifacts 均已核对，因此 RC1 判定 PASS。

RC1 保留首次 hosted CI 失败记录，并将动态 v4-lite-3 fixture 迁移为 checked-in JSON；
公共 MVP 机器误差断言改为版本化科学容差，没有改变 D1 `<=1e-10` 水量门或 Pump/Gate
残差门。详细见 `HYDRO-MODEL-02-D1-RC1-release-report.md`。

## 2. D1 专项门

- P1：Q-H/Q-η 分段线性、端点、域外失败；
- P2：可独立求根的静态工作点、扬程、效率和功率；
- P3：source stage 改变后 Q 改变，证明不是固定 `design_flow`；
- P4：start/hold/stop、阈值等号、min run、min stop、maximum starts；
- P5：只用 accepted RK1/RK2 stage 独立积分 kWh；
- GP1：20 断面、6 小时 Gate/Pump 联合闭环；
- GP2：无根、根迭代耗尽、event refinement 耗尽、positivity retry 耗尽、
  water balance fail、曲线/效率/机组/放置/尾水/干源错误全部失败。

## 3. 强耦合证据

- 每个接受步恰有 Pump RK1/RK2 两条 evidence；
- Stage 2 的 source stage 与 Pump Q 不复用 Stage 1；
- Gate 和 Pump action 只影响下一接受子区间；
- 失败 trial 生成过正能耗证据，但最终结果只含 accepted stage，start 事件没有重复；
- Pump stage head、power、volume、energy 可由结果独立复算；
- Gate 内部转输不进入 external water balance，Pump external volume 明确扣除；
- v7 section `volume_m3` 全部有限且正，solver 全程拒绝负面积/NaN/Inf。

## 4. 兼容回归

完整 MODEL-02 与仓库聚合回归覆盖：v1/v2/v3、现有 v4-lite policies、C1、C2、
C3b、C3c、legacy OnOffPump、legacy Gate、Gate/Pump simulation 与 dispatch。
没有修改旧冻结期望来迁就 D1 算法。

## 5. 判定

D1 完成定义中的 Q-H、Q-η、逐 stage 重求、无根失败、功率、能耗、滞回、最小运行/停机、
completed-interface Gate、联合案例、无前向回填、水量、有限性、非负面积、retry 纯净、
专项 benchmark、legacy 回归和 NO-GO 文档均已满足。
