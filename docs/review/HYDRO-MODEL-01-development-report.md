# HYDRO-MODEL-01 一维闸泵联合调度开发报告

> **历史归档 / 自研 Solver 路线已废止（2026-08-31）：** 本文保留 2026-08-19 合成案例的工程记录，不是当前 Standard 1D 实现或生产验收。旧 `HydraulicEngine`/准动态河网路线已由 [HYDRO-1D-RESET-01](../migration/HYDRO-1D-RESET-01.md) 废止。

- 项目：大禹·天工（dayu-tiangong）
- 报告日期：2026-08-19
- 阶段：HYDRO-MODEL-01
- 当前结论：合成数据上的准恒定闸泵联合调度软件闭环、真实 PG16 回库与外部 Redis/Celery 双任务链已验证；内置浏览器视觉验收、真实工程率定和生产适用性均未完成
- 基线审查：`docs/review/HYDRO-MODEL-01-current-gate-pump-audit.md`

## 1. 结论与证据口径

本阶段没有新建第二套 Gate/Pump 数据库，也没有替换 Dataset Version、
SimulationTask、StructureResult 或 DispatchEvent。实现复用现有静态资产、冻结任务、
水力公式、控制规则、异步任务和结果表，在 `dayu.model-input.v3` 边界补齐结构物包络、
兼容 ID 重写和 baseline/controlled 独立冻结，并增加一个 5 km、20 断面、24 h 的
确定性合成验收案例。

当前证据支持以下结论：

1. Gate/Pump 可以在冻结的 v3 合成输入中参与准恒定河网计算和规则调度；
2. 闸门开度/流量、泵站机组/流量/功率/累计能耗和调度事件可以形成结构化结果；
3. v3 的 public/hydraulic ID 映射、外部 Redis/Celery 双任务和闸泵结果回库在真实 PostgreSQL 16/PostGIS 中通过门禁；
4. 前端源码合同、OpenAPI 同步、TypeScript 和生产构建通过；
5. 截至本报告生成时，HYDRO-MODEL-01 新页面尚未完成浏览器交互与视觉结果验收；
6. 当前算法不是 Saint-Venant 非恒定流求解器，合成案例也不是生产率定或真实工程验证。

状态术语：`PASS` 表示对应证据本轮已实际执行；`PARTIAL` 表示实现存在但仍缺指定环境或
端到端证据；`PENDING` 表示本轮尚未执行。不同证据层不得相互替代。

## 2. 复用现有 Gate/Pump，不建立第二套工程对象

### 2.1 数据库与运行态分工

权威静态对象继续使用：

- `backend/app/gis/models.py::Gate`；
- `backend/app/gis/models.py::Pump`；
- `backend/app/gis/models.py::SimulationTask`；
- `backend/app/gis/models.py::StructureResult`；
- `backend/app/gis/models.py::DispatchEvent`。

Gate 已有河道、旧河段、桩号、上下游节点、宽高、底槛/堰顶、流量系数、开度上下限、
开度变化率、最小保持时间、倒流策略和可用状态。Pump 已有进出水节点、转输类型、设计
流量、扬程/效率曲线、功率、机组数、最短启停、启动次数、工作扬程和倒流保护。

本阶段没有增加 Alembic 迁移，也没有把某次计算的开度、启停或累计能耗写回静态资产表。
运行态仍由 `GateControlState`、`PumpControlState` 在单次模拟内部维护，逐时输出由既有
StructureResult/DispatchEvent 持久化边界承接。

### 2.2 领域模型复用

`GateModel` 和 `PumpModel` 是已有权威计算函数的轻量领域入口：

- Gate 继续调用同一套关闭、自由孔流、淹没孔流、堰流、倒流和流量上限公式；
- Pump 继续调用同一套机组约束、扬程/效率曲线、进水深度、功率和能耗计算；
- 没有复制第二套闸门或泵站公式；
- 显式固定运行态只有在 `control_state.mode=fixed` 且目标值有效时才生效；
- 数据库资产的 `control_mode` 只是静态管理属性，不会把空开度或空机组数误解释为固定指令。

