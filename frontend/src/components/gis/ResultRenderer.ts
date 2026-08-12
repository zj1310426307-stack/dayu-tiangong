import { Cartesian3, Color, Material, PointPrimitiveCollection, PolylineCollection, type Scene } from 'cesium';
import type { GISComparisonFrame, SpatialFeature } from '../../api/generated/client';

/** Render analysis and A/B difference results through Cesium primitive collections. */
export class ResultRenderer {
  private readonly points: PointPrimitiveCollection;
  private readonly lines: PolylineCollection;

  constructor(scene: Scene) {
    this.points = scene.primitives.add(new PointPrimitiveCollection());
    this.lines = scene.primitives.add(new PolylineCollection());
  }

  /** Draw selected point features and line/polygon boundaries with stable feature IDs. */
  renderSpatial(features: SpatialFeature[]): void {
    this.clear();
    for (const feature of features) {
      const geometry = feature.geometry as { type?: string; coordinates?: unknown };
      if (geometry.type === 'Point' && Array.isArray(geometry.coordinates)) {
        const [longitude, latitude] = geometry.coordinates as number[];
        this.points.add({
          id: { kind: 'analysis', feature }, position: Cartesian3.fromDegrees(longitude, latitude, 100),
          color: Color.fromCssColorString('#ffcf5c'), pixelSize: 12,
          outlineColor: Color.fromCssColorString('#071923'), outlineWidth: 2,
        });
      }
      if (geometry.type === 'LineString' && Array.isArray(geometry.coordinates)) {
        const coordinates = geometry.coordinates as number[][];
        this.lines.add({
          id: { kind: 'analysis', feature },
          positions: coordinates.map(([longitude, latitude]) => Cartesian3.fromDegrees(longitude, latitude, 95)),
          width: 4,
          material: Material.fromType(Material.ColorType, {
            color: Color.fromCssColorString('#ffcf5c'),
          }),
        });
      }
    }
  }

  /** Render positive/negative water differences using one bounded point collection. */
  renderComparison(frame: GISComparisonFrame | null): void {
    this.clear();
    if (!frame) return;
    for (const sample of frame.water_samples) {
      const magnitude = Math.min(18, 8 + Math.abs(sample.water_level_difference) * 8);
      this.points.add({
        id: { kind: 'comparison', sample },
        position: Cartesian3.fromDegrees(sample.longitude, sample.latitude, 120),
        color: Color.fromCssColorString(sample.water_level_difference >= 0 ? '#ff5b62' : '#38a8ff'),
        pixelSize: magnitude,
        outlineColor: Color.WHITE.withAlpha(0.8), outlineWidth: 1.5,
      });
    }
  }

  clear(): void {
    this.points.removeAll();
    this.lines.removeAll();
  }

  destroy(scene: Scene): void {
    scene.primitives.remove(this.points);
    scene.primitives.remove(this.lines);
  }
}
