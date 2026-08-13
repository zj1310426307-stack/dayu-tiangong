import { Card, Tree } from 'antd';
import type { DataNode } from 'antd/es/tree';

import type { DGISCatalogResponse } from '../../api/generated/client';


interface LayerTreeProps {
  catalog: DGISCatalogResponse | null;
}


/** Present vector, raster, and 3D assets as one version-owned layer hierarchy. */
export function LayerTree({ catalog }: LayerTreeProps) {
  const nodes: DataNode[] = [
    {
      key: 'vector', title: 'Vector Tile · Martin',
      children: (catalog?.vector_tile_sources ?? []).map((source) => ({ key: `vector:${source}`, title: source })),
    },
    {
      key: 'raster', title: 'Raster Layer · TiTiler',
      children: (catalog?.simulation_layers ?? [])
        .filter((layer) => layer.service_type === 'TITILER')
        .map((layer) => ({ key: `raster:${layer.id}`, title: layer.name })),
    },
    {
      key: '3d', title: '3D Tiles · Cesium',
      children: (catalog?.simulation_layers ?? [])
        .filter((layer) => layer.service_type === '3D_TILES')
        .map((layer) => ({ key: `3d:${layer.id}`, title: layer.name })),
    },
  ];
  return <Card size="small" title="LayerTree · 图层树"><Tree treeData={nodes} defaultExpandedKeys={['vector', 'raster', '3d']} /></Card>;
}
