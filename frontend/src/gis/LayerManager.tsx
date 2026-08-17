import { ArrowDownOutlined, ArrowUpOutlined } from '@ant-design/icons';
import { Button, Slider, Switch } from 'antd';
import { layerAccent } from './StyleManager';

export interface WebLayerState {
  key: string;
  title: string;
  groupTitle: string;
  visible: boolean;
  opacity: number;
  identifyEnabled: boolean;
}

interface LayerManagerProps {
  layers: WebLayerState[];
  onVisibility: (key: string, visible: boolean) => void;
  onOpacity: (key: string, opacity: number) => void;
  onMove: (key: string, direction: -1 | 1) => void;
  hidden?: boolean;
}

/** Control only presentation state; sources and styles remain Catalog-owned. */
export function LayerManager({ layers, onVisibility, onOpacity, onMove, hidden = false }: LayerManagerProps) {
  return (
    <aside id="gis-layer-tool" className="ol-layer-manager" aria-label="图层管理" hidden={hidden}>
      <header><strong>图层管理</strong><span>{layers.filter((item) => item.visible).length}/{layers.length}</span></header>
      <div className="ol-layer-manager__list">
        {[...layers].reverse().map((layer, reverseIndex) => {
          const index = layers.length - 1 - reverseIndex;
          return (
            <section key={layer.key} className="ol-layer-row">
              <div className="ol-layer-row__title">
                <i style={{ background: layerAccent(layer.key) }} />
                <div><strong>{layer.title}</strong><small>{layer.groupTitle}</small></div>
                <Switch size="small" checked={layer.visible} onChange={(checked) => onVisibility(layer.key, checked)} />
              </div>
              <div className="ol-layer-row__controls">
                <Slider min={0} max={100} value={Math.round(layer.opacity * 100)} onChange={(value) => onOpacity(layer.key, value / 100)} tooltip={{ formatter: (value) => `${value}%` }} />
                <Button size="small" type="text" icon={<ArrowUpOutlined />} disabled={index === layers.length - 1} onClick={() => onMove(layer.key, 1)} aria-label={`上移${layer.title}`} />
                <Button size="small" type="text" icon={<ArrowDownOutlined />} disabled={index === 0} onClick={() => onMove(layer.key, -1)} aria-label={`下移${layer.title}`} />
              </div>
            </section>
          );
        })}
      </div>
    </aside>
  );
}
