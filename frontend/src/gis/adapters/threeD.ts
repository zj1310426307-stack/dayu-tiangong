import { Cesium3DTileset } from 'cesium';
import type { LayerRuntime } from '../catalog/runtime';
import type { AdapterContext, AdapterHandle, GisLayerAdapter } from './types';
import { layerSignature } from './types';

export class ThreeDTilesAdapter implements GisLayerAdapter {
  async create(context: AdapterContext, layer: LayerRuntime): Promise<AdapterHandle> {
    const path = String(layer.descriptor.service.tileset_path ?? layer.service.endpoint);
    if (!path.startsWith('/3d/')) throw new Error(`THREE_D_PATH_BLOCKED: ${layer.key}`);
    const tileset = await Cesium3DTileset.fromUrl(path);
    context.viewer.scene.primitives.add(tileset);
    tileset.show = layer.visible;
    return { layerKey: layer.key, signature: layerSignature(layer), resource: tileset };
  }
  async update(_context: AdapterContext, handle: AdapterHandle, layer: LayerRuntime): Promise<void> { this.setVisible(handle, layer.visible); }
  setVisible(handle: AdapterHandle, visible: boolean): void { (handle.resource as Cesium3DTileset).show = visible; }
  setOpacity(_handle: AdapterHandle, _opacity: number): void { /* 3D style is asset-owned. */ }
  destroy(context: AdapterContext, handle: AdapterHandle): void { if (!context.viewer.isDestroyed()) context.viewer.scene.primitives.remove(handle.resource as Cesium3DTileset); }
}
