import {
  ApartmentOutlined,
  CheckCircleFilled,
  ControlOutlined,
  DashboardOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { Progress } from 'antd';
import { useEffect, useState } from 'react';
import { getGISStatistics, type GISStatisticsResponse } from '../api/generated/client';
import { useDatasetVersion } from '../context/DatasetVersionContext';

// 统计值全部来自 PostGIS；加载失败时明确显示错误，不回退到伪造数量。
export function StatusPanel() {
  const { datasetVersionId } = useDatasetVersion();
  const [statistics, setStatistics] = useState<GISStatisticsResponse | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!datasetVersionId) return undefined;
    let cancelled = false;
    setError('');
    getGISStatistics(datasetVersionId)
      .then((value) => {
        if (!cancelled) setStatistics(value);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : '统计读取失败');
      });
    return () => { cancelled = true; };
  }, [datasetVersionId]);

  const metrics = [
    { label: '河道数量', value: statistics?.rivers, unit: '条', icon: <ApartmentOutlined />, tone: 'cyan' },
    { label: '闸门数量', value: statistics?.gates, unit: '座', icon: <ControlOutlined />, tone: 'blue' },
    { label: '泵站数量', value: statistics?.pumps, unit: '座', icon: <ThunderboltOutlined />, tone: 'violet' },
  ];

  return (
    <aside className="status-panel panel-surface" aria-label="状态监控面板">
      <div className="panel-heading">
        <div>
          <span className="panel-kicker">SYSTEM PULSE / 02</span>
          <h2>状态监控</h2>
        </div>
        <span className={`live-pill ${error ? 'live-pill--error' : ''}`}><i />{error ? '连接异常' : statistics ? 'PostGIS 在线' : '正在连接'}</span>
      </div>

      <div className="metric-list">
        {metrics.map((metric) => (
          <article className={`metric-card metric-card--${metric.tone}`} key={metric.label}>
            <div className="metric-icon">{metric.icon}</div>
            <div className="metric-copy">
              <span>{metric.label}</span>
              <strong>{metric.value ?? '—'}<small>{metric.unit}</small></strong>
            </div>
            <span className="metric-tag">DEMO</span>
          </article>
        ))}
      </div>

      <div className="model-status">
        <div className="model-status__title">
          <span><DashboardOutlined /> 空间底座</span>
          <strong><CheckCircleFilled /> {statistics ? `${statistics.cross_sections} 个断面` : '读取中'}</strong>
        </div>
        <Progress
          percent={100}
          showInfo={false}
          strokeColor={{ '0%': '#2fe6d6', '100%': '#3b8fff' }}
          trailColor="rgba(95, 126, 154, 0.16)"
          size="small"
        />
        <p>PostGIS · GeoJSON API · CesiumJS</p>
      </div>

      <div className="status-footnote">
        <span>数据口径：{statistics?.source ?? '等待 PostGIS 响应'}</span>
        <p>{error || '当前为 Phase 1 演示数据，数量直接由数据库聚合，不代表生产资产。'}</p>
      </div>
    </aside>
  );
}
