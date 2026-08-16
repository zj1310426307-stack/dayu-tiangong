# GIS-OPT-2 Step 3 Architecture and Contract Verification

- Date：2026-08-15
- Scope：ADR 与合同冻结；不实现 GIS-OPT-2 runtime
- Authoritative start：远端 `main` / `f72b675e4681823e35cf74219a0721825dca8082`
- Baseline tree：`a9d6750c2e0c7f7834c8bac64acc955d6e7da020`
- Local start：`193ffdfc387521a6169f0afd9a45a2a1f97d889f`（与远端 baseline tree 一致）
- End：由本文件所属 Git commit 元数据和交付说明记录，避免自引用 hash
- Implementation status：NOT IMPLEMENTED

## 1. Deliverables

| File | Purpose | Status |
|---|---|---|
| `docs/adr/ADR-0012-qgis-server-integration.md` | QGIS Server、部署工程、只读角色、安全 Gateway、版本和回滚 | DESIGN FROZEN |
| `docs/adr/ADR-0013-gis-layer-registry.md` | Registry 权威、字段、枚举、Catalog 合并和兼容策略 | DESIGN FROZEN |
| `docs/gis/gis_catalog_contract.md` | 统一 Catalog endpoint、DTO、错误、合并、缓存和测试 | CONTRACT FROZEN |
| `docs/gis/gis_frontend_adapter_contract.md` | Catalog → adapter、状态、身份、迁移和回滚 | CONTRACT FROZEN |
| `docs/gis/qgis_bridge_security_contract.md` | QGIS Bridge IAM、scope、凭据、深链路、issue 和威胁模型 | CONTRACT FROZEN |
| `docs/gis/gis_opt2_step3_verification.md` | 当前验证证据、决策矩阵、风险和下一阶段入口 | THIS RECORD |

## 2. Baseline Facts Revalidated

| Fact | Evidence | Result |
|---|---|---|
| QGIS Desktop 工程是 3.44.13 / EPSG:4490 / 3 group / 14 layer / 3 relation | `qgis/projects/dayu_tiangong_ltr.qgs` + contract tests | CONFIRMED |
| 工程含 4 个 editable staging、10 个 readonly reference/publish | QGS XML | CONFIRMED |
| 工程无 Layout，且 publish.river 重复、缺 3 个现有 publish layer | QGS XML 与 0012 | CONFIRMED |
| 当前无 QGIS Server Compose/Nginx/FastAPI/health/test 路径 | repository search | CONFIRMED |
| GeoServer 当前静态发布 12 层，7 层缓存，Basic WFS 保留 | backend/geoserver bootstrap/verify | CONFIRMED |
| 主地图仍硬编码业务图层、分组、标题、缓存和解析规则 | `CesiumMap.tsx` / `LayerManager` | CONFIRMED |
| `/gis-analysis/layers` 与 `/dgis/catalog` 不是当前主地图统一目录 | routers + frontend call graph | CONFIRMED |
| Alembic 单 head 为 `20260814_0012` | migration/tests | CONFIRMED |
| 12 个 publish 视图可同时包含多个 published Dataset Version | migration/view SQL | CONFIRMED |
| 当前 actor/reviewer/publisher 字段是本地审计，不是统一 IAM | governance schema/docs | CONFIRMED |
| 横断面现合同为 Point geometry + points JSON + station | model/service/validation | CONFIRMED; MUST REMAIN ADDITIVE |

## 3. Architecture Decision Matrix

| 决策 | 已冻结 | 有回滚 | 有安全边界 | 可测试 |
|---|---|---|---|---|
| Server Project strategy | Yes | Yes | Yes | Yes |
| Server DB role | Yes | Yes | Yes | Yes |
| dataset version gateway | Yes | Yes | Yes | Yes |
| Registry ownership | Yes | Yes | Yes | Yes |
| Catalog DTO | Yes | Yes | Yes | Yes |
| legacy API migration | Yes | Yes | Yes | Yes |
| frontend adapters | Yes | Yes | Yes | Yes |
| Bridge identity | Yes | Yes | Yes | Yes |
| basemap SSRF | Yes | Yes | Yes | Yes |
| cross-section compatibility | Yes | Yes | Yes | Yes |

“Yes”表示合同中已明确对应规则和验收方法，不表示运行实现已完成。

### Detailed decisions

