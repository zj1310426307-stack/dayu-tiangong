# HYDRO-MODEL-02-C 验证报告

- 日期：2026-08-23
- 范围：C1 moving-energy + C2a bracketed crossing + C2b 固定 Gate completed-interface + C2c 组合门 + C3a 基础门
- 结论：限定子集 `PASS`；完整科学/生产 `NO-GO`

## 1. 可复现命令

```powershell
backend\.venv\Scripts\python.exe -m pytest -c backend\pyproject.toml -p no:cacheprovider tests\model02 -q
backend\.venv\Scripts\python.exe -m pytest -c backend\pyproject.toml -p no:cacheprovider tests --ignore=tests\model02 -q
cd backend
.\.venv\Scripts\python.exe -m pytest -c pyproject.toml -p no:cacheprovider -ra
```

## 2. 结果

- C3a 定向：`10 passed`。
- MODEL-02 定向：`277 passed`。
- 全仓聚合：`585 passed, 71 skipped, 0 failed`。
- 71 条 skip 均为 PostGIS/GDAL/QGIS 等显式外部环境门，未计入通过数。
- `py_compile` 通过；`git diff --check` 无 whitespace error，仅 Windows LF/CRLF 提示。

## 3. C1 科学证据

25/50/100 网格、`dt=0.1s`、`T=5s`：

| 指标 | N=25 | N=50 | N=100 |
|---|---:|---:|---:|
| H 加权 L1 相对误差 | `1.7180e-5` | `8.6457e-6` | `4.3352e-6` |
| Q 加权 L1 相对误差 | `2.5828e-5` | `1.3050e-5` | `6.5333e-6` |

- H 观测阶：`0.9907 / 0.9959`。
- Q 观测阶：`0.9849 / 0.9981`。
- N=100 能头 L∞：`2.1061e-5 m`；水量相对误差 `7.42e-17`；0 retry。
- v4 端到端 H/Q L1：`6.2584e-6 / 1.1948e-5`；能头 L∞ `2.6877e-5 m`。

这些数字只对冻结 reference family 有效，不是任意非棱柱水流误差保证。

## 4. C2a 事件证据

v4-lite-4 冻结案例的 Gate/Pump 同时监测 Section 1：

- 阈值：`10.00001 m`；定位容差：`0.01 s`。
- 右括端事件时刻：`0.0078125 s`。
- `H_pre=10.0 m <= threshold < H_post=10.000022865853659 m`。
- 细分次数：`5`；Gate 与 Pump 同时原子触发。
- 输出轴仍为 `0/0.5/1.0 s`；事件可位于输出点之间。
- Gate opening：`0/1/1 m`；Pump status：`off/on/on`；触发步本身仍用旧命令。
- Pump 外排体积：`1.48828125 m³`，只从触发后子区间计入。
- 水量残差：`3.2241e-13 m³`；相对误差 `9.6723e-17`。
- 最大 CFL：`0.0037142`；接受步 `5`；数值 retry `0`。

反例覆盖：初始等于/高于阈值、永不 crossing、细分次数耗尽、失败试算污染、伪造/缺字段 bracket、错误监测 Section、旧版结果混入新证据。

## 5. C2b Gate completed-interface 证据

冻结案例：单 Gate、`opening=0.5m`、`width=2m`、`Cd=0.62`、平床同断面、零摩阻、特征边界、初始上/下游水位 `11.0/10.5m`，模拟 `2s`、`dt<=0.1s`。

- 接受步 `20`，RK stage 证据 `40` 条，数值 retry `0`。
- Gate 流量范围：`1.9333502231–1.9373770281 m³/s`。
- 内部转输体积：`3.8707148013 m³`，独立按 `0.5*dt*(Q1+Q2)` 复算一致。
- 最大绝对能头残差：`5.8207549891e-11 m`，小于冻结 `1e-10m` 容差。
- 最大根迭代次数：`32`，小于冻结上限 `80`。
- 单位密度结构反力范围（下游减上游）：`-50.19355–-50.00813 m⁴/s²`。
- 水量相对误差：`1.97994e-17`；最大 CFL `0.00125284`；最小接受步约 `0.1s`。
- `gate_completed_interface_submerged_orifice_energy_momentum_v1` 存在，旧 `structure_momentum_closure_mass_only_mvp` 不存在。

