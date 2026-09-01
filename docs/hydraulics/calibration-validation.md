# 率定与独立验证

率定只生成候选输入覆盖，不直接修改权威断面或粗糙率记录。当前支持手工候选和有上限的笛卡尔参数扫描；首个生产参数是显式 Cross Section group 的 Manning n，任务快照记录 group、目标 section 和采用值。候选总数超过 `max_runs` 时在排队前拒绝。

## 指标和对齐

Observed 与 Simulated 在不移动观测时刻的前提下按明确策略对齐：exact、interpolation 或 nearest-with-tolerance。只有 GOOD 观测进入指标，MISSING/REJECTED 不变为零。H 与 Q 分开计算单位一致的 MAE、RMSE、Bias、NSE、R²、峰值误差、峰现时间误差、有效样本数和覆盖率。

正式率定/验证不接受调用方提交的 metrics 作为状态依据。请求必须给出已导入 `observation_series_id`、明确的 `cross_section_id`、经审核的最大桩号距离和时间对齐方法；后端核对 Dataset/Branch/chainage/水位基准后，从持久化观测与不可变任务断面结果重新计算。率定扫描创建后不允许更换该映射，防止看到结果后选点。

候选排序使用用户声明的权重和可读键，例如 `water_level.rmse` 或 `discharge.nse`。不满足样本/覆盖率或缺少目标指标的候选不参与合格排序。选中候选必须由专业人员记录接受人、原因和项目 Acceptance Criteria；后端使用已持久化的候选 metrics 与任务水量平衡诊断重新评价，不接受前端自报的“已达标”布尔值。接受操作会基于候选 override 创建一个新的冻结快照、重建生产 QA 封套并交回现有 Job Manager 执行；候选任务本身不会被偷换为正式运行。

## 验证独立性

Calibration 和 Validation 均保存 dataset ID、event ID、station IDs、含时区起止时间和角色。完全复用率定资料会返回 `VALIDATION_DATA_REUSED`；时间留出会明确标为 temporal holdout，不冒充独立洪水事件。只有不重叠的不同事件才能满足 independent evidence。

验收限值由项目填写，可包括 H/Q RMSE、峰值相对误差、峰现时间、NSE、R²、观测覆盖率和质量平衡相对误差。正式验证只读取晋升后正式重跑任务的已持久化水量平衡诊断；如果请求中同时声明该值，必须与服务端证据严格一致。软件门全部通过时状态最多进入 `VALIDATED`，仍要求专业批准后才能成为 `PRODUCTION_APPROVED`。

```text
DRAFT → QA_PASSED → CALIBRATED → VALIDATED → PRODUCTION_APPROVED
```

每次运行绑定 Dataset Version、Simulation Case、不可变模型快照、Engine/Runtime provenance、率定/验证数据窗口和结果哈希，历史结果不会因后续参数晋级而改写。
