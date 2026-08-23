# HYDRO-MODEL-02 科学验证与生产门禁设计

- 文档状态：`VALIDATION PLAN / NOT EXECUTED`
- 当前结论：现有 64 项是 legacy/software regression，不是 64 项 Saint-Venant 科学 Benchmark

## 1. 现有证据能证明什么

本轮以运行时代码树 `4f681b4360e27f8c81042716c1b35bf11d9df364` 为基线；工作区仅有
文档改动，不包含 runtime 改动。仓库根目录实际执行：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH='.;backend'
backend\.venv\Scripts\python.exe -m pytest -c backend/pyproject.toml `
  -p no:cacheprovider `
  tests/test_hydraulic_engine.py `
  tests/test_phase4_hydraulic_gate.py `
  tests/test_phase4_network.py `
  tests/test_model_input_v3_adapter.py `
  tests/test_gate_model.py `
  tests/test_pump_model.py `
  tests/test_dispatch_engine.py `
  tests/test_gate_pump_simulation.py `
  tests/benchmarks/test_phase4_benchmarks.py -ra
# 64 passed in 0.55s
```

同一运行时代码树还在 `backend/` 目录执行了全仓测试：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest -c pyproject.toml -p no:cacheprovider -ra
# 308 passed, 71 skipped in 13.89s
```

71 项 skip 均是需要 PostGIS/Timescale/GDAL/QGIS 等外部环境的显式门，不计为通过。本轮另一
只读审校运行的 56 项是上述 64 项的重叠子集，仅作交叉复核，不与 64 或 308 相加。

可证明：

- v1 小型单河输入产生有限、对齐的 H/Q/V；
- v1 请求步长过大时 CFL 会真实缩步；
- 同宽矩形变床静水基准和断面 A↔H 基本合同；
- v2/v3 准恒定 Y 形汇/分流、边界校验和确定性；
- v3 Reach 投影和结构物权威包络合同；
- Gate/Pump 代数方程、设备约束和调度审计；
- 5 km/20 断面/24 h 合成准恒定案例的软件闭环；
- 现有 Phase 4 的 10 个回归案例。

不能证明：

- v3/v4 河网完整 Saint-Venant；
- 动态蓄量、节点动量/能量和回流；
- 网格/时间步收敛阶；
- 湿/干溃坝波和正性；
- 分区糙率对求解生效；
- Gate/Pump 与 FV 每个 stage 强耦合；
- HEC-RAS/MIKE11 精度；
- 100 km/500 断面/20 结构物性能；
- 真实工程率定或生产适用性。

现有 `tests/benchmarks/test_phase4_benchmarks.py` 保留原名和历史语义，不能简单改名为
MODEL-02 科学验证来制造通过记录。

## 2. 分阶段门禁

### A0：审查冻结

- [x] 双路径事实已确认；
- [x] 64 项 legacy regression 通过；
- [x] 当前未实现项明确为 NO-GO；
- [x] 数学、架构、验证和迁移计划形成；
- [ ] 水力负责人冻结 A1/A2 的误差阈值。

### A1：v4 合同与影子路由

- 固定 provenance 输入时，v3 canonical bytes/serializer 保持稳定；v3 业务字段与 legacy
  solver/result 语义不变；每个任务自身保存的 snapshot 与 hash 必须相符；
- task 行的 input schema、engine version/commit 必须与 snapshot schema/provenance 一致；
- canonicalization ID、SHA-256 algorithm 和 snapshot/mesh/manifest hash domain 有契约测试，
  manifest hash 不自引用；
- v3 明确使用 legacy solver；
- v4 默认禁用；
- v4 缺初态、边界、Profile/processing、结构位置或 solver 参数时 fail closed；
- v4 保存 source hash、schema、solver、commit、validation policy；
- API/OpenAPI/生成客户端合同同步。

### A2：单河 FV

- lake-at-rest；
- 非零坡/糙率恒定均匀流；
- 湿床和干床溃坝；
- 分区 `K(h)` 手算对照；
- 有限性、正性、CFL、水量；
- 三组以上网格和时间步收敛。

