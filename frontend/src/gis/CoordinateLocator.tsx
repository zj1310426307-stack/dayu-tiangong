import { AimOutlined, CloseOutlined } from '@ant-design/icons';
import { Button, InputNumber, Segmented, Select } from 'antd';
import { FormEvent, useState } from 'react';

export type CoordinateInputMode = 'lonlat' | 'webmercator' | 'cgcs2000';
export type CgcsCentralMeridian = 111 | 114 | 117;

export interface CoordinateLocatorProps {
  onLocate: (first: number, second: number, mode: CoordinateInputMode, centralMeridian: CgcsCentralMeridian) => [number, number] | null;
  onClear: () => void;
  hidden?: boolean;
}

const WEB_MERCATOR_LIMIT = 20_037_508.342789244;

/** Collect validated geographic or Web Mercator coordinates for a client-only map jump. */
export function CoordinateLocator({ onLocate, onClear, hidden = false }: CoordinateLocatorProps) {
  const [mode, setMode] = useState<CoordinateInputMode>('lonlat');
  const [centralMeridian, setCentralMeridian] = useState<CgcsCentralMeridian>(114);
  const [first, setFirst] = useState<number | null>(null);
  const [second, setSecond] = useState<number | null>(null);
  const [located, setLocated] = useState(false);
  const [result, setResult] = useState<[number, number] | null>(null);
  const [error, setError] = useState('');

  /** Reject incomplete or out-of-range input before changing the OpenLayers view. */
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (first === null || second === null) {
      setError(mode === 'lonlat' ? '请输入完整的经度和纬度' : '请输入完整的 X 和 Y 坐标');
      return;
    }
    if (mode === 'lonlat' && (first < -180 || first > 180 || second < -90 || second > 90)) {
      setError('经度应在 -180～180，纬度应在 -90～90');
      return;
    }
    if (mode === 'webmercator' && (Math.abs(first) > WEB_MERCATOR_LIMIT || Math.abs(second) > WEB_MERCATOR_LIMIT)) {
      setError('EPSG:3857 的 X、Y 应在 ±20,037,508.343 米以内');
      return;
    }
    if (mode === 'cgcs2000' && (first < 0 || first > 1_000_000 || second < 0 || second > 10_000_000)) {
      setError('CGCS2000 高斯坐标应为 X 东坐标 0～100 万米、Y 北坐标 0～1,000 万米');
      return;
    }
    setError('');
    const nextResult = onLocate(first, second, mode, centralMeridian);
    if (!nextResult) {
      setError('地图尚未完成初始化，请稍后重试');
      return;
    }
    setLocated(true);
    setResult(nextResult);
  };

  /** Switch coordinate semantics explicitly and discard values from the previous CRS. */
  const changeMode = (nextMode: CoordinateInputMode) => {
    setMode(nextMode);
    setFirst(null);
    setSecond(null);
    setLocated(false);
    setResult(null);
    setError('');
    onClear();
  };

  /** Invalidate the previous projection result when the central meridian changes. */
  const changeCentralMeridian = (value: CgcsCentralMeridian) => {
    setCentralMeridian(value);
    setLocated(false);
    setResult(null);
    setError('');
    onClear();
  };

  /** Remove only the temporary locator marker; published GIS layers remain untouched. */
  const clear = () => {
    setLocated(false);
    setResult(null);
    setError('');
    onClear();
  };

  return (
    <form id="gis-coordinate-tool" className="ol-coordinate-locator" aria-label="GIS 坐标定位" hidden={hidden} onSubmit={submit}>
      <header>
        <span><AimOutlined /><strong>坐标定位</strong></span>
        <small>{mode === 'lonlat' ? '十进制度 · EPSG:4326' : mode === 'webmercator' ? '米制坐标 · EPSG:3857' : `CGCS2000 · CM ${centralMeridian}°E`}</small>
      </header>
      <Segmented
        className="ol-coordinate-locator__mode"
        block
        size="small"
        aria-label="定位坐标类型"
        value={mode}
        options={[
          { label: '经纬度', value: 'lonlat' },
          { label: 'Web XY', value: 'webmercator' },
          { label: 'CGCS2000', value: 'cgcs2000' },
        ]}
        onChange={(value) => changeMode(value as CoordinateInputMode)}
      />
      {mode === 'cgcs2000' && <label className="ol-coordinate-locator__crs">
        <span>中央经线</span>
        <Select
          aria-label="CGCS2000 中央经线"
          value={centralMeridian}
          options={[
            { label: '111°E · EPSG:4546', value: 111 },
            { label: '114°E · EPSG:4547', value: 114 },
            { label: '117°E · EPSG:4548', value: 117 },
          ]}
          onChange={(value) => changeCentralMeridian(value as CgcsCentralMeridian)}
        />
      </label>}
      <div className="ol-coordinate-locator__inputs">
        <label>
          <span>{mode === 'lonlat' ? '经度' : mode === 'cgcs2000' ? 'X(东)' : 'X'}</span>
          <InputNumber
            aria-label={mode === 'lonlat' ? '经度' : mode === 'cgcs2000' ? 'CGCS2000 X东坐标' : 'Web X坐标'}
            min={mode === 'lonlat' ? -180 : mode === 'cgcs2000' ? 0 : -WEB_MERCATOR_LIMIT}
            max={mode === 'lonlat' ? 180 : mode === 'cgcs2000' ? 1_000_000 : WEB_MERCATOR_LIMIT}
            precision={mode === 'lonlat' ? 8 : 3}
            placeholder={mode === 'lonlat' ? '例如 113.2644' : mode === 'cgcs2000' ? '例如 641444.743' : '例如 12608535.3'}
            value={first}
            onChange={(value) => setFirst(value)}
          />
        </label>
        <label>
          <span>{mode === 'lonlat' ? '纬度' : mode === 'cgcs2000' ? 'Y(北)' : 'Y'}</span>
          <InputNumber
            aria-label={mode === 'lonlat' ? '纬度' : mode === 'cgcs2000' ? 'CGCS2000 Y北坐标' : 'Web Y坐标'}
            min={mode === 'lonlat' ? -90 : mode === 'cgcs2000' ? 0 : -WEB_MERCATOR_LIMIT}
            max={mode === 'lonlat' ? 90 : mode === 'cgcs2000' ? 10_000_000 : WEB_MERCATOR_LIMIT}
            precision={mode === 'lonlat' ? 8 : 3}
            placeholder={mode === 'lonlat' ? '例如 23.1291' : mode === 'cgcs2000' ? '例如 2464480.899' : '例如 2647638.6'}
            value={second}
            onChange={(value) => setSecond(value)}
          />
        </label>
      </div>
      <div className="ol-coordinate-locator__actions">
        <Button type="primary" htmlType="submit" size="small" icon={<AimOutlined />}>定位</Button>
        <Button type="text" size="small" icon={<CloseOutlined />} disabled={!located} onClick={clear}>清除</Button>
        <span className={error ? 'is-error' : ''} aria-live="polite">{error || (result
          ? `转换结果：${result[0].toFixed(6)}°E, ${result[1].toFixed(6)}°N`
          : `输入顺序：${mode === 'lonlat' ? '经度、纬度' : mode === 'cgcs2000' ? 'X 东坐标、Y 北坐标' : 'X、Y'}`)}</span>
      </div>
    </form>
  );
}
