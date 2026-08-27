# HYDRO-MODEL-02-D1-RC1 跨平台审计

- 日期：2026-08-28
- RC1 基线：`9002f10b584ac8c95439e9e161027897f7e3d803`
- RC1 测试候选：`e85c95c4bad675eb404b439f696f53dccb7ac47a`
- 分支：`feature/HYDRO-MODEL-02-D1-pump-strong-coupling`
- 状态：本地门与 hosted CI 均通过

## 1. 首次 hosted CI 事实

GitHub Actions 运行 [`33097599382`](https://github.com/zj1310426307-stack/dayu-tiangong/actions/runs/33097599382) 在 D1 HEAD `9002f10` 上结束为 `failure`：

- `frontend-contract`：PASS；
- `hydraulic-model`：FAIL；
- legacy hydraulic：因与 MODEL-02 位于同一 job，在前序失败后被跳过。

失败严格限定为两项：

1. Ubuntu 公共 MVP 相对水量误差为 `2.7284841053187855e-16`，Windows 冻结值为 `1.3642420526593927e-16`，旧测试以 `abs=1e-18` 比较机器误差末位；
2. v4-lite-3 fixture 在运行时执行 `math.sin()` 和 100 次浮点二分，Ubuntu snapshot hash 为 `313964ba...53ba`，Windows 为 `96eb4e4d...bec1`。

两项都不是 Gate/Pump 物理失败，而是跨平台身份与测试合同错误。

## 2. Canonical JSON 合同

RC1 将 canonical policy 显式命名为 `dayu-canonical-json-v1`：

- mapping key 按字符串键排序；
- JSON 使用紧凑分隔符，不含 BOM 或结尾 newline；
- canonical text 以 UTF-8 编码后计算 SHA-256；
- `allow_nan=False`，NaN/Inf 拒绝；
- `-0.0` 归一为 `0.0`；
- boolean/null 使用标准 JSON 语义；
- Unicode 保留输入 code points，不做隐式 normalization；
- 权威数字必须来自冻结输入，不得由平台 libm 在身份计算前生成。

`snapshot_hash` 保留为兼容入口，其语义等同 `authoritative_input_hash`。

## 3. Hash domain

| Domain | RC1 含义 | 身份策略 |
|---|---|---|
| authoritative input | 用户/数据库冻结 JSON | `input_snapshot_hash` 兼容字段 + `dayu-canonical-json-v1` |
| runtime projection | Pydantic 校验、默认展开后进入数值适配器的输入，不含 provenance 元数据 | `dayu.v4-lite.runtime-projection.v1` |
| mesh | 实际 cell、dx、断面点、床高程、糙率和 Profile 身份 | 既有 `dayu.finite-volume-mesh.v1/v2` |
| solver policy | scheme、边界、摩阻、结构、事件、时间推进和数值容差 | 既有 `dayu.solver-policy.v1-v5` |
| validation policy | 公开 v4-lite validation policy 身份 | `dayu.v4-lite.validation-policy.v1` |

固定 v4-lite-3 fixture 的 Windows 本地结果：

```text
authoritative_input_hash  96eb4e4d28bc05c865c3f5e8f24e3b0169b4d29f95bfe515e22e72237bf2bec1
runtime_projection_hash   76123a26e539fbf5775be3ea8feb9570dc7e864a3c475036e383ae8ea8230312
mesh_hash                 056f3bc492bf64a12ecb9c1be66d0f2935ff941214c8c0e8c318db90d433f4ea
solver_policy_hash        c788c33c40f800fc469af1260a4a94150d16623a800c0083b56e15ad9c032618
validation_policy_hash    bb70c5a3af5942d16c43ec8c7f490333653e7efa2051d2e734c66aa8d3f17795
```

新的 authoritative hash 与旧 Windows 值相同，但身份来源已从“运行时生成浮点”迁移为 checked-in JSON。旧 Linux 动态值不写回 expected，也不作为新的权威身份。

## 4. Fixture 与科学门

`tests/fixtures/model02/v4-lite-3-moving-nonprismatic.json` 固定数值文本；冻结测试直接读取该文件。动态 helper 仍保留给变异和性质测试，但不再承担跨平台 frozen identity。

公共 MVP 水量测试改为：有限值、结果 tolerance 与冻结 tolerance 一致、`relative_error <= tolerance`。约 `1e-16` 的残差是数值质量观测值，不是逐 bit 业务合同。

以下科学门未修改：

- D1 `water_balance_tolerance <= 1e-10`；
- Pump head residual `<= 1e-10 m`；
- Gate energy residual 既有合同；
- CFL、正面积、有限 H/Q/V、no fallback；
- D1 20 断面 6 小时物理工况。

## 5. CI 审计

- MODEL-02 使用 Ubuntu/Windows、Python 3.11 matrix，`fail-fast=false`；
- legacy hydraulic 与 frontend 独立 job；
- pytest 生成 JUnit，诊断脚本生成平台与 hash JSON，`if: always()` 上传 artifacts；
- 官方 action 升级为 `checkout/setup-python/setup-node/upload-artifact@v7`；
- frontend Node 升级为 24，并已在本地 Node 24.17 验证。

## 6. Hosted RC1 结论

GitHub Actions 运行 [`33102252587`](https://github.com/zj1310426307-stack/dayu-tiangong/actions/runs/33102252587) 在 `e85c95c` 上通过：

- `MODEL02 Ubuntu Python 3.11`：355/355，PASS；
- `MODEL02 Windows Python 3.11`：355/355，PASS；
- `Legacy hydraulic`：26/26，PASS；
- `Frontend contract`：Node 24 typecheck/build，PASS；
- artifacts：`model02-ubuntu-py311`、`model02-windows-py311`、`legacy-hydraulic-ubuntu-py311` 均存在。

Ubuntu glibc 2.39 与 Windows MSVC 环境的五类 hash 完全相同；水量残差也都为 `1.0231815394945443e-12 m³`。因此 RC1 跨平台门判定为 PASS。
