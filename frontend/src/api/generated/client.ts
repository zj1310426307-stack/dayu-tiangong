/* 本文件由 npm run openapi:update 自动生成，请勿手工修改。 */

export interface Body_import_csv_api_v1_import_csv_post {
  "resource": "rivers" | "cross_sections" | "gates" | "pumps";
  "dataset_version_id": number;
  "file": string;
}

export interface Body_import_excel_api_v1_import_excel_post {
  "resource": "rivers" | "cross_sections" | "gates" | "pumps";
  "dataset_version_id": number;
  "file": string;
}

export interface Body_import_geojson_api_v1_import_geojson_post {
  "resource": "rivers" | "cross_sections" | "gates" | "pumps";
  "dataset_version_id": number;
  "file": string;
}

export interface BoundaryConditionCreate {
  "dataset_version_id": number;
  "name": string;
  "boundary_type": string;
  "target_node_id"?: number | null;
  "values": Record<string, unknown>;
  "unit": string;
  "description"?: string | null;
}

export interface BoundaryConditionRecord {
  "dataset_version_id": number;
  "name": string;
  "boundary_type": string;
  "target_node_id"?: number | null;
  "values": Record<string, unknown>;
  "unit": string;
  "description"?: string | null;
  "id": number;
}

export interface BoundaryConditionUpdate {
  "name"?: string | null;
  "boundary_type"?: string | null;
  "target_node_id"?: number | null;
  "values"?: Record<string, unknown> | null;
  "unit"?: string | null;
  "description"?: string | null;
}

export interface CrossSectionCreate {
  "dataset_version_id": number;
  "river_id": number;
  "section_code": string;
  "section_name": string;
  "station": number;
  "points": Record<string, Array<Array<number>>>;
  "roughness": number;
  "elevation_min": number;
  "survey_date"?: string | null;
  "geometry": Record<string, unknown>;
}

export interface CrossSectionListResponse {
  "items": Array<CrossSectionRecord>;
  "total": number;
  "limit": number;
  "offset": number;
}

export interface CrossSectionRecord {
  "dataset_version_id": number;
  "river_id": number;
  "section_code": string;
  "section_name": string;
  "station": number;
  "points": Record<string, Array<Array<number>>>;
  "roughness": number;
  "elevation_min": number;
  "survey_date"?: string | null;
  "geometry": Record<string, unknown>;
  "id": number;
  "created_time": string;
}

export interface CrossSectionUpdate {
  "river_id"?: number | null;
  "section_code"?: string | null;
  "section_name"?: string | null;
  "station"?: number | null;
  "points"?: Record<string, Array<Array<number>>> | null;
  "roughness"?: number | null;
  "elevation_min"?: number | null;
  "survey_date"?: string | null;
  "geometry"?: Record<string, unknown> | null;
}

export interface DatasetVersionCreate {
  "version": string;
  "name": string;
  "description"?: string | null;
  "creator": string;
}

export interface DatasetVersionRecord {
  "version": string;
  "name": string;
  "description"?: string | null;
  "creator": string;
  "id": number;
  "created_time": string;
}

export interface DatasetVersionUpdate {
  "name"?: string | null;
  "description"?: string | null;
}

export interface GateCreate {
  "dataset_version_id": number;
  "name": string;
  "river_id": number;
  "control_mode": string;
  "status"?: "online" | "offline" | "maintenance" | "fault";
  "geometry": Record<string, unknown>;
  "gate_code": string;
  "gate_type": string;
  "opening_direction": string;
  "width": number;
  "height": number;
  "max_flow": number;
  "bottom_elevation": number;
}

export interface GateListResponse {
  "items": Array<GateRecord>;
  "total": number;
  "limit": number;
  "offset": number;
}

export interface GateRecord {
  "dataset_version_id": number;
  "name": string;
  "river_id": number;
  "control_mode": string;
  "status"?: "online" | "offline" | "maintenance" | "fault";
  "geometry": Record<string, unknown>;
  "gate_code": string;
  "gate_type": string;
  "opening_direction": string;
  "width": number;
  "height": number;
  "max_flow": number;
  "bottom_elevation": number;
  "id": number;
  "created_time": string;
}

