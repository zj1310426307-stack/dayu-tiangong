# GIS Frontend Adapter Contract

- Contract status：Frozen for GIS-OPT-2 implementation
- Date：2026-08-15
- Decision baseline：远端 `main` / `f72b675e4681823e35cf74219a0721825dca8082`
- Runtime status：NOT IMPLEMENTED

## 1. Goal

主地图从“Cesium 组件枚举业务图层”迁移到“Catalog 驱动、协议 adapter 执行”。迁移后，增加一个已支持服务模式的业务图层只需要 Registry/QGIS 配置和 Catalog 验证，不再修改 `CesiumMap.tsx`、`GisPage.tsx` 或 `LayerManager.tsx` 的业务 key 清单。

本合同只冻结职责、状态和测试；本阶段不改 React/Cesium 运行代码。

## 2. Target Flow

```text
GET /api/v1/gis/catalog?dataset_version_id=N
                    ↓
Catalog schema validation + revision guard
                    ↓
LayerRuntime normalization
                    ↓
AdapterRegistry[service_mode/render_mode]
                    ↓
QGIS WMS / legacy GeoServer / Martin / TiTiler /
FastAPI dynamic / 3D Tiles
                    ↓
Cesium resources + normalized feature selection
```

`LayerManager` 只显示 Catalog group/layer 和当前 UI 状态；`CesiumMap` 只承载地图生命周期与 adapter 资源，不理解 `river/gate/pump/...` 业务枚举。

## 3. LayerRuntime

前端通过 generated OpenAPI DTO 转成内部只读模型，概念接口如下：

```ts
type LayerRuntime = {
  identity: {
    layerKey: string;
    datasetVersionId: number;
  };
  presentation: {
    title: string;
    groupKey: string;
    order: number;
    visible: boolean;
    opacity: number;
    minScale?: number;
    maxScale?: number;
  };
  service: CatalogService;
  renderMode: CatalogRenderMode;
  capabilities: LayerCapabilities;
  legend?: LegendDescriptor;
  identify: IdentifyDescriptor;
};
```

该示例是设计合同，不是要求本轮创建代码。转换函数必须穷尽 enum；未知模式返回可诊断的 unsupported 状态，不请求 Catalog 提供的未知 endpoint。

## 4. Adapter Registry

Adapter 由 `service_mode + render_mode` 选择，不由 layer key 选择。

```ts
interface GisLayerAdapter {
  create(ctx: MapContext, layer: LayerRuntime): Promise<AdapterHandle>;
  update(handle: AdapterHandle, layer: LayerRuntime): Promise<void>;
  setVisible(handle: AdapterHandle, visible: boolean): void;
  setOpacity(handle: AdapterHandle, opacity: number): void;
  identify?(handle: AdapterHandle, input: IdentifyInput): Promise<FeatureIdentity[]>;
  getLegend?(layer: LayerRuntime): Promise<LegendModel>;
  destroy(handle: AdapterHandle): void;
}
```

必须提供的 adapter 合同：

| Adapter | service/render | 初始职责 |
|---|---|---|
| `QgisWmsAdapter` | QGIS_WMS + RASTER_WMS | 调同源安全 Gateway；只传平台参数，不拼 FILTER/MAP |
| `LegacyGeoServerWmsAdapter` | GEOSERVER_WMS_LEGACY + RASTER_WMS/RASTER_TILE | 保持当前 WMS/WMTS 兼容和回滚 |
| `MartinMvtAdapter` | MARTIN_MVT + VECTOR_TILE | 版本化 MVT template、样式与 pick 归一化 |
| `TiTilerAdapter` | TITILER + RASTER_TILE | 只加载已登记 asset/tile template |
| `CesiumDynamicAdapter` | FASTAPI/CESIUM_DYNAMIC + DYNAMIC_PRIMITIVE | 复用时序、仿真、设施状态 API |
| `ThreeDTilesAdapter` | THREE_D_TILES + THREE_D | 加载登记 tileset 并释放资源 |

每个 adapter 必须保证 create/update/destroy 对称；Dataset Version 切换、Catalog revision 变化、页面卸载时不得遗留 imagery layer、primitive、datasource、event handler 或网络请求。

## 5. What May Remain Static

前端允许静态维护：

- `service_mode/render_mode → adapter` 的协议映射；
- 每种协议的安全参数编码、错误归一化和资源生命周期；
- 通用 UI 组件、图标和状态文案；
- 合同版本兼容器和 feature flag 名称。

前端禁止继续静态维护：

- 业务 `layer_key`、标题、分组、排序、默认显隐、透明度；
- 哪些业务层使用 WMS/WMTS/MVT/COG/3D；
- GeoServer/QGIS qualified layer 名；
- 缓存层业务清单；
- `dataset_version_id` 对应的 FILTER/CQL 表达式；
- 通过正则从 Cesium asset key 反推业务身份；
- 外部底图 URL 或 credential。

## 6. State Semantics

状态必须分层，禁止把不同语义压成一个 `status`：

| 状态 | 所有者 | 示例 |
|---|---|---|
| Dataset lifecycle | 后端治理 | published/retired |
| Catalog availability | Catalog | healthy/unsupported/revision_mismatch |
| Adapter lifecycle | 前端 adapter | idle/loading/ready/error/disposed |
| Layer UI state | 前端 | visible/opacity/selected |
| Feature dynamic state | 时序/仿真 API | water level、gate opening |

Dataset Version 切换时按顺序执行：

1. 标记旧 Catalog 请求过期并取消可取消请求；
2. 清空当前 feature selection 和不兼容详情；
3. 获取并验证新 Catalog；
4. 按稳定 layer key 做 adapter diff；
5. 先 destroy 被删除/服务模式改变/版本不可复用的 handle；
6. create/update 新资源；
7. 只在 revision 一致后提交 UI ready。

