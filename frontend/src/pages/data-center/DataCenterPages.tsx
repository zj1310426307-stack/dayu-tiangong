import {
  CheckCircleOutlined,
  CloudUploadOutlined,
  DeleteOutlined,
  EditOutlined,
  FileExcelOutlined,
  NodeIndexOutlined,
  PlusOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons';
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { UploadFile } from 'antd/es/upload/interface';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type {
  CrossSectionCreate,
  CrossSectionRecord,
  GateCreate,
  GateRecord,
  ImportResource,
  ModelInputSnapshot,
  PumpCreate,
  PumpRecord,
  RiverCreate,
  RiverRecord,
  ValidationReport,
} from '../../api/generated/client';
import { useDatasetVersion } from '../../context/DatasetVersionContext';
import {
  createCrossSectionRecord,
  createGateRecord,
  createPumpRecord,
  createRiverRecord,
  deleteCrossSectionRecord,
  deleteGateRecord,
  deletePumpRecord,
  deleteRiverRecord,
  generateTopology,
  getBoundaryConditions,
  getDatasetVersions,
  getModelInput,
  getModelParameters,
  getSimulationCases,
  listCrossSectionRecords,
  listGateRecords,
  listPumpRecords,
  listRiverRecords,
  runValidation,
  updateCrossSectionRecord,
  updateGateRecord,
  updatePumpRecord,
  updateRiverRecord,
  uploadDataFile,
} from '../../api/generated/client';

const { Paragraph, Text, Title } = Typography;

function DataPageHeader({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: React.ReactNode }) {
  return (
    <header className="data-page__header">
      <div>
        <span className="hero-kicker"><i /> {eyebrow}</span>
        <Title level={1}>{title}</Title>
        <Paragraph>{description}</Paragraph>
      </div>
      {action}
    </header>
  );
}

function useRemoteList<T>(loader: () => Promise<T>, dependencies: readonly unknown[]) {
  const [data, setData] = useState<T>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const reload = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setData(await loader());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '数据加载失败');
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, dependencies);
  useEffect(() => { void reload(); }, [reload]);
  return { data, loading, error, reload };
}

