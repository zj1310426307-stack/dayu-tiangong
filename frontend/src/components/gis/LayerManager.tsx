import { DownOutlined, UpOutlined } from '@ant-design/icons';
import { Button, Checkbox, Slider } from 'antd';

export type LayerGroupKey = 'base' | 'engineering' | 'analysis' | 'dispatch';

export interface LayerManagerItem {
  key: string;
  label: string;
  group: LayerGroupKey;
  visible: boolean;
  opacity: number;
  dynamic?: boolean;
}

interface LayerManagerProps {
  basemapLabel: string;
  basemapVisible: boolean;
  items: LayerManagerItem[];
  onBasemapChange: (visible: boolean) => void;
  onLayerChange: (key: string, update: { visible?: boolean; opacity?: number }) => void;
  onMove: (key: string, direction: 'up' | 'down') => void;
}

const groupLabels: Record<LayerGroupKey, string> = {
  base: '基础地图', engineering: '水利工程', analysis: '分析结果', dispatch: '调度状态',
};

/** Render an ArcGIS-style grouped layer tree with visibility, opacity, and draw order. */
export function LayerManager({
  basemapLabel, basemapVisible, items, onBasemapChange, onLayerChange, onMove,
}: LayerManagerProps) {
  return (
    <div className="layer-control" aria-label="ArcGIS 风格图层管理">
      <div className="layer-control__title"><strong>LayerManager</strong><span>显示 · 透明度 · 顺序</span></div>
      {(Object.keys(groupLabels) as LayerGroupKey[]).map((group) => {
        const groupItems = items.filter((item) => item.group === group);
        return (
          <section className="layer-control__group" key={group} aria-label={groupLabels[group]}>
            <div className="layer-control__group-title">{groupLabels[group]}</div>
            {group === 'base' && (
              <div className="layer-control__row">
                <Checkbox checked={basemapVisible} onChange={(event) => onBasemapChange(event.target.checked)}>{basemapLabel}</Checkbox>
              </div>
            )}
            {groupItems.map((item, index) => (
              <div className={`layer-control__row ${item.dynamic ? 'layer-control__row--dynamic' : ''}`} key={item.key}>
                <Checkbox checked={item.visible} onChange={(event) => onLayerChange(item.key, { visible: event.target.checked })}>{item.label}</Checkbox>
                <Slider min={0.1} max={1} step={0.1} value={item.opacity} onChange={(value) => onLayerChange(item.key, { opacity: value })} tooltip={{ formatter: (value) => `${Math.round((value ?? 0) * 100)}%` }} />
                <span className="layer-control__order">
                  <Button type="text" size="small" disabled={index === 0} icon={<UpOutlined />} aria-label={`上移${item.label}`} onClick={() => onMove(item.key, 'up')} />
                  <Button type="text" size="small" disabled={index === groupItems.length - 1} icon={<DownOutlined />} aria-label={`下移${item.label}`} onClick={() => onMove(item.key, 'down')} />
                </span>
              </div>
            ))}
          </section>
        );
      })}
      <div className="layer-legend">
        <span><i className="legend-normal" />正常</span><span><i className="legend-warning" />警戒</span><span><i className="legend-danger" />危险</span>
        <span><i className="legend-flow" />流向</span><span><i className="legend-running" />运行/开启</span>
      </div>
    </div>
  );
}
