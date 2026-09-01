# MASCARET v9.1.1 正式验证

更新日期：2026-09-01  
验证范围：HYDRO-1D-MASCARET-02

## 结论

Dayu Standard 1D 已通过官方 MASCARET `v9.1.1` 原生运行时的五组真实数值验收、并发隔离和故障边界验证。生产调用链保持：

```text
Unified Hydraulic Model → Adapter → verified runtime → native Opthyca
→ strict parser → Unified Hydraulic Result → PostGIS/API/GIS
```

Gate 与 Pump 继续 fail closed；本结论不扩大到桥梁、涵洞、堰坝、复杂河网或真实工程率定。

## 上游身份与许可证

| 项目 | 已验证值 |
|---|---|
| 官方项目 | `otm/telemac-mascaret` |
| tag | `v9.1.1`（protected tag） |
| tag object | `ed0ec0c755ed5a8618865b250c38c85d20f1cff5` |
| release commit | `1fe3b5141f7d9c9fa8fe6d6d0316c994a39c2d95` |
| source archive SHA-256 | `54b52798435baeb294ad3418c2fe146b5c10ef0d6e8e3e9d72d606e0f9fdb5e3` |
| canonical source tree SHA-256 | `cd116294009e08872331cab1dedc54f2321f13bbb304c863c0e06c07e17e3a6f` |
| local verified executable SHA-256 | `632967296f39bf548b37eceee242f0125ed4364ddced4e50a697d3047b7c48b9` |
| official runtime resource digest | `fa720e8a5a023ff46feccede55f69861ca0a1afbd408e12d6c2be49af934cb39` |
| license | GPL-3.0-only；容器保留上游 `LICENSE.txt` |

官方来源为 `https://gitlab.pam-retd.fr/otm/telemac-mascaret`，许可证说明为 `https://www.opentelemac.org/index.php/licence`。本仓库只保存构建说明、固定身份和 Adapter，不 vendoring 上游源码。许可证的具体商业分发义务须由部署方独立审查。

GitLab 的提交归档是动态生成的；同一提交的 gzip/tar 时间、所有者和权限映射可能变化。表中的归档 SHA-256 是本次审查样本记录，构建门禁实际强制校验按相对路径排序的逐文件内容 SHA-256 清单摘要。文件内容或相对路径有任何变化都会失败关闭。

## 可重复运行时

`docker/mascaret.Dockerfile` 从固定官方提交及规范化源码树摘要构建 `homere_mascaret`，运行镜像记录 OCI version/revision/created/license 标签；`tools/build_mascaret_runtime.sh` 为受控 Linux CI 构建同一目标。External 模式核验 binary hash、tag、commit、build timestamp 和四项官方资源；Container 模式只接受不可变 digest 并核验 OCI 标签。

每个执行尝试使用独立 workspace。Linux 使用新 session/process group 与 attempt token，Windows 使用 kill-on-close Job Object。超时、取消、进程失败、结果缺失、身份未知和无法证明释放均 fail closed。成功/失败/debug/benchmark 四类保留策略具有有界清理规则。

## 数值验收

机器证据由 `tools/run_mascaret_acceptance.py` 生成，不写入源码树。阈值唯一来源为 `tests/benchmark/hydraulic_1d/acceptance-manifest.json`。

| 算例 | 真实运行结果 | 关键验收 |
|---|---|---|
| B01 矩形恒定均匀流 | PASS | Manning Q ≤0.5%；水深/水位/速度 ≤1% |
| B02 n1/n2/n3 糙率 | PASS | `n↑ → H↑、V↓`，21 个断面、三级单调 |
| B03 洪水传播 | PASS | 洪峰延迟、响应和非放大；质量残差 `0.014894%` |
| B04 天然断面 | PASS | 断面身份、顺序、桩号及非矩形映射完整 |
| B05 Q(t)+H(t) | PASS | 相对时间同步；Q/H 边界 RMSE 在清单阈值内 |

五组质量守恒相对残差分别为 `0.005900%`、`0.005252%`、`0.014894%`、`0.076376%`、`0.030428%`，均低于 `0.5%`。公式为：

```text
relative residual = abs((storage_end - storage_start) - integral(Qin - Qout)dt)
                    / max(abs(net_flux), abs(storage_start), 1)
```

体积由权威断面流通面积沿桩号做梯形积分；边界流量沿统一相对时间轴做梯形积分。正式 JSON 共 5 个 case、31 个检查，并保存 7 份原生 `.opt` 快照的 SHA-256。

## 官方示例与 Adapter 分离验证

官方 `examples/mascaret/01_Steady_Kernel/mascaret_exp.xcas` 未修改物理参数，直接由上述原生二进制运行，退出码为 0，生成非空 `mascaret_exp_ecr.opt`。Dayu Adapter 生成的五类原生 case 由同一二进制接受并求解，从而分别证明官方 runtime 可用和 Adapter 输出可执行。官方示例采用可变时间步与上游自带初始水面，当前 Dayu 冻结模型采用固定相对时间步，因此不宣称两者逐行完全等价；该差异不以放宽 B01–B05 阈值掩盖。

## 平台与测试

- Parser 输出的 `runtime_provenance` 随统一结果进入任务 diagnostics，并由持久化服务写入数据库；结果 API 和 GIS 继续读取统一断面结果，不暴露原生路径。
- Readiness API 新增结构化 `runtime_identity`；生成的 OpenAPI 客户端已同步，前端高级信息展示官方 tag、commit、运行方式、平台、hash 和构建时间。
- Python 3.12：`270 passed, 67 skipped`；跳过项均为未提供的外部服务或禁用运行时门。
- 官方 MASCARET B01–B05：5/5 PASS；两作业并发隔离 PASS。
- TypeScript typecheck PASS；Vite production build PASS；Ruff PASS。
- GitHub 新增受控 `MASCARET production acceptance`，构建官方 runtime、直接运行官方示例、执行真实验收并上传 JSON/原生快照。

## 已知限制与回退

- 当前本机没有可用 Docker CLI/daemon，因此运行时容器镜像的本地构建留给新增的受控 GitHub job 复验；不得在该 job 通过前声明最终 `PRODUCTION_READY`。
- 本机没有启动持久 PostGIS/Redis/Celery 全栈；既有 persistence/API/GIS 合同由全量测试覆盖，真实服务托管闭环需由受控 CI 或部署环境复验。
- Gate、Pump、其他结构物、多 Branch/复杂河网及真实工程率定均不在本阶段能力内。
- 回退时设置 `MASCARET_ENABLED=0` 即恢复明确的 runtime-unavailable 行为；不得回退到已废止的 Dayu 自研生产 Solver。
