import { Card, Select, Space, Switch, Tag } from 'antd';

import type { SimulationLayerRecord } from '../../api/generated/client';


interface RasterLayerProps {
  layers: SimulationLayerRecord[];
  selectedId: number | null;
  onChange: (value: number | null) => void;
}


/** Select one registered COG while exposing its model-result provenance and units. */
export function RasterLayer({ layers, selectedId, onChange }: RasterLayerProps) {
  const selected = layers.find((layer) => layer.id === selectedId);
  return (
    <Card size="small" title="RasterLayer · 水动力 COG">
      <Space wrap>
        <Switch checked={selectedId !== null} onChange={(checked) => onChange(checked ? layers[0]?.id ?? null : null)} />
        <Select
          allowClear value={selectedId ?? undefined} placeholder="选择水深 / 流速 / 风险"
          options={layers.map((layer) => ({ value: layer.id, label: layer.name }))}
          onChange={(value) => onChange(value ?? null)} style={{ minWidth: 210 }}
        />
        {selected && <Tag color="blue">{String(selected.style.unit ?? selected.layer_type)}</Tag>}
      </Space>
    </Card>
  );
}
