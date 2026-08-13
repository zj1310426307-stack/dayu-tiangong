import { Button, Card, Input, Select, Space, Upload, message } from 'antd';
import type { UploadFile } from 'antd';
import { useState } from 'react';

import {
  convertDGISToCOG,
  convertDGISToGeoJSON,
  importDGISToPostGIS,
  inspectDGISFile,
} from '../../api/generated/client';


type Operation = 'inspect' | 'geojson' | 'cog' | 'postgis';


/** Send one validated spatial asset through the generated-client GDAL workflow. */
export function DataManager() {
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [operation, setOperation] = useState<Operation>('inspect');
  const [layerName, setLayerName] = useState('uploaded_layer');
  const [loading, setLoading] = useState(false);
  const run = async () => {
    const file = files[0]?.originFileObj;
    if (!file) return message.warning('请先选择空间文件');
    setLoading(true);
    try {
      const result = operation === 'inspect' ? await inspectDGISFile(file)
        : operation === 'geojson' ? await convertDGISToGeoJSON(file)
          : operation === 'cog' ? await convertDGISToCOG(file)
            : await importDGISToPostGIS(file, layerName);
      message.success(`GDAL ${result.operation} 完成：${result.output_name ?? result.output_format}`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'GDAL 数据处理失败');
    } finally {
      setLoading(false);
    }
  };
  return (
    <Card size="small" title="DataManager · GDAL 数据转换">
      <Space wrap>
        <Upload beforeUpload={() => false} maxCount={1} fileList={files} onChange={({ fileList }) => setFiles(fileList)}>
          <Button>选择文件</Button>
        </Upload>
        <Select value={operation} onChange={setOperation} options={[
          { value: 'inspect', label: '检查元数据' }, { value: 'geojson', label: '转 GeoJSON' },
          { value: 'cog', label: '转 COG' }, { value: 'postgis', label: '导入 PostGIS' },
        ]} />
        {operation === 'postgis' && <Input value={layerName} onChange={(event) => setLayerName(event.target.value)} placeholder="imports 图层名" />}
        <Button type="primary" loading={loading} onClick={() => void run()}>执行</Button>
      </Space>
    </Card>
  );
}