function jsonText(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function coordinatesOf(geometry: Record<string, unknown>): unknown {
  return geometry.coordinates;
}

interface RiverFormValues {
  dataset_version_id: number;
  name: string;
  code: string;
  length: number;
  level: string;
  status: 'active' | 'inactive' | 'planned';
  description?: string;
  coordinates_json: string;
}

export function RiversDatabasePage() {
  const { datasetVersionId } = useDatasetVersion();
  const [search, setSearch] = useState('');
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<RiverRecord>();
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm<RiverFormValues>();
  const { data, loading, error, reload } = useRemoteList(
    () => listRiverRecords({ dataset_version_id: datasetVersionId, search, limit: 500 }), [datasetVersionId, search],
  );

  const showEditor = (record?: RiverRecord) => {
    setEditing(record);
    form.setFieldsValue(record ? {
      dataset_version_id: record.dataset_version_id,
      name: record.name,
      code: record.code,
      length: record.length,
      level: record.level,
      status: record.status,
      description: record.description ?? undefined,
      coordinates_json: jsonText(coordinatesOf(record.geometry)),
    } : {
      dataset_version_id: datasetVersionId ?? 1,
      level: 'main',
      status: 'active',
      coordinates_json: '[[120.00, 30.25], [120.10, 30.28]]',
    });
    setOpen(true);
  };

  const submit = async (values: RiverFormValues) => {
    setSubmitting(true);
    try {
      const { coordinates_json, ...fields } = values;
      const payload: RiverCreate = {
        ...fields,
        geometry: { type: 'LineString', coordinates: JSON.parse(coordinates_json) as unknown },
      };
      if (editing) {
        const { dataset_version_id: _, ...updates } = payload;
        await updateRiverRecord(editing.id, updates);
      }
      else await createRiverRecord(payload);
      message.success(editing ? '河道已更新' : '河道已新增');
      setOpen(false);
      form.resetFields();
      await reload();
    } catch (reason) {
      message.error(reason instanceof Error ? reason.message : '保存失败');
    } finally { setSubmitting(false); }
  };

  const columns: ColumnsType<RiverRecord> = [
    { title: '编码', dataIndex: 'code', width: 150 },
    { title: '河道名称', dataIndex: 'name' },
    { title: '等级', dataIndex: 'level', width: 110, render: (value: string) => <Tag color="cyan">{value}</Tag> },
    { title: '长度', dataIndex: 'length', width: 135, render: (value: number) => `${(value / 1000).toFixed(2)} km` },
    { title: '状态', dataIndex: 'status', width: 110, render: (value: string) => <Tag color={value === 'active' ? 'success' : 'default'}>{value}</Tag> },
    { title: '断面/拓扑版本', dataIndex: 'dataset_version_id', width: 135, render: (value: number) => `V-ID ${value}` },
    { title: '操作', key: 'actions', width: 130, render: (_, record) => <Space><Button type="text" icon={<EditOutlined />} onClick={() => showEditor(record)} /><Popconfirm title="确认删除该河道？" onConfirm={async () => { await deleteRiverRecord(record.id); await reload(); }}><Button danger type="text" icon={<DeleteOutlined />} /></Popconfirm></Space> },
  ];

  return (
    <div className="data-page">
      <DataPageHeader eyebrow="HYDRAULIC DATABASE / RIVERS" title="河道数据库" description="统一维护河道编码、等级、长度、状态与 CGCS2000 / EPSG:4490 空间线。" action={<Button type="primary" icon={<PlusOutlined />} onClick={() => showEditor()}>新增河道</Button>} />
      {error && <Alert className="data-alert" type="error" showIcon message={error} />}
      <Card className="data-card" title={`河道清单 · ${data?.total ?? 0} 条`} extra={<Space><Input.Search allowClear placeholder="名称或编码" onSearch={setSearch} /><Button icon={<NodeIndexOutlined />} disabled={!datasetVersionId} onClick={async () => { if (!datasetVersionId) return; await generateTopology({ dataset_version_id: datasetVersionId, tolerance: 0.00001 }); message.success('河网拓扑已重新生成'); }}>生成拓扑</Button><Button icon={<ReloadOutlined />} onClick={() => void reload()} /></Space>}>
        <Table rowKey="id" loading={loading} columns={columns} dataSource={data?.items ?? []} pagination={{ pageSize: 12 }} scroll={{ x: 960 }} />
      </Card>
      <Modal open={open} title={editing ? '编辑河道' : '新增河道'} onCancel={() => setOpen(false)} onOk={() => form.submit()} confirmLoading={submitting} width={720} destroyOnHidden>
        <Form form={form} layout="vertical" onFinish={(values) => void submit(values)}>
          <Row gutter={14}><Col span={8}><Form.Item name="dataset_version_id" label="数据版本 ID" rules={[{ required: true }]}><InputNumber min={1} style={{ width: '100%' }} disabled={Boolean(editing)} /></Form.Item></Col><Col span={8}><Form.Item name="code" label="河道编码" rules={[{ required: true }]}><Input /></Form.Item></Col><Col span={8}><Form.Item name="name" label="河道名称" rules={[{ required: true }]}><Input /></Form.Item></Col></Row>
          <Row gutter={14}><Col span={8}><Form.Item name="length" label="长度（m）" rules={[{ required: true }]}><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col><Col span={8}><Form.Item name="level" label="河道等级" rules={[{ required: true }]}><Select options={[{ value: 'main', label: '干流' }, { value: 'tributary', label: '支流' }, { value: 'channel', label: '渠道' }]} /></Form.Item></Col><Col span={8}><Form.Item name="status" label="状态" rules={[{ required: true }]}><Select options={[{ value: 'active', label: '启用' }, { value: 'inactive', label: '停用' }, { value: 'planned', label: '规划' }]} /></Form.Item></Col></Row>
          <Form.Item name="coordinates_json" label="河道坐标序列（经度、纬度）" rules={[{ required: true }]}><Input.TextArea rows={4} /></Form.Item>
          <Form.Item name="description" label="说明"><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

interface SectionFormValues {
  dataset_version_id: number; river_id: number; section_code: string; section_name: string;
  station: number; roughness: number; elevation_min: number; survey_date?: string;
  longitude: number; latitude: number; points_json: string;
}

function SectionProfileChart({ section }: { section?: CrossSectionRecord }) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!element.current || !section) return undefined;
    let dispose: (() => void) | undefined;
    void import('echarts').then((echarts) => {
      if (!element.current) return;
      const chart = echarts.init(element.current);
      const points = section.points.points ?? [];
      chart.setOption({
        grid: { left: 45, right: 20, top: 24, bottom: 38 },
        tooltip: { trigger: 'axis' },
        xAxis: { type: 'value', name: '横距 / m', axisLabel: { color: '#7891a4' }, splitLine: { lineStyle: { color: 'rgba(100,151,183,.12)' } } },
        yAxis: { type: 'value', name: '高程 / m', axisLabel: { color: '#7891a4' }, splitLine: { lineStyle: { color: 'rgba(100,151,183,.12)' } } },
        series: [{ type: 'line', data: points, smooth: true, symbolSize: 7, lineStyle: { color: '#2fe6d6', width: 3 }, areaStyle: { color: 'rgba(47,230,214,.12)' } }],
      });
      dispose = () => chart.dispose();
    });
    return () => dispose?.();
  }, [section]);
  return <div className="section-profile-chart" ref={element} />;
}

