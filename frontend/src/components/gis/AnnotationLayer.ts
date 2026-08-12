import {
  Cartesian2, Cartesian3, Color, HorizontalOrigin, LabelCollection, LabelStyle,
  VerticalOrigin, type Scene,
} from 'cesium';
import type { AnnotationRecord } from '../../api/generated/client';

/** Own one Cesium LabelCollection and update it in place for scale/time changes. */
export class AnnotationLayer {
  private readonly labels: LabelCollection;

  constructor(scene: Scene) {
    this.labels = scene.primitives.add(new LabelCollection({ scene }));
  }

  /** Replace one bounded annotation page without allocating Cesium Entities. */
  sync(items: AnnotationRecord[], scaleDenominator: number): void {
    this.labels.removeAll();
    const displayItems = items.length > 500
      ? clusterAnnotations(items, Math.max(0.004, scaleDenominator / 12_500_000))
      : items.map((item) => ({
        id: item.id, longitude: item.longitude, latitude: item.latitude,
        text: item.display_text, fontSize: item.font_size ?? 14, color: item.color ?? '#E8F7FF',
      }));
    for (const item of displayItems) {
      this.labels.add({
        id: { kind: 'annotation', annotationId: item.id },
        position: Cartesian3.fromDegrees(item.longitude, item.latitude, 70),
        text: item.text,
        font: `600 ${item.fontSize}px "Microsoft YaHei", sans-serif`,
        fillColor: Color.fromCssColorString(item.color),
        outlineColor: Color.fromCssColorString('#06101c'),
        outlineWidth: 3,
        style: LabelStyle.FILL_AND_OUTLINE,
        pixelOffset: new Cartesian2(0, -12),
        horizontalOrigin: HorizontalOrigin.CENTER,
        verticalOrigin: VerticalOrigin.BOTTOM,
        showBackground: true,
        backgroundColor: Color.fromCssColorString('#05141f').withAlpha(0.72),
        backgroundPadding: new Cartesian2(7, 4),
      });
    }
  }

  /** Remove the primitive collection when its owning Viewer is torn down. */
  destroy(scene: Scene): void {
    scene.primitives.remove(this.labels);
  }

  get count(): number {
    return this.labels.length;
  }
}

interface DisplayAnnotation {
  id: string | number;
  longitude: number;
  latitude: number;
  text: string;
  fontSize: number;
  color: string;
}

/** Aggregate dense labels into deterministic geographic grid cells before Cesium allocation. */
function clusterAnnotations(items: AnnotationRecord[], gridDegrees: number): DisplayAnnotation[] {
  const bins = new Map<string, AnnotationRecord[]>();
  for (const item of items) {
    const key = `${Math.floor(item.longitude / gridDegrees)}:${Math.floor(item.latitude / gridDegrees)}`;
    bins.set(key, [...(bins.get(key) ?? []), item]);
  }
  return [...bins.entries()].map(([key, members]) => ({
    id: `cluster-${key}`,
    longitude: members.reduce((sum, item) => sum + item.longitude, 0) / members.length,
    latitude: members.reduce((sum, item) => sum + item.latitude, 0) / members.length,
    text: members.length === 1 ? members[0].display_text : `${members.length} 条注记`,
    fontSize: members.length === 1 ? members[0].font_size ?? 14 : 13,
    color: members.length === 1 ? members[0].color ?? '#E8F7FF' : '#FFC85C',
  }));
}
