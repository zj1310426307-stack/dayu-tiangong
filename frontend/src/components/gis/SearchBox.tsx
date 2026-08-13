import { EnvironmentOutlined, SearchOutlined } from '@ant-design/icons';
import { Button, Empty, Input, Spin, Tag, message } from 'antd';
import { useEffect, useState } from 'react';
import {
  searchGISLocations,
  type LocationSearchItem,
} from '../../api/generated/client';

interface SearchBoxProps {
  datasetVersionId: number;
  onLocate: (item: LocationSearchItem) => void;
}

/** Search coordinates or the local PostGIS gazetteer through the generated client. */
export function SearchBox({ datasetVersionId, onLocate }: SearchBoxProps) {
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [items, setItems] = useState<LocationSearchItem[]>([]);

  useEffect(() => {
    setItems([]); setSearched(false);
  }, [datasetVersionId]);

  async function search(value: string) {
    const token = value.trim();
    if (!token) return;
    setLoading(true); setSearched(true);
    try {
      const result = await searchGISLocations({ dataset_version_id: datasetVersionId, q: token, limit: 12 });
      setItems(result.items);
      if (result.items.length === 1 && result.mode === 'coordinate') onLocate(result.items[0]);
    } catch (reason) {
      setItems([]);
      message.error(reason instanceof Error ? reason.message : '地图定位失败');
    } finally { setLoading(false); }
  }

  return (
    <div className="gis-search" aria-label="坐标与地名搜索">
      <Input.Search
        aria-label="地图搜索框"
        value={query}
        prefix={<SearchOutlined />}
        placeholder="坐标、地名、道路或 POI"
        enterButton="定位"
        loading={loading}
        onChange={(event) => setQuery(event.target.value)}
        onSearch={(value) => void search(value)}
      />
      {(loading || searched) && (
        <div className="gis-search__results">
          {loading ? <Spin size="small" /> : items.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="本地底图库无匹配结果" /> : items.map((item, index) => (
            <Button className="gis-search__result" type="text" key={`${item.result_type}-${item.object_id ?? index}`} onClick={() => onLocate(item)}>
              <EnvironmentOutlined />
              <span><strong>{item.name}</strong><small>{item.address ?? `${item.longitude.toFixed(6)}, ${item.latitude.toFixed(6)}`}</small></span>
              <Tag>{item.result_type}</Tag>
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
