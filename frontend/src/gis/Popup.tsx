import { CloseOutlined } from '@ant-design/icons';
import { Button, Empty } from 'antd';
import type { CatalogFeature } from '../api/generated/client';

export interface PopupSelection {
  layerTitle: string;
  pixel: [number, number];
  features: CatalogFeature[];
}

/** Render bounded, sanitized attributes returned by the FastAPI gateway. */
export function Popup({ selection, onClose }: { selection: PopupSelection | null; onClose: () => void }) {
  if (!selection) return null;
  const feature = selection.features[0];
  const style = { left: Math.min(selection.pixel[0] + 14, 680), top: Math.max(selection.pixel[1] - 20, 64) };
  return (
    <aside className="ol-popup" style={style} aria-label="要素属性">
      <header>
        <div><small>图层</small><strong>{selection.layerTitle}</strong></div>
        <Button type="text" size="small" icon={<CloseOutlined />} onClick={onClose} aria-label="关闭属性窗口" />
      </header>
      {!feature ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未点选到要素" /> : (
        <dl>
          <div><dt>ID</dt><dd>{feature.id}</dd></div>
          {Object.entries(feature.properties).slice(0, 30).map(([key, value]) => (
            <div key={key}><dt>{key}</dt><dd>{typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value ?? '—')}</dd></div>
          ))}
        </dl>
      )}
    </aside>
  );
}