export function CrossSectionsDatabasePage() {
  const { datasetVersionId } = useDatasetVersion();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<CrossSectionRecord>();
  const [selected, setSelected] = useState<CrossSectionRecord>();
  const [form] = Form.useForm<SectionFormValues>();
  const { data, loading, error, reload } = useRemoteList(() => listCrossSectionRecords({ dataset_version_id: datasetVersionId, limit: 500 }), [datasetVersionId]);
  const showEditor = (record?: CrossSectionRecord) => {
    setEditing(record);
    const coordinates = record ? coordinatesOf(record.geometry) : [120.1, 30.25];
    const point = Array.isArray(coordinates) ? coordinates : [120.1, 30.25];
    form.setFieldsValue(record ? {
      dataset_version_id: record.dataset_version_id, river_id: record.river_id, section_code: record.section_code,
      section_name: record.section_name, station: record.station, roughness: record.roughness,
      elevation_min: record.elevation_min, survey_date: record.survey_date ?? undefined,
      longitude: Number(point[0]), latitude: Number(point[1]), points_json: jsonText(record.points.points),
    } : { dataset_version_id: datasetVersionId ?? 1, river_id: 1, roughness: 0.035, longitude: 120.1, latitude: 30.25, points_json: '[[0, 10], [5, 8], [10, 10]]' });
    setOpen(true);
  };
  const submit = async (values: SectionFormValues) => {
    try {
      const points = JSON.parse(values.points_json) as Array<Array<number>>;
      const payload: CrossSectionCreate = {
        dataset_version_id: values.dataset_version_id, river_id: values.river_id,
        section_code: values.section_code, section_name: values.section_name,
        station: values.station, roughness: values.roughness, elevation_min: values.elevation_min,
        survey_date: values.survey_date, points: { points },
        geometry: { type: 'Point', coordinates: [values.longitude, values.latitude] },
      };
      if (editing) {
        const { dataset_version_id: _, ...updates } = payload;
        await updateCrossSectionRecord(editing.id, updates);
      } else await createCrossSectionRecord(payload);
      setOpen(false); message.success('横断面已保存'); await reload();
    } catch (reason) { message.error(reason instanceof Error ? reason.message : '保存失败'); }
  };
  const columns: ColumnsType<CrossSectionRecord> = [
    { title: '断面编码', dataIndex: 'section_code', width: 150 }, { title: '断面名称', dataIndex: 'section_name' },
    { title: '河道 ID', dataIndex: 'river_id', width: 95 }, { title: '桩号', dataIndex: 'station', width: 120, render: (value: number) => `${value.toFixed(1)} m` },
    { title: '糙率', dataIndex: 'roughness', width: 90 }, { title: '最低高程', dataIndex: 'elevation_min', width: 115, render: (value: number) => `${value.toFixed(2)} m` },
    { title: '测量日期', dataIndex: 'survey_date', width: 120, render: (value?: string) => value ?? '未登记' },
    { title: '操作', key: 'actions', width: 130, render: (_, record) => <Space><Button type="text" icon={<EditOutlined />} onClick={() => showEditor(record)} /><Popconfirm title="确认删除该断面？" onConfirm={async () => { await deleteCrossSectionRecord(record.id); await reload(); }}><Button danger type="text" icon={<DeleteOutlined />} /></Popconfirm></Space> },
  ];
  return <div className="data-page">
    <DataPageHeader eyebrow="HYDRAULIC DATABASE / SECTIONS" title="横断面数据库" description="维护桩号、剖面点、糙率和测量日期；点击记录可预览断面曲线。" action={<Button type="primary" icon={<PlusOutlined />} onClick={() => showEditor()}>新增断面</Button>} />
    {error && <Alert className="data-alert" type="error" showIcon message={error} />}
    <div className="data-split"><Card className="data-card" title={`断面清单 · ${data?.total ?? 0} 条`}><Table rowKey="id" loading={loading} columns={columns} dataSource={data?.items ?? []} pagination={{ pageSize: 10 }} scroll={{ x: 980 }} onRow={(record) => ({ onClick: () => setSelected(record) })} /></Card><Card className="data-card profile-card" title="断面剖面预览">{selected ? <><Descriptions column={1} size="small" items={[{ key: 'name', label: '断面', children: selected.section_name }, { key: 'station', label: '桩号', children: `${selected.station} m` }, { key: 'roughness', label: '糙率', children: selected.roughness }]} /><SectionProfileChart section={selected} /></> : <div className="data-empty">从左侧选择一个横断面</div>}</Card></div>
    <Modal open={open} title={editing ? '编辑横断面' : '新增横断面'} onCancel={() => setOpen(false)} onOk={() => form.submit()} width={760} destroyOnHidden><Form form={form} layout="vertical" onFinish={(values) => void submit(values)}><Row gutter={12}><Col span={6}><Form.Item name="dataset_version_id" label="版本 ID" rules={[{ required: true }]}><InputNumber min={1} disabled={Boolean(editing)} /></Form.Item></Col><Col span={6}><Form.Item name="river_id" label="河道 ID" rules={[{ required: true }]}><InputNumber min={1} /></Form.Item></Col><Col span={6}><Form.Item name="section_code" label="断面编码" rules={[{ required: true }]}><Input /></Form.Item></Col><Col span={6}><Form.Item name="section_name" label="断面名称" rules={[{ required: true }]}><Input /></Form.Item></Col></Row><Row gutter={12}><Col span={6}><Form.Item name="station" label="桩号（m）" rules={[{ required: true }]}><InputNumber min={0} /></Form.Item></Col><Col span={6}><Form.Item name="roughness" label="糙率" rules={[{ required: true }]}><InputNumber min={0.001} step={0.001} /></Form.Item></Col><Col span={6}><Form.Item name="elevation_min" label="最低高程" rules={[{ required: true }]}><InputNumber /></Form.Item></Col><Col span={6}><Form.Item name="survey_date" label="测量日期"><Input placeholder="YYYY-MM-DD" /></Form.Item></Col></Row><Row gutter={12}><Col span={12}><Form.Item name="longitude" label="经度" rules={[{ required: true }]}><InputNumber style={{ width: '100%' }} /></Form.Item></Col><Col span={12}><Form.Item name="latitude" label="纬度" rules={[{ required: true }]}><InputNumber style={{ width: '100%' }} /></Form.Item></Col></Row><Form.Item name="points_json" label="剖面点 [横距, 高程]" rules={[{ required: true }]}><Input.TextArea rows={5} /></Form.Item></Form></Modal>
  </div>;
}

