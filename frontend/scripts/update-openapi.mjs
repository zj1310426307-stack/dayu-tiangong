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
  '/api/v1/gis/rivers', '/api/v1/rivers', '/api/v1/cross-sections',
  '/api/v1/gates', '/api/v1/pumps', '/api/v1/import/excel',
  '/api/v1/validation/run', '/api/v1/model-data/dataset-versions',
  '/api/v1/model-data/simulation-cases/{case_id}/input',
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

export interface GISListQuery { bbox?: string; limit?: number; offset?: number; }
export interface DatabaseListQuery { dataset_version_id?: number; river_id?: number; search?: string; limit?: number; offset?: number; }
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

function jsonOptions(method: 'POST' | 'PUT', body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}

export const getSystemInfo = (baseUrl = '') => requestJson<SystemInfoResponse>('/', {}, baseUrl);
export const getHealth = (baseUrl = '') => requestJson<HealthResponse>('/api/v1/health', {}, baseUrl);
export const getGISHealth = (baseUrl = '') => requestJson<GISHealthResponse>('/api/v1/gis/health', {}, baseUrl);
export const getGISStatistics = (baseUrl = '') => requestJson<GISStatisticsResponse>('/api/v1/gis/stats', {}, baseUrl);
export const getRivers = (params: GISListQuery = {}, baseUrl = '') => requestJson<GeoJSONFeatureCollection>(\`/api/v1/gis/rivers\${toQuery(params)}\`, {}, baseUrl);
export const getRiver = (id: number, baseUrl = '') => requestJson<GeoJSONFeature>(\`/api/v1/gis/rivers/\${id}\`, {}, baseUrl);
export const getGates = (params: GISListQuery = {}, baseUrl = '') => requestJson<GeoJSONFeatureCollection>(\`/api/v1/gis/gates\${toQuery(params)}\`, {}, baseUrl);
export const getGate = (id: number, baseUrl = '') => requestJson<GeoJSONFeature>(\`/api/v1/gis/gates/\${id}\`, {}, baseUrl);
export const getPumps = (params: GISListQuery = {}, baseUrl = '') => requestJson<GeoJSONFeatureCollection>(\`/api/v1/gis/pumps\${toQuery(params)}\`, {}, baseUrl);
export const getPump = (id: number, baseUrl = '') => requestJson<GeoJSONFeature>(\`/api/v1/gis/pumps/\${id}\`, {}, baseUrl);
export const getCrossSections = (params: GISListQuery = {}, baseUrl = '') => requestJson<GeoJSONFeatureCollection>(\`/api/v1/gis/cross_sections\${toQuery(params)}\`, {}, baseUrl);
export const getCrossSection = (id: number, baseUrl = '') => requestJson<GeoJSONFeature>(\`/api/v1/gis/cross_sections/\${id}\`, {}, baseUrl);

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
