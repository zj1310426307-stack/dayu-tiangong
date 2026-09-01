# MASCARET 1D Adapter

更新日期：2026-09-02
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

本 Adapter 锁定 MASCARET `v9.1.1`、官方提交 `1fe3b5141f7d9c9fa8fe6d6d0316c994a39c2d95`。MASCARET 作为 TELEMAC-MASCARET 的外部 GPL-3.0-only 运行时使用，Dayu 仓库和默认业务镜像均不复制其源码或执行文件；独立运行时镜像保留上游许可证。部署和分发方仍须自行完成许可证合规审查，本文件不作法律判断。

`D-Flow FM` 只完成独立 HYDROLIB-core 结构序列化 Spike，没有实现、配置或对外声明生产可用。

官方依据：

- [MASCARET v9.1.1 launcher](https://gitlab.pam-retd.fr/otm/telemac-mascaret/-/blob/v9.1.1/scripts/python3/mascaret.py)
- [official MASCARET runner](https://gitlab.pam-retd.fr/otm/telemac-mascaret/-/blob/v9.1.1/scripts/python3/execution/run_mascaret.py)
- [official Opthyca parser](https://gitlab.pam-retd.fr/otm/telemac-mascaret/-/blob/v9.1.1/scripts/python3/data_manip/formats/mascaret_file.py)
- [official variable catalogue](https://gitlab.pam-retd.fr/otm/telemac-mascaret/-/blob/v9.1.1/scripts/python3/data_manip/formats/mascaret_variables_fr.csv)
- [OpenTELEMAC licence](https://www.opentelemac.org/index.php/licence)

## 运行时边界

经验证的原生运行时调用形式为：

```text
cd <isolated-job-workspace>
<verified-mascaret-binary>
```

原生二进制从当前 job 目录读取带单引号的 `FichierCas.txt`；兼容测试仍允许已审查的官方 Python launcher。两种方式均不使用 shell，并对身份未知、超时、取消、非零退出、缺失或空 `.opt` 结果 fail closed。长时计算每 15 秒刷新执行租约；Linux session/process-group 与 Windows Job Object 负责进程归属和崩溃恢复。

| 变量 | 含义 | 默认 |
|---|---|---|
| `MASCARET_ENABLED` | 明确启用外部运行时 | `0` |
| `MASCARET_RUNTIME` | `external` 或 `container`；旧 `cli` 只作只读别名 | `external` |
| `MASCARET_EXECUTABLE` | 官方原生二进制/launcher 路径 | `mascaret` |
| `MASCARET_EXECUTABLE_SHA256` | 已审查可执行文件 SHA-256；启用 external 时必填 | 空 |
| `MASCARET_DATA_DIR` | 原生运行时官方资源目录 | 空 |
| `MASCARET_UPSTREAM_TAG` | 审核锁定的官方 tag | `v9.1.1` |
| `MASCARET_UPSTREAM_COMMIT` | 审核锁定的官方提交 | `1fe3b514...` |
| `MASCARET_BUILD_TIMESTAMP` | 构建身份时间；启用时必填 | 空 |
| `MASCARET_CONTAINER_IMAGE` | 经许可审查且固定为 `image@sha256:...` 的外部镜像 | 空 |
| `MASCARET_TIMEOUT` | 单 job 超时秒数 | `3600` |
| `HYDRAULIC_WORKSPACE_ROOT` | 唯一 job 目录根 | `backend/storage/hydraulic-workspaces` |
| `MASCARET_RETENTION_CLASS` | `success`/`failed`/`debug`/`benchmark` | `failed` |
| `MASCARET_RETENTION_MAX_WORKSPACES` | 有界保留数量 | `20` |

`container` 模式还要求 Worker 主机存在 Docker CLI 和显式镜像名。运行时禁用网络，仅把当前 job 目录以 `/work` 挂载。默认 Compose 不提供 Docker socket，因此不构成已开启的 container 运行时声明。

`.xcas/.geo/.lig/.loi/.opt` 与 stdout/stderr 只属于该 job 的私有交换目录。成功默认清理，失败默认保留诊断；四类保留策略均有数量上限，且只有已证明外部资源释放的目录可清理。当前 API 不暴露主机绝对路径或容器内部路径。

## 模型映射

| Dayu | MASCARET | 当前状态 |
|---|---|---|
| Network / directed Branch graph | native branch/node lists | N01–N03 已验证；当前内部 native node 限三条 extremity |
| Cross Section / profile points | `.geo` profile | 已验证 |
| longitudinal Manning `n` | Strickler `K=1/n` | 已验证 |
| upstream Q(t) / constant Q | hydraulic law | 已验证 |
| downstream H(t) / constant H | hydraulic law | 已验证 |
| point lateral inflow/withdrawal | `debitsApports`, zero length | 已验证；正值入流、负值取水 |
| fixed broad-crested geometric weir | native geometric seuil / REZO | S01 已验证；不外推到活动或淹没控制 |
| initial stage / flow | `.lig` | 已验证 |
| Bridge / Culvert / CASIER | 上游线索存在但 Dayu 映射证据不足 | **未验证，fail closed** |
| Gate | 尚未完成全业务语义与真实运行时验证 | **不支持，fail closed** |
| Pump | 无经证实的官方对应 | **不支持，fail closed** |
| transverse roughness variation | 未在当前转换合同内 | 不支持，fail closed |

不得把 Gate/Pump 伪装成 lateral flow，也不得为不可表达的结构物填充猜测参数。CLI 启用前会核对 launcher SHA-256；Container 只接受不可变镜像 digest，结果 diagnostics 保存经核对的运行时指纹。

所有断面必须具有与 Network 完全一致且非 `unknown` 的垂向基准；同一 Branch 桩号必须严格递增。由最小断面间距推导的计算网格设置 100,000 断面硬上限，超限时显式拒绝而非生成不可控网格。

## 结果合同

Parser 严格读取 Opthyca `[variables]` / `[resultats]`，核对列数、时间、reach/section、分支原生桩号偏移、桩号、重复行、非有限数以及完整输出 cadence；同时兼容平台 `t=0` 轴和官方从首个计算步开始的原生轴。水位和流量为必需变量；统一结果至少包含：

```text
simulation_id, scenario_id, engine, engine_version,
branch_id, chainage_m, cross_section_id, timestamp_seconds,
water_level_m, depth_m, discharge_m3s, velocity_ms, flow_area_m2
```

若官方输出含 `S1/S2`、`B1/B2`、`P1/P2`，则使用两部分之和计算流通面积、顶宽、湿周和水力半径，并以 `Q/area` 统一速度；REZO 带方向符号的 Froude 归一为统一合同中的非负幅值。Parser 还提取全局及汇流控制体质量报告。MASCARET 私有文件和原始变量不直接暴露给前端。

## 测试口径

- `tests/hydraulic_1d/`：Adapter、验证、Parser、运行时边界和架构隔离。
- `tests/benchmark/hydraulic_1d/`：五类 solver-neutral benchmark；运行时可用时必须真实执行 `engine.run` 并计算 water level、Q、V、peak、peak time、mass balance 与 runtime 七项指标。Benchmark 01 的 Q/H/V 来自同一个矩形 Manning 均匀流工况。
- 未提供真实运行时时，集成测试状态是 `SKIPPED_MASCARET_RUNTIME_NOT_AVAILABLE`，不是 fake pass。
- 所有生产验收阈值集中在 `acceptance-manifest.json`；机器报告记录 expected/actual/绝对误差/相对误差/tolerance/operator，不根据结果自动调整阈值。
