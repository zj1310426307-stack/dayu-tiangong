import {
  MVTDataProvider,
  UrlTemplateImageryProvider,
  WebMapServiceImageryProvider,
  WebMapTileServiceImageryProvider,
  type ImageryLayer,
} from 'cesium';
import type { LayerRuntime } from '../catalog/runtime';
import type { AdapterContext, AdapterHandle, GisLayerAdapter } from './types';
import { layerSignature } from './types';

function imageHandle(layer: LayerRuntime, resource: ImageryLayer): AdapterHandle {
  resource.show = layer.visible;
  resource.alpha = layer.opacity;
  return { layerKey: layer.key, signature: layerSignature(layer), resource };
}

abstract class ImageryAdapter implements GisLayerAdapter {
  abstract create(context: AdapterContext, layer: LayerRuntime): Promise<AdapterHandle>;
  async update(_context: AdapterContext, handle: AdapterHandle, layer: LayerRuntime): Promise<void> {
    this.setVisible(handle, layer.visible);
    this.setOpacity(handle, layer.opacity);
  }
  setVisible(handle: AdapterHandle, visible: boolean): void { (handle.resource as ImageryLayer).show = visible; }
  setOpacity(handle: AdapterHandle, opacity: number): void { (handle.resource as ImageryLayer).alpha = opacity; }
  destroy(context: AdapterContext, handle: AdapterHandle): void {
    if (!context.viewer.isDestroyed()) context.viewer.imageryLayers.remove(handle.resource as ImageryLayer, true);
  }
}

export class QgisWmsAdapter extends ImageryAdapter {
  async create(context: AdapterContext, layer: LayerRuntime): Promise<AdapterHandle> {
    if (!layer.descriptor.capabilities.render) throw new Error(`QGIS_LAYER_UNAVAILABLE: ${layer.key}`);
    const endpoint = layer.service.endpoint.replace(/\/$/, '');
    const url = `${endpoint}?request=GetMap&dataset_version_id=${layer.datasetVersionId}&layer_key=${encodeURIComponent(layer.key)}&bbox={westDegrees},{southDegrees},{eastDegrees},{northDegrees}&width=256&height=256&crs=EPSG:4490&format=image/png&transparent=true`;
    const provider = new UrlTemplateImageryProvider({ url, maximumLevel: 20, credit: 'QGIS Server / PostGIS / CGCS2000' });
    return imageHandle(layer, context.viewer.imageryLayers.addImageryProvider(provider));
  }
}

export class LegacyGeoServerWmsAdapter extends ImageryAdapter {
  async create(context: AdapterContext, layer: LayerRuntime): Promise<AdapterHandle> {
    const provider = new WebMapServiceImageryProvider({
      url: layer.service.endpoint,
      layers: `dayu:${layer.key}`,
      parameters: { transparent: true, format: 'image/png', version: '1.1.1', CQL_FILTER: `dataset_version_id=${layer.datasetVersionId}` },
      getFeatureInfoParameters: { info_format: 'application/json', feature_count: 5, CQL_FILTER: `dataset_version_id=${layer.datasetVersionId}` },
      srs: 'EPSG:4490', enablePickFeatures: layer.descriptor.identify_enabled,
    });
    return imageHandle(layer, context.viewer.imageryLayers.addImageryProvider(provider));
  }
}

export class LegacyGeoServerWmtsAdapter extends ImageryAdapter {
  async create(context: AdapterContext, layer: LayerRuntime): Promise<AdapterHandle> {
    const endpoint = layer.service.wmts_endpoint;
    if (!endpoint) throw new Error(`LEGACY_WMTS_ENDPOINT_MISSING: ${layer.key}`);
    const provider = new WebMapTileServiceImageryProvider({
      url: endpoint, layer: `dayu:${layer.key}`, style: '', format: 'image/png',
      tileMatrixSetID: 'EPSG:900913',
      tileMatrixLabels: Array.from({ length: 23 }, (_, level) => `EPSG:900913:${level}`),
      maximumLevel: 22, enablePickFeatures: false,
      dimensions: { CQL_FILTER: `dataset_version_id=${layer.datasetVersionId}` },
      credit: 'GeoWebCache legacy compatibility',
    });
    return imageHandle(layer, context.viewer.imageryLayers.addImageryProvider(provider));
  }
}

export class TiTilerAdapter extends ImageryAdapter {
  async create(context: AdapterContext, layer: LayerRuntime): Promise<AdapterHandle> {
    const endpoint = String(layer.descriptor.service.endpoint ?? layer.service.endpoint);
    const provider = new UrlTemplateImageryProvider({ url: endpoint, maximumLevel: 18, credit: 'TiTiler / COG' });
    return imageHandle(layer, context.viewer.imageryLayers.addImageryProvider(provider));
  }
}

export class MartinMvtAdapter implements GisLayerAdapter {
  async create(context: AdapterContext, layer: LayerRuntime): Promise<AdapterHandle> {
    const source = String(layer.descriptor.service.source ?? layer.key);
    const provider = await MVTDataProvider.fromUrl(`/vector/${encodeURIComponent(source)}/{z}/{x}/{y}?dataset_version_id=${layer.datasetVersionId}`, { minZoom: 0, maxZoom: 18, featureIdProperty: 'id' });
    context.viewer.scene.primitives.add(provider);
    provider.show = layer.visible;
    return { layerKey: layer.key, signature: layerSignature(layer), resource: provider };
  }
  async update(_context: AdapterContext, handle: AdapterHandle, layer: LayerRuntime): Promise<void> { this.setVisible(handle, layer.visible); }
  setVisible(handle: AdapterHandle, visible: boolean): void { (handle.resource as MVTDataProvider).show = visible; }
  setOpacity(_handle: AdapterHandle, _opacity: number): void { /* MVT style opacity is provider-owned. */ }
  destroy(context: AdapterContext, handle: AdapterHandle): void { if (!context.viewer.isDestroyed()) context.viewer.scene.primitives.remove(handle.resource as MVTDataProvider); }
}
