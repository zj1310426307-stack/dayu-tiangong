# 持续优化 01 发布说明

发布日期：2026-08-24

状态：功能分支 `608d4a653990ed17eefb42ec71f5d28e1fb06e15` 已上传，并以普通双亲合并提交 `b58207ba9195e001c8e535b990dc0d2c563a12a5` 合入 `main`

## 新增

- `app.files` 本地文件基础模块：统一存储根、命名空间、路径边界、有界读取和原子写入；
- `DAYU_STORAGE_ROOT` 本地配置与 `DAYU_STORAGE_HOST_PATH` Compose 宿主挂载配置；
- 三类任务监控列表的可选 `dataset_version_id` 查询；
- 文件边界、任务过滤、生成客户端和浏览器夹具契约测试；
- 现状审查、Backlog、执行计划、兼容、验证和发布文档。

## 修改

- AI、普通导入、DGIS 转换、水动力上传统一使用文件读取边界；
- conversion 失败清理，GDAL/AI 报告采用原子发布，AI 数据库失败执行文件补偿；
- backend/worker 共享固定容器存储根，backend 宿主端口仅绑定本机；
- Nginx API 总门调整为 102 MiB，backend 镜像加入水动力模板；
- 水动力、优化、调度页面按当前 Dataset Version 查询并防止迟到响应覆盖；
- 生成客户端保留旧 baseUrl 签名兼容；
- 水动力、数据中心、调度图表修复 StrictMode 异步初始化生命周期；
- 实时引擎 UI 夹具补齐任务列表、结果和计划查询。

## 未删除

没有删除旧 endpoint、数据库字段、求解器、模型输入版本、历史结果或 GIS 主链。

## 能力边界

- 文件能力是“入口与本地存储基础”，不是完整文件管理；
- 任务能力是“监控列表过滤”，不是授权或跨版本安全隔离；
- 本地 bind mount 不是集群共享存储；
- OpenAPI 仍没有 security scheme，所有 mutation 不适合公网生产；
- GIS、Celery、数值求解语义与数据库结构未改变；
- v4 后端任务链、完整 Gate/Pump 强耦合、湿干、端点断面和真实工程率定仍按既有 `NO-GO` 管理。

## 发布前检查

1. 备份 `.env` 和存储目录；
2. 同步发布后端与生成客户端；
3. 检查 backend/worker 目录权限和同一挂载；
4. 在有 Docker 的环境重跑 Compose、模板和真实代理上传门；
5. 在真实 PostGIS 中验证多版本列表；
6. IAM 未完成时保持公网控制面关闭。

兼容、迁移和回滚详见 `docs/migration/COMPATIBILITY_AND_MIGRATION.md`；验证证据详见 `docs/verification/OPTIMIZATION_VERIFICATION_REPORT.md`。

## GitHub 发布记录

- 原 `main`：`07948e663fedc220d8ca6cdbdb34fd3fb4e2beee`；
- 功能分支：`feature/continuous-optimization-01@608d4a653990ed17eefb42ec71f5d28e1fb06e15`；
- 合并提交：`b58207ba9195e001c8e535b990dc0d2c563a12a5`；
- 合并提交两父依次为原 `main` 与功能分支 HEAD，Tree 与功能分支完全一致；
- 发布未使用强制更新，功能分支保留；
- 默认 Git HTTPS 节点不可达，发布通过本机 Git Credential Manager 与 GitHub 官方 Git Data API 完成；44 个唯一 Blob、4 个功能 Tree/Commit 及合并 Commit 均与本地 SHA 精确一致。
