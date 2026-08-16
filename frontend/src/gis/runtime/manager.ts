import type { GISInteractionFrame } from '../../api/generated/client';
import type { Viewer } from 'cesium';
import type { LayerRuntime } from '../catalog/runtime';
import { adapterFor } from '../adapters/registry';
import type { AdapterHandle } from '../adapters/types';
import { layerSignature } from '../adapters/types';

interface Managed { handle: AdapterHandle; layer: LayerRuntime; }

export class GisAdapterRuntime {
  private readonly managed = new Map<string, Managed>();
  private generation = 0;
  readonly errors = new Map<string, string>();

  constructor(private readonly viewer: Viewer) {}

  async sync(layers: LayerRuntime[], interactionFrame: GISInteractionFrame | null): Promise<void> {
    const generation = ++this.generation;
    const next = new Map(layers.map((layer) => [layer.key, layer]));
    for (const [key, current] of this.managed) {
      const desired = next.get(key);
      if (!desired || current.handle.signature !== layerSignature(desired)) {
        adapterFor(current.layer).destroy({ viewer: this.viewer, interactionFrame }, current.handle);
        this.managed.delete(key);
      }
    }
    await Promise.allSettled(layers.map(async (layer) => {
      try {
        const adapter = adapterFor(layer);
        const current = this.managed.get(layer.key);
        if (current) {
          current.layer = layer;
          await adapter.update({ viewer: this.viewer, interactionFrame }, current.handle, layer);
        } else {
          const handle = await adapter.create({ viewer: this.viewer, interactionFrame }, layer);
          if (generation !== this.generation || this.viewer.isDestroyed()) {
            adapter.destroy({ viewer: this.viewer, interactionFrame }, handle);
            return;
          }
          this.managed.set(layer.key, { handle, layer });
        }
        this.errors.delete(layer.key);
      } catch (error) {
        this.errors.set(layer.key, error instanceof Error ? error.message : 'ADAPTER_CREATE_FAILED');
      }
    }));
    if (!this.viewer.isDestroyed()) this.viewer.scene.requestRender();
  }

  setState(key: string, update: { visible?: boolean; opacity?: number }): void {
    const current = this.managed.get(key);
    if (!current) return;
    const adapter = adapterFor(current.layer);
    if (update.visible !== undefined) adapter.setVisible(current.handle, update.visible);
    if (update.opacity !== undefined) adapter.setOpacity(current.handle, update.opacity);
    current.layer = { ...current.layer, visible: update.visible ?? current.layer.visible, opacity: update.opacity ?? current.layer.opacity };
    this.viewer.scene.requestRender();
  }

  raiseInOrder(keys: string[]): void {
    for (const key of keys) {
      const resource = this.managed.get(key)?.handle.resource;
      if (resource && typeof resource === 'object' && 'imageryProvider' in resource) this.viewer.imageryLayers.raiseToTop(resource as never);
    }
  }

  destroy(interactionFrame: GISInteractionFrame | null): void {
    ++this.generation;
    for (const current of this.managed.values()) adapterFor(current.layer).destroy({ viewer: this.viewer, interactionFrame }, current.handle);
    this.managed.clear();
  }
}