## 3. model-input v3 结构物与控制包络

### 3.1 权威结构

v3 新增以下结构化入口：

```json
{
  "structures": {
    "gates": [],
    "pumps": []
  },
  "controls": {
    "rules": []
  }
}
```

每个结构物必须包含：

```text
id
dataset_version_id
branch_id
chainage
geometry
parameters
control_state
provenance
```

`structures` 是 v3 消费者的主入口。为兼容现有求解器和旧调用方，顶层 `gates`、`pumps`
继续存在，但只能是 nested 数据的完全一致镜像；adapter 在两者不一致时 fail closed。
外部 v3 输入可以省略顶层镜像，由 nested 结构直接进入适配器。

### 3.2 Gate 位置语义

- `branch_id` 使用已验证的 hydraulic Branch ID；
- 生产 builder 将现有 `Gate.station` 原样写入 `chainage`，不做几何猜测；
- 有显式 `reach_id` 时优先采用，并验证 Reach 属于 Branch、chainage 落在其范围内；
- 无显式 Reach 时，可用 `branch_id + chainage` 定位严格位于某一 Reach 内部的 Gate；
- Gate 恰在两个 Reach 的共同边界时，不自动选择上游或下游 Reach，必须提供显式 `reach_id`；
- Reach 选择和来源写入结构物 provenance。

### 3.3 Pump 位置语义

现有 public Pump 没有权威 station 字段。生产 builder 因此输出：

```json
{
  "chainage": null,
  "provenance": {
    "chainage_source": "unavailable_not_inferred"
  }
}
```

通用或合成 v3 输入可以提供 chainage，但必须同时提供非
`unavailable_not_inferred` 的明确来源。24 h demo 的 Pump 使用 `chainage=4000`、
`reach_id=103` 和 `chainage_source=synthetic_demo_contract`；这只是合成案例合同，
不是从生产数据库点位推算出的工程桩号。

## 4. 冻结、哈希与 public→hydraulic ID 重写

### 4.1 冻结顺序

受控计划现在作为参数进入 `freeze_task_input`，而不是在快照哈希生成后追加 JSON：

```text
冻结 DispatchPlan
        ↓
build_model_input_v3(..., dispatch_plan=...)
        ↓
校验 Network / Branch / Reach / active Profile
        ↓
重写 public 兼容 ID → hydraulic ID
        ↓
生成 structures / controls.rules
        ↓
合并数据 provenance + engine commit/schema
        ↓
计算 canonical snapshot hash
```

重写范围包括：

- 边界条件的 public RiverNode → HydraulicNode；
- Gate 上下游节点的 public RiverNode → HydraulicNode；
- Gate 旧 RiverSegment → HydraulicBranch；
- Pump 进出水节点的 public RiverNode → HydraulicNode；
- 规则的节点水位观测对象 → HydraulicNode；
- 规则的断面水位观测对象 → HydraulicCrossSection。

无法证明映射的非空 ID 会阻止 v3 就绪，不按整数碰巧相等进行猜测。闸门水头差和泵进口
水位规则引用的是既有 Gate/Pump 主键，保持原身份域。

### 4.2 baseline 与 controlled

调度运行分别调用 v3 builder 冻结两份独立输入：

- baseline：`dispatch_plan=null`；
- controlled：传入已冻结的 DispatchPlan；
- 两份任务都声明 `dayu.model-input.v3` 和 tabulated 断面；
- 两份快照分别计算哈希，不再通过浅拷贝 baseline 后追加计划；
- `freeze_task_input` 合并既有 provenance，不覆盖测量来源、校核引用等上游证据。

这一改动保证模型真正执行的规则 ID、结构物 ID、来源和最终哈希属于同一个冻结合同。

## 5. 准恒定联合计算与控制闭环

每个同步输出/动作时刻执行：

1. 读取冻结边界和上一步结构物运行态；
2. 按有向无环河网传播基础流量并反算节点水位；
3. 读取人工计划、阈值规则或显式 fixed state；
4. 应用闸门开度上下限、变化率、保持时间和资产可用性；
5. 应用泵站机组数、最短启停、启动次数、扬程、进水深度和资产可用性；
6. 将 Gate 作为指定河段通量、Pump 作为节点源汇重新执行连续性路由；
7. 输出断面、节点、结构物、调度事件和水量平衡诊断。

