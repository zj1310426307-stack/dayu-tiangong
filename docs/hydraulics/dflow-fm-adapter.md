# D-Flow FM Adapter 与外部运行时边界

更新日期：2026-09-03
适用版本：`dayu-dflow-fm-adapter-v1` / `DIMRset_2026.02`
当前结论：reviewed Container Runtime 已通过合成开发验收；CLI 与生产能力继续关闭

## 当前状态

仓库已经具备 D-Flow FM 的开发期边界：多引擎登记、Solver-neutral 模型校验、HYDROLIB-core 类型化文件生成、Gate/Pump 严格子集映射、HIS NetCDF 结果解析、隔离 Workspace、CLI/Container 进程监督及完整 Runtime provenance 合同。

固定官方源码构建出的 reviewed Container Runtime 已由 digest `sha256:e53a7c22cdce6a63f39357006ba73f2254ace24979c1f374ba111ee52d5b12b9` 锁定，并通过官方 D-Flow、官方 D-Flow+FBC、DF01、DRTC-S01、G01–G03、PUMP01–PUMP02、GP01–GP03 和 24h L01。证据仍是 `SYNTHETIC_NUMERICAL_ONLY`，D-Flow 登记项保持 `production_eligible=false`，不得描述为真实工程或生产水力验证。Pump 为受限原生子集：固定 aggregate Capacity 与 FBC 手工 Capacity schedule 已验收，Pump threshold/PUMP03 仍为 `BLOCKED_BY_NATIVE_CONTROL_SEMANTICS`。

`DFlowFMEngine.run()` 的 DF01 路径已通过真实 DIMR/D-Flow 运行。它对带活动结构但没有显式 Gate/Pump spec 的普通 run 继续拒绝推断。

Controlled path 与普通 DF01 path 保持独立。`validate_controlled_model()`、`compile_control()`、`run_controlled()` 和 `parse_controlled_results()` 已开放单 Gate schedule/threshold、单 Pump Capacity schedule、Gate+Pump 联合 schedule，以及单 Gate threshold + 独立 Pump schedule 子集；所有身份与 registry 检查 fail closed，且不会用 Python 逐时步耦合器代替官方 DIMR/FBC。

## 固定源码与 Python 包

| 对象 | 固定身份 | 本仓库用途 |
|---|---|---|
| Delft3D FM suite | tag `DIMRset_2026.02`；commit `5a4649830b1e5072caf019fb4850bbdefd9ad431` | `dflowfm`、`dimr`、`fbc` 的唯一允许源码基线 |
| D-Flow FM native version | `1.2.184` | 当前 Adapter/Result 元数据版本；不代替 suite tag/commit |
| HYDROLIB-core | tag/PyPI `1.0.1`；commit `878d526ed028308e8778d6227a559de6ce49d297` | 类型化生成 Network、MDU、INI、BC、DIMR XML |
| HYDROLIB-core wheel | SHA-256 `15e9bb37c9d87922d2199f5142c471962fb1e457d1f553eb23a15574181e901f` | 官方 PyPI wheel 身份记录 |
| HYDROLIB-core sdist | SHA-256 `6a084d34403f10d378c4b1c9f1e9f3eb28dbc65feb23faffddf57a4370f5bbea` | 官方 PyPI source distribution 身份记录 |

`backend/requirements-dflow.txt` 独立固定 Adapter 与结果解析所需 Python 依赖，不进入默认后端依赖。建议在专用 Builder/Worker 环境中与 `backend/requirements.txt` 一起安装；它不会安装 Solver：

```text
pip install -r backend/requirements.txt -r backend/requirements-dflow.txt
```

HYDROLIB-core 的 Git 基线固定为 tag `1.0.1` 与 commit `878d526ed028308e8778d6227a559de6ce49d297`，不由代码猜测。真实运行的 provenance manifest 仍必须显式提供它的 version、upstream tag、完整 commit、包/二进制 SHA-256、source manifest、platform、architecture 和 build timestamp。

## Adapter 数据流

```text
Dayu Hydraulic1DModel
        ↓ 严格校验
DFlowFMModelBuilder + DFlowFMStructureMapper
        ↓ HYDROLIB-core 1.0.1
dimr_config.xml + dayu.mdu + dayu_net.nc + INI/BC
        ↓ 仅允许 DIMR 作为顶层入口
D-Flow FM + 已锁定的 DIMR/FBC 受限控制子集
        ↓ dayu_his.nc
DFlowFMResultParser
        ↓
Dayu HydraulicResult
```

Builder 不写第二套数据库 Domain，也不接受 native file 作为业务权威源。生成前必须通过以下校验：

- 明确的二维节点坐标与每条 Branch 的 GeoJSON LineString，方向、几何长度和 Dayu chainage 一致；
- 显式 `mesh_edge_length_m`，SI 单位与统一高程基准；
- 每个外部端点恰好一个支持的边界，当前拒绝 lateral boundary；
- 完整断面、粗糙率覆盖、非干初始水位、固定时间步及输出间隔；
- active Gate/Pump 的位置、类型与 Solver-neutral spec 一一匹配；
- 所有 native ID 符合受限字符集，不通过近邻或默认值猜测身份。