type StructureKind = 'gate' | 'pump';
type StructureRecord = GateRecord | PumpRecord;
interface StructureFormValues { dataset_version_id: number; river_id: number; name: string; code: string; status: 'online' | 'offline' | 'maintenance' | 'fault'; control_mode: string; longitude: number; latitude: number; gate_type?: string; opening_direction?: string; width?: number; height?: number; max_flow?: number; bottom_elevation?: number; design_flow?: number; head?: number; power?: number; efficiency_curve_json?: string; }

function StructureDatabasePage({ kind }: { kind: StructureKind }) {
  const isGate = kind === 'gate';
  const { datasetVersionId } = useDatasetVersion();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<StructureRecord>();
  const [form] = Form.useForm<StructureFormValues>();
  const { data, loading, error, reload } = useRemoteList(async () => {
    const response = isGate ? await listGateRecords({ dataset_version_id: datasetVersionId, limit: 500 }) : await listPumpRecords({ dataset_version_id: datasetVersionId, limit: 500 });
    return { ...response, items: response.items as StructureRecord[] };
  }, [datasetVersionId, isGate]);
  const showEditor = (record?: StructureRecord) => {
    setEditing(record);
    const coords = record ? coordinatesOf(record.geometry) : [120.1, 30.25];
    const point = Array.isArray(coords) ? coords : [120.1, 30.25];
    const values: Partial<StructureFormValues> = record ? { dataset_version_id: record.dataset_version_id, river_id: record.river_id, name: record.name, code: 'gate_code' in record ? record.gate_code : record.pump_code, status: record.status, control_mode: record.control_mode, longitude: Number(point[0]), latitude: Number(point[1]) } : { dataset_version_id: datasetVersionId ?? 1, river_id: 1, status: 'offline', control_mode: 'local', longitude: 120.1, latitude: 30.25 };
    if (record && 'gate_code' in record) Object.assign(values, { gate_type: record.gate_type, opening_direction: record.opening_direction, width: record.width, height: record.height, max_flow: record.max_flow, bottom_elevation: record.bottom_elevation });
    if (record && 'pump_code' in record) Object.assign(values, { design_flow: record.design_flow, head: record.head, power: record.power, efficiency_curve_json: jsonText(record.efficiency_curve.points) });
    if (!record && isGate) Object.assign(values, { gate_type: '节制闸', opening_direction: 'vertical' });
    if (!record && !isGate) Object.assign(values, { efficiency_curve_json: '[[0, 0], [0.5, 0.78], [1, 0.84]]' });
    form.setFieldsValue(values); setOpen(true);
  };
  const submit = async (values: StructureFormValues) => {
    try {
      const geometry = { type: 'Point', coordinates: [values.longitude, values.latitude] };
      if (isGate) {
        const payload: GateCreate = { dataset_version_id: values.dataset_version_id, river_id: values.river_id, name: values.name, gate_code: values.code, gate_type: values.gate_type!, opening_direction: values.opening_direction!, control_mode: values.control_mode, width: values.width!, height: values.height!, max_flow: values.max_flow!, bottom_elevation: values.bottom_elevation!, status: values.status, geometry };
        if (editing) {
          const { dataset_version_id: _, ...updates } = payload;
          await updateGateRecord(editing.id, updates);
        } else await createGateRecord(payload);
      } else {
        const payload: PumpCreate = { dataset_version_id: values.dataset_version_id, river_id: values.river_id, name: values.name, pump_code: values.code, design_flow: values.design_flow!, head: values.head!, power: values.power!, efficiency_curve: { points: JSON.parse(values.efficiency_curve_json!) as Array<Array<number>> }, control_mode: values.control_mode, status: values.status, geometry };
        if (editing) {
          const { dataset_version_id: _, ...updates } = payload;
          await updatePumpRecord(editing.id, updates);
        } else await createPumpRecord(payload);
      }
      setOpen(false); message.success(`${isGate ? '闸门' : '泵站'}已保存`); await reload();
    } catch (reason) { message.error(reason instanceof Error ? reason.message : '保存失败'); }
  };
  const rows = data?.items ?? [];
  const columns: ColumnsType<StructureRecord> = [
    { title: '编码', key: 'code', render: (_, record) => 'gate_code' in record ? record.gate_code : record.pump_code }, { title: '名称', dataIndex: 'name' }, { title: '河道 ID', dataIndex: 'river_id', width: 95 },
    isGate ? { title: '类型', key: 'type', width: 105, render: (_, record) => 'gate_type' in record ? record.gate_type : '-' } : { title: '设计流量', key: 'flow', width: 115, render: (_, record) => 'design_flow' in record ? `${record.design_flow} m³/s` : '-' },
    isGate ? { title: '孔口尺寸', key: 'size', width: 120, render: (_, record) => 'width' in record ? `${record.width} × ${record.height} m` : '-' } : { title: '扬程 / 功率', key: 'head', width: 140, render: (_, record) => 'head' in record ? `${record.head} m / ${record.power} kW` : '-' },
    { title: '控制', dataIndex: 'control_mode', width: 100 }, { title: '状态', dataIndex: 'status', width: 115, render: (value?: string) => <Tag color={value === 'online' ? 'success' : value === 'fault' ? 'error' : 'default'}>{value}</Tag> },
    { title: '操作', key: 'actions', width: 130, render: (_, record) => <Space><Button type="text" icon={<EditOutlined />} onClick={() => showEditor(record)} /><Popconfirm title={`确认删除该${isGate ? '闸门' : '泵站'}？`} onConfirm={async () => { if (isGate) await deleteGateRecord(record.id); else await deletePumpRecord(record.id); await reload(); }}><Button danger type="text" icon={<DeleteOutlined />} /></Popconfirm></Space> },
  ];
  return <div className="data-page"><DataPageHeader eyebrow={`HYDRAULIC DATABASE / ${isGate ? 'GATES' : 'PUMPS'}`} title={`${isGate ? '闸门' : '泵站'}数据库`} description={`维护${isGate ? '闸门尺寸、过流能力、底板高程' : '设计流量、扬程、功率和效率曲线'}及空间位置。`} action={<Button type="primary" icon={<PlusOutlined />} onClick={() => showEditor()}>新增{isGate ? '闸门' : '泵站'}</Button>} />{error && <Alert className="data-alert" type="error" showIcon message={error} />}<Card className="data-card" title={`${isGate ? '闸门' : '泵站'}清单 · ${rows.length} 条`}><Table rowKey="id" loading={loading} columns={columns} dataSource={rows} pagination={{ pageSize: 12 }} scroll={{ x: 900 }} /></Card><Modal open={open} title={`${editing ? '编辑' : '新增'}${isGate ? '闸门' : '泵站'}`} width={760} onCancel={() => setOpen(false)} onOk={() => form.submit()} destroyOnHidden><Form form={form} layout="vertical" onFinish={(values) => void submit(values)}><Row gutter={12}><Col span={6}><Form.Item name="dataset_version_id" label="版本 ID" rules={[{ required: true }]}><InputNumber min={1} disabled={Boolean(editing)} /></Form.Item></Col><Col span={6}><Form.Item name="river_id" label="河道 ID" rules={[{ required: true }]}><InputNumber min={1} /></Form.Item></Col><Col span={6}><Form.Item name="code" label="设施编码" rules={[{ required: true }]}><Input /></Form.Item></Col><Col span={6}><Form.Item name="name" label="设施名称" rules={[{ required: true }]}><Input /></Form.Item></Col></Row><Row gutter={12}><Col span={8}><Form.Item name="control_mode" label="控制方式" rules={[{ required: true }]}><Select options={[{ value: 'local', label: '就地' }, { value: 'remote', label: '远程' }, { value: 'automatic', label: '自动' }]} /></Form.Item></Col><Col span={8}><Form.Item name="status" label="状态" rules={[{ required: true }]}><Select options={['online', 'offline', 'maintenance', 'fault'].map((value) => ({ value, label: value }))} /></Form.Item></Col><Col span={4}><Form.Item name="longitude" label="经度" rules={[{ required: true }]}><InputNumber /></Form.Item></Col><Col span={4}><Form.Item name="latitude" label="纬度" rules={[{ required: true }]}><InputNumber /></Form.Item></Col></Row>{isGate ? <><Row gutter={12}><Col span={6}><Form.Item name="gate_type" label="闸门类型" rules={[{ required: true }]}><Input /></Form.Item></Col><Col span={6}><Form.Item name="opening_direction" label="启闭方向" rules={[{ required: true }]}><Input /></Form.Item></Col><Col span={6}><Form.Item name="width" label="宽度（m）" rules={[{ required: true }]}><InputNumber min={0.01} /></Form.Item></Col><Col span={6}><Form.Item name="height" label="高度（m）" rules={[{ required: true }]}><InputNumber min={0.01} /></Form.Item></Col></Row><Row gutter={12}><Col span={12}><Form.Item name="max_flow" label="最大流量（m³/s）" rules={[{ required: true }]}><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col><Col span={12}><Form.Item name="bottom_elevation" label="底板高程（m）" rules={[{ required: true }]}><InputNumber style={{ width: '100%' }} /></Form.Item></Col></Row></> : <><Row gutter={12}><Col span={8}><Form.Item name="design_flow" label="设计流量（m³/s）" rules={[{ required: true }]}><InputNumber min={0} /></Form.Item></Col><Col span={8}><Form.Item name="head" label="扬程（m）" rules={[{ required: true }]}><InputNumber min={0} /></Form.Item></Col><Col span={8}><Form.Item name="power" label="功率（kW）" rules={[{ required: true }]}><InputNumber min={0} /></Form.Item></Col></Row><Form.Item name="efficiency_curve_json" label="效率曲线 [流量比, 效率]" rules={[{ required: true }]}><Input.TextArea rows={4} /></Form.Item></>}</Form></Modal></div>;
}