输入与生命周期门禁同时收紧：边界值和时间必须为有限数值，同一节点不得混配流量与
水位边界，源/汇节点必须使用正确边界类型，时序边界必须覆盖完整计算时域；结果存在
NaN/Inf、水量平衡失败或相对残差达到 1% 时不得标记任务成功。两个 Celery 任务投递时，
首个或第二个投递失败都会把未投递对象和 DispatchRun 持久化为明确失败；第二个投递失败
还会保留已成功投递的 baseline job ID，不留下无法解释的永久 queued 状态。

规则继续使用结构化白名单，不执行用户脚本。支持人工时序动作，以及节点水位、断面
水位、闸门水头差、泵进口水位和 elapsed time 阈值；滞回、最小保持、冷却、优先级、
冲突和实际约束结果均留有审计字段。

## 6. 24 小时合成案例

案例位于 `examples/hydraulic/gate-pump-demo/`，输入是冻结的
`dayu.model-input.v3`：

| 项目 | 值 |
|---|---:|
| 河道长度 | 5,000 m |
| HydraulicReach | 3 段：0–2,500、2,500–4,000、4,000–5,000 m |
| 横断面 Profile | 20 个 |
| Gate | 1 座，2,500 m，显式绑定 Reach 102 |
| Pump | 1 座，4,000 m，显式绑定 Reach 103；位置来源为合成合同 |
| 计算历时 | 86,400 s（24 h） |
| 输出 | 每小时一次，共 25 帧 |
| 控制 | 4 条冻结水位规则 |

`run_demo.py` 实际执行成功，并与提交的 `result_summary.json` 精确一致：

| 指标 | 结果 |
|---|---:|
| 输入 schema | `dayu.model-input.v3` |
| 结果 schema | `dayu.hydraulic-result.v2` |
| solver | `synchronous-network-continuity-manning-v1` |
| HydraulicReach 数 | 3 |
| 断面时序对象数 | 20 |
| 结构物逐时记录数 | 50（2 个结构物 × 25 帧） |
| DispatchEvent 数 | 4；来源仅 `rule` |
| rule trigger count | 2 |
| 数值有限性 | 全部有限，无 NaN/Inf |
| 外部入流体积 | 1,728,000 m³ |
| 外部出流体积 | 1,728,000 m³ |
| Gate 内部转输体积 | 1,728,000 m³ |
| Pump 外排体积 | 172,800 m³ |
| storage change | 0 m³ |
| balance residual | 0 m³ |
| relative balance residual | 0.0，`pass` |
| production calibrated | `false` |
| scientific scope | `quasi-steady software acceptance only` |

这里的零残差证明该合成准恒定路由的记账闭合，不证明真实河道非恒定蓄量计算、参数率定
或洪水过程模拟准确。

## 7. 结果持久化与 API

既有异步 Worker 持久化服务继续负责：

- `SimulationResult`：断面水位、流量、流速；
- `JunctionResult`：节点水位、入流、出流、源汇和残差；
- `StructureResult`：闸泵请求值、实际值、流量、水位、扬程差、功率、能耗、流态和约束；
- `DispatchEvent`：来源、请求命令、实际命令、结果与原因。

本阶段没有增加新的 HTTP 路由或手写前端 API wrapper。OpenAPI 重新生成成功，生成客户端
无 diff，前端仍通过既有 generated client 获取调度结构物和事件。

本轮 PG16 专项实际从真实 v3 快照执行 `HydraulicEngine`，再通过 Worker 使用的唯一
`persist_engine_result` 入口落库并读回：6 条 `SimulationResult`、4 条 `JunctionResult`、
4 条 `StructureResult` 和不少于 4 条 `DispatchEvent`。断面 public ID 为 3001–3003、
hydraulic ID 从 1 起；节点 public ID 从 1001 起、hydraulic ID 从 1 起，错开序列下外键
仍正确，证明结果不能依赖“两个 schema 的整数主键碰巧相等”。