### A3：动态边界与 Junction

- Q/H 边界折点精确对齐；
- rating/lateral/closed 的独立合同；
- 非恒定 Y 汇流、分流和一次回流；
- 节点质量与能头残差；
- 不收敛、错误变量数、时域不覆盖的失败测试；
- `saint_venant` 模式不得触发长度倒数 fallback。

### A4：Gate/Pump 强耦合

- Gate 阶跃和斜坡开度；
- Pump 启停、Q-H/Q-η 系统工作点；
- 每个 RK stage 使用一致水位；
- 动作时刻无前向回填；
- 内部 Pump 进出等量反号；
- 体积、功率和累计能量独立复核；
- 结构迭代不收敛不得 success。

### A5：外部结果级验证

- HEC-RAS 和 MIKE11 分开报告；
- 输入、基准、断面、时间和方向显式映射；
- 指标和阈值预登记；
- 不把商业模型原生工程文件作为 Dayu 内部格式；
- 不把商业结果替代 Dayu 自身计算。

### A6：规模性能

- 只有 A0-A5 全部通过才计时；
- 所有数值门失败时，性能成绩自动无效。

### A7：shadow/cutover

- 同一冻结案例保存 v3 legacy 与 v4 原生结果及 solver ID；
- 真实率定前只 shadow；
- 默认切换需专家签字、回退演练和历史结果隔离验证。

## 3. 科学 Benchmark

以下阈值是**建议起始线，待水力负责人实现前冻结**，不是已通过指标。在本节的指标定义、
案例输入、参考解和 policy hash 全部冻结前，它们也不是可执行硬门。

### 3.1 指标定义草案

当前兼容诊断的体积残差为：

```text
R_V = (V_final - V_initial)
      - (V_external,in + V_lateral,in - V_external,out - V_lateral,out)
S_V = max(|V_initial|, |V_final - V_initial|,
          |V_external,in| + |V_external,out|, 1 m3)
epsilon_V = |R_V| / S_V
```

这精确记录现有 `evaluate_water_balance` 的尺度；其分母尚未纳入 lateral volume。v4 在实现前
必须由水力负责人决定是保持该兼容定义还是发布包含 lateral scale 的新版 policy，且不得在
同一个 policy ID 下悄然改变公式。下文 `balance` 均指冻结 policy 的无量纲 `epsilon_V`，
不是绝对立方米。

空间 L1 候选定义为：

```text
L1_rel(y) = sum_j(dx_j * |y_j - y_ref,j|)
            / max(sum_j(dx_j * |y_ref,j|), y_floor * sum_j(dx_j))
```

`y_floor`、比较时刻/窗口、空间权重和 h/Q 各自的 reference 必须预登记。节点归一化质量残差
候选定义为：

```text
r_node = |sum(Q_in) + q_node - sum(Q_out)|
         / max(sum(|Q_in|) + |q_node| + sum(|Q_out|), Q_floor)
```

其中 `q_node>0` 表示外部注入；`Q_floor` 必须随案例冻结。湿干波前由预登记的 `h_dry` 等值线
识别，并同时报告米和 cell 数。收敛阶使用固定网格比 `r=2`、相同物理时刻和同一误差范数：
`p=log(E_dx/E_dx/2)/log(2)`；时间收敛必须另固定空间网格，不能混算。

### Benchmark 0：静水保持

场景：变床、Q=0、自由水面恒定，逐步加入不同断面与局部干区。

检查：

- 最大伪流速和水位漂移；
- 全域水量；
- 网格加密后误差不恶化；
- 无未解释 clamp。

### Benchmark 1：恒定均匀流

场景：矩形与复式棱柱河道，非零床坡和 Manning n，已知正常水深。

检查：末态 H/Q、沿程坡降、质量和网格收敛。候选起始线为 Q 相对误差不超过 0.1%；
水深绝对误差和相对误差必须同时报告，是否采用 `0.01 m`、`0.1%` 或二者同时满足，留待
案例精度与水力负责人签字后冻结。稳定开边界案例的 `epsilon_V` 候选不超过 `1e-6`。