export const GatesDatabasePage = () => <StructureDatabasePage kind="gate" />;
export const PumpsDatabasePage = () => <StructureDatabasePage kind="pump" />;

export function DataImportPage() {
  const { datasetVersionId } = useDatasetVersion();
  const [resource, setResource] = useState<ImportResource>('rivers');
  const [kind, setKind] = useState<'excel' | 'csv' | 'geojson'>('excel');
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [result, setResult] = useState<Awaited<ReturnType<typeof uploadDataFile>>>();
  const [loading, setLoading] = useState(false);
  const upload = async () => {
    const origin = files[0]?.originFileObj;
    if (!origin) { message.warning('请先选择文件'); return; }
    setLoading(true);
    if (!datasetVersionId) { message.warning('请先选择数据版本'); return; }
    try { const response = await uploadDataFile(kind, resource, datasetVersionId, origin); setResult(response); if (response.status === 'success') message.success(`成功导入 ${response.imported_count} 条`); }
    catch (reason) { message.error(reason instanceof Error ? reason.message : '导入失败'); }
    finally { setLoading(false); }
  };
  return <div className="data-page"><DataPageHeader eyebrow="DATA PIPELINE / IMPORT" title="数据导入中心" description="支持 Excel、CSV 与 GeoJSON；文件先整体校验，再在单一事务中写入。" /><Row gutter={18}><Col xs={24} lg={15}><Card className="data-card" title="上传数据文件"><Row gutter={14}><Col span={8}><Text>资源类型</Text><Select value={resource} onChange={setResource} style={{ width: '100%', marginTop: 8 }} options={[{ value: 'rivers', label: '河道' }, { value: 'cross_sections', label: '横断面' }, { value: 'gates', label: '闸门' }, { value: 'pumps', label: '泵站' }]} /></Col><Col span={8}><Text>文件格式</Text><Select value={kind} onChange={setKind} style={{ width: '100%', marginTop: 8 }} options={[{ value: 'excel', label: 'Excel .xlsx' }, { value: 'csv', label: 'CSV UTF-8' }, { value: 'geojson', label: 'GeoJSON' }]} /></Col><Col span={8}><Text>当前数据版本</Text><InputNumber min={1} value={datasetVersionId} disabled style={{ width: '100%', marginTop: 8 }} /></Col></Row><Upload.Dragger className="data-uploader" beforeUpload={() => false} maxCount={1} fileList={files} onChange={({ fileList }) => setFiles(fileList)}><p className="ant-upload-drag-icon"><CloudUploadOutlined /></p><p className="ant-upload-text">点击或拖拽文件到这里</p><p className="ant-upload-hint">单文件不超过 20 MB；失败批次不会写入部分数据</p></Upload.Dragger><Space wrap><Button type="primary" loading={loading} onClick={() => void upload()}>开始校验并导入</Button><Button icon={<FileExcelOutlined />} href={`/api/v1/import/templates/${resource}`}>下载 Excel 模板</Button></Space></Card></Col><Col xs={24} lg={9}><Card className="data-card" title="最近一次导入结果">{result ? <><Alert type={result.status === 'success' ? 'success' : 'error'} showIcon message={result.status === 'success' ? `已导入 ${result.imported_count} 条` : '导入未写入'} description={`存档：${result.stored_filename}`} /><div className="import-issues">{result.errors.map((issue) => <Alert key={`${issue.row}-${issue.message}`} type="error" message={`第 ${issue.row} 行：${issue.message}`} />)}</div></> : <div className="data-empty">完成一次导入后，这里会显示数量和逐行错误。</div>}</Card></Col></Row></div>;
}

