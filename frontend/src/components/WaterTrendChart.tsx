import * as echarts from 'echarts/core';
import { GridComponent, TooltipComponent } from 'echarts/components';
import { LineChart } from 'echarts/charts';
import { CanvasRenderer } from 'echarts/renderers';
import { useEffect, useRef } from 'react';

echarts.use([GridComponent, TooltipComponent, LineChart, CanvasRenderer]);

// 渲染轻量水位趋势示意图，并在容器尺寸变化时同步调整画布。
export function WaterTrendChart() {
  const chartRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!chartRef.current) return undefined;

    const chart = echarts.init(chartRef.current);
    chart.setOption({
      animationDuration: 900,
      grid: { top: 16, right: 12, bottom: 24, left: 36 },
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(6, 20, 34, 0.96)',
        borderColor: 'rgba(47, 230, 214, 0.35)',
        textStyle: { color: '#dff9ff' },
      },
      xAxis: {
        type: 'category',
        boundaryGap: false,
        data: ['00:00', '04:00', '08:00', '12:00', '16:00', '20:00', '24:00'],
        axisLabel: { color: '#6f8da5', fontSize: 10 },
        axisLine: { lineStyle: { color: 'rgba(111, 141, 165, 0.18)' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        min: 2,
        max: 5,
        axisLabel: { color: '#6f8da5', fontSize: 10 },
        splitLine: { lineStyle: { color: 'rgba(111, 141, 165, 0.10)' } },
      },
      series: [
        {
          type: 'line',
          data: [2.8, 3.15, 3.02, 3.75, 4.18, 3.62, 3.35],
          smooth: true,
          symbol: 'circle',
          symbolSize: 6,
          lineStyle: { width: 2.5, color: '#2fe6d6' },
          itemStyle: { color: '#06101c', borderColor: '#2fe6d6', borderWidth: 2 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(47, 230, 214, 0.28)' },
              { offset: 1, color: 'rgba(47, 230, 214, 0.01)' },
            ]),
          },
        },
      ],
    });

    const resizeObserver = new ResizeObserver(() => chart.resize());
    resizeObserver.observe(chartRef.current);
    return () => {
      resizeObserver.disconnect();
      chart.dispose();
    };
  }, []);

  return <div ref={chartRef} className="trend-chart" role="img" aria-label="24 小时水位趋势示意图" />;
}