Builder 通过 HYDROLIB 递归保存、重新加载并核对必需文件，最后写入带各文件 SHA-256 的 `dayu-dflow-fm-manifest.json`。这证明文件合同可序列化，不证明 Solver 接受或数值正确。

## Gate 与 Pump 映射边界

| Dayu 语义 | 当前 native 表示 | 限制 |
|---|---|---|
| `vertical_underflow_gate` | HYDROLIB `Orifice` | 只允许竖向开度；几何、方向、系数与开度必须显式 |
| `general_opening` | HYDROLIB `GeneralStructure` | 几何与正/反向自由/淹没系数全部显式；包含 1.0.1 discriminator 兼容处理 |
| inline Pump | HYDROLIB `Pump`，`numStages=0` | 只允许 aggregate `Capacity`；必须有 availability 与至少两点的有证据 head/reduction curve |

`unit_count`、`pump_enabled`、跨流域/外部转输 Pump 不能转换成 aggregate Capacity。未知 Gate subtype、缺少来源状态的参数、默认 Q-H 曲线或隐式方向均在生成 native 文件前 fail closed。运行期仅将 `pump_target_flow` 精确映射为小写 BMI 路径 `pumps/<id>/capacity`；Capacity 是限定值，不是 actual Q，Capacity=0 也不自动表示物理停机。

## 结果合同

`DFlowFMResultParser` 只读预期的 `output/dayu_his.nc`，并通过 xarray 精确匹配变量、dimension、unit、Dayu observation ID 和完整时间轴。它不搜索“相似变量”、不选最近位置、不填补缺失 H/Q，也不把空文件或成功退出但无结果视为成功。

当前默认合同要求 water level、cross-section discharge、flow area 与 velocity。Pump 结果额外精确核对原生 Capacity、actual discharge、intake/outlet water level、structure/pump head、reduction factor 及 endpoint identity；Solver 未给出分级时 `active_stage=null`，不由 `unit_count` 推断。任何文件缺失、维度/单位/身份漂移、重复或缺失位置、非有限值、时间轴错误均返回稳定的 `DFLOW_RESULT_*` 错误。

## Runtime 模式与 Workspace

`DFLOW_RUNTIME` 支持 `disabled`、`cli`、`container`，默认 `disabled`；配置输入 `external` 只作为 `cli` 的兼容别名。禁止自动换 Solver。

| 变量 | 行为 |
|---|---|
| `DFLOW_RUNTIME` | 默认 `disabled`；启用值为 `cli` 或 `container` |
| `DFLOW_DIMR_EXECUTABLE` | CLI 必须是显式绝对路径，指向 host DIMR 工件；Container 模式中是镜像内 DIMR argv |
| `DFLOW_DIMR_EXECUTABLE_SHA256` | 可选的额外 DIMR 固定值；CLI 仍会按 provenance 的 `binary_sha256` 重新计算并核对 |
| `DFLOW_DFLOWFM_ARTIFACT` | CLI 必填的 D-Flow FM 显式绝对工件路径；按 provenance 重新计算 SHA-256 |
| `DFLOW_FBC_ARTIFACT` | CLI 必填的 FBC/D-RTC 显式绝对工件路径；按 provenance 重新计算 SHA-256 |
| `DFLOW_HYDROLIB_CORE_ARTIFACT` | CLI 必填的 HYDROLIB-core 显式绝对工件路径；按 provenance 重新计算 SHA-256 |
| `DFLOW_PROVENANCE_FILE` | 四组件完整 JSON provenance；启用模式缺失即 blocked |
| `DFLOW_CONTAINER_IMAGE` | Container 模式必须为非 `latest` 的 `image@sha256:<digest>` |
| `DFLOW_DOCKER_EXECUTABLE` | 已安装 Docker client；Runtime 不拉取镜像 |
| `DFLOW_TIMEOUT` | 有限正数秒数；默认 3600 |
| `DFLOW_WORKSPACE_ROOT` | D-Flow 专用根；未设置时使用项目内 hydraulic workspace |
| `DFLOW_UPSTREAM_TAG` / `DFLOW_UPSTREAM_COMMIT` | 只能等于已审计 tag/commit，漂移立即拒绝 |

每个 Job 的受控目录为：

```text
runtime/<simulation_id>/<job_id>/
├── input/
├── control/
├── output/
├── logs/
└── metadata/
```

simulation/job ID 使用严格单路径段；重复 Job、marker 不匹配、symlink 或 `..`/绝对路径均拒绝。CLI 和 Container 都以 argv、`shell=False` 启动唯一顶层进程 DIMR；Dayu 不逐时步调用 D-Flow/FBC。取消或超时会终止完整进程树。Container 额外强制 `--pull never`、固定 job ownership label、只挂载当前 Workspace、`--read-only`、`--network none`；强制清理前必须用 cidfile 和 label 证明容器属于当前 Job。

## Runtime provenance 与可用判据