export interface GateUpdate {
  "name"?: string | null;
  "river_id"?: number | null;
  "gate_code"?: string | null;
  "gate_type"?: string | null;
  "opening_direction"?: string | null;
  "control_mode"?: string | null;
  "width"?: number | null;
  "height"?: number | null;
  "max_flow"?: number | null;
  "bottom_elevation"?: number | null;
  "status"?: "online" | "offline" | "maintenance" | "fault" | null;
  "geometry"?: Record<string, unknown> | null;
}

export interface GeoJSONFeature {
  "type"?: "Feature";
  "id": number;
  "geometry": Record<string, unknown>;
  "properties": Record<string, unknown>;
}

export interface GeoJSONFeatureCollection {
  "type"?: "FeatureCollection";
  "features": Array<GeoJSONFeature>;
  "meta": PaginationMeta;
}

export interface GISHealthResponse {
  "status": "healthy";
  "database": string;
  "postgis_version": string;
  "srid"?: 4326;
}

export interface GISStatisticsResponse {
  "rivers": number;
  "gates": number;
  "pumps": number;
  "cross_sections": number;
  "demo_data"?: true;
  "source"?: "PostGIS / DEMO DATA";
}

export interface HealthResponse {
  "status": "healthy";
  "service": string;
  "version": string;
}

export interface HTTPValidationError {
  "detail"?: Array<ValidationError>;
}

export interface ImportIssue {
  "row": number;
  "message": string;
}

export interface ImportResponse {
  "status": "success" | "failed";
  "resource": string;
  "imported_count": number;
  "stored_filename": string;
  "errors": Array<ImportIssue>;
  "warnings": Array<ImportIssue>;
}

export interface ModelInputSnapshot {
  "schema_version"?: string;
  "generated_time": string;
  "simulation_case": SimulationCaseRecord;
  "dataset_version": DatasetVersionRecord;
  "rivers": Array<Record<string, unknown>>;
  "nodes": Array<Record<string, unknown>>;
  "segments": Array<Record<string, unknown>>;
  "connections": Array<Record<string, unknown>>;
  "cross_sections": Array<Record<string, unknown>>;
  "gates": Array<Record<string, unknown>>;
  "pumps": Array<Record<string, unknown>>;
  "parameters": Array<ModelParameterRecord>;
  "boundary_conditions": Array<BoundaryConditionRecord>;
}

export interface ModelParameterCreate {
  "dataset_version_id": number;
  "parameter_type": string;
  "parameter_name": string;
  "value": number;
  "unit": string;
  "description"?: string | null;
}

export interface ModelParameterRecord {
  "dataset_version_id": number;
  "parameter_type": string;
  "parameter_name": string;
  "value": number;
  "unit": string;
  "description"?: string | null;
  "id": number;
}

export interface ModelParameterUpdate {
  "value"?: number | null;
  "unit"?: string | null;
  "description"?: string | null;
}

export interface PaginationMeta {
  "total": number;
  "limit": number;
  "offset": number;
  "bbox"?: Array<number> | null;
  "demo_data"?: true;
  "crs"?: "EPSG:4326";
}

export interface PumpCreate {
  "dataset_version_id": number;
  "name": string;
  "river_id": number;
  "control_mode": string;
  "status"?: "online" | "offline" | "maintenance" | "fault";
  "geometry": Record<string, unknown>;
  "pump_code": string;
  "design_flow": number;
  "head": number;
  "power": number;
  "efficiency_curve": Record<string, Array<Array<number>>>;
}

export interface PumpListResponse {
  "items": Array<PumpRecord>;
  "total": number;
  "limit": number;
  "offset": number;
}

export interface PumpRecord {
  "dataset_version_id": number;
  "name": string;
  "river_id": number;
  "control_mode": string;
  "status"?: "online" | "offline" | "maintenance" | "fault";
  "geometry": Record<string, unknown>;
  "pump_code": string;
  "design_flow": number;
  "head": number;
  "power": number;
  "efficiency_curve": Record<string, Array<Array<number>>>;
  "id": number;
  "created_time": string;
}