| Required decision | Frozen answer | Gate |
|---|---|---|
| Desktop 与 Server 工程关系 | Desktop 唯一人工制图源；Server qgz 确定性生成且不可人工编辑 | PASS |
| 是否直接部署 Desktop 工程 | No | PASS |
| 是否维护第二个人工 Server 工程 | No | PASS |
| QGIS Server DB role | 独立 `dayu_qgis_server`，只读 publish allowlist | PASS |
| 是否复用 GeoServer/backend/editor/publisher role | No | PASS |
| 浏览器如何访问 QGIS Server | 同源 `/qgis-server/wms` → FastAPI safe Gateway → 私网 QGIS Server | PASS |
| MAP/FILTER 所有者 | MAP 禁止；FILTER 仅服务端由 validated integer + Registry 构造 | PASS |
| 初期 QGIS Server services | WMS subset；Print 默认禁用；WFS/WMTS/WCS/OAPIF 不进核心 | PASS |
| Catalog 权威 | Registry + QGIS manifest + runtime + Dataset Version，由后端唯一合并 | PASS |
| Catalog 是否实时解析 GetProjectSettings | No；只用于构建/受控诊断 | PASS |
| 业务 layer identity | `layer_key`；QGIS short name 为服务身份；QGIS layer id 非公开 | PASS |
| 前端扩展方式 | service/render adapter，不再按业务 key 编码 | PASS |
| Feature identity | `{layer_key, feature_id, dataset_version_id}` | PASS |
| 外部底图 | 首期仅预登记 allowlist；不接受任意 URL | PASS |
| QGIS Bridge 身份 | 生产 IAM token；当前 actor 明确 unverified | PASS |
| 无 IAM 时生产 mutation | 全部拒绝 | PASS |
| severity 映射 | error/warning/info → ERROR/WARNING/INFO，无 CRITICAL | PASS |
| GeoServer | 保留 legacy/fallback，不在本阶段切换或退役 | PASS |
| 现有横断面 schema | 后续 only-additive，不改义、不破坏模型路径 | PASS |

## 4. Security Assertions

- Catalog DTO 不包含 schema/relation、internal URL、project path、MAP、FILTER、SQL、DSN、credential。
- QGIS Server 不公开宿主端口，不读取 staging，不使用 editor/backend/owner/publisher/GeoServer role。
- Gateway 对 operation、layer、version、尺寸、CRS、格式和参数实行 allowlist；未知参数拒绝。
- Registry 不存任意 SQL、QGIS XML、运行对象、文件路径或任意 URL。
- Bridge 不持有数据库或服务管理员凭据；无生产 IAM 时治理写操作 fail closed。
- Dataset Version 状态、Registry active 和 runtime health 必须同时满足，任何单项不能替代其他门禁。
- GeoServer 作为 rollback 路径保留，不以扩大 DB 权限处理 QGIS Server 故障。

## 5. Step 4 Entry Gates

| Gate | Evidence in Step 3 | Status |
|---|---|---|
| QGIS Server 工程来源与构建策略唯一 | ADR-0012 Option C | READY |
| 独立只读角色和权限矩阵明确 | ADR-0012 §5 | READY |
| Gateway 公开/内部路径及参数门禁明确 | ADR-0012 §4/§6 | READY |
| Print、GetProjectSettings、WFS/WMTS/WCS 边界明确 | ADR-0012 §3/§8 | READY |
| Registry 字段、枚举、禁止字段和合并优先级明确 | ADR-0013 | READY |
| Catalog DTO 和结构化错误明确 | Catalog Contract | READY |
| 前端 adapter/state/identity/rollback 明确 | Frontend Adapter Contract | READY |
| Bridge IAM/credential/deep link/issue 规则明确 | Bridge Security Contract | READY |
| GeoServer fallback 保留 | ADR-0012 / frontend migration | READY |
| 设计交付不越界实现 runtime | Git diff + verification | PASS — repo 仅新增六份指定文档 |
| 基线回归无退化 | command evidence below | PASS |

“READY”只表示设计输入已冻结，不表示相应组件已实现或部署。

## 6. Verification Commands and Results

以下结果取自本轮真实执行：

