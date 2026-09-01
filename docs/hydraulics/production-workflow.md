# 一维水动力生产工作流

Production-04 把现有统一 Hydraulic Domain、MASCARET Adapter、不可变任务和 GIS 结果扩展为一条审计链：

```text
Project/Data → Preview/Issues/Import → QA → Model/Scenario
→ Production Run → Calibration → Independent Validation
→ External Compare → Result Products → Professional Approval
```

## 操作入口

前端 `/hydraulic/production` 包含 Data、QA、Calibration、Validation、Compare 和 Results。原有 `/data-center/hydraulic` 继续管理河网/断面权威数据，`/hydraulic/config|tasks|results` 继续承担普通 Standard 1D 任务。正式 Production Run 只能使用 `/api/v1/hydraulic/production/runs`，不能把普通任务页面顺序当成生产状态。

关键 API 采用小操作而非 mega endpoint：

- `/capabilities`、`/qa/evaluate`、`/metrics/evaluate`
- `/calibration/sweeps/plan|create`、`/calibration/candidates/rank`、`/calibration/runs`、`/calibration/runs/{id}/accept`
- `/validation/independence`、`/validation/acceptance`、`/validation/runs`
- `/time-series/preview`、`/observations/import`
- `/external-results/preview|import|compare`
- `/products/generate|commit|export.csv|export.xlsx|export.geojson`
- `/runs`、`/runs/{id}/approve`、`/audit`、`/acceptance-manifest`

前端只能调用生成客户端；数据库访问、QA、状态机、导入重解析、参数排序、验收和成果计算都由后端拥有。Worker 只从哈希校验后的冻结模型执行外部 MASCARET。

## 结果产品

统一结果生成 maximum H/depth/Q/V 及峰现时间、水位纵剖面、Baseline vs Project 的精确时刻 ΔH、最大壅水和超过项目阈值的连续一维区段、Key Section Table 以及事实 GeoJSON。缺失岸顶/河底/几何保持 null。CSV、XLSX 和 GeoJSON 共享同一产品对象；XLSX 按现有数据动态创建 Summary、Max Results、Longitudinal Profile、Scenario Compare、Afflux Reaches 和 Key Sections。

## 可追溯性

迁移 `20260902_0026` 新增 mapping profile、observation series、external result、production run、calibration run、validation assessment、result product 和 production audit event。文件保留来源哈希，运行保留模型快照哈希与 Engine/Runtime provenance，Worker 成功持久化时同步实际构建身份、结果 schema、记录数和水量平衡诊断，产品保留内容哈希。`dayu_backend` 对审计表只有 SELECT/INSERT 权限。

Acceptance Manifest 是 UTF-8、键排序的规范 JSON，包含 project/model、QA、Engine、Runtime、Calibration、Validation、Comparison、Run、Metrics 和 result hashes。生成 manifest 不等于专业批准。

## 当前真实数据门

受控资料仅有 3 个不连通 Branch、40 个断面和 2,069 个剖面点，缺少权威 Boundary、Observed H/Q、独立验证事件、结构完整参数、控制点和 MIKE11 exported result。因此 P01–P06 只证明软件框架，R01–R07 均为 `DATA_NOT_AVAILABLE`，最终状态应为 `FRAMEWORK_READY_DATA_REQUIRED`。

真实资料进入后依次执行：确认 CRS/垂直基准和线性索引；导入河网/断面/Boundary/Observation/Structure；通过 QA；运行真实 MASCARET；只用率定资料选择候选；用独立事件验证；若有合法 MIKE11 结果再做交叉对比；生成并签署工程成果。