export interface PumpUpdate {
  "name"?: string | null;
  "river_id"?: number | null;
  "pump_code"?: string | null;
  "design_flow"?: number | null;
  "head"?: number | null;
  "power"?: number | null;
  "efficiency_curve"?: Record<string, Array<Array<number>>> | null;
  "control_mode"?: string | null;
  "status"?: "online" | "offline" | "maintenance" | "fault" | null;
  "geometry"?: Record<string, unknown> | null;
}

export interface RiverConnectionRecord {
  "id": number;
  "dataset_version_id": number;
  "from_node_id": number;
  "to_node_id": number;
  "river_id": number;
}

export interface RiverCreate {
  "dataset_version_id": number;
  "name": string;
  "code": string;
  "length": number;
  "level": string;
  "status"?: "active" | "inactive" | "planned";
  "description"?: string | null;
  "geometry": Record<string, unknown>;
}

export interface RiverListResponse {
  "items": Array<RiverRecord>;
  "total": number;
  "limit": number;
  "offset": number;
}

export interface RiverNodeRecord {
  "id": number;
  "dataset_version_id": number;
  "node_code": string;
  "node_type": string;
  "longitude": number;
  "latitude": number;
  "geometry": Record<string, unknown>;
}

export interface RiverRecord {
  "dataset_version_id": number;
  "name": string;
  "code": string;
  "length": number;
  "level": string;
  "status"?: "active" | "inactive" | "planned";
  "description"?: string | null;
  "geometry": Record<string, unknown>;
  "id": number;
  "created_time": string;
}

export interface RiverSegmentRecord {
  "id": number;
  "dataset_version_id": number;
  "river_id": number;
  "segment_code": string;
  "upstream_node_id": number;
  "downstream_node_id": number;
  "length": number;
  "geometry": Record<string, unknown>;
}

export interface RiverUpdate {
  "name"?: string | null;
  "code"?: string | null;
  "length"?: number | null;
  "level"?: string | null;
  "status"?: "active" | "inactive" | "planned" | null;
  "description"?: string | null;
  "geometry"?: Record<string, unknown> | null;
}

export interface SimulationCaseCreate {
  "name": string;
  "description"?: string | null;
  "dataset_version_id": number;
  "boundary_condition_id": number;
}

export interface SimulationCaseRecord {
  "name": string;
  "description"?: string | null;
  "dataset_version_id": number;
  "boundary_condition_id": number;
  "id": number;
  "created_time": string;
}

export interface SimulationCaseUpdate {
  "name"?: string | null;
  "description"?: string | null;
  "boundary_condition_id"?: number | null;
}

export interface SystemInfoResponse {
  "name": string;
  "version": string;
  "description": string;
  "status": "running";
}

export interface TopologyGenerateRequest {
  "dataset_version_id": number;
  "tolerance"?: number;
}

export interface TopologyResponse {
  "dataset_version_id": number;
  "nodes": Array<RiverNodeRecord>;
  "segments": Array<RiverSegmentRecord>;
  "connections": Array<RiverConnectionRecord>;
}

export interface ValidationError {
  "loc": Array<string | number>;
  "msg": string;
  "type": string;
}

export interface ValidationItem {
  "code": string;
  "category": "spatial" | "hydraulic" | "structure" | "topology" | "model";
  "severity": "error" | "warning" | "passed";
  "message": string;
  "count": number;
  "sample_ids"?: Array<number>;
}

export interface ValidationReport {
  "dataset_version_id": number;
  "checked_time": string;
  "summary": ValidationSummary;
  "items": Array<ValidationItem>;
}

export interface ValidationRequest {
  "dataset_version_id": number;
}

export interface ValidationSummary {
  "errors": number;
  "warnings": number;
  "passed": number;
  "is_model_ready": boolean;
}

