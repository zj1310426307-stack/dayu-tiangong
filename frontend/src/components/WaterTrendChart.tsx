const labels = ['00:00', '04:00', '08:00', '12:00', '16:00', '20:00', '24:00'];
const values = [2.8, 3.15, 3.02, 3.75, 4.18, 3.62, 3.35];

/** 使用原生 SVG 渲染首页趋势，避免 Canvas/ECharts 影响受限浏览器进程。 */
export function WaterTrendChart() {
  const points = values.map((value, index) => {
    const x = 42 + index * 70;
    const y = 128 - ((value - 2) / 3) * 104;
    return { x, y, value, label: labels[index] };
  });
  const line = points.map(({ x, y }) => `${x},${y}`).join(' ');
  const area = `42,140 ${line} 462,140`;

  return (
    <svg className="trend-chart" viewBox="0 0 500 165" role="img" aria-label="24 小时水位趋势示意图" preserveAspectRatio="none">
      <defs>
        <linearGradient id="water-trend-area" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#2fe6d6" stopOpacity="0.28" />
          <stop offset="100%" stopColor="#2fe6d6" stopOpacity="0.01" />
        </linearGradient>
      </defs>
      {[36, 70, 104, 138].map((y) => <line key={y} x1="32" y1={y} x2="472" y2={y} stroke="rgba(111,141,165,0.12)" />)}
      <polygon points={area} fill="url(#water-trend-area)" />
      <polyline points={line} fill="none" stroke="#2fe6d6" strokeWidth="2.5" vectorEffect="non-scaling-stroke" />
      {points.map(({ x, y, value, label }) => (
        <g key={label}>
          <circle cx={x} cy={y} r="4" fill="#06101c" stroke="#2fe6d6" strokeWidth="2" vectorEffect="non-scaling-stroke" />
          <title>{`${label} · ${value.toFixed(2)} m`}</title>
          <text x={x} y="158" fill="#6f8da5" fontSize="10" textAnchor="middle">{label}</text>
        </g>
      ))}
    </svg>
  );
}