export function DataValidationPage() {
  const { datasetVersionId } = useDatasetVersion();
  const [report, setReport] = useState<ValidationReport>();
  const [loading, setLoading] = useState(false);
  const execute = async () => { if (!datasetVersionId) return; setLoading(true); try { setReport(await runValidation(datasetVersionId)); } catch (reason) { message.error(reason instanceof Error ? reason.message : '校验失败'); } finally { setLoading(false); } };
  const columns: ColumnsType<ValidationReport['items'][number]> = [{ title: '规则', dataIndex: 'code', width: 250 }, { title: '类别', dataIndex: 'category', width: 100 }, { title: '结果', dataIndex: 'severity', width: 100, render: (value: string) => <Tag color={value === 'passed' ? 'success' : value === 'warning' ? 'warning' : 'error'}>{value}</Tag> }, { title: '说明', dataIndex: 'message' }, { title: '数量', dataIndex: 'count', width: 80 }];
  return <div className="data-page"><DataPageHeader eyebrow="QUALITY GATE / VALIDATION" title="数据校验中心" description="在进入水动力模型前，自动检查空间几何、水力断面、建筑物参数、拓扑与模型配置完整性。" action={<Space><InputNumber min={1} value={datasetVersionId} disabled addonBefore="当前版本 ID" /><Button type="primary" icon={<SafetyCertificateOutlined />} loading={loading} disabled={!datasetVersionId} onClick={() => void execute()}>运行校验</Button></Space>} />{report ? <><Row gutter={16} className="quality-stats"><Col span={6}><Card className="data-card"><Statistic title="模型就绪" value={report.summary.is_model_ready ? '是' : '否'} prefix={report.summary.is_model_ready ? <CheckCircleOutlined /> : undefined} /></Card></Col><Col span={6}><Card className="data-card"><Statistic title="错误规则" value={report.summary.errors} valueStyle={{ color: report.summary.errors ? '#ff6b68' : '#2fe6d6' }} /></Card></Col><Col span={6}><Card className="data-card"><Statistic title="警告规则" value={report.summary.warnings} /></Card></Col><Col span={6}><Card className="data-card"><Statistic title="通过规则" value={report.summary.passed} /></Card></Col></Row><Card className="data-card" title={`校验报告 · ${new Date(report.checked_time).toLocaleString()}`}><Progress percent={Math.round((report.summary.passed / Math.max(report.items.length, 1)) * 100)} status={report.summary.errors ? 'exception' : 'success'} /><Table rowKey="code" columns={columns} dataSource={report.items} pagination={false} scroll={{ x: 820 }} /></Card></> : <Card className="data-card"><div className="data-empty">选择数据版本并运行校验，结果将按错误、警告和通过分类展示。</div></Card>}</div>;
}

