# HYDRO-MODEL-02-C 瞬变加固审查

## 审查结论

- C1 受限 moving non-prismatic reference：`GO`。
- C2a 保守 bracketed crossing：`GO`。
- C2b 固定 Gate completed-interface 限定子集：`GO`。
- 湿干、端点 face、Branch/Junction、后端生产任务链：`NO-GO / NOT RUN`。

## 关键审查点

1. 新行为分别由 `v4-lite-3` 和 `v4-lite-4` 显式选择；旧版未被重解释。
2. C1 API 与 core 双层作用域门一致，对百万米 datum、大 Q/网格尺度采用 `rel_tol=0` 和 ULP 下限，不因数值量级扩大容差。
3. C2a 不在 RK stage 中推进 controller lifecycle；只有可接受守恒状态可以原子提交 latch。
4. result DTO 反向检查命令变化、事件身份、监测 Section、括区间、版本和前/后命令一致性。
5. mesh hash 不包含事件容差；solver-policy hash 使用 v2 domain 并冻结 event policy、容差、细分上限和命令生效语义。
6. 水量 pass 只是必要条件，未用它替代 C1 的 H/Q/能头/收敛门或 C2a 的括区间门。
7. C2b 只由 `v4-lite-5` 显式选择；旧 Gate 仍走冻结 mass-only 路径。
8. completed-interface 每个 RK stage 同时冻结 `Q`、孔口损失、能头残差、两侧 `A/T/I1`、左右动量和结构反力；结果 DTO 会独立复算而不是信任状态标签。
9. C2b API 与 core 双层限制单 Gate、fixed opening、平床同断面、全湿正向亚临界、零摩阻、特征边界且无 Pump；越界不回退。

## 下一步

后续必须继续拆分：先评审 C2a 事件定位与 C2b Gate 物理的组合门，再单独处理湿干、显式端点断面和 Pump Q-H。v4 后端任务链与真实工程率定仍为 `NO-GO`。
