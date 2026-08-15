import { Button, Card, Input, InputNumber, Select, Space, Upload, message } from 'antd';
import type { UploadFile } from 'antd';
import { useState } from 'react';

import {
  convertDGISToCOG,
  convertDGISToGeoJSON,
  importDGISToPostGIS,
  inspectDGISFile,
  type DGISGovernedEntityType,
} from '../../api/generated/client';


type Operation = 'inspect' | 'geojson' | 'cog' | 'postgis';
const DEFAULT_OPERATOR = 'web-dgis-operator';
const LAYER_NAME_PATTERN = /^[A-Za-z][A-Za-z0-9_]{0,62}$/;
const ENTITY_TYPE_OPTIONS: Array<{ value: DGISGovernedEntityType; label: string }> = [
  { value: 'river', label: '河道' },
  { value: 'cross_section', label: '断面' },
  { value: 'gate', label: '闸门' },
  { value: 'pump', label: '泵站' },
];


/** Send one validated spatial asset through the generated-client GDAL workflow. */
export function DataManager() {
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [operation, setOperation] = useState<Operation>('inspect');
  const [layerName, setLayerName] = useState('uploaded_layer');
  const [entityType, setEntityType] = useState<DGISGovernedEntityType>('river');
  const [parentVersionId, setParentVersionId] = useState<number | null>(null);
  const [operator, setOperator] = useState(DEFAULT_OPERATOR);
  const [loading, setLoading] = useState(false);
  const run = async () => {
    const file = files[0]?.originFileObj;
    if (!file) return message.warning('请先选择空间文件');
    if (operation === 'postgis') {
      if (!LAYER_NAME_PATTERN.test(layerName)) {
        return message.warning('图层名需以字母开头，且只能包含字母、数字和下划线');
      }
      if (!operator.trim()) return message.warning('请填写操作人');
    }
    setLoading(true);
    try {
      const result = operation === 'inspect' ? await inspectDGISFile(file)
        : operation === 'geojson' ? await convertDGISToGeoJSON(file)
          : operation === 'cog' ? await convertDGISToCOG(file)
            : await importDGISToPostGIS(file, layerName, {
              entityType,
              parentVersionId: parentVersionId ?? undefined,
              operator: operator.trim(),
            });
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
        {operation === 'postgis' && (
          <>
            <Input
              aria-label="PostGIS 图层名"
              value={layerName}
              onChange={(event) => setLayerName(event.target.value)}
              placeholder="imports 图层名"
              maxLength={63}
            />
            <Select
              aria-label="数据对象类型"
              value={entityType}
              onChange={setEntityType}
              options={ENTITY_TYPE_OPTIONS}
              style={{ minWidth: 110 }}
            />
            <InputNumber
              aria-label="父数据版本 ID"
              min={1}
              precision={0}
              value={parentVersionId}
              onChange={setParentVersionId}
              placeholder="父版本 ID（可选）"
              style={{ width: 165 }}
            />
            <Input
              aria-label="导入操作人"
              value={operator}
              onChange={(event) => setOperator(event.target.value)}
              placeholder="操作人"
              maxLength={64}
            />
          </>
        )}
        <Button type="primary" loading={loading} onClick={() => void run()}>执行</Button>
      </Space>
    </Card>
  );
}
