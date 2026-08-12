import { CaretRightOutlined, PauseOutlined } from '@ant-design/icons';
import { Button, Slider, Tag } from 'antd';
import { useEffect, useMemo, useState } from 'react';

interface SimulationTimelineProps {
  timeline: number[];
  selectedTime?: number | null;
  loading?: boolean;
  onChange: (timeSeconds: number) => void;
}

/** Format simulation seconds as the professional HH:MM timeline label. */
export function formatSimulationTime(value: number): string {
  const totalMinutes = Math.round(value / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;
}

/** Control one authoritative set of hydraulic and dispatch frames. */
export function SimulationTimeline({ timeline, selectedTime, loading, onChange }: SimulationTimelineProps) {
  const [playing, setPlaying] = useState(false);
  const selectedIndex = Math.max(0, timeline.findIndex((value) => value === selectedTime));
  const marks = useMemo(() => {
    if (timeline.length === 0) return {};
    const stride = Math.max(1, Math.ceil(timeline.length / 7));
    return Object.fromEntries(timeline.map((value, index) => (
      index % stride === 0 || index === timeline.length - 1
        ? [index, formatSimulationTime(value)]
        : [index, '']
    )));
  }, [timeline]);

  useEffect(() => {
    if (!playing || timeline.length < 2) return undefined;
    const timer = window.setInterval(() => {
      const current = Math.max(0, timeline.findIndex((value) => value === selectedTime));
      const next = current >= timeline.length - 1 ? 0 : current + 1;
      onChange(timeline[next]);
    }, 900);
    return () => window.clearInterval(timer);
  }, [onChange, playing, selectedTime, timeline]);

  if (timeline.length === 0) {
    return <div className="simulation-timeline simulation-timeline--empty"><strong>SimulationTimeline</strong><span>{loading ? '正在读取仿真帧…' : '当前版本暂无成功水动力结果'}</span></div>;
  }
  return (
    <div className="simulation-timeline" aria-label="仿真时间轴">
      <div className="simulation-timeline__title">
        <Button
          type="text"
          size="small"
          icon={playing ? <PauseOutlined /> : <CaretRightOutlined />}
          onClick={() => setPlaying((value) => !value)}
          aria-label={playing ? '暂停时间轴' : '播放时间轴'}
        />
        <strong>SimulationTimeline</strong>
        <Tag color="cyan">{formatSimulationTime(selectedTime ?? timeline[0])}</Tag>
        {loading && <span>同步中</span>}
      </div>
      <Slider
        min={0}
        max={timeline.length - 1}
        step={1}
        value={selectedIndex < 0 ? 0 : selectedIndex}
        marks={marks}
        tooltip={{ formatter: (index) => formatSimulationTime(timeline[index ?? 0]) }}
        onChange={(index) => onChange(timeline[index])}
      />
    </div>
  );
}
