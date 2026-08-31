# MASCARET 1D Adapter

更新日期：2026-08-31
状态：当前 Standard 1D 产品路线

## 架构与版本

```text
HYDRO-DATA-01
  → Dayu Unified Hydraulic Model
  → Hydraulic1DEngine
  → MascaretEngine / Adapter
  → official MASCARET v9.1.1 process
  → Opthyca parser
  → Dayu Unified Hydraulic Result
```

本 Adapter 锁定 MASCARET `v9.1.1`。MASCARET 作为 TELEMAC-MASCARET 的外部开源运行时使用，Dayu 仓库和默认镜像均不复制、修改或捆绑其源码/执行文件。部署方必须独立审查官方软件的 GPL 许可证和发布方式。

`D-Flow FM` 只在 engine registry 中作为未来保留位，本阶段没有实现、配置或对外声明其可用。

官方依据：

- [MASCARET v9.1.1 launcher](https://gitlab.pam-retd.fr/otm/telemac-mascaret/-/blob/v9.1.1/scripts/python3/mascaret.py)
- [official MASCARET runner](https://gitlab.pam-retd.fr/otm/telemac-mascaret/-/blob/v9.1.1/scripts/python3/execution/run_mascaret.py)
- [official Opthyca parser](https://gitlab.pam-retd.fr/otm/telemac-mascaret/-/blob/v9.1.1/scripts/python3/data_manip/formats/mascaret_file.py)
- [official variable catalogue](https://gitlab.pam-retd.fr/otm/telemac-mascaret/-/blob/v9.1.1/scripts/python3/data_manip/formats/mascaret_variables_fr.csv)
- [OpenTELEMAC licence](https://www.opentelemac.org/index.php/licence)

## 运行时边界

官方 Python launcher 的调用形式为：

```text
python <official-telemac>/scripts/python3/mascaret.py case.xcas
```

`MASCARET_EXECUTABLE` 应指向上述官方 `mascaret.py`，或指向一个等价的、已审查非 shell launcher。Adapter 会将 case 文件名作为唯一位置参数，在当前 job 的唯一工作目录中启动进程。不使用 shell，并对超时、取消、非零退出、缺失或空 `.opt` 结果 fail closed。长时计算每 15 秒通过任务回调刷新一次执行租约；取消、回调异常或超时会终止 launcher 及其子进程组。

| 变量 | 含义 | 默认 |
|---|---|---|
| `MASCARET_ENABLED` | 明确启用外部运行时 | `0` |
| `MASCARET_RUNTIME` | `cli` 或 `container` | `cli` |
| `MASCARET_EXECUTABLE` | 官方 launcher 路径/镜像内路径 | `mascaret.py` |
| `MASCARET_EXECUTABLE_SHA256` | 已审查 v9.1.1 CLI launcher 的 SHA-256；启用 CLI 时必填 | 空 |
| `MASCARET_CONTAINER_IMAGE` | 经许可审查且固定为 `image@sha256:...` 的外部镜像 | 空 |
| `MASCARET_TIMEOUT` | 单 job 超时秒数 | `3600` |
| `HYDRAULIC_WORKSPACE_ROOT` | 唯一 job 目录根 | `backend/storage/hydraulic-workspaces` |

`container` 模式还要求 Worker 主机存在 Docker CLI 和显式镜像名。运行时禁用网络，仅把当前 job 目录以 `/work` 挂载。默认 Compose 不提供 Docker socket，因此不构成已开启的 container 运行时声明。

`.xcas/.geo/.lig/.loi/.opt` 与 stdout/stderr 只属于该 job 的私有交换目录。Parser 生成统一结果后，无论成功或失败都会删除该目录；当前接口不会返回已经删除的伪 artifact。需要长期保留原始文件时，必须另建经审计的对象存储发布流程。

## 模型映射

| Dayu | MASCARET | 当前状态 |
|---|---|---|
| Network / single Branch | 单 reach case | 已验证；多 Branch 显式拒绝 |
| Cross Section / profile points | `.geo` profile | 已验证 |
| longitudinal Manning `n` | Strickler `K=1/n` | 已验证 |
| upstream Q(t) / constant Q | hydraulic law | 已验证 |
| downstream H(t) / constant H | hydraulic law | 已验证 |
| point lateral inflow/withdrawal | `debitsApports`, zero length | 已验证；正值入流、负值取水 |
| initial stage / flow | `.lig` | 已验证 |
| Gate | 尚未完成全业务语义与真实运行时验证 | **不支持，fail closed** |
| Pump | 无经证实的官方对应 | **不支持，fail closed** |
| transverse roughness variation | 未在当前转换合同内 | 不支持，fail closed |

不得把 Gate/Pump 伪装成 lateral flow，也不得为不可表达的结构物填充猜测参数。CLI 启用前会核对 launcher SHA-256；Container 只接受不可变镜像 digest，结果 diagnostics 保存经核对的运行时指纹。

所有断面必须具有与 Network 完全一致且非 `unknown` 的垂向基准；同一 Branch 桩号必须严格递增。由最小断面间距推导的计算网格设置 100,000 断面硬上限，超限时显式拒绝而非生成不可控网格。

## 结果合同

Parser 严格读取 Opthyca `[variables]` / `[resultats]`，核对列数、时间、reach/section、桩号、重复行、非有限数以及从 `t=0` 到冻结时段末的完整输出 cadence。水位和流量为必需变量；统一结果至少包含：

```text
simulation_id, scenario_id, engine, engine_version,
branch_id, chainage_m, cross_section_id, timestamp_seconds,
water_level_m, depth_m, discharge_m3s, velocity_ms, flow_area_m2
```

若官方输出含 `S1/S2`、`B1/B2`、`P1/P2`，则使用两部分之和计算流通面积、顶宽、湿周和水力半径，并以 `Q/area` 统一速度。MASCARET 私有文件和原始变量不直接暴露给前端。

## 测试口径

- `tests/hydraulic_1d/`：Adapter、验证、Parser、运行时边界和架构隔离。
- `tests/benchmark/hydraulic_1d/`：五类 solver-neutral benchmark；运行时可用时必须真实执行 `engine.run` 并计算 water level、Q、V、peak、peak time、mass balance 与 runtime 七项指标。Benchmark 01 的 Q/H/V 来自同一个矩形 Manning 均匀流工况。
- 未提供真实运行时时，集成测试状态是 `SKIPPED_MASCARET_RUNTIME_NOT_AVAILABLE`，不是 fake pass。
