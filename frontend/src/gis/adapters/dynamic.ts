import { Cartesian3, Color, Material, Math as CesiumMath, PointPrimitiveCollection, PolylineCollection } from 'cesium';
import type { GISStructureSample, GISWaterSample } from '../../api/generated/client';
import type { LayerRuntime } from '../catalog/runtime';
import type { AdapterContext, AdapterHandle, CatalogPick, GisLayerAdapter } from './types';
import { layerSignature } from './types';

interface DynamicResources { points: PointPrimitiveCollection; lines: PolylineCollection; }

const riskColor = (level: GISWaterSample['risk_level'], opacity: number) => level === 'danger' ? Color.fromCssColorString('#ff5b62').withAlpha(opacity) : level === 'warning' ? Color.fromCssColorString('#ffc85c').withAlpha(opacity) : Color.fromCssColorString('#2fe6d6').withAlpha(opacity);
const velocityColor = (level: GISWaterSample['velocity_level'], opacity: number) => level === 'high' ? Color.fromCssColorString('#a972ff').withAlpha(opacity) : level === 'medium' ? Color.fromCssColorString('#3b8fff').withAlpha(opacity) : Color.fromCssColorString('#77d9ff').withAlpha(opacity);

function arrowEnd(sample: GISWaterSample): Cartesian3 {
  const bearing = CesiumMath.toRadians(sample.flow_bearing_degrees);
  const distance = 900;
  return Cartesian3.fromDegrees(sample.longitude + Math.sin(bearing) * distance / (111_320 * Math.max(0.2, Math.cos(CesiumMath.toRadians(sample.latitude)))), sample.latitude + Math.cos(bearing) * distance / 110_540, 45);
}

function pick(layer: LayerRuntime, id: number, properties: Record<string, unknown>): CatalogPick {
  return { kind: 'catalog-feature', identity: { layerKey: layer.key, featureId: id, datasetVersionId: layer.datasetVersionId }, detailRouteKey: layer.descriptor.identify.detail_route_key as string | null, properties };
}

export class CesiumDynamicAdapter implements GisLayerAdapter {
  async create(context: AdapterContext, layer: LayerRuntime): Promise<AdapterHandle> {
    const resources = { points: context.viewer.scene.primitives.add(new PointPrimitiveCollection()), lines: context.viewer.scene.primitives.add(new PolylineCollection()) };
    const handle = { layerKey: layer.key, signature: layerSignature(layer), resource: resources };
    await this.update(context, handle, layer);
    return handle;
  }
  async update(context: AdapterContext, handle: AdapterHandle, layer: LayerRuntime): Promise<void> {
    const resources = handle.resource as DynamicResources;
    resources.points.removeAll(); resources.lines.removeAll();
    if (!layer.visible) return;
    const water = context.interactionFrame?.water_samples ?? [];
    const structures = context.interactionFrame?.structure_samples ?? [];
    if (layer.key === 'water_result' || layer.key === 'risk_result' || layer.key === 'velocity_result') {
      for (const sample of water) {
        const color = layer.key === 'risk_result' ? riskColor(sample.risk_level, layer.opacity) : layer.key === 'velocity_result' ? velocityColor(sample.velocity_level, layer.opacity) : Color.fromCssColorString('#2fe6d6').withAlpha(layer.opacity);
        resources.points.add({ position: Cartesian3.fromDegrees(sample.longitude, sample.latitude, 70), pixelSize: layer.key === 'risk_result' && sample.risk_level === 'danger' ? 14 : 9, color, outlineColor: Color.WHITE.withAlpha(0.8), outlineWidth: 1.5, id: pick(layer, sample.section_id, sample as unknown as Record<string, unknown>) });
        if (layer.key === 'velocity_result' && sample.flow_direction !== 'stationary') resources.lines.add({ positions: [Cartesian3.fromDegrees(sample.longitude, sample.latitude, 75), arrowEnd(sample)], width: sample.velocity_level === 'high' ? 5 : 3, material: Material.fromType('PolylineArrow', { color }), id: pick(layer, sample.section_id, sample as unknown as Record<string, unknown>) });
      }
    }
    if (layer.key === 'gate_status' || layer.key === 'pump_status') {
      const expected = layer.key === 'gate_status' ? 'gate' : 'pump';
      for (const sample of structures.filter((item) => item.structure_type === expected)) this.addStructure(resources.points, layer, sample);
    }
    context.viewer.scene.requestRender();
  }
  private addStructure(points: PointPrimitiveCollection, layer: LayerRuntime, sample: GISStructureSample): void {
    const active = sample.state === 'open' || sample.state === 'running';
    points.add({ position: Cartesian3.fromDegrees(sample.longitude, sample.latitude, 100), pixelSize: sample.structure_type === 'gate' ? 15 : 17, color: (active ? Color.fromCssColorString('#48e58b') : Color.fromCssColorString('#8092a2')).withAlpha(layer.opacity), outlineColor: sample.constraint_flags.length ? Color.fromCssColorString('#ffc85c') : Color.WHITE.withAlpha(0.8), outlineWidth: sample.constraint_flags.length ? 3 : 1.5, id: pick(layer, sample.structure_id, sample as unknown as Record<string, unknown>) });
  }
  setVisible(handle: AdapterHandle, visible: boolean): void { const value = handle.resource as DynamicResources; value.points.show = visible; value.lines.show = visible; }
  setOpacity(_handle: AdapterHandle, _opacity: number): void { /* update rebuilds primitives with canonical colors. */ }
  destroy(context: AdapterContext, handle: AdapterHandle): void { const value = handle.resource as DynamicResources; if (!context.viewer.isDestroyed()) { context.viewer.scene.primitives.remove(value.points); context.viewer.scene.primitives.remove(value.lines); } }
}
