// 从运行中的 FastAPI OpenAPI 文档生成前端类型与唯一 API 客户端入口。
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const outputDirectory = resolve(scriptDirectory, '../src/api/generated');
const outputFile = resolve(outputDirectory, 'client.ts');
const schemaUrl = process.env.OPENAPI_URL ?? 'http://127.0.0.1:8001/openapi.json';

function toType(schema = {}) {
  if (Object.keys(schema).length === 0) return 'unknown';
  if (schema.$ref) return schema.$ref.split('/').at(-1);
  if (Object.hasOwn(schema, 'const')) return JSON.stringify(schema.const);
  if (schema.enum) return schema.enum.map((value) => JSON.stringify(value)).join(' | ');
  if (schema.anyOf) return [...new Set(schema.anyOf.map(toType))].join(' | ');
  if (schema.oneOf) return [...new Set(schema.oneOf.map(toType))].join(' | ');
  if (schema.allOf) return schema.allOf.map(toType).join(' & ');
  if (schema.type === 'array') return `Array<${toType(schema.items)}>`;
  if (schema.type === 'object') {
    return schema.additionalProperties ? `Record<string, ${toType(schema.additionalProperties)}>` : 'Record<string, unknown>';
  }
  if (schema.type === 'integer' || schema.type === 'number') return 'number';
  if (schema.type === 'boolean') return 'boolean';
  if (schema.type === 'null') return 'null';
  return 'string';
}

function renderInterface(name, schema) {
  const required = new Set(schema.required ?? []);
  const fields = Object.entries(schema.properties ?? {}).map(
    ([key, value]) => `  ${JSON.stringify(key)}${required.has(key) ? '' : '?'}: ${toType(value)};`,
  );
  return `export interface ${name} {\n${fields.join('\n')}\n}`;
}

const response = await fetch(schemaUrl);
if (!response.ok) throw new Error(`无法读取 OpenAPI：${response.status} ${response.statusText}`);
const openapi = await response.json();
const schemas = openapi.components?.schemas ?? {};

const requiredPaths = [
  '/api/v1/gis/rivers', '/api/v1/gis/interaction-frame', '/api/v1/rivers', '/api/v1/cross-sections',
  '/api/v1/gates', '/api/v1/pumps', '/api/v1/import/excel',
  '/api/v1/validation/run', '/api/v1/model-data/dataset-versions',
  '/api/v1/model-data/simulation-cases/{case_id}/input',
  '/api/v1/model/tasks', '/api/v1/model/tasks/{task_id}/run',
  '/api/v1/model/tasks/{task_id}', '/api/v1/model/results/{task_id}',
  '/api/v1/model/tasks/{task_id}/enqueue', '/api/v1/model/tasks/{task_id}/cancel',
  '/api/v1/model/tasks/{task_id}/retry', '/api/v1/model/tasks/{task_id}/snapshot',
  '/api/v1/dispatch/plans', '/api/v1/dispatch/plans/{plan_id}',
  '/api/v1/dispatch/plans/{plan_id}/actions', '/api/v1/dispatch/plans/{plan_id}/rules',
  '/api/v1/dispatch/plans/{plan_id}/runs', '/api/v1/dispatch/runs',
  '/api/v1/dispatch/runs/{run_id}', '/api/v1/dispatch/runs/{run_id}/comparison',
  '/api/v1/optimization/tasks', '/api/v1/optimization/tasks/{task_id}',
  '/api/v1/optimization/tasks/{task_id}/run',
  '/api/v1/optimization/tasks/{task_id}/candidates',
  '/api/v1/optimization/tasks/{task_id}/pareto',
  '/api/v1/optimization/tasks/{task_id}/recommendation',
  '/api/v1/ai/chat', '/api/v1/ai/knowledge/search',
  '/api/v1/ai/knowledge/documents', '/api/v1/ai/report/generate',
  '/api/v1/ai/tools/logs',
  '/api/v1/gis/geoserver/health', '/api/v1/gis/geoserver/layers',
  '/api/v1/gis/geoserver/config',
  '/api/v1/gis-analysis/layers', '/api/v1/gis-analysis/annotations',
  '/api/v1/gis-analysis/search',
  '/api/v1/gis-analysis/annotations/{annotation_id}', '/api/v1/gis-analysis/trace',
  '/api/v1/gis-analysis/select', '/api/v1/gis-analysis/buffer',
  '/api/v1/gis-analysis/nearest', '/api/v1/gis-analysis/comparison-frame',
  '/api/v1/gis-analysis/thematic-map.pdf',
  '/api/v1/gis-analysis/vector-tiles/{layer}/{z}/{x}/{y}.mvt',
  '/api/v1/dgis/health', '/api/v1/dgis/catalog',
  '/api/v1/dgis/feature-states', '/api/v1/dgis/feature-states/replay',
  '/api/v1/dgis/simulation-layers', '/api/v1/dgis/3d-tiles',
  '/api/v1/dgis/raster/{layer_id}/{z}/{x}/{y}.png',
  '/api/v1/dgis/conversions/capabilities', '/api/v1/dgis/conversions/inspect',
  '/api/v1/dgis/conversions/geojson', '/api/v1/dgis/conversions/cog',
  '/api/v1/dgis/conversions/postgis',
];
for (const path of requiredPaths) {
  if (!openapi.paths?.[path]) throw new Error(`OpenAPI 缺少接口：${path}`);
}