### Benchmark 2：溃坝波

先做 Stoker 湿床解析案，再做 Ritter 干床正性案。

检查：h/Q 的 `L1_rel`、激波/稀疏波/湿干前沿位置、守恒和收敛。候选起始线为 h/Q 各自
`L1_rel` 不超过 2%，以冻结 `h_dry` 识别的波前误差不超过两个 cell 且同时报告米，
`epsilon_V` 不超过 `1e-4`，绝不出现负水深或非有限值。

### Benchmark 3：闸门调节

场景：上下游池和内部 Gate，冻结阶跃/斜坡开度，独立计算孔流/堰流参考。

检查：事件时刻、`Q_gate(t)`、上下游 H、累计转输。建议起始线：流量误差不超过 0.5%，
累计体积误差不超过 0.1%。

### Benchmark 4：泵站调度

场景：两池/两节点、Q-H/Q-η 曲线、启停序列和最短启停约束。

检查：Q/H/P/E、系统工作点、内部等量转输。建议起始线：Q/P 误差不超过 0.5%，累计
能量/水量误差不超过 0.1%。

### Benchmark 5：多分支汇流

场景：非恒定 Y 网，两条错峰入流过程和一个下游 H，至少包含一次局部回流。

检查：节点质量、能头/局部损失、峰值/峰时、全域蓄量，并与高分辨率 reference 网格
对比。候选起始线为按 3.1 定义的 `r_node` 不超过 `1e-6`、全域 `epsilon_V` 不超过
`1e-3`。

## 4. 收敛与鲁棒性

每个适用案例至少运行三组网格和三组最大时间步；网格序列固定 `r=2`，空间与时间收敛
分开研究，并使用 3.1 的相同时刻、窗口、reference 与范数。报告：

- L1/L2/L∞；
- observed order；
- step count、min/mean/max dt；
- CFL maximum；
- dry/wet cell count；
- limiter/fallback/retry count；
- 节点/结构迭代次数和失败数；
- 水量残差。

建议起始线：非光滑一阶案 observed order 约不低于 0.8；启用 MUSCL 的光滑案约不低于
1.5。最终阈值由水力负责人冻结。

## 5. HEC-RAS/MIKE11 结果级对比

### 5.1 对比 manifest

每个外部案例保存：

- 软件名称、版本、运行人和运行时间；
- 输入/结果文件 hash；
- 水平/垂直基准和单位；
- Branch/Section 显式映射；
- 时间原点、时区、符号方向、输出间隔；
- 允许的重采样方法和有效配对率；
- Dayu snapshot/mesh/solver/commit hash。

原生商业文件留在受控环境。核心只消费经审核的中立 CSV/Parquet 结果，不允许
nearest-section 猜测。

### 5.2 指标

令 `e_i = Dayu_i - Ref_i`：

```text
RMSE = sqrt(mean(e_i^2))
Bias = mean(e_i)
NSE  = 1 - sum(e_i^2) / sum((Ref_i - mean(Ref))^2)
```

reference 为常值时 NSE 标记 `NA`，不能除零或伪造。H/Q/V 逐断面报告 RMSE、Bias、MAE、
MaxAE、NSE；这里 V 仅指同一映射断面的平均流速 `Q/A`，不得与商业软件的主槽速度或点
流速混比。Q 的候选归一化定义为
`NRMSE_Q=RMSE_Q/max(max(|Q_ref|), Q_floor)`，Bias 使用同一分母；当 reference 为零流或
尺度低于预登记 `Q_floor` 时，两项标记 `NA`，不能除零或借符号反转放大/缩小分母。

比较必须冻结公共时间网格、比较窗口、预热剔除、时区和原始输出间隔，禁止时域外外推；
峰时门同时规定“最多一个冻结输出步”和案例级绝对秒数上限，不能通过放粗输出间隔放宽。
另报告洪峰值误差、峰时误差、体积误差和有效配对覆盖率。