| Check | Command | Result |
|---|---|---|
| Full backend/repository offline | `$env:PYTHONPATH='backend;.'; backend\.venv\Scripts\python.exe -m pytest -q` | PASS — 170 passed, 67 skipped |
| QGIS project contract | `QGIS_PROCESS_EXECUTABLE=<project QGIS 3.44.13 launcher>; ... pytest -q tests/test_qgis_project_contract.py` | PASS — 11 passed，包含原生 `qgis_process --version` smoke |
| Frontend typecheck | `npm.cmd run typecheck` in `frontend` | PASS |
| Frontend production build | `npm.cmd run build` in `frontend` | PASS — 5100 modules，只有既有 large-chunk warning |
| Compose static config | `docker compose ... config --quiet` | NOT RUN — 当前 shell 无 Docker CLI，Engine 不可从本轮验证环境访问；纯文档交付不阻塞 |
| Diff whitespace | `git diff --cached --check` | PASS |
| Deliverable scope | exact six repo docs, exclude user Phase 1 report | PASS |
| QGIS Server runtime | intentionally not started | NOT RUN — OUT OF STEP 3 SCOPE |
| QGIS GUI/manual | no project mutation required | NOT RUN — OUT OF STEP 3 SCOPE |

## 7. Risk Register

| Priority | Risk | Control / Next evidence |
|---|---|---|
| BLOCKER | Server project accidentally includes staging or duplicate/unknown layer | Deterministic builder + manifest contract + native QGIS readback tests |
| BLOCKER | Dataset version filter can be controlled or omitted by browser | Safe Gateway owns FILTER; MAP/raw FILTER rejected; two-version isolation tests |
| HIGH | QGIS Server role can read core/staging or write DB | Exact allowlist grants + real positive/negative permission tests |
| HIGH | Catalog, manifest and runtime revision drift | canonical revision, health join, fail closed, shadow diff |
| HIGH | Frontend double-renders legacy and Catalog layers | single owner per layer + phased allowlist + screenshot/traffic tests |
| HIGH | Print mixes versions or leaks data/path | disabled by default; layout/version/security gate before enable |
| HIGH | Bridge self-reported actor used as production identity | production IAM-derived identity; mutation denied without IAM |
| MEDIUM | QGIS WMS performance lacks shared tile cache | capacity tests; retain GeoServer/GeoWebCache and Martin |
| MEDIUM | Existing QGIS 14 layers and GeoServer 12 layers differ | initial Registry import report; explicit mapping, no silent guess |
| MEDIUM | Basemap URL registration becomes SSRF path | initial allowlist only; future separate security workflow |
| LOW | Canonical qgz differs by ZIP timestamp | compare canonical XML + manifest hash, not binary ZIP alone |

## 8. Explicitly Not Implemented in Step 3

- QGIS Server image、Compose service、Nginx route、FastAPI Gateway 和健康检查；
- Server qgz/manifest builder、Server project、Print layout 和字体包；
- `dayu_qgis_server` 数据库角色；
- GIS Layer Registry migration、seed、CRUD 或 admin UI；
- unified Catalog API/OpenAPI/generated client；
- frontend adapters 或主地图切换；
- QGIS Bridge plugin 和统一 IAM；
- GeoServer 退役或既有 12 层切换；
- 横断面 schema、治理状态机、QGIS Desktop 主工程和业务数据修改。

## 9. Recommended Next Phase

全部 Step 3 gate 和本轮基线测试通过后，只推荐启动 `GIS-OPT-2A1`：QGIS Server deployment-project builder + contract tests。A1 只实现确定性 Server project builder、canonical manifest 和静态/native QGIS readback 门禁；不启动 QGIS Server、不切前端主路径。

后续仅作为路线图，不得描述为已实现：

```text
GIS-OPT-2A2  QGIS Server read-only runtime + same-origin gateway + health
GIS-OPT-2B1  gis_layer_registry migration + seed + validation
GIS-OPT-2B2  /api/v1/gis/catalog backend implementation
GIS-OPT-2C   frontend shadow catalog + adapter runtime
GIS-OPT-2D   frontend cutover and hardcode removal
GIS-OPT-2E   QGIS Bridge read-only panel
GIS-OPT-2F   QGIS Bridge validation / issue workflow
GIS-OPT-2G   cross-section additive spatial model
```

## 10. References

- `docs/review/GIS-OPT-2_Baseline_Audit.md`
- `docs/adr/ADR-0012-qgis-server-integration.md`
- `docs/adr/ADR-0013-gis-layer-registry.md`
- `docs/gis/gis_catalog_contract.md`
- `docs/gis/gis_frontend_adapter_contract.md`
- `docs/gis/qgis_bridge_security_contract.md`
- [QGIS Server 3.44 configuration](https://docs.qgis.org/3.44/en/docs/server_manual/config.html)
- [QGIS Server 3.44 WMS service](https://docs.qgis.org/3.44/en/docs/server_manual/services/wms.html)
