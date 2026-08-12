import { getRivers, type GeoServerConfigResponse } from '../../api/generated/client';

export interface GISPerformanceMetric {
  source: 'WMS' | 'WMTS' | 'GeoJSON';
  durationMs: number | null;
  bytes: number | null;
  status: 'testing' | 'ready' | 'error';
}

/** Measure one public OGC payload without crossing into a GeoServer management endpoint. */
async function measureOgcRequest(
  source: 'WMS' | 'WMTS',
  url: string,
): Promise<GISPerformanceMetric> {
  const started = performance.now();
  try {
    const response = await fetch(url, { cache: 'no-store' });
    const payload = await response.arrayBuffer();
    if (!response.ok) throw new Error(`${response.status}`);
    return { source, durationMs: performance.now() - started, bytes: payload.byteLength, status: 'ready' };
  } catch {
    return { source, durationMs: performance.now() - started, bytes: null, status: 'error' };
  }
}

/** Measure the business GeoJSON path through the generated FastAPI client. */
async function measureGeoJson(datasetVersionId: number): Promise<GISPerformanceMetric> {
  const started = performance.now();
  try {
    const payload = await getRivers({ dataset_version_id: datasetVersionId, limit: 100, offset: 0 });
    const bytes = new TextEncoder().encode(JSON.stringify(payload)).byteLength;
    return { source: 'GeoJSON', durationMs: performance.now() - started, bytes, status: 'ready' };
  } catch {
    return { source: 'GeoJSON', durationMs: performance.now() - started, bytes: null, status: 'error' };
  }
}

/** Compare the three Phase 1B delivery modes for one isolated data version. */
export function runPerformanceProbes(
  config: GeoServerConfigResponse,
  datasetVersionId: number,
): Promise<GISPerformanceMetric[]> {
  const cql = `dataset_version_id=${datasetVersionId}`;
  const wms = new URLSearchParams({
    service: 'WMS', version: '1.1.1', request: 'GetMap', layers: 'dayu:river', styles: '',
    format: 'image/png', transparent: 'true', srs: 'EPSG:4490', bbox: '120.0,30.0,120.6,30.5',
    width: '256', height: '256', CQL_FILTER: cql,
  });
  const wmts = new URLSearchParams({
    service: 'WMTS', version: '1.0.0', request: 'GetTile', layer: 'dayu:river', style: '',
    format: 'image/png', tilematrixset: 'EPSG:900913', tilematrix: 'EPSG:900913:8',
    tilerow: '105', tilecol: '213', CQL_FILTER: cql,
  });
  return Promise.all([
    measureOgcRequest('WMS', `${config.wms_url}?${wms}`),
    measureOgcRequest('WMTS', `${config.wmts_url}?${wmts}`),
    measureGeoJson(datasetVersionId),
  ]);
}

/** Display compact payload sizes without treating unavailable values as zero. */
export function formatBytes(value: number | null): string {
  if (value === null) return '—';
  if (value < 1024) return `${value} B`;
  return `${(value / 1024).toFixed(1)} KB`;
}
