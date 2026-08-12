import * as echarts from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { useEffect, useMemo, useRef } from 'react';

echarts.use([GridComponent, TooltipComponent, LineChart, CanvasRenderer]);

interface CrossSectionProfileProps {
  points: unknown;
  roughness?: unknown;
  minimumElevation?: unknown;
}

/** Normalize the accepted historical cross-section JSON shapes into [offset, elevation]. */
function normalizeProfile(value: unknown): Array<[number, number]> {
  const candidates: unknown[] = [];
  if (Array.isArray(value)) candidates.push(value);
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    candidates.push(record.points, record.values, ...Object.values(record));
  }
  for (const candidate of candidates) {
    if (!Array.isArray(candidate)) continue;
    const normalized = candidate
      .filter((point): point is [number, number] => (
        Array.isArray(point)
        && point.length >= 2
        && Number.isFinite(Number(point[0]))
        && Number.isFinite(Number(point[1]))
      ))
      .map((point) => [Number(point[0]), Number(point[1])] as [number, number]);
    if (normalized.length > 1) return normalized;
  }
  return [];
}

/** Render an engineering cross-section profile without introducing a second data source. */
export function CrossSectionProfile({ points, roughness, minimumElevation }: CrossSectionProfileProps) {
  const element = useRef<HTMLDivElement>(null);
  const profile = useMemo(() => normalizeProfile(points), [points]);

  useEffect(() => {
    if (!element.current || profile.length < 2) return undefined;
    const chart = echarts.init(element.current);
    chart.setOption({
      animationDuration: 350,
      grid: { top: 18, right: 12, bottom: 28, left: 42 },
      tooltip: {
        trigger: 'axis',
        formatter: (items: unknown) => {
          const first = Array.isArray(items) ? items[0] as { value?: [number, number] } : undefined;
          const value = first?.value;
          return value ? `横距 ${value[0].toFixed(2)} m<br/>高程 ${value[1].toFixed(3)} m` : '';
        },
      },
      xAxis: {
        type: 'value',
        name: '横距 / m',
        nameTextStyle: { color: '#648397', fontSize: 9 },
        axisLabel: { color: '#7898aa', fontSize: 8 },
        splitLine: { lineStyle: { color: 'rgba(96, 128, 148, 0.10)' } },
      },
      yAxis: {
        type: 'value',
        name: '高程 / m',
        scale: true,
        nameTextStyle: { color: '#648397', fontSize: 9 },
        axisLabel: { color: '#7898aa', fontSize: 8 },
        splitLine: { lineStyle: { color: 'rgba(96, 128, 148, 0.10)' } },
      },
      series: [{
        type: 'line',
        data: profile,
        showSymbol: true,
        symbolSize: 4,
        lineStyle: { color: '#2fe6d6', width: 2 },
        itemStyle: { color: '#2fe6d6' },
        areaStyle: { color: 'rgba(47, 230, 214, 0.10)' },
      }],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(element.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [profile]);

  if (profile.length < 2) return <p className="section-profile__empty">该断面没有可绘制的高程点。</p>;
  return (
    <div className="section-profile">
      <div className="section-profile__meta">
        <span>糙率 <strong>{String(roughness ?? '—')}</strong></span>
        <span>最低高程 <strong>{String(minimumElevation ?? '—')} m</strong></span>
        <span>测点 <strong>{profile.length}</strong></span>
      </div>
      <div ref={element} className="section-profile__chart" role="img" aria-label="横断面高程图" />
    </div>
  );
}
