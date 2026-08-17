export interface CoordinateProps {
  longitudeLatitude: [number, number] | null;
  xy: [number, number] | null;
}

/** Display pointer position in both geographic and Web Mercator coordinate systems. */
export function Coordinate({ longitudeLatitude, xy }: CoordinateProps) {
  return (
    <div className="ol-coordinate" aria-live="polite">
      <strong>坐标</strong>
      {longitudeLatitude && xy ? <span>
        经度 {longitudeLatitude[0].toFixed(6)}　纬度 {longitudeLatitude[1].toFixed(6)}
        <em>X {xy[0].toFixed(2)}　Y {xy[1].toFixed(2)} m</em>
      </span> : <span>移动鼠标查看经纬度与 XY</span>}
    </div>
  );
}