`dayu.dflow-runtime-provenance.v1` 必须同时包含 `dflowfm`、`dimr`、`fbc`、`hydrolib_core`。每个组件必须具有：

- `version`
- `upstream_tag`
- 40 字符 `upstream_commit`
- `binary_sha256`
- `source_manifest` SHA-256
- `platform`
- `architecture`
- 带时区的 `build_timestamp`

D-Flow FM、DIMR 与 FBC 必须共享已审计 suite tag、commit 和 source manifest，并分别精确报告原生版本 `1.2.184`、`2.00`、`1.6.1`；四组件必须同平台/架构。CLI 必须同时提供 DIMR、D-Flow FM、FBC 与 HYDROLIB-core 四个显式工件，并对四者重新计算 SHA-256 与 provenance 比对。Container 还会检查本地 digest、OCI `source/version/revision` 标签及完整 provenance 的 canonical SHA-256 标签，且以 `--pull never` 禁止隐式拉取。任一证据缺失或不一致，readiness 必须返回 `DFLOW_RUNTIME_BLOCKED`。

上述路径和 hash 校验只是必要条件；Container 还必须命中源码内唯一 reviewed digest，并由 acceptance registry 绑定完整 benchmark 集。不存在环境变量跳过 provenance/acceptance。CLI 尚无经验收的“已核验工件→实际装载模块”路径绑定，继续 `BLOCKED / UNVERIFIED`。

两次独立官方源码构建由于上游二进制嵌入构建时间而不具备 bit-for-bit 一致性，明确分类为 `NON_BIT_REPRODUCIBLE`。信任基础是同一 source manifest、固定 recipe/compiler/dependency 基线、每次构建独立哈希及官方功能 case；未修改上游源码，也未用第三方 Solver 二进制替代。

## 许可证与分发边界

| 组件/产物 | 已核对的上游事实 | 本仓库处理 | 分发前置 |
|---|---|---|---|
| D-Flow FM | 固定组件许可事实：AGPL-3.0 | 仅作为独立 CLI/Container 进程；Backend Python 包不 vendoring 源码或二进制 | 必须完成 tag 级源文件/SPDX 盘点、通知/源码提供义务评审和依赖许可兼容审查 |
| DIMR | 固定组件许可事实：GPL-3.0 | 是唯一允许的顶层启动边界；不进入 Backend wheel | 容器/安装包分发必须同时带完整许可清单、notices、对应源码/获取方式及人工批准 |
| FBC / D-RTC | 固定 FBC 组件许可事实：GPL-2.0 | 仅在锁定 DIMR coupling Runtime 中执行经 acceptance registry 允许的最小 artifact 子集 | 完成源码头、构建链、依赖、配置文件及分发模式的专项审查 |
| Delft3D 共享 utilities / third party | 上游说明若干 utilities 为 LGPL-2.1，第三方包保留各自许可证 | 不假定 `fm-suite` 镜像只有一种许可证 | 对实际 runtime image 生成 SBOM、文件/包级许可映射、notices 和源码义务清单 |
| HYDROLIB-core `1.0.1` | 固定组件许可事实：MIT；已记录 wheel/sdist SHA-256 | 仅在隔离 Adapter/Worker 环境按固定版本安装 | 随产物保留 MIT 文本与 attribution，核对实际安装 artifact hash |
| `requirements-dflow.txt` 转递依赖 | 每个 Python 包使用各自许可证，HYDROLIB-core 的 MIT 不会覆盖转递依赖 | 与默认 Backend 依赖隔离 | 按实际解析的锁定包/平台 wheel 生成 Python SBOM 和许可清单 |
| Dayu Adapter/Runtime 代码 | 本项目尚未在仓库根部提供可由本文确认的统一许可文件 | 与上游 Solver 源码/二进制分离 | 对外分发前由项目所有者确认 Dayu 自身授权和与运行时打包方式 |

上表的 D-Flow FM/DIMR/FBC/HYDROLIB-core 许可标识是已核对的组件事实；它们不代替对实际镜像、连接方式与转递依赖的逐文件审查。构建或分发运行时镜像前必须生成逐文件/逐组件许可清单并完成人工审查。本文只记录上游事实，不构成法律意见。

官方来源：

- [Deltares Delft3D `DIMRset_2026.02`](https://github.com/Deltares/Delft3D/tree/DIMRset_2026.02)
- [Delft3D `engines_gpl` component tree at the pinned tag](https://github.com/Deltares/Delft3D/tree/DIMRset_2026.02/src/engines_gpl)
- [Delft3D FM suite development overview](https://github.com/Deltares/Delft3D/blob/DIMRset_2026.02/doc/development.md)
- [Delft3D Linux build instructions](https://github.com/Deltares/Delft3D/blob/DIMRset_2026.02/doc/compiling_Linux.md)
- [HYDROLIB-core 1.0.1 on PyPI](https://pypi.org/project/hydrolib-core/1.0.1/)
- [HYDROLIB-core documentation](https://deltares.github.io/HYDROLIB-core/)
- [下一阶段真实工程资料要求](./dflow-fm-real-data-requirements.md)
