import type { GISInteractionFrame } from '../../api/generated/client';
import type { Viewer } from 'cesium';
import type { LayerRuntime } from '../catalog/runtime';

export interface CatalogPick {
  kind: 'catalog-feature';
  identity: { layerKey: string; featureId: number; datasetVersionId: number };
  detailRouteKey: string | null;
  properties: Record<string, unknown>;
}

export interface AdapterContext {
  viewer: Viewer;
  interactionFrame: GISInteractionFrame | null;
}

export interface AdapterHandle {
  layerKey: string;
  signature: string;
  resource: unknown;
  auxiliary?: unknown;
}

export interface GisLayerAdapter {
  create(context: AdapterContext, layer: LayerRuntime): Promise<AdapterHandle>;
  update(context: AdapterContext, handle: AdapterHandle, layer: LayerRuntime): Promise<void>;
  setVisible(handle: AdapterHandle, visible: boolean): void;
  setOpacity(handle: AdapterHandle, opacity: number): void;
  destroy(context: AdapterContext, handle: AdapterHandle): void;
}

export const layerSignature = (layer: LayerRuntime) => `${layer.serviceMode}|${layer.renderMode}|${layer.datasetVersionId}|${layer.service.revision ?? ''}`;