export interface GISListQuery { bbox?: string; limit?: number; offset?: number; }
export interface DatabaseListQuery { dataset_version_id?: number; river_id?: number; search?: string; limit?: number; offset?: number; }
export type ImportResource = 'rivers' | 'cross_sections' | 'gates' | 'pumps';

function toQuery<T extends object>(params: T): string {
  const query = new URLSearchParams();
  Object.entries(params as Record<string, string | number | undefined>).forEach(([key, value]) => { if (value !== undefined && value !== '') query.set(key, String(value)); });
  const value = query.toString();
  return value ? `?${value}` : '';
}

async function requestJson<T>(path: string, options: RequestInit = {}, baseUrl = ''): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(payload?.detail ?? `API 请求失败：${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function jsonOptions(method: 'POST' | 'PUT', body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}

export const getSystemInfo = (baseUrl = '') => requestJson<SystemInfoResponse>('/', {}, baseUrl);
export const getHealth = (baseUrl = '') => requestJson<HealthResponse>('/api/v1/health', {}, baseUrl);
export const getGISHealth = (baseUrl = '') => requestJson<GISHealthResponse>('/api/v1/gis/health', {}, baseUrl);
export const getGISStatistics = (baseUrl = '') => requestJson<GISStatisticsResponse>('/api/v1/gis/stats', {}, baseUrl);
export const getRivers = (params: GISListQuery = {}, baseUrl = '') => requestJson<GeoJSONFeatureCollection>(`/api/v1/gis/rivers${toQuery(params)}`, {}, baseUrl);
export const getRiver = (id: number, baseUrl = '') => requestJson<GeoJSONFeature>(`/api/v1/gis/rivers/${id}`, {}, baseUrl);
export const getGates = (params: GISListQuery = {}, baseUrl = '') => requestJson<GeoJSONFeatureCollection>(`/api/v1/gis/gates${toQuery(params)}`, {}, baseUrl);
export const getGate = (id: number, baseUrl = '') => requestJson<GeoJSONFeature>(`/api/v1/gis/gates/${id}`, {}, baseUrl);
export const getPumps = (params: GISListQuery = {}, baseUrl = '') => requestJson<GeoJSONFeatureCollection>(`/api/v1/gis/pumps${toQuery(params)}`, {}, baseUrl);
export const getPump = (id: number, baseUrl = '') => requestJson<GeoJSONFeature>(`/api/v1/gis/pumps/${id}`, {}, baseUrl);
export const getCrossSections = (params: GISListQuery = {}, baseUrl = '') => requestJson<GeoJSONFeatureCollection>(`/api/v1/gis/cross_sections${toQuery(params)}`, {}, baseUrl);
export const getCrossSection = (id: number, baseUrl = '') => requestJson<GeoJSONFeature>(`/api/v1/gis/cross_sections/${id}`, {}, baseUrl);

export const listRiverRecords = (params: DatabaseListQuery = {}, baseUrl = '') => requestJson<RiverListResponse>(`/api/v1/rivers${toQuery(params)}`, {}, baseUrl);
export const createRiverRecord = (body: RiverCreate, baseUrl = '') => requestJson<RiverRecord>('/api/v1/rivers', jsonOptions('POST', body), baseUrl);
export const updateRiverRecord = (id: number, body: RiverUpdate, baseUrl = '') => requestJson<RiverRecord>(`/api/v1/rivers/${id}`, jsonOptions('PUT', body), baseUrl);
export const deleteRiverRecord = (id: number, baseUrl = '') => requestJson<void>(`/api/v1/rivers/${id}`, { method: 'DELETE' }, baseUrl);
export const generateTopology = (body: TopologyGenerateRequest, baseUrl = '') => requestJson<TopologyResponse>('/api/v1/rivers/topology/generate', jsonOptions('POST', body), baseUrl);
export const getTopology = (datasetVersionId: number, baseUrl = '') => requestJson<TopologyResponse>(`/api/v1/rivers/topology?dataset_version_id=${datasetVersionId}`, {}, baseUrl);

export const listCrossSectionRecords = (params: DatabaseListQuery = {}, baseUrl = '') => requestJson<CrossSectionListResponse>(`/api/v1/cross-sections${toQuery(params)}`, {}, baseUrl);
export const createCrossSectionRecord = (body: CrossSectionCreate, baseUrl = '') => requestJson<CrossSectionRecord>('/api/v1/cross-sections', jsonOptions('POST', body), baseUrl);
export const updateCrossSectionRecord = (id: number, body: CrossSectionUpdate, baseUrl = '') => requestJson<CrossSectionRecord>(`/api/v1/cross-sections/${id}`, jsonOptions('PUT', body), baseUrl);
export const deleteCrossSectionRecord = (id: number, baseUrl = '') => requestJson<void>(`/api/v1/cross-sections/${id}`, { method: 'DELETE' }, baseUrl);

export const listGateRecords = (params: DatabaseListQuery = {}, baseUrl = '') => requestJson<GateListResponse>(`/api/v1/gates${toQuery(params)}`, {}, baseUrl);
export const createGateRecord = (body: GateCreate, baseUrl = '') => requestJson<GateRecord>('/api/v1/gates', jsonOptions('POST', body), baseUrl);
export const updateGateRecord = (id: number, body: GateUpdate, baseUrl = '') => requestJson<GateRecord>(`/api/v1/gates/${id}`, jsonOptions('PUT', body), baseUrl);
export const deleteGateRecord = (id: number, baseUrl = '') => requestJson<void>(`/api/v1/gates/${id}`, { method: 'DELETE' }, baseUrl);

export const listPumpRecords = (params: DatabaseListQuery = {}, baseUrl = '') => requestJson<PumpListResponse>(`/api/v1/pumps${toQuery(params)}`, {}, baseUrl);
export const createPumpRecord = (body: PumpCreate, baseUrl = '') => requestJson<PumpRecord>('/api/v1/pumps', jsonOptions('POST', body), baseUrl);
export const updatePumpRecord = (id: number, body: PumpUpdate, baseUrl = '') => requestJson<PumpRecord>(`/api/v1/pumps/${id}`, jsonOptions('PUT', body), baseUrl);
export const deletePumpRecord = (id: number, baseUrl = '') => requestJson<void>(`/api/v1/pumps/${id}`, { method: 'DELETE' }, baseUrl);

export const getDatasetVersions = (baseUrl = '') => requestJson<Array<DatasetVersionRecord>>('/api/v1/model-data/dataset-versions', {}, baseUrl);
export const getModelParameters = (datasetVersionId?: number, baseUrl = '') => requestJson<Array<ModelParameterRecord>>(`/api/v1/model-data/parameters${toQuery({ dataset_version_id: datasetVersionId })}`, {}, baseUrl);
export const getBoundaryConditions = (datasetVersionId?: number, baseUrl = '') => requestJson<Array<BoundaryConditionRecord>>(`/api/v1/model-data/boundary-conditions${toQuery({ dataset_version_id: datasetVersionId })}`, {}, baseUrl);
export const getSimulationCases = (datasetVersionId?: number, baseUrl = '') => requestJson<Array<SimulationCaseRecord>>(`/api/v1/model-data/simulation-cases${toQuery({ dataset_version_id: datasetVersionId })}`, {}, baseUrl);
export const getModelInput = (caseId: number, baseUrl = '') => requestJson<ModelInputSnapshot>(`/api/v1/model-data/simulation-cases/${caseId}/input`, {}, baseUrl);
export const runValidation = (datasetVersionId: number, baseUrl = '') => requestJson<ValidationReport>('/api/v1/validation/run', jsonOptions('POST', { dataset_version_id: datasetVersionId }), baseUrl);

export async function uploadDataFile(kind: 'excel' | 'csv' | 'geojson', resource: ImportResource, datasetVersionId: number, file: File, baseUrl = ''): Promise<ImportResponse> {
  const body = new FormData();
  body.set('resource', resource);
  body.set('dataset_version_id', String(datasetVersionId));
  body.set('file', file);
  return requestJson<ImportResponse>(`/api/v1/import/${kind}`, { method: 'POST', body }, baseUrl);
}
