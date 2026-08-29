# HYDRO-MODEL-02-D3A-1 Manning 能力合同

- 日期：2026-08-29
- 能力 ID：`single-branch-gate-pump-manning-v1`
- 验证策略：`d3a-1-v1`
- 状态：本地科学门通过，等待 Hosted CI 封口

## 1. 方程与数值处理

Manning 摩阻坡度采用：

```text
Sf = n² Q |Q| / (A² R^(4/3))
```

动量源项为 `-g A Sf`，等价于：

```text
dQ/dt |_friction = -g n² Q |Q| / (A R^(4/3))
```

数值核沿用现有逐单元、逐 SSP-RK2 stage 的分裂半隐式更新。令
`k = g n² / (A R^(4/3))`，每个 stage 的更新为：

```text
Q(new) = Q(*) / (1 + dt k |Q(*)|)
```

该式保持符号并耗散 `|Q|`；`n=0` 精确退化为 D1，`Q=0` 精确保持为零。
它不是全局二阶 IMEX 声明。小面积继续由既有 fully-wet、positivity 与有限性门负责。

## 2. 摩阻稳定性合同

能力策略限制每个 Section/cell 的有效标量糙率为 `0 < n <= 0.10`。该范围由
`d3a-1-v1` 控制，不写死在数值核，也不从土地类型或 GIS 数据推断。

每个候选 stage 计算摩阻数：

```text
mu = dt k |Q(*)|
```

本能力要求 `mu <= 0.1`。超限 trial 被拒绝并缩小时间步；最终结果只汇总 accepted
steps 的 `maximum_friction_number`，并用 `friction_retry_count` 单独记录摩阻门重试。

## 3. 平台路由与兼容性

`dayu.model-input.v4` 必须显式选择能力 ID。Registry 将同一个
`saint-venant-fv-hll-ssp-rk2-d1-v1` 求解器核绑定到独立 D3A-1 adapter、策略与
engine route；没有新建 solver2，也不会根据输入中的 Manning 值自动升级能力。

D1 仍显式要求 `n=0`，其 adapter、policy、wire result 与冻结回归不变。D3A-1 结果在
诊断区增加摩阻数与摩阻重试证据；旧能力序列化时不会出现这些新增字段。

## 4. 当前作用域

已解锁范围是：单 Branch、全湿、正向严格亚临界、平床、相同 Profile、正的
section-effective Manning、一个 completed-interface Gate 和一个 external
Q-H/Q-efficiency Pump，仅用于 validation。

仍禁止：

- 非零床坡与未经确认的床高程；
- 非同 Profile、突变或不连续断面拓扑；
- 横向复式断面分区糙率；
- Junction、一般河网、湿干、倒流、超临界与水跃；
- 率定、生产调度或工程决策声明。
