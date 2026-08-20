# HYDRO-MODEL-02-C 瞬变加固审查

## 审查结论

- C1 受限 moving non-prismatic reference：`GO`。
- C2a 保守 bracketed crossing：`GO`。
- C2b Gate completed-interface：`NO-GO / NOT IMPLEMENTED`。
- 湿干、端点 face、Branch/Junction、后端生产任务链：`NO-GO / NOT RUN`。

## 关键审查点

1. 新行为分别由 `v4-lite-3` 和 `v4-lite-4` 显式选择；旧版未被重解释。
2. C1 API 与 core 双层作用域门一致，对百万米 datum、大 Q/网格尺度采用 `rel_tol=0` 和 ULP 下限，不因数值量级扩大容差。
3. C2a 不在 RK stage 中推进 controller lifecycle；只有可接受守恒状态可以原子提交 latch。
4. result DTO 反向检查命令变化、事件身份、监测 Section、括区间、版本和前/后命令一致性。
5. mesh hash 不包含事件容差；solver-policy hash 使用 v2 domain 并冻结 event policy、容差、细分上限和命令生效语义。
6. 水量 pass 只是必要条件，未用它替代 C1 的 H/Q/能头/收敛门或 C2a 的括区间门。

## 下一步

下一个独立数值切片是 C2b：只对单 Gate、平床棱柱、全湿正向亚临界、fixed opening 实现 completed-interface 能头与左右动量闭合。不与连续事件定位或 Pump Q-H 同时修改，以便失败可归因。
