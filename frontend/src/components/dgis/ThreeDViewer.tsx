import { Card, Select, Space, Switch, Tag } from 'antd';
import { Cesium3DTileset } from 'cesium';
import { useEffect } from 'react';

import type { ThreeDTilesAsset } from '../../api/generated/client';


interface ThreeDViewerProps {
  assets: ThreeDTilesAsset[];
  selectedId: number | null;
  onChange: (value: number | null) => void;
  onTilesetsChange: (tilesets: Cesium3DTileset[]) => void;
}


/** Load registered 3D Tiles with Cesium's native runtime and cleanly release old assets. */
export function ThreeDViewer({ assets, selectedId, onChange, onTilesetsChange }: ThreeDViewerProps) {
  const selected = assets.find((asset) => asset.layer_id === selectedId);
  useEffect(() => {
    let disposed = false;
    if (!selected) {
      onTilesetsChange([]);
      return undefined;
    }
    void Cesium3DTileset.fromUrl(selected.tileset_url, {
      maximumScreenSpaceError: selected.maximum_screen_space_error,
    }).then((tileset) => {
      if (!disposed) onTilesetsChange([tileset]);
    }).catch(() => { if (!disposed) onTilesetsChange([]); });
    return () => { disposed = true; onTilesetsChange([]); };
  }, [onTilesetsChange, selected]);
  return (
    <Card size="small" title="ThreeDViewer · 三维工程设施">
      <Space wrap>
        <Switch checked={selectedId !== null} onChange={(checked) => onChange(checked ? assets[0]?.layer_id ?? null : null)} />
        <Select
          allowClear value={selectedId ?? undefined} placeholder="选择 3D Tiles"
          options={assets.map((asset) => ({ value: asset.layer_id, label: asset.name }))}
          onChange={(value) => onChange(value ?? null)} style={{ minWidth: 210 }}
        />
        {selected && <Tag>{selected.version}</Tag>}
      </Space>
    </Card>
  );
}
