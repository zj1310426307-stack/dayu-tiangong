# HYDRO-MODEL-02-D3A Release Readiness

- 日期：2026-08-29
- 状态：`PASS — PR REVIEW READY`
- PR：[#12](https://github.com/zj1310426307-stack/dayu-tiangong/pull/12)
- Merge status：`NOT MERGED`
- D3A tag：不创建

## 基线身份

- D2 main merge SHA：`a40a9f8a5728d6d03c127409491a38321540ac99`；
- D2 tag：`hydro-model-02-d2-rc2`，解引用到上述 merge commit；
- D3A base SHA：`a40a9f8a5728d6d03c127409491a38321540ac99`；
- D3A branch：`feature/HYDRO-MODEL-02-D3A-engineering-single-river`；
- D3A engineering candidate：`169c3846e26da373710abd4b271b84804cdb5b52`；
- 最终证据头：以包含本文件的分支最新提交为准。

## 完成门

- [x] PR #11 使用 merge commit 合并；
- [x] D2 main required checks 全绿；
- [x] D2 annotated tag 指向 main merge commit；
- [x] D3A 从该 main 创建；
- [x] D1 capability 语义未修改；
- [x] D3A-1/2/3 capability 独立注册并保存 provenance；
- [x] 未新增公共 v4-lite schema 旁路；
- [x] D3A-1 M1/M2、收敛与 Gate/Pump PASS；
- [x] D3A-2 S1/S2/S3、收敛与 Gate/Pump PASS；
- [x] D3A-3 P1/P2/P3、收敛与不同 Profile Gate/Pump PASS；
- [x] FINAL 6 h synthetic benchmark 的水量、能量、事件、重试和来源身份 PASS；
- [x] 全湿、正向、严格亚临界范围已冻结；
- [x] D1 frozen 与 D2 platform/fault/shipping 回归 PASS；
- [x] RuntimeBuildIdentity 和 Backend/Worker 同镜像来源 PASS；
- [x] Hosted science、Ubuntu/Windows、Frontend/OpenAPI PASS；
- [x] 阶段文档、总报告、限制和 release readiness 完整；
- [x] PR #12 已创建并保持 `NOT MERGED`；
- [x] 不作生产、率定或一般河网声明。

## Hosted evidence

- [`model02` run 33254053757](https://github.com/zj1310426307-stack/dayu-tiangong/actions/runs/33254053757)：SUCCESS；
- [`hydraulic-platform` run 33254053772](https://github.com/zj1310426307-stack/dayu-tiangong/actions/runs/33254053772)：SUCCESS。

## D3B readiness

D3A 的数值与平台门已闭合，可以进入 D3B 真实小型单河闸泵工程验证。D3B 必须补充可追溯的真实断面、床高、糙率依据、闸泵参数、边界过程、运行记录和水位/流量观测，并进行率定、事件复现和误差统计；在此之前不得升级为生产能力声明。