`H RMSE≤0.05 m`、`|Bias_H|≤0.02 m`、`Q NRMSE≤5%`、归一化 `|Bias_Q|≤2%`、
`H/Q NSE≥0.90` 仅是讨论用候选线。正式门必须按案例的数据精度、用途和参考模型分别预登记
并由专家签字；商业结果不是“真值”，这些数字不表示当前仓库已达到，也不表示完全兼容。

## 6. 目标规模性能合同草案

“100 km、500 断面、20 结构物、单工况 <10 min”目前是待冻结草案，以下项目全部写入
公开合成 performance snapshot/manifest 后才成为可复现合同：

- 24 h 模拟；
- 有向多分支 100 km；
- 500 物理断面，并冻结实际 FV cell/face、Branch/Reach/Junction 数和 mesh hash；
- 冻结每个 Profile/查算表行数、初始湿干比例、边界过程幅值及 snapshot hash；
- 10 Gate + 10 Pump；
- 冻结结构动作次数、每个 RK stage 的结构求值数、候选非线性迭代难度和期望结果行数；
- Q/H 边界至少每 5 min 一个折点；
- 输出间隔 300 s；
- `storage_level=full`，约 144,500 条 section rows，另有 node/structure rows；
- CPU-only，单 Celery Worker，concurrency=1；
- 固定 4 物理核 affinity、8 GiB 容器硬上限、本地 NVMe；
- Python、OS、PG16/PostGIS、Redis、精确 CPU 型号/频率/功耗模式、Docker/WSL 资源、
  DB/Redis 是否同机、commit 和 solver flags 写入 manifest。

计时从 Worker claim 开始，到结果全量 commit 且 task=success 结束；排除排队、浏览器和外部
网络，同时拆分 snapshot/mesh/solve/serialization/persistence。

冷启动定义为新 Worker/空进程缓存，热启动定义为相同镜像与已就绪服务但新 task；正式主成绩
在一次不计分预热后测量 5 个热启动 task，同时另报一次冷启动。RSS 必须分别声明采样对象
是 Worker 进程、容器还是完整 Worker+DB+Redis 栈。候选门为：

- 每次必须 <600 s；
- 建议 median≤540 s，保留 10% 余量；
- CV≤5%；
- Worker 容器 peak RSS≤6.5 GiB，8 GiB 仅为硬上限而非无余量目标；完整栈另行报告；
- 每次 snapshot hash 相同、无并发负载；
- 任何数值门禁失败，成绩作废。

同时报告 50/100/250/500 断面与 0/10/20 结构的缩放曲线。现有 20 断面 demo 和 1000
断面数据组件测试均不能外推为该目标已通过。

## 7. 自动化测试文件规划

未来新增而非本阶段伪造：

```text
tests/test_saint_venant.py
tests/test_unsteady_flow.py
tests/test_gate_coupling.py
tests/test_pump_coupling.py
tests/test_branch_network.py
tests/test_hecras_compare.py
tests/benchmarks/model02/
```

MIKE11 对比可以独立增加 `test_mike11_compare.py`，但必须有获准的中立结果夹具；缺外部数据
应为 BLOCKED/NOT RUN，而不是 skip 后计为通过。

## 8. 当前完成矩阵

| 项目 | 状态 |
|---|---|
| 当前求解器审查 | PASS |
| Saint-Venant 数学模型明确 | PROPOSED / PENDING EXPERT FREEZE |
| 数值方法确定 | BASELINE FAMILY SELECTED；HLL/干湿/时间—摩阻组合细节待冻结 |
| 非恒定 v4 运行 | NOT IMPLEMENTED |
| 动态波传播验证 | NOT RUN |
| 分区糙率求解生效 | NOT IMPLEMENTED |
| 闸泵强耦合 | NOT IMPLEMENTED |
| v4 时序边界运行 | NOT IMPLEMENTED |
| 多分支 Saint-Venant | NOT IMPLEMENTED |
| HEC-RAS/MIKE11 对比 | BLOCKED：无正式比较器/获准夹具 |
| 目标规模性能 | NOT RUN |

除“当前求解器审查”外，其余各项均按对应门禁真实通过后，HYDRO-MODEL-02 才能讨论生产 GO。
