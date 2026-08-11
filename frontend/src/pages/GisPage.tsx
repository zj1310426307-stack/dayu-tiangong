import { CesiumMap } from '../components/gis/CesiumMap';

export function GisPage() {
  return (
    <div className="gis-page">
      <header className="gis-page__header">
        <div>
          <span className="hero-kicker"><i /> SPATIAL FOUNDATION</span>
          <h1>GIS 一张图空间底座</h1>
          <p>真实 PostGIS 空间对象、GeoJSON 服务与 Cesium 图层交互已贯通。</p>
        </div>
        <span className="gis-page__badge">PHASE 1 · DEMO DATA</span>
      </header>
      <CesiumMap variant="workspace" />
    </div>
  );
}
