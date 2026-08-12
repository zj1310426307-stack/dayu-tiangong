import { Button, Tag } from 'antd';
import { CrossSectionProfile } from './CrossSectionProfile';

export interface SelectedGISFeature {
  id: string;
  properties: Record<string, unknown>;
}

interface FeatureInspectorProps {
  feature: SelectedGISFeature;
  onClose: () => void;
  onOpenHydraulicResult: (sectionId: string) => void;
}

const fieldLabels: Record<string, string> = {
  name: '名称', code: '编码', river_id: '河道 ID', length: '长度',
  cross_section_count: '断面数量', dataset_version_id: '数据版本',
  section_code: '断面编码', section_name: '断面名称', station: '桩号',
  roughness: '糙率', elevation_min: '最低高程', survey_date: '测量日期',
  gate_code: '闸门编号', gate_type: '闸门类型', opening_direction: '开启方向',
  control_mode: '控制模式', width: '宽度', height: '高度', max_flow: '最大流量',
  bottom_elevation: '底板高程', pump_code: '泵站编号', design_flow: '设计流量',
  head: '扬程', power: '功率', status: '静态状态', water_level: '模拟水位',
  flow: '模拟流量', velocity: '模拟流速', flow_direction: '模拟流向',
  risk_level: '风险等级', actual_value: '当前模拟值', requested_value: '请求值',
  power_kw: '模拟功率', state: '模拟状态', constraint_flags: '约束标记',
  time_seconds: '仿真时刻', feature_type: '对象类型', section_id: '断面 ID',
};

const hiddenFields = new Set(['points', 'elevation_points', 'efficiency_curve', 'demo_data', 'created_time']);

/** Format compact attribute values while preserving zero and false values. */
function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (Array.isArray(value)) return value.join('、') || '—';
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(3);
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

/** Show authoritative FastAPI attributes and the professional cross-section chart. */
export function FeatureInspector({ feature, onClose, onOpenHydraulicResult }: FeatureInspectorProps) {
  const type = String(feature.properties.feature_type ?? 'feature');
  const isSection = type === 'cross_section' || type === 'water_result' || type === 'velocity_result';
  const title = isSection
    ? String(feature.properties.section_code ?? `断面 #${feature.id}`)
    : String(feature.properties.name ?? feature.properties.code ?? `对象 #${feature.id}`);
  const entries = Object.entries(feature.properties).filter(([key]) => !hiddenFields.has(key));
  return (
    <aside className="feature-inspector" aria-label="空间要素属性">
      <div className="feature-inspector__head">
        <div><span>FastAPI 业务属性</span><strong>{title}</strong></div>
        <button type="button" onClick={onClose} aria-label="关闭属性面板">×</button>
      </div>
      <div className="feature-inspector__tags">
        <Tag color="cyan">{type}</Tag>
        <Tag>ID {feature.id}</Tag>
        <Tag color="gold">DEMO / 模拟</Tag>
      </div>
      <dl>
        {entries.map(([key, value]) => (
          <div key={key}><dt>{fieldLabels[key] ?? key}</dt><dd>{displayValue(value)}</dd></div>
        ))}
      </dl>
      {isSection && (
        <CrossSectionProfile
          points={feature.properties.points ?? feature.properties.elevation_points}
          roughness={feature.properties.roughness}
          minimumElevation={feature.properties.elevation_min}
        />
      )}
      {isSection && (
        <Button block type="primary" size="small" onClick={() => onOpenHydraulicResult(feature.id)}>
          查看该断面完整水动力结果
        </Button>
      )}
    </aside>
  );
}