反例覆盖：未淹没、倒流、无正根、超临界、迭代不收敛、Pump/摩阻混入、非固定控制、缺 sill、缺策略字段、伪造反力或缺失耦合证据。旧 Gate 公式、旧诊断、v1–v4 冻结哈希与结果形状继续通过。

## 6. C2c 组合证据

冻结案例为单 Gate、关闭初态、`target_opening=0.5m`、`width=4m`、`sill=9m`、零摩阻、平床同断面、特征边界，阈值由监测 Section 水位上升跨越：

- 事件右括端：`0.0078125s`；接受步 `5`，RK stage 证据 `10` 条，数值 retry `0`。
- 事件步的两个 RK stage 均为 `actual_opening=0`、`Q_gate=0`；目标开度没有前向回填。
- 下一接受子区间才以 `actual_opening=0.5m` 进入总能头孔流求解。
- Gate 内部转输体积：`0.18963193173761772m³`，由实际 stage 流量独立积分复算一致。
- 最大绝对能头残差：`8.926485462260048e-11m < 1e-10m`；最大迭代次数 `24`。
- 水量状态 `pass`；最大 CFL `0.0022352348424436405`；最小接受步 `0.0078125s`。
- `gate_completed_interface_bracketed_control_v1` 与强 Gate 诊断存在；旧 mass-only 诊断不存在。

双层反例覆盖：API/core 作用域不一致、Gate 两侧初始水位不等、初始非零 Q、动态上游 Q、缺事件、事件步提前开 Gate、下一子区间未启用、关闭 Gate 非零流、开/关 evidence 伪造、转输体积或哈希不一致。

## 7. C3a 基础门证据

- 1-in/2-out 的三 Branch DAG 可确定性生成 incidence 和 `B0/B1/B2` 拓扑顺序；有向环、断开分量、重复 Branch/cell 身份关闭失败。
- 状态映射必须精确覆盖全部 Branch、cell 数量匹配且处于同一接受时刻；缺失或陈旧状态关闭失败。
- Junction 以 `10=6+4m³/s` 和共同 `10m` 水位通过质量/水位预闭合；证据仍固定 `strong_coupling_ready=false`。流量残差、水位偏差、错误端点方向和伪造 pass 标志均被检测。
- 两个 Manning zone 将三个 cell 解析为 `0.02/0.04/0.04`；现有半隐式摩阻对高 n cell 产生更强阻尼。分区缺口和切穿 cell 的边界关闭失败。
- Gate 只能绑定同一 Branch 的有序相邻 cell；内部 Pump 必须同时解析 source 与 target cell，外排 Pump 禁止携带网络目标。
- Gate/Pump 强闭合 DTO 分别通过质量、能头/扬程与损失、左右动量和反力自洽案例；任一残差或 Gate 伪造正扬程都会拒绝。
- `git diff --check` 无 whitespace error；当前环境未安装 Ruff，未把未运行的 Ruff 写成通过。

## 8. 尚未通过

- 步内未在端点形成符号变化的双 crossing检测；
- 连续调节、多次 crossing、步内双 crossing 与多 Gate 同步强耦合；
- Gate 自由出流、倒流、多个 Gate、非棱柱/湿干结构界面；
- Pump Q-H/Q-η 工作点、能耗与内部转输；
- Branch 同步 SSP-RK2、Junction 动量/特征相容、网络边界分配与河网结果；
- 分区糙率公开 v4 输入、分区 conveyance、滩槽复合断面与率定；
- 湿干/溃坝、端点 Profile face；
- v4 HTTP/Worker/持久化、外部模型对比和真实工程率定。
