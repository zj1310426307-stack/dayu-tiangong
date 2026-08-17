export interface CoordinateProps {
  coordinate: [number, number] | null;
}

/** Display the WebGIS view coordinate without changing authoritative data CRS. */
export function Coordinate({ coordinate }: CoordinateProps) {
  return (
    <div className="ol-coordinate" aria-live="polite">
      <strong>EPSG:3857</strong>
      <span>{coordinate ? `X ${coordinate[0].toFixed(2)}  Y ${coordinate[1].toFixed(2)}` : '移动鼠标查看坐标'}</span>
    </div>
  );
}