旧请求迟到不得覆盖新版本状态。

## 6.1 普通新增图层验收

未来若新增 `levee`，且复用 `QGIS_WMS + RASTER_WMS`，允许修改数据库/publish view、QGIS Project、Registry seed/admin data，以及确有需要的 backend entity API；不得为了让它出现在图层树而修改 `CesiumMap.tsx`、`GisPage.tsx` 或 `LayerManager.tsx`。若仍需修改这三个组件的业务枚举，GIS Catalog 化验收失败。

## 7. Visibility and Persistence

- Catalog 的 `visible/opacity` 是初始值；
- 用户会话覆盖只按 `{catalog schema major, project_key, layer_key}` 保存；
- layer inactive/删除时清理覆盖；
- 服务或 Dataset Version 不可用时，显示禁用和明确原因，不用“隐藏”伪装成功；
- 不在 localStorage 保存 endpoint、token、FILTER、内部资源 id 或整份 Catalog。

## 8. Feature Identity and Deep Link

所有 adapter 把 pick/FeatureInfo 归一化为：

```ts
type FeatureIdentity = {
  layerKey: string;
  featureId: string;
  datasetVersionId: number;
};
```

深链路统一为：

```text
/gis?datasetVersionId={id}&selectedAsset={percent-encoded-layer_key}:{percent-encoded-feature_id}
```

构建与解析必须使用单一安全 helper，并验证：

- version 为正整数；
- layerKey 出现在当前 Catalog 且可 identify；
- featureId 符合该 layer 的 opaque id 长度/字符上限；
- 返回记录的 dataset_version_id 与当前版本一致。

禁止继续依赖固定 asset key 正则或展示标题解析。QGIS `qgis_layer_id`、GeoServer fid 和 Cesium entity id 不直接成为跨系统身份。

## 9. QGIS WMS Adapter

`QgisWmsAdapter` 只调用 `/qgis-server/wms`，参数采用 ADR-0012 的平台字段。它不得：

- 提交 MAP、FILTER、SQL、datasource、external URL；
- 自行构造 `dataset_version_id` CQL/FILTER；
-直接访问 QGIS Server 容器、端口或 FCGI；
- 把 GetProjectSettings 当 Catalog；
- 绕过 Catalog 的 capabilities 启用 Print 或 FeatureInfo。

GetFeatureInfo 返回先经后端规范化；adapter 不信任任意上游属性成为详情 API 路由。

## 10. Error Contract

Adapter 错误至少归一化为：

```text
CATALOG_UNAVAILABLE
CATALOG_REVISION_MISMATCH
UNSUPPORTED_ADAPTER
LAYER_UNAVAILABLE
VERSION_NOT_PUBLIC
UPSTREAM_TIMEOUT
UPSTREAM_INVALID_RESPONSE
IDENTITY_MISMATCH
```

保留后端 `ApiError.status/code/context`，但 UI 不显示 DSN、内部 URL、stack 或上游响应全文。单层失败不应销毁所有已健康图层；Catalog/版本整体失败则保持旧地图只读并明确“数据版本未切换成功”。

## 11. Migration Strategy

### Phase 0 — legacy

保持当前 `CesiumMap` 静态清单和 GeoServer 路径，建立行为快照。

### Phase 1 — shadow

获取 Catalog、创建 LayerRuntime 并比较，不创建第二套可见资源。记录 layer/group/order/service/capability 差异。

### Phase 2 — adapter opt-in

按 group/layer allowlist 切换个别图层；同一 layer 只能有一个可见所有者，避免双绘制。

### Phase 3 — catalog default

Catalog 驱动全部支持层；保留 legacy feature flag 和旧端点观察期。

### Phase 4 — cleanup

只有回滚窗口、性能、视觉、选择、版本隔离测试全部通过后，才删除业务硬编码和已弃用端点。

## 12. Acceptance Gates

- [ ] 新增 Registry 中的已支持 layer 不修改三个主地图组件的业务枚举；
- [ ] adapter enum 穷尽且未知模式 fail closed；
- [ ] create/update/destroy 与版本快速切换无资源泄漏；
- [ ] layer/group/title/order/visible/opacity 来自 Catalog；
- [ ] QGIS WMS 请求不含浏览器构造的 FILTER/MAP；
- [ ] 所有选择都携带 layer/version identity，跨版本结果被拒绝；
- [ ] generated OpenAPI client 与后端合同同步；
- [ ] shadow 差异和视觉回归有可审查记录；
- [ ] legacy feature flag 可立即回滚；
- [ ] Martin、TiTiler、动态设施和 3D Tiles 现有能力不退化。

## 13. Testing Matrix

| 层级 | 必测内容 |
|---|---|
| Unit | Catalog → LayerRuntime、enum 穷尽、深链路、state reducer、错误归一化 |
| Adapter | URL/参数编码、create/update/destroy、abort、opacity/visibility、identity |
| Contract | generated DTO、unknown enum、structured ApiError、禁止字段 |
| Integration | 两个 published 版本切换、快速切换竞态、单层失败隔离、legacy rollback |
| Visual | 图层顺序、样式、标注、透明度、比例尺、重复图层、截图差异 |
| Security | FILTER/MAP/external URL 注入、内部地址泄露、恶意 FeatureInfo identity |

## 14. Explicit Non-goals

- 本文不实现 React/Cesium adapter；
- 不删除当前业务静态清单；
- 不改变 QGIS 工程、GeoServer、Martin 或 TiTiler；
- 不开放 Web 端空间编辑；
- 不把 QGIS Desktop 插件和浏览器前端合并为同一状态机。
