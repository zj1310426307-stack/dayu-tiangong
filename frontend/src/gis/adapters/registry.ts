import type { LayerRuntime } from '../catalog/runtime';
import { CesiumDynamicAdapter } from './dynamic';
import { LegacyGeoServerWmsAdapter, LegacyGeoServerWmtsAdapter, MartinMvtAdapter, QgisWmsAdapter, TiTilerAdapter } from './imagery';
import { ThreeDTilesAdapter } from './threeD';
import type { GisLayerAdapter } from './types';

export const SUPPORTED_ADAPTER_KEYS = [
  'QGIS_WMS|RASTER_WMS',
  'GEOSERVER_WMS_LEGACY|RASTER_WMS',
  'GEOSERVER_WMS_LEGACY|RASTER_TILE',
  'MARTIN_MVT|VECTOR_TILE',
  'TITILER|RASTER_TILE',
  'FASTAPI|DYNAMIC_PRIMITIVE',
  'CESIUM_DYNAMIC|DYNAMIC_PRIMITIVE',
  'THREE_D_TILES|THREE_D',
] as const;

const qgis = new QgisWmsAdapter();
const legacy = new LegacyGeoServerWmsAdapter();
const legacyWmts = new LegacyGeoServerWmtsAdapter();
const martin = new MartinMvtAdapter();
const titiler = new TiTilerAdapter();
const dynamic = new CesiumDynamicAdapter();
const threeD = new ThreeDTilesAdapter();

const adapters: Record<(typeof SUPPORTED_ADAPTER_KEYS)[number], GisLayerAdapter> = {
  'QGIS_WMS|RASTER_WMS': qgis,
  'GEOSERVER_WMS_LEGACY|RASTER_WMS': legacy,
  'GEOSERVER_WMS_LEGACY|RASTER_TILE': legacyWmts,
  'MARTIN_MVT|VECTOR_TILE': martin,
  'TITILER|RASTER_TILE': titiler,
  'FASTAPI|DYNAMIC_PRIMITIVE': dynamic,
  'CESIUM_DYNAMIC|DYNAMIC_PRIMITIVE': dynamic,
  'THREE_D_TILES|THREE_D': threeD,
};

export class UnsupportedAdapterError extends Error {}

export function adapterFor(layer: LayerRuntime): GisLayerAdapter {
  const key = `${layer.serviceMode}|${layer.renderMode}` as keyof typeof adapters;
  const adapter = adapters[key];
  if (!adapter) throw new UnsupportedAdapterError(`UNSUPPORTED_GIS_ADAPTER: ${key}`);
  return adapter;
}