export function ModelDataPage() {
  const { datasetVersionId } = useDatasetVersion();
  const [snapshot, setSnapshot] = useState<ModelInputSnapshot>();
  const versions = useRemoteList(() => getDatasetVersions(), []);
  const parameters = useRemoteList(() => getModelParameters(datasetVersionId), [datasetVersionId]);
  const boundaries = useRemoteList(() => getBoundaryConditions(datasetVersionId), [datasetVersionId]);
  const cases = useRemoteList(() => getSimulationCases(datasetVersionId), [datasetVersionId]);
  const tabs = [
    { key: 'versions', label: `数据版本 ${versions.data?.length ?? 0}`, children: <Table rowKey="id" loading={versions.loading} dataSource={versions.data ?? []} pagination={false} columns={[{ title: '版本', dataIndex: 'version' }, { title: '名称', dataIndex: 'name' }, { title: '创建者', dataIndex: 'creator' }, { title: '创建时间', dataIndex: 'created_time', render: (value: string) => new Date(value).toLocaleString() }]} /> },
    { key: 'parameters', label: `模型参数 ${parameters.data?.length ?? 0}`, children: <Table rowKey="id" loading={parameters.loading} dataSource={parameters.data ?? []} pagination={false} columns={[{ title: '类型', dataIndex: 'parameter_type' }, { title: '参数', dataIndex: 'parameter_name' }, { title: '数值', dataIndex: 'value' }, { title: '单位', dataIndex: 'unit' }]} /> },
    { key: 'boundaries', label: `边界条件 ${boundaries.data?.length ?? 0}`, children: <Table rowKey="id" loading={boundaries.loading} dataSource={boundaries.data ?? []} pagination={false} columns={[{ title: '名称', dataIndex: 'name' }, { title: '类型', dataIndex: 'boundary_type' }, { title: '目标节点', dataIndex: 'target_node_id' }, { title: '单位', dataIndex: 'unit' }]} /> },
    { key: 'cases', label: `计算方案 ${cases.data?.length ?? 0}`, children: <Table rowKey="id" loading={cases.loading} dataSource={cases.data ?? []} pagination={false} columns={[{ title: '名称', dataIndex: 'name' }, { title: '数据版本', dataIndex: 'dataset_version_id' }, { title: '边界条件', dataIndex: 'boundary_condition_id' }, { title: '操作', render: (_, record: { id: number }) => <Button onClick={async () => setSnapshot(await getModelInput(record.id))}>查看模型输入</Button> }]} /> },
  ];
  const inputCounts = snapshot ? [{ label: '河道', value: snapshot.rivers.length }, { label: '河段', value: snapshot.segments.length }, { label: '节点', value: snapshot.nodes.length }, { label: '断面', value: snapshot.cross_sections.length }, { label: '闸门', value: snapshot.gates.length }, { label: '泵站', value: snapshot.pumps.length }] : [];
  return <div className="data-page"><DataPageHeader eyebrow="PHASE 3 HANDOFF / MODEL DATA" title="模型数据管理" description="以数据版本和计算方案为边界，生成只读、可追溯的一维水动力模型输入快照。" /><Card className="data-card"><Tabs items={tabs} /></Card>{snapshot && <Card className="data-card model-snapshot" title={`输入快照 · ${snapshot.simulation_case.name}`} extra={<Tag color="cyan">{snapshot.schema_version}</Tag>}><Row gutter={12}>{inputCounts.map((item) => <Col key={item.label} span={4}><Statistic title={item.label} value={item.value} /></Col>)}</Row><Descriptions className="snapshot-meta" column={2} items={[{ key: 'version', label: '数据版本', children: `${snapshot.dataset_version.version} · ${snapshot.dataset_version.name}` }, { key: 'time', label: '生成时间', children: new Date(snapshot.generated_time).toLocaleString() }]} /></Card>}</div>;
}