const interfaces = Object.entries(schemas)
  .filter(([, schema]) => schema.type === 'object' || schema.properties)
  .sort(([left], [right]) => left.localeCompare(right))
  .map(([name, schema]) => renderInterface(name, schema))
  .join('\n\n');

const generated = `/* 本文件由 npm run openapi:update 自动生成，请勿手工修改。 */

${interfaces}

export type ValidationReport = app__validation__schemas__ValidationReport;
export type DispatchValidationReport = app__dispatch__schemas__ValidationReport;
export interface GISListQuery { dataset_version_id: number; bbox?: string; limit?: number; offset?: number; }
export interface GISInteractionQuery { dataset_version_id: number; time_seconds?: number; task_id?: number; dispatch_run_id?: number; }
export interface GISAnnotationQuery { dataset_version_id: number; scale_denominator?: number; bbox?: string; annotation_type?: string; limit?: number; offset?: number; time_seconds?: number; task_id?: number; dispatch_run_id?: number; }
export interface GISLocationSearchQuery { dataset_version_id: number; q: string; limit?: number; }
export interface GISComparisonQuery { dataset_version_id: number; baseline_task_id: number; comparison_task_id: number; time_seconds?: number; baseline_dispatch_run_id?: number; comparison_dispatch_run_id?: number; }
export interface DGISStateQuery { dataset_version_id: number; feature_type?: string; feature_id?: number; time_start?: string; time_end?: string; bbox?: string; task_id?: number; limit?: number; offset?: number; }
export interface DGISReplayQuery { dataset_version_id: number; at: string; feature_type?: string; task_id?: number; }
export interface DGISLayerQuery { dataset_version_id: number; layer_type?: string; task_id?: number; }
export interface DatabaseListQuery { dataset_version_id?: number; river_id?: number; search?: string; limit?: number; offset?: number; }
export interface DispatchListQuery { dataset_version_id?: number; plan_id?: number; status?: string; limit?: number; offset?: number; }
export interface PageResult<T> { items: T[]; total: number; limit: number; offset: number; }
export type ImportResource = 'rivers' | 'cross_sections' | 'gates' | 'pumps';

function toQuery<T extends object>(params: T): string {
  const query = new URLSearchParams();
  Object.entries(params as Record<string, string | number | undefined>).forEach(([key, value]) => { if (value !== undefined && value !== '') query.set(key, String(value)); });
  const value = query.toString();
  return value ? \`?\${value}\` : '';
}

async function requestJson<T>(path: string, options: RequestInit = {}, baseUrl = ''): Promise<T> {
  const response = await fetch(\`\${baseUrl}\${path}\`, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(payload?.detail ?? \`API 请求失败：\${response.status}\`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

async function requestBlob(path: string, options: RequestInit = {}, baseUrl = ''): Promise<Blob> {
  const response = await fetch(\`\${baseUrl}\${path}\`, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(payload?.detail ?? \`API 请求失败：\${response.status}\`);
  }
  return response.blob();
}

function jsonOptions(method: 'POST' | 'PUT' | 'PATCH', body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}

export const getSystemInfo = (baseUrl = '') => requestJson<SystemInfoResponse>('/', {}, baseUrl);
export const getHealth = (baseUrl = '') => requestJson<HealthResponse>('/api/v1/health', {}, baseUrl);
export const getGISHealth = (baseUrl = '') => requestJson<GISHealthResponse>('/api/v1/gis/health', {}, baseUrl);
export const getGISStatistics = (datasetVersionId: number, baseUrl = '') => requestJson<GISStatisticsResponse>(\`/api/v1/gis/stats\${toQuery({ dataset_version_id: datasetVersionId })}\`, {}, baseUrl);
export const getGeoServerHealth = (baseUrl = '') => requestJson<GeoServerHealthResponse>('/api/v1/gis/geoserver/health', {}, baseUrl);
export const getGeoServerLayers = (baseUrl = '') => requestJson<Array<GeoServerLayerRecord>>('/api/v1/gis/geoserver/layers', {}, baseUrl);
export const getGeoServerConfig = (baseUrl = '') => requestJson<GeoServerConfigResponse>('/api/v1/gis/geoserver/config', {}, baseUrl);
export const getRivers = (params: GISListQuery, baseUrl = '') => requestJson<GeoJSONFeatureCollection>(\`/api/v1/gis/rivers\${toQuery(params)}\`, {}, baseUrl);
export const getRiver = (id: number, datasetVersionId: number, baseUrl = '') => requestJson<GeoJSONFeature>(\`/api/v1/gis/rivers/\${id}\${toQuery({ dataset_version_id: datasetVersionId })}\`, {}, baseUrl);
export const getGates = (params: GISListQuery, baseUrl = '') => requestJson<GeoJSONFeatureCollection>(\`/api/v1/gis/gates\${toQuery(params)}\`, {}, baseUrl);
export const getGate = (id: number, datasetVersionId: number, baseUrl = '') => requestJson<GeoJSONFeature>(\`/api/v1/gis/gates/\${id}\${toQuery({ dataset_version_id: datasetVersionId })}\`, {}, baseUrl);
export const getPumps = (params: GISListQuery, baseUrl = '') => requestJson<GeoJSONFeatureCollection>(\`/api/v1/gis/pumps\${toQuery(params)}\`, {}, baseUrl);
export const getPump = (id: number, datasetVersionId: number, baseUrl = '') => requestJson<GeoJSONFeature>(\`/api/v1/gis/pumps/\${id}\${toQuery({ dataset_version_id: datasetVersionId })}\`, {}, baseUrl);
export const getCrossSections = (params: GISListQuery, baseUrl = '') => requestJson<GeoJSONFeatureCollection>(\`/api/v1/gis/cross_sections\${toQuery(params)}\`, {}, baseUrl);
export const getCrossSection = (id: number, datasetVersionId: number, baseUrl = '') => requestJson<GeoJSONFeature>(\`/api/v1/gis/cross_sections/\${id}\${toQuery({ dataset_version_id: datasetVersionId })}\`, {}, baseUrl);
export const getGISInteractionFrame = (params: GISInteractionQuery, baseUrl = '') => requestJson<GISInteractionFrame>(\`/api/v1/gis/interaction-frame\${toQuery(params)}\`, {}, baseUrl);
export const getGISLayerCatalog = (baseUrl = '') => requestJson<Array<LayerCatalogItem>>('/api/v1/gis-analysis/layers', {}, baseUrl);
export const searchGISLocations = (params: GISLocationSearchQuery, baseUrl = '') => requestJson<LocationSearchResponse>(\`/api/v1/gis-analysis/search\${toQuery(params)}\`, {}, baseUrl);
export const getGISAnnotations = (params: GISAnnotationQuery, baseUrl = '') => requestJson<AnnotationCollection>(\`/api/v1/gis-analysis/annotations\${toQuery(params)}\`, {}, baseUrl);
export const createGISAnnotation = (body: AnnotationCreate, baseUrl = '') => requestJson<AnnotationRecord>('/api/v1/gis-analysis/annotations', jsonOptions('POST', body), baseUrl);
export const updateGISAnnotation = (id: number, datasetVersionId: number, body: AnnotationUpdate, baseUrl = '') => requestJson<AnnotationRecord>(\`/api/v1/gis-analysis/annotations/\${id}\${toQuery({ dataset_version_id: datasetVersionId })}\`, jsonOptions('PUT', body), baseUrl);
export const deleteGISAnnotation = (id: number, datasetVersionId: number, baseUrl = '') => requestJson<void>(\`/api/v1/gis-analysis/annotations/\${id}\${toQuery({ dataset_version_id: datasetVersionId })}\`, { method: 'DELETE' }, baseUrl);
export const traceGISRiver = (datasetVersionId: number, riverId: number, baseUrl = '') => requestJson<TraceResponse>(\`/api/v1/gis-analysis/trace\${toQuery({ dataset_version_id: datasetVersionId, river_id: riverId })}\`, {}, baseUrl);
export const selectGISFeatures = (body: SpatialSelectRequest, baseUrl = '') => requestJson<SpatialSelectResponse>('/api/v1/gis-analysis/select', jsonOptions('POST', body), baseUrl);
export const bufferGISFeatures = (body: BufferAnalysisRequest, baseUrl = '') => requestJson<BufferAnalysisResponse>('/api/v1/gis-analysis/buffer', jsonOptions('POST', body), baseUrl);
export const getNearestGISFacilities = (body: NearestFacilityRequest, baseUrl = '') => requestJson<NearestFacilityResponse>('/api/v1/gis-analysis/nearest', jsonOptions('POST', body), baseUrl);
export const getGISComparisonFrame = (params: GISComparisonQuery, baseUrl = '') => requestJson<GISComparisonFrame>(\`/api/v1/gis-analysis/comparison-frame\${toQuery(params)}\`, {}, baseUrl);
export const downloadGISThematicMap = (body: ThematicMapRequest, baseUrl = '') => requestBlob('/api/v1/gis-analysis/thematic-map.pdf', jsonOptions('POST', body), baseUrl);
export const getGISVectorTile = (layer: 'river' | 'gate' | 'pump' | 'cross_section' | 'map_annotation', z: number, x: number, y: number, datasetVersionId: number, baseUrl = '') => requestBlob(\`/api/v1/gis-analysis/vector-tiles/\${layer}/\${z}/\${x}/\${y}.mvt\${toQuery({ dataset_version_id: datasetVersionId })}\`, {}, baseUrl);

export const getDGISHealth = (baseUrl = '') => requestJson<DGISHealthResponse>('/api/v1/dgis/health', {}, baseUrl);
export const getDGISCatalog = (datasetVersionId: number, baseUrl = '') => requestJson<DGISCatalogResponse>(\`/api/v1/dgis/catalog\${toQuery({ dataset_version_id: datasetVersionId })}\`, {}, baseUrl);
export const getDGISFeatureStates = (params: DGISStateQuery, baseUrl = '') => requestJson<FeatureStateCollection>(\`/api/v1/dgis/feature-states\${toQuery(params)}\`, {}, baseUrl);
export const createDGISFeatureState = (body: FeatureStateCreate, baseUrl = '') => requestJson<FeatureStateRecord>('/api/v1/dgis/feature-states', jsonOptions('POST', body), baseUrl);
export const replayDGISFeatureStates = (params: DGISReplayQuery, baseUrl = '') => requestJson<FeatureStateCollection>(\`/api/v1/dgis/feature-states/replay\${toQuery(params)}\`, {}, baseUrl);
export const getDGISSimulationLayers = (params: DGISLayerQuery, baseUrl = '') => requestJson<Array<SimulationLayerRecord>>(\`/api/v1/dgis/simulation-layers\${toQuery(params)}\`, {}, baseUrl);
export const getDGISThreeDTiles = (datasetVersionId: number, baseUrl = '') => requestJson<Array<ThreeDTilesAsset>>(\`/api/v1/dgis/3d-tiles\${toQuery({ dataset_version_id: datasetVersionId })}\`, {}, baseUrl);
export const getDGISConversionCapabilities = (baseUrl = '') => requestJson<ConversionCapabilityResponse>('/api/v1/dgis/conversions/capabilities', {}, baseUrl);

async function uploadDGISConversion(path: 'inspect' | 'geojson' | 'cog' | 'postgis', file: File, fields: Record<string, string | number> = {}, baseUrl = ''): Promise<ConversionJobResponse> {
  const body = new FormData();
  body.set('file', file);
  Object.entries(fields).forEach(([key, value]) => body.set(key, String(value)));
  return requestJson<ConversionJobResponse>(\`/api/v1/dgis/conversions/\${path}\`, { method: 'POST', body }, baseUrl);
}

export const inspectDGISFile = (file: File, baseUrl = '') => uploadDGISConversion('inspect', file, {}, baseUrl);
export const convertDGISToGeoJSON = (file: File, targetSrid = 4490, baseUrl = '') => uploadDGISConversion('geojson', file, { target_srid: targetSrid }, baseUrl);
export const convertDGISToCOG = (file: File, targetSrid = 4490, baseUrl = '') => uploadDGISConversion('cog', file, { target_srid: targetSrid }, baseUrl);
export const importDGISToPostGIS = (file: File, layerName: string, targetSrid = 4490, baseUrl = '') => uploadDGISConversion('postgis', file, { layer_name: layerName, target_srid: targetSrid }, baseUrl);

export const listRiverRecords = (params: DatabaseListQuery = {}, baseUrl = '') => requestJson<RiverListResponse>(\`/api/v1/rivers\${toQuery(params)}\`, {}, baseUrl);
export const createRiverRecord = (body: RiverCreate, baseUrl = '') => requestJson<RiverRecord>('/api/v1/rivers', jsonOptions('POST', body), baseUrl);
export const updateRiverRecord = (id: number, body: RiverUpdate, baseUrl = '') => requestJson<RiverRecord>(\`/api/v1/rivers/\${id}\`, jsonOptions('PUT', body), baseUrl);
export const deleteRiverRecord = (id: number, baseUrl = '') => requestJson<void>(\`/api/v1/rivers/\${id}\`, { method: 'DELETE' }, baseUrl);
export const generateTopology = (body: TopologyGenerateRequest, baseUrl = '') => requestJson<TopologyResponse>('/api/v1/rivers/topology/generate', jsonOptions('POST', body), baseUrl);
export const getTopology = (datasetVersionId: number, baseUrl = '') => requestJson<TopologyResponse>(\`/api/v1/rivers/topology?dataset_version_id=\${datasetVersionId}\`, {}, baseUrl);

export const listCrossSectionRecords = (params: DatabaseListQuery = {}, baseUrl = '') => requestJson<CrossSectionListResponse>(\`/api/v1/cross-sections\${toQuery(params)}\`, {}, baseUrl);
export const createCrossSectionRecord = (body: CrossSectionCreate, baseUrl = '') => requestJson<CrossSectionRecord>('/api/v1/cross-sections', jsonOptions('POST', body), baseUrl);
export const updateCrossSectionRecord = (id: number, body: CrossSectionUpdate, baseUrl = '') => requestJson<CrossSectionRecord>(\`/api/v1/cross-sections/\${id}\`, jsonOptions('PUT', body), baseUrl);
export const deleteCrossSectionRecord = (id: number, baseUrl = '') => requestJson<void>(\`/api/v1/cross-sections/\${id}\`, { method: 'DELETE' }, baseUrl);

export const listGateRecords = (params: DatabaseListQuery = {}, baseUrl = '') => requestJson<GateListResponse>(\`/api/v1/gates\${toQuery(params)}\`, {}, baseUrl);
export const createGateRecord = (body: GateCreate, baseUrl = '') => requestJson<GateRecord>('/api/v1/gates', jsonOptions('POST', body), baseUrl);
export const updateGateRecord = (id: number, body: GateUpdate, baseUrl = '') => requestJson<GateRecord>(\`/api/v1/gates/\${id}\`, jsonOptions('PUT', body), baseUrl);
export const deleteGateRecord = (id: number, baseUrl = '') => requestJson<void>(\`/api/v1/gates/\${id}\`, { method: 'DELETE' }, baseUrl);

export const listPumpRecords = (params: DatabaseListQuery = {}, baseUrl = '') => requestJson<PumpListResponse>(\`/api/v1/pumps\${toQuery(params)}\`, {}, baseUrl);
export const createPumpRecord = (body: PumpCreate, baseUrl = '') => requestJson<PumpRecord>('/api/v1/pumps', jsonOptions('POST', body), baseUrl);
export const updatePumpRecord = (id: number, body: PumpUpdate, baseUrl = '') => requestJson<PumpRecord>(\`/api/v1/pumps/\${id}\`, jsonOptions('PUT', body), baseUrl);
export const deletePumpRecord = (id: number, baseUrl = '') => requestJson<void>(\`/api/v1/pumps/\${id}\`, { method: 'DELETE' }, baseUrl);

export const getDatasetVersions = (baseUrl = '') => requestJson<Array<DatasetVersionRecord>>('/api/v1/model-data/dataset-versions', {}, baseUrl);
export const getModelParameters = (datasetVersionId?: number, baseUrl = '') => requestJson<Array<ModelParameterRecord>>(\`/api/v1/model-data/parameters\${toQuery({ dataset_version_id: datasetVersionId })}\`, {}, baseUrl);
export const getBoundaryConditions = (datasetVersionId?: number, baseUrl = '') => requestJson<Array<BoundaryConditionRecord>>(\`/api/v1/model-data/boundary-conditions\${toQuery({ dataset_version_id: datasetVersionId })}\`, {}, baseUrl);
export const getSimulationCases = (datasetVersionId?: number, baseUrl = '') => requestJson<Array<SimulationCaseRecord>>(\`/api/v1/model-data/simulation-cases\${toQuery({ dataset_version_id: datasetVersionId })}\`, {}, baseUrl);
export const getModelInput = (caseId: number, baseUrl = '') => requestJson<ModelInputSnapshot>(\`/api/v1/model-data/simulation-cases/\${caseId}/input\`, {}, baseUrl);
export const runValidation = (datasetVersionId: number, baseUrl = '') => requestJson<ValidationReport>('/api/v1/validation/run', jsonOptions('POST', { dataset_version_id: datasetVersionId }), baseUrl);

export const createHydraulicTask = (body: SimulationTaskCreate, baseUrl = '') => requestJson<SimulationTaskRecord>('/api/v1/model/tasks', jsonOptions('POST', body), baseUrl);
export const listHydraulicTasks = (baseUrl = '') => requestJson<Array<SimulationTaskRecord>>('/api/v1/model/tasks', {}, baseUrl);
export const getHydraulicTask = (taskId: number, baseUrl = '') => requestJson<SimulationTaskRecord>(\`/api/v1/model/tasks/\${taskId}\`, {}, baseUrl);
export const runHydraulicTask = (taskId: number, baseUrl = '') => requestJson<SimulationTaskRecord>(\`/api/v1/model/tasks/\${taskId}/run\`, { method: 'POST' }, baseUrl);
export const enqueueHydraulicTask = (taskId: number, baseUrl = '') => requestJson<SimulationTaskRecord>(\`/api/v1/model/tasks/\${taskId}/enqueue\`, { method: 'POST' }, baseUrl);
export const cancelHydraulicTask = (taskId: number, baseUrl = '') => requestJson<SimulationTaskRecord>(\`/api/v1/model/tasks/\${taskId}/cancel\`, { method: 'POST' }, baseUrl);
export const retryHydraulicTask = (taskId: number, baseUrl = '') => requestJson<SimulationTaskRecord>(\`/api/v1/model/tasks/\${taskId}/retry\`, { method: 'POST' }, baseUrl);
export const getHydraulicTaskSnapshot = (taskId: number, baseUrl = '') => requestJson<TaskSnapshotResponse>(\`/api/v1/model/tasks/\${taskId}/snapshot\`, {}, baseUrl);
export const getHydraulicResult = (taskId: number, sectionId?: number, baseUrl = '') => requestJson<SimulationResultResponse>(\`/api/v1/model/results/\${taskId}\${toQuery({ section_id: sectionId })}\`, {}, baseUrl);

export const listDispatchPlans = (params: DispatchListQuery = {}, baseUrl = '') => requestJson<PageResult<DispatchPlanRecord>>(\`/api/v1/dispatch/plans\${toQuery(params)}\`, {}, baseUrl);
export const createDispatchPlan = (body: DispatchPlanCreate, baseUrl = '') => requestJson<DispatchPlanRecord>('/api/v1/dispatch/plans', jsonOptions('POST', body), baseUrl);
export const getDispatchPlan = (planId: number, baseUrl = '') => requestJson<DispatchPlanRecord>(\`/api/v1/dispatch/plans/\${planId}\`, {}, baseUrl);
export const updateDispatchPlan = (planId: number, body: DispatchPlanUpdate, baseUrl = '') => requestJson<DispatchPlanRecord>(\`/api/v1/dispatch/plans/\${planId}\`, jsonOptions('PATCH', body), baseUrl);
export const deleteDispatchPlan = (planId: number, baseUrl = '') => requestJson<void>(\`/api/v1/dispatch/plans/\${planId}\`, { method: 'DELETE' }, baseUrl);
export const cloneDispatchPlan = (planId: number, baseUrl = '') => requestJson<DispatchPlanRecord>(\`/api/v1/dispatch/plans/\${planId}/clone\`, { method: 'POST' }, baseUrl);
export const validateDispatchPlan = (planId: number, baseUrl = '') => requestJson<DispatchValidationReport>(\`/api/v1/dispatch/plans/\${planId}/validate\`, { method: 'POST' }, baseUrl);
export const freezeDispatchPlan = (planId: number, baseUrl = '') => requestJson<DispatchPlanRecord>(\`/api/v1/dispatch/plans/\${planId}/freeze\`, { method: 'POST' }, baseUrl);
export const listDispatchActions = (planId: number, baseUrl = '') => requestJson<Array<DispatchActionRecord>>(\`/api/v1/dispatch/plans/\${planId}/actions\`, {}, baseUrl);
export const createDispatchAction = (planId: number, body: DispatchActionCreate, baseUrl = '') => requestJson<DispatchActionRecord>(\`/api/v1/dispatch/plans/\${planId}/actions\`, jsonOptions('POST', body), baseUrl);
export const updateDispatchAction = (actionId: number, body: DispatchActionUpdate, baseUrl = '') => requestJson<DispatchActionRecord>(\`/api/v1/dispatch/actions/\${actionId}\`, jsonOptions('PATCH', body), baseUrl);
export const deleteDispatchAction = (actionId: number, baseUrl = '') => requestJson<void>(\`/api/v1/dispatch/actions/\${actionId}\`, { method: 'DELETE' }, baseUrl);
export const listDispatchRules = (planId: number, baseUrl = '') => requestJson<Array<DispatchRuleRecord>>(\`/api/v1/dispatch/plans/\${planId}/rules\`, {}, baseUrl);
export const createDispatchRule = (planId: number, body: DispatchRuleCreate, baseUrl = '') => requestJson<DispatchRuleRecord>(\`/api/v1/dispatch/plans/\${planId}/rules\`, jsonOptions('POST', body), baseUrl);
export const updateDispatchRule = (ruleId: number, body: DispatchRuleUpdate, baseUrl = '') => requestJson<DispatchRuleRecord>(\`/api/v1/dispatch/rules/\${ruleId}\`, jsonOptions('PATCH', body), baseUrl);
export const deleteDispatchRule = (ruleId: number, baseUrl = '') => requestJson<void>(\`/api/v1/dispatch/rules/\${ruleId}\`, { method: 'DELETE' }, baseUrl);
export const createDispatchRun = (planId: number, baseUrl = '') => requestJson<DispatchRunRecord>(\`/api/v1/dispatch/plans/\${planId}/runs\`, { method: 'POST' }, baseUrl);
export const listDispatchRuns = (params: DispatchListQuery = {}, baseUrl = '') => requestJson<PageResult<DispatchRunRecord>>(\`/api/v1/dispatch/runs\${toQuery(params)}\`, {}, baseUrl);
export const getDispatchRun = (runId: number, baseUrl = '') => requestJson<DispatchRunRecord>(\`/api/v1/dispatch/runs/\${runId}\`, {}, baseUrl);
export const cancelDispatchRun = (runId: number, baseUrl = '') => requestJson<DispatchRunRecord>(\`/api/v1/dispatch/runs/\${runId}/cancel\`, { method: 'POST' }, baseUrl);
export const retryDispatchRun = (runId: number, baseUrl = '') => requestJson<DispatchRunRecord>(\`/api/v1/dispatch/runs/\${runId}/retry\`, { method: 'POST' }, baseUrl);
export const getDispatchComparison = (runId: number, baseUrl = '') => requestJson<DispatchComparison>(\`/api/v1/dispatch/runs/\${runId}/comparison\`, {}, baseUrl);
export const getDispatchEvents = (runId: number, baseUrl = '') => requestJson<Array<Record<string, unknown>>>(\`/api/v1/dispatch/runs/\${runId}/events\`, {}, baseUrl);
export const getDispatchStructures = (runId: number, baseUrl = '') => requestJson<Array<Record<string, unknown>>>(\`/api/v1/dispatch/runs/\${runId}/structures\`, {}, baseUrl);
export const getDispatchNodes = (runId: number, baseUrl = '') => requestJson<Array<Record<string, unknown>>>(\`/api/v1/dispatch/runs/\${runId}/nodes\`, {}, baseUrl);

export const createOptimizationTask = (body: OptimizationTaskCreate, baseUrl = '') => requestJson<OptimizationTaskRecord>('/api/v1/optimization/tasks', jsonOptions('POST', body), baseUrl);
export const listOptimizationTasks = (baseUrl = '') => requestJson<Array<OptimizationTaskRecord>>('/api/v1/optimization/tasks', {}, baseUrl);
export const getOptimizationTask = (taskId: number, baseUrl = '') => requestJson<OptimizationTaskRecord>(\`/api/v1/optimization/tasks/\${taskId}\`, {}, baseUrl);
export const runOptimizationTask = (taskId: number, baseUrl = '') => requestJson<OptimizationTaskRecord>(\`/api/v1/optimization/tasks/\${taskId}/run\`, { method: 'POST' }, baseUrl);
export const cancelOptimizationTask = (taskId: number, baseUrl = '') => requestJson<OptimizationTaskRecord>(\`/api/v1/optimization/tasks/\${taskId}/cancel\`, { method: 'POST' }, baseUrl);
export const getOptimizationCandidates = (taskId: number, baseUrl = '') => requestJson<Array<OptimizationCandidateRecord>>(\`/api/v1/optimization/tasks/\${taskId}/candidates\`, {}, baseUrl);
export const getOptimizationPareto = (taskId: number, baseUrl = '') => requestJson<Array<ParetoCandidateRecord>>(\`/api/v1/optimization/tasks/\${taskId}/pareto\`, {}, baseUrl);
export const getOptimizationRecommendation = (taskId: number, baseUrl = '') => requestJson<RecommendationResponse>(\`/api/v1/optimization/tasks/\${taskId}/recommendation\`, {}, baseUrl);
export const explainOptimizationRecommendation = (taskId: number, baseUrl = '') => requestJson<OptimizationExplanation>(\`/api/v1/optimization/tasks/\${taskId}/explain\`, {}, baseUrl);

export const chatWithAI = (body: AIChatRequest, baseUrl = '') => requestJson<AIChatResponse>('/api/v1/ai/chat', jsonOptions('POST', body), baseUrl);
export const searchAIKnowledge = (query: string, limit = 5, baseUrl = '') => requestJson<KnowledgeSearchResponse>(\`/api/v1/ai/knowledge/search\${toQuery({ q: query, limit })}\`, {}, baseUrl);
export const listAIKnowledgeDocuments = (baseUrl = '') => requestJson<Array<KnowledgeDocumentRecord>>('/api/v1/ai/knowledge/documents', {}, baseUrl);
export const generateAIReport = (body: ReportGenerateRequest, baseUrl = '') => requestJson<ReportGenerateResponse>('/api/v1/ai/report/generate', jsonOptions('POST', body), baseUrl);
export const listAIToolLogs = (limit = 20, offset = 0, baseUrl = '') => requestJson<Array<AIToolCallLogRecord>>(\`/api/v1/ai/tools/logs\${toQuery({ limit, offset })}\`, {}, baseUrl);

export async function uploadAIKnowledgeDocument(file: File, category: string, version: string, baseUrl = ''): Promise<KnowledgeDocumentRecord> {
  const body = new FormData();
  body.set('file', file);
  body.set('category', category);
  body.set('version', version);
  return requestJson<KnowledgeDocumentRecord>('/api/v1/ai/knowledge/documents', { method: 'POST', body }, baseUrl);
}

export async function uploadDataFile(kind: 'excel' | 'csv' | 'geojson', resource: ImportResource, datasetVersionId: number, file: File, baseUrl = ''): Promise<ImportResponse> {
  const body = new FormData();
  body.set('resource', resource);
  body.set('dataset_version_id', String(datasetVersionId));
  body.set('file', file);
  return requestJson<ImportResponse>(\`/api/v1/import/\${kind}\`, { method: 'POST', body }, baseUrl);
}
`;

await mkdir(outputDirectory, { recursive: true });
await writeFile(outputFile, generated, 'utf8');
console.log(`已生成 OpenAPI 客户端：${outputFile}`);
