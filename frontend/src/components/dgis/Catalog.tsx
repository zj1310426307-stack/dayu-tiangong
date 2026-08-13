import { Badge, Button, Card, Space, Tag } from 'antd';

import type { DGISCatalogResponse } from '../../api/generated/client';


interface CatalogProps {
  catalog: DGISCatalogResponse | null;
  loading: boolean;
}


/** Summarize component ownership and live service state from the DGIS catalog. */
export function Catalog({ catalog, loading }: CatalogProps) {
  return (
    <Card size="small" loading={loading} title="Catalog · 开源 GIS 服务目录">
      <Space wrap>
        {(catalog?.components ?? []).map((component) => (
          <Tag key={component.key} color={component.status === 'online' ? 'success' : component.status === 'offline' ? 'error' : 'default'}>
            <Badge status={component.status === 'online' ? 'success' : component.status === 'offline' ? 'error' : 'default'} />
            {component.name} · {component.status}
          </Tag>
        ))}
        {catalog?.geonode_url && (
          <Button href={catalog.geonode_url} target="_blank" rel="noreferrer">
            打开 GeoNode 数据目录
          </Button>
        )}
      </Space>
      <p className="dgis-note">GeoNode 管理资产与元数据；FastAPI 继续负责水利模型、调度、分析和 AI。</p>
    </Card>
  );
}