在此直接持久化门禁之后，本轮又以外部 Redis broker 和独立 Celery solo Worker
完成了 24 h baseline/controlled 双任务。主验收 run #4 的 task #6/#7 均为
`dayu.model-input.v3`，均有独立 `queue_job_id`、Worker 记录和 64 位快照哈希。
数据库读回 baseline/controlled 各 4,323 条 `SimulationResult`，controlled 读回
2,882 条 `StructureResult` 和 4 条 `DispatchEvent`。run #5 通过第二个 API 入口
再次创建同一冻结计划的双任务，约 17.4 s 进入 `success`，数量和质量门禁与 run #4
一致；两个运行共享同一 Redis 队列，不能表述为两条隔离 Worker 链。

## 8. 前端实现与验证状态

### 8.1 已实现

- 水动力配置页的新任务默认选择 `dayu.model-input.v3`；
- 调度详情从 generated client 的真实 StructureResult/DispatchEvent 响应构建页面；
- 增加闸泵当前运行状态表；
- 增加 0/6/12/24 h 里程碑；
- 增加闸门开度、闸门流量、泵站流量、泵站累计能耗四组曲线；
- 页面显示实际结果覆盖时长；不足 24 h 时保留空缺，不插值、不伪造；
- 静态资产状态、模拟运行态和调度来源分开显示。

### 8.2 已执行的前端门禁

| 门禁 | 结果 |
|---|---|
| `npm.cmd run openapi:update` | PASS；generated client 无 diff |
| `npm.cmd run typecheck` | PASS |
| `npm.cmd run build` | PASS；3,927 modules，最新复验 52.24 s |
| 构建告警 | 仅既有大于 500 kB 的 AntD/ECharts chunk warning |
| 前端仓库、页面及真实引擎夹具合同 | `8 passed` |

### 8.3 浏览器状态

截至 2026-08-19 本报告生成时：`PENDING`。

尚无证据证明本轮页面已在浏览器中完成真实交互、图表渲染、里程碑覆盖、空数据提示、
控制台错误检查或真实 DB/API 结果闭环。TypeScript、生产构建和源码合同不能替代浏览器
验收。外部 Celery 与 PostgreSQL/API 数据闭环已由 run #4 主验收和 run #5 重复运行证明，
但不能代替
浏览器 DOM、图表渲染和控制台验收。用户明确要求此类任务只使用 Codex 内置
浏览器；本轮已清空会话并以显式 `iab` 选择器重试，仍在 Browser 插件的受信路径
校验处失败，发生在页面导航前。按用户约束，不再用 Chrome、Windows 界面工具或
独立 Playwright 替代。

## 9. 自动化与真实 PostgreSQL 16 门禁

### 9.1 本轮已实际执行

| 层级 | 命令/环境 | 结果 |
|---|---|---|
| HYDRO-MODEL-01 求解专项 | Gate、Pump、Dispatch、24 h demo、v3 adapter | `21 passed` |
| 既有 Phase 4 模型回归 | structures、control、network、benchmarks | `39 passed` |
| 全仓离线 | `pytest -c backend/pyproject.toml -p no:cacheprovider -ra` | `308 passed / 71 skipped / 0 failed`，最新复验 17.60 s |
| demo 可复现脚本 | `examples/hydraulic/gate-pump-demo/run_demo.py` | PASS；与 summary 精确一致 |
| 前端与夹具合同 | repository + 页面 + engine-driven fixture | `8 passed` |

71 个 skip 是显式外部服务/环境门，不能计为通过。

### 9.2 PostgreSQL 16 / PostGIS 真实门禁

本轮使用无持久卷的一次性隔离容器：

- 镜像：`timescale/timescaledb-ha:pg16.14-ts2.28.3-all`；
- PostgreSQL：16.14；
- PostGIS：3.6.4；
- TimescaleDB：2.28.3；
- fresh migration：升级到 Alembic `20260818_0019`；
- 专项：`RUN_HYDRAULIC_POSTGIS_TESTS=1 backend/tests/test_hydraulic_postgis.py`；
- 结果：`1 passed`，2.07 s；
- 隔离性：容器 `Mounts=[]`，执行后已通过 `--rm` 清理。

