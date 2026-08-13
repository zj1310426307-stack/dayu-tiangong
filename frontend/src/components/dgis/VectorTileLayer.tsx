import { Card, Select, Space, Switch } from 'antd';


interface VectorTileLayerProps {
  sources: string[];
  selected: string | null;
  onChange: (value: string | null) => void;
}


/** Select one Martin MVT source for Cesium's native vector-tile provider. */
export function VectorTileLayer({ sources, selected, onChange }: VectorTileLayerProps) {
  return (
    <Card size="small" title="VectorTileLayer · 大规模矢量">
      <Space wrap>
        <Switch checked={selected !== null} onChange={(checked) => onChange(checked ? sources[0] ?? null : null)} />
        <Select
          allowClear value={selected ?? undefined} placeholder="选择 Martin MVT"
          options={sources.map((source) => ({ value: source, label: source }))}
          onChange={(value) => onChange(value ?? null)} style={{ minWidth: 210 }}
        />
      </Space>
    </Card>
  );
}
