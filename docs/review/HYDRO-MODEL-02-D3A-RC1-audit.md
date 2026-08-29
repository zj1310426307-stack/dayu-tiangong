# HYDRO-MODEL-02-D3A-RC1 实施审计

- 日期：2026-08-30
- 分支：`feature/HYDRO-MODEL-02-D3A-engineering-single-river`
- PR：[#12](https://github.com/zj1310426307-stack/dayu-tiangong/pull/12)，保持 `OPEN / NOT MERGED`
- RC1 base：`0306e7b0388b4debffb6c8c66adfd962e99c0553`
- 基线审计提交：`25446cf`
- 方案文件 SHA-256：`ddc873827d5db3ded5b039ff63c7e00a4ef025a0b93240822cd88a9fc73ac1dc`

## 审查结论

RC1 已在代码和本地科学证据上关闭独立审查提出的三项 P0 缺口：动态运行包络、FINAL 空间/时间收敛、Python 3.12 发布镜像科学门；摩阻预测器同时关闭 P1 性能缺口。当前判定为：

```text
LOCAL IMPLEMENTATION: PASS
LOCAL SCIENCE: PASS
HOSTED RC1 CHECKS: PASS
MAIN REQUIRED CHECKS: 11 (D3A shipping science ADDED)
PR #12: NOT MERGED
D3A TAG: NOT CREATED
```

Implementation head `8da24aa12f05f9e13731c85b69ed864961c748dd` 的 push/PR 四项 hosted workflows 均成功；发布镜像 artifact 已核对，精确 check context 已在首次成功后加入 main 保护。机器门闭合不替代独立审查，也不构成合并或打 tag 授权。

## 变更追踪

| 提交 | 作用 |
| --- | --- |
| `e26ce68` | 动态运行包络、关闭闸门面几何一致性、摩阻时间步预测器、结果/持久化门 |
| `4a7e4ec` | 运行包络和 Backend 防伪造测试 |
| `2321c4c` | 物理坐标一致的 FINAL 60/70/80 + fine CFL/2 收敛矩阵 |
| `d7593a5` | `D3A shipping science` Python 3.12 发布镜像门 |
| `0798712` | OpenAPI 类型、生成客户端和前端诊断展示 |

## 关键发现

关闭 Gate 在 `hydraulic-function-linear-face-v1` 路径上曾使用 cell pressure moment，而相邻非棱柱 geometry source 使用 face pressure moment；二者不一致会在闸门两侧生成约 `1e-3–1e-2 m3/s` 的虚假负 stage flow。RC1 令关闭 Gate 与 geometry source 共用同一个 face geometry。修复后 FINAL 的最小 Q 为舍入量级（最坏 `-1.77e-15 m3/s`），没有裁剪 Q、depth 或 Fr。

## 兼容性

- D1 不绑定 `RuntimeEnvelope v1`，时间步路径未 retro-fit；
- D1/旧结果 DTO 在可选字段缺失时保持原序列化形状；
- D3A Registry、solver policy、validation policy 和结果 provenance 显式包含包络身份；
- 未新增或修改 Alembic 迁移，`0023` 保持不可变；
- D2 shipping runtime 继续负责 PostGIS/Redis/Backend/Worker/Artifact 平台 E2E。

基线详情见 [RC1 baseline audit](./HYDRO-MODEL-02-D3A-RC1-baseline-audit.md)。
