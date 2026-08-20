# HYDRO-MODEL-02-C 验证报告

- 日期：2026-08-20
- 范围：C1 受限 moving-energy 科学门 + C2a 保守 bracketed crossing 软件门
- 结论：限定子集 `PASS`；完整科学/生产 `NO-GO`

## 1. 可复现命令

```powershell
backend\.venv\Scripts\python.exe -m pytest -c backend\pyproject.toml -p no:cacheprovider tests\model02 -q
backend\.venv\Scripts\python.exe -m pytest -c backend\pyproject.toml -p no:cacheprovider tests --ignore=tests\model02 -q
cd backend
.\.venv\Scripts\python.exe -m pytest -c pyproject.toml -p no:cacheprovider -ra
```

## 2. 结果

- MODEL-02 定向：`223 passed`。
- 全仓聚合：`531 passed, 71 skipped, 0 failed`。
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

## 5. 尚未通过

- 步内未在端点形成符号变化的双 crossing检测；
- Gate 左右动量/能头完成界面；
- Pump Q-H/Q-η 工作点与内部转输；
- 湿干/溃坝、端点 Profile face、河网节点；
- v4 HTTP/Worker/持久化、外部模型对比和真实工程率定。
