import { DownOutlined, UpOutlined } from '@ant-design/icons';
import { Button, Checkbox, Slider } from 'antd';

export interface LayerManagerItem {
  key: string;
  label: string;
  group: string;
  groupTitle: string;
  groupOrder: number;
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

/** Render Catalog groups without owning business layer names or ordering. */
export function LayerManager({
  basemapLabel, basemapVisible, items, onBasemapChange, onLayerChange, onMove,
}: LayerManagerProps) {
  return (
    <div className="layer-control" aria-label="ArcGIS 风格图层管理">
      <div className="layer-control__title"><strong>LayerManager</strong><span>显示 · 透明度 · 顺序</span></div>
      {[...new Map(items.map((item) => [item.group, { key: item.group, title: item.groupTitle, order: item.groupOrder }])).values()]
        .sort((left, right) => left.order - right.order || left.key.localeCompare(right.key))
        .map(({ key: group, title }) => {
        const groupItems = items.filter((item) => item.group === group);
        return (
          <section className="layer-control__group" key={group} aria-label={title}>
            <div className="layer-control__group-title">{title}</div>
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
      <section className="layer-control__group" aria-label="底图">
        <div className="layer-control__group-title">底图</div>
        <div className="layer-control__row">
          <Checkbox checked={basemapVisible} onChange={(event) => onBasemapChange(event.target.checked)}>{basemapLabel}</Checkbox>
        </div>
      </section>
      <div className="layer-legend">
        <span><i className="legend-normal" />正常</span><span><i className="legend-warning" />警戒</span><span><i className="legend-danger" />危险</span>
        <span><i className="legend-flow" />流向</span><span><i className="legend-running" />运行/开启</span>
      </div>
    </div>
  );
}
