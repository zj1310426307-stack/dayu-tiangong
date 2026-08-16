import { getQgisWmsFeatureInfo } from '../../api/generated/client';
import type { LayerRuntime } from '../catalog/runtime';
import type { CatalogPick } from './types';

export interface QgisIdentifyContext {
  bbox: [number, number, number, number];
  width: number;
  height: number;
  i: number;
  j: number;
}

function featureId(value: unknown): number | null {
  const match = String(value ?? '').match(/(?:^|\.)([1-9][0-9]*)$/);
  if (!match) return null;
  const parsed = Number(match[1]);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

/** Query only the platform WMS gateway; raw FILTER/MAP never enters the browser. */
export async function identifyQgisLayer(
  layer: LayerRuntime,
  context: QgisIdentifyContext,
): Promise<CatalogPick | null> {
  if (
    layer.serviceMode !== 'QGIS_WMS'
    || layer.renderMode !== 'RASTER_WMS'
    || !layer.visible
    || !layer.descriptor.identify_enabled
  ) return null;
  const response = await getQgisWmsFeatureInfo({
    request: 'GetFeatureInfo',
    dataset_version_id: layer.datasetVersionId,
    layer_key: layer.key,
    bbox: context.bbox.join(','),
    width: context.width,
    height: context.height,
    crs: 'EPSG:4490',
    format: 'image/png',
    transparent: 'true',
    i: context.i,
    j: context.j,
    feature_count: 5,
  });
  const feature = response.features?.[0];
  if (!feature) return null;
  const properties = feature.properties ?? {};
  const id = featureId(properties.id ?? feature.id);
  if (id === null) return null;
  return {
    kind: 'catalog-feature',
    identity: {
      layerKey: layer.key,
      featureId: id,
      datasetVersionId: layer.datasetVersionId,
    },
    detailRouteKey: layer.descriptor.identify.detail_route_key as string | null,
    properties: { ...properties, layer_key: layer.key },
  };
}