该门禁真实证明：0019 可在 PG16/PostGIS 上 fresh upgrade；hydraulic/public 双写、拓扑、
SRID、Profile 处理、v3 结构物包络、public→hydraulic 节点/河段/断面 ID 重写、
`controls.rules` 镜像、真实引擎计算以及断面/节点/结构物/事件结果回库成立；未映射 ID
继续 fail closed。

它没有证明：本阶段单独执行过 downgrade/upgrade 往返、持久数据库升级、浏览器调用
或真实工程数据精度。HYDRO-DATA-02 的历史迁移证据不能替代这些步骤。

### 9.3 外部 Redis/Celery + API + PG16 闭环

- 数据库：PostgreSQL 16.14 / PostGIS 3.6.4 / TimescaleDB 2.28.3，Alembic `20260818_0019`；
- broker：Redis 7.4.10，实测 `PONG`；
- 执行：临时 FastAPI 进程、Redis 队列和外部 Celery solo Worker，通过真实
  `POST /api/v1/dispatch/plans/{plan_id}/runs` 创建双任务；
- 主验收 run #4：24 h、60 s 输出间隔、1,441 帧，baseline task #6 和 controlled task #7
  均为 `success`，均有独立队列 ID、Worker ID 和 64 位快照哈希；
- 结果：baseline/controlled 各 4,323 条断面结果、各 2,882 条节点结果；controlled
  另有 2,882 条闸泵结果，run #4 有 4 条调度事件；`maximum_cfl=0.3938789038`，
  水量平衡 `pass`、相对残差 0；
- 重复性：run #5 由第二个 API 入口再次创建，产生同样的 24 h 数量和质量结果；两个
  Celery Worker 共享同一 Redis 队列，run #5 的 baseline task #8 被原 Worker 消费，
  因此这里只证明第二次运行成功，不声称存在第二条隔离 Worker 链；
- provenance：run #4 的 `engine_commit=workspace-hydro-model-01` 是阶段标签而非 Git
  SHA；run #5 task #8/#9 的 `engine_commit=uncommitted`。冻结输入哈希和结果证据成立，
  但任务元数据本身没有把两轮运行精确锁定到功能提交 `ed0c645`。

该隔离 fixture 的 Gate/Pump 均通过已验证节点/河网拓扑及冻结调度参与计算，
但 Gate 桩号仍为 `null/unconfirmed`，Pump 桩号为 `null/unavailable_not_inferred`。
本门禁不证明真实工程闸泵桩号定位已通过。

## 10. 任务书完成矩阵

| 完成标准 | 状态 | 本轮证据与限制 |
|---|---|---|
| 完成现有 Gate/Pump 代码审查 | PASS | `HYDRO-MODEL-01-current-gate-pump-audit.md`，日期已复核为 2026-08-19 |
| Gate 参与计算 | PASS（合成软件验收） | Gate 模型专项、控制专项和 24 h demo；不代表工程率定 |
| Pump 参与计算 | PASS（合成软件验收） | Pump 曲线/约束专项、控制专项和 24 h demo；不代表真实泵站曲线验证 |
| model-input v3 支持结构物 | PASS | nested 主入口、顶层兼容镜像、必需字段、provenance、PG16 实库门禁 |
| 控制规则运行 | PASS（合成软件验收） | 24 h demo 产生 4 个 rule 事件，trigger count=2 |
| 24 小时模拟成功 | PASS（合成软件验收） | 86,400 s、25 帧、20 断面、50 条结构物结果、全部有限 |
| 闸泵结果回库 | PASS（外部 Celery） | PG16 上的 24 h baseline/controlled 双任务成功；controlled 读回 2,882 条 StructureResult |
| DispatchEvent 生成 | PASS | demo 输出 4 条；外部 Celery run #4/#5 均在 PG16 读回 4 条 |
| 水量平衡通过 | PASS（限定口径） | 合成准恒定记账 relative residual=0；未计算真实动态河道蓄量 |
| 前端展示调度过程 | PARTIAL | 代码、OpenAPI、typecheck、build、静态合同通过；浏览器结果 PENDING |
| 自动测试通过 | PASS | 全仓离线 308 passed / 71 skipped / 0 failed；PG16 专项 1 passed |
| 输出开发报告 | PASS | 本文件 |

