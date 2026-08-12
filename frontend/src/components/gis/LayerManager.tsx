import { Checkbox, Slider } from 'antd';

export interface LayerManagerItem {
  key: string;
  label: string;
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
}

/** Render one reusable layer directory with visibility and opacity semantics. */
export function LayerManager({
  basemapLabel, basemapVisible, items, onBasemapChange, onLayerChange,
}: LayerManagerProps) {
  return (
    <div className="layer-control" aria-label="专业图层管理">
      <div className="layer-control__title"><strong>LayerManager</strong><span>显示 · 透明度</span></div>
      <div className="layer-control__row">
        <Checkbox checked={basemapVisible} onChange={(event) => onBasemapChange(event.target.checked)}>{basemapLabel}</Checkbox>
      </div>
      {items.map((item) => (
        <div className={`layer-control__row ${item.dynamic ? 'layer-control__row--dynamic' : ''}`} key={item.key}>
          <Checkbox checked={item.visible} onChange={(event) => onLayerChange(item.key, { visible: event.target.checked })}>{item.label}</Checkbox>
          <Slider min={0.1} max={1} step={0.1} value={item.opacity} onChange={(value) => onLayerChange(item.key, { opacity: value })} tooltip={{ formatter: (value) => `${Math.round((value ?? 0) * 100)}%` }} />
        </div>
      ))}
      <div className="layer-legend">
        <span><i className="legend-normal" />正常</span><span><i className="legend-warning" />警戒</span><span><i className="legend-danger" />危险</span>
        <span><i className="legend-flow" />流向</span><span><i className="legend-running" />运行/开启</span>
      </div>
    </div>
  );
}