因此，HYDRO-MODEL-01 的“代码、合成计算、真实 PG16 持久化与外部 Celery
baseline/controlled 双任务闭环”已经形成。任务书全部完成标准尚未全部关闭：
仅“Codex 内置浏览器结果验收”仍因插件运行时阻断保持 `PENDING`。

## 11. 科学适用边界

当前 solver 明确标识为 `synchronous-network-continuity-manning-v1`，属于准恒定软件验收
模型。其适用性必须按以下边界理解。

### 11.1 当前实际求解内容

- 只接受有向无环河网；有向环会被拒绝；
- 在输出时刻和计划动作时刻按节点连续性传播流量；
- 汇流直接累加，分流按下游边长度倒数权重分配，不解分流节点动量/能量方程；
- 从下游定水位沿 Manning 损失反推节点水位；
- 每条 Branch 使用代表断面估算面积和水力半径，再在线性节点水位间计算断面状态；
- Gate 使用局部代数孔流/堰流关系，结果再受上游可用流量和控制约束限制；
- Pump 作为节点源汇计算机组数、流量、功率和能耗；
- 规则只在离散同步时刻读取观测并产生动作；
- CFL 值和保守时间步作为诊断输出，不代表已经按该步长积分完整瞬变方程。

### 11.2 明确未实现

- 未联立求解 Saint-Venant 连续方程和动量方程；
- 未实现动态波、惯性项、压力波、回水传播时滞、反射、涌浪或水锤；
- 未实现节点动量/能量兼容和完整复式河网非线性迭代；
- 未进行闸门、泵站与河道水位的全隐式强耦合求解；
- 未把河道断面蓄量作为动态状态推进；诊断中 initial/final storage 均为 0；
- 未实现二维漫滩、风险范围、溃口、复杂建筑物群或地下管网耦合；
- 未完成真实测量断面、糙率、边界过程和机电曲线的参数率定；
- 未与 HEC-RAS、MIKE11、实测水位/流量或人工审定成果对比；
- 未进行数值网格收敛、时间步敏感性、不确定性、极端工况或生产容量评估。

### 11.3 禁止外推的结论

本阶段不得表述为：

- “已实现完整 Saint-Venant 一维非恒定流”；
- “已达到 HEC-RAS/MIKE11 同等级能力”；
- “已完成真实工程率定或生产验收”；
- “零水量残差证明真实洪水过程准确”；
- “PG16 直接持久化或外部 Celery 门禁可以替代浏览器视觉验收”；
- “前端构建通过等同于浏览器验收通过”。

## 12. 待完成项与下一阶段建议

1. 修复 Codex 内置 Browser 插件的受信路径运行时，再完成调度详情验收，记录实际 URL、
   数据来源、24 h 覆盖、四组曲线、空数据提示、
   控制台 warning/error 和截图；
2. 为 public Gate/Pump CRUD 补充同 Dataset Version 的 river/segment/node 引用完整性门禁；
3. 继续把 v3 readiness 预检前移到计划校验界面；本轮创建与重试运行入口已统一映射为
   业务 409，未就绪数据不会在这两条入口表现为未处理 500；
4. 真实工程使用前，补充测量资料、闸泵铭牌/曲线、边界过程和对照成果，单独执行率定、
   验证、敏感性和不确定性分析；
5. HYDRO-MODEL-02 若进入非恒定流，应另建科学验证矩阵，不以本阶段合成零残差作为替代。

最终口径：本阶段交付的是“冻结、可审计、可复现的准恒定闸泵联合调度最小软件闭环”，
不是完整 Saint-Venant 求解器，也不是已通过真实工程或生产标定的水动力产品。
