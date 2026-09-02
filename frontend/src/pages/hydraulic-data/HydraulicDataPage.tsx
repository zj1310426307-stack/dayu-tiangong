import {
  CheckCircleOutlined,
  CloudUploadOutlined,
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  FileExcelOutlined,
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
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Tree,
  Typography,
  Upload,
  message,
} from 'antd';
import type { DataNode } from 'antd/es/tree';
import type { ColumnsType } from 'antd/es/table';
import type { UploadFile } from 'antd/es/upload/interface';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  buildHydraulicTopology,
  commitHydraulicImport,
  createHydraulicStructure,
  deleteHydraulicStructure,
  downloadHydraulicNetwork,
  downloadHydraulicSections,
  downloadHydraulicTemplate,
  getHydraulicCapabilities,
  getHydraulicEngineCapabilities,
  getHydraulicSection,
  listHydraulicImportJobs,
  listHydraulicNetworks,
  listHydraulicStructures,
  locateHydraulicSection,
  previewHydraulicImport,
  processHydraulicProfile,
  recalculateHydraulicBranchChainage,
  reverseHydraulicBranch,
  runHydraulicDataValidation,
  updateHydraulicStructure,
  type HydraulicCapabilityResponse,
  type HydraulicImportJobRecord,
  type HydraulicImportPreview,
  type HydraulicIssue,
  type HydraulicNetworkRecord,
  type HydraulicProfileRecord,
  type HydraulicSectionDetail,
  type HydraulicStructureCreate,
  type HydraulicStructureRecord,
  type HydraulicValidationRunRecord,
  type SolverCapabilityRecord,
} from '../../api/generated/client';
import { datasetVersionStatusLabel, useDatasetVersion } from '../../context/DatasetVersionContext';


const { Paragraph, Text, Title } = Typography;
const SOURCE_SRIDS = [4490, 4326, 4546, 4547, 4548, 4549];
const ENGINEERING_SRIDS = [4546, 4547, 4548, 4549];
const CENTRAL_MERIDIANS: Record<number, number> = {
  4546: 111, 4547: 114, 4548: 117, 4549: 120,
};
type StructureFormValues = HydraulicStructureCreate & { discharge_coefficient?: number };

/** Trigger a browser download for a blob returned through the generated API client. */
function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

/** Keep severity styling consistent between preview and persisted validation findings. */
function issueTag(severity: string): React.ReactNode {
  const colors: Record<string, string> = {
    error: 'error', warning: 'warning', info: 'processing', passed: 'success',
  };
  return <Tag color={colors[severity] ?? 'default'}>{severity.toUpperCase()}</Tag>;
}

/** Render a dependency-free distance/elevation profile with explicit scales and units. */
function SectionProfileChart({ section, profile }: { section?: HydraulicSectionDetail; profile?: HydraulicProfileRecord }) {
  const points = profile?.points ?? [];
  if (!section || points.length < 2) {
    return <div className="hydraulic-data-empty">从左侧河网树选择一个断面后显示距离—高程曲线。</div>;
  }
  const width = 760;
  const height = 300;
  const margin = { left: 64, right: 24, top: 24, bottom: 50 };
  const distances = points.map((point) => point.distance);
  const elevations = points.map((point) => point.elevation);
  const minX = Math.min(...distances);
  const maxX = Math.max(...distances);
  const rawMinY = Math.min(...elevations);
  const rawMaxY = Math.max(...elevations);
  const paddingY = Math.max((rawMaxY - rawMinY) * 0.12, 0.5);
  const minY = rawMinY - paddingY;
  const maxY = rawMaxY + paddingY;
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const x = (value: number) => margin.left + ((value - minX) / Math.max(maxX - minX, 1)) * plotWidth;
  const y = (value: number) => margin.top + ((maxY - value) / Math.max(maxY - minY, 1)) * plotHeight;
  const path = points.map((point, index) => `${index ? 'L' : 'M'} ${x(point.distance)} ${y(point.elevation)}`).join(' ');
  const xTicks = Array.from({ length: 5 }, (_, index) => minX + ((maxX - minX) * index) / 4);
  const yTicks = Array.from({ length: 5 }, (_, index) => minY + ((maxY - minY) * index) / 4);
  return (
    <div className="section-profile-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${section.section_code} 距离高程曲线`}>
        {yTicks.map((tick) => (
          <g key={`y-${tick}`}>
            <line x1={margin.left} x2={width - margin.right} y1={y(tick)} y2={y(tick)} className="profile-grid" />
            <text x={margin.left - 10} y={y(tick) + 4} textAnchor="end">{tick.toFixed(2)}</text>
          </g>
        ))}
        {xTicks.map((tick) => (
          <g key={`x-${tick}`}>
            <line x1={x(tick)} x2={x(tick)} y1={margin.top} y2={height - margin.bottom} className="profile-grid" />
            <text x={x(tick)} y={height - margin.bottom + 22} textAnchor="middle">{tick.toFixed(1)}</text>
          </g>
        ))}
        <path d={path} className="profile-line" />
        {points.map((point) => (
          <circle key={point.sequence} cx={x(point.distance)} cy={y(point.elevation)} r="4" className="profile-point">
            <title>{`距离 ${point.distance.toFixed(3)} m，高程 ${point.elevation.toFixed(3)} m`}</title>
          </circle>
        ))}
        <text x={margin.left + plotWidth / 2} y={height - 8} textAnchor="middle" className="profile-axis-label">距离（m）</text>
        <text transform={`translate(18 ${margin.top + plotHeight / 2}) rotate(-90)`} textAnchor="middle" className="profile-axis-label">高程（m）</text>
      </svg>
    </div>
  );
}

/** Build stable tree keys while retaining the selected network needed by exports. */
function networkTree(
  items: HydraulicNetworkRecord[],
  structures: HydraulicStructureRecord[],
): DataNode[] {
  return items.map((network) => ({
    key: `network:${network.id}`,
    title: `${network.name} · ${network.code}`,
    children: [
      {
        key: `nodes:${network.id}`,
        title: `节点（${network.nodes?.length ?? 0}）`,
        children: (network.nodes ?? []).map((node) => ({
          key: `node:${network.id}:${node.id}`,
          title: `${node.node_code} · ${node.node_type}`,
          isLeaf: true,
        })),
      },
      ...(network.branches ?? []).map((branch) => ({
        key: `branch:${network.id}:${branch.id}`,
        title: `${branch.branch_name} · ${branch.branch_code} · ${branch.direction_status} · ${branch.reach_count} Reach`,
        children: [
          ...(branch.sections ?? []).map((section) => ({
            key: `section:${network.id}:${branch.id}:${section.id}`,
            title: `${section.section_code} · K${section.chainage.toFixed(3)}`,
            isLeaf: true,
          })),
          ...structures.filter((item) => item.branch_id === branch.id).map((item) => ({
            key: `structure:${network.id}:${branch.id}:${item.id}`,
            title: `${item.structure_name} · ${item.structure_type} · K${item.chainage_m.toFixed(3)}`,
            isLeaf: true,
          })),
        ],
      })),
    ],
  }));
}

/** Present versioned hydraulic exchange data without bypassing generated OpenAPI functions. */
export function HydraulicDataPage() {
  const { datasetVersionId, currentVersion, isMutable } = useDatasetVersion();
  const [networks, setNetworks] = useState<HydraulicNetworkRecord[]>([]);
  const [jobs, setJobs] = useState<HydraulicImportJobRecord[]>([]);
  const [capabilities, setCapabilities] = useState<HydraulicCapabilityResponse>();
  const [engineCapabilities, setEngineCapabilities] = useState<SolverCapabilityRecord[]>([]);
  const [structures, setStructures] = useState<HydraulicStructureRecord[]>([]);
  const [structureModalOpen, setStructureModalOpen] = useState(false);
  const [editingStructure, setEditingStructure] = useState<HydraulicStructureRecord>();
  const [structureForm] = Form.useForm<StructureFormValues>();
  const [section, setSection] = useState<HydraulicSectionDetail>();
  const [selectedNetworkId, setSelectedNetworkId] = useState<number>();
  const [selectedBranchId, setSelectedBranchId] = useState<number>();
  const [selectedProfileId, setSelectedProfileId] = useState<number>();
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [sourceSrid, setSourceSrid] = useState(4547);
  const [engineeringSrid, setEngineeringSrid] = useState(4547);
  const [axisMapping, setAxisMapping] = useState<'x_easting_y_northing' | 'x_northing_y_easting'>('x_easting_y_northing');
  const [preview, setPreview] = useState<HydraulicImportPreview>();
  const [validation, setValidation] = useState<HydraulicValidationRunRecord>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const reload = useCallback(async () => {
    if (!datasetVersionId) return;
    setLoading(true);
    setError('');
    try {
      const [networkRows, jobRows, capability, engineRows, structureRows] = await Promise.all([
        listHydraulicNetworks(datasetVersionId),
        listHydraulicImportJobs(datasetVersionId),
        getHydraulicCapabilities(),
        getHydraulicEngineCapabilities(),
        listHydraulicStructures({ dataset_version_id: datasetVersionId }),
      ]);
      setNetworks(networkRows);
      setJobs(jobRows);
      setCapabilities(capability);
      setEngineCapabilities(
        engineRows.filter((item) => item.engine === 'mascaret'),
      );
      setStructures(structureRows);
      setSelectedNetworkId((current) => (
        current && networkRows.some((item) => item.id === current)
          ? current
          : networkRows[0]?.id
      ));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '水动力数据加载失败');
    } finally {
      setLoading(false);
    }
  }, [datasetVersionId]);

  useEffect(() => {
    setSection(undefined);
    setSelectedBranchId(undefined);
    setSelectedProfileId(undefined);
    setPreview(undefined);
    setValidation(undefined);
    void reload();
  }, [reload]);

  const selectTreeNode = async (keys: React.Key[]) => {
    const key = String(keys[0] ?? '');
    const parts = key.split(':');
    if (parts[0] === 'network') setSelectedNetworkId(Number(parts[1]));
    if (parts[0] === 'branch') {
      setSelectedNetworkId(Number(parts[1]));
      setSelectedBranchId(Number(parts[2]));
    }
    if (parts[0] !== 'section') return;
    setSelectedNetworkId(Number(parts[1]));
    setSelectedBranchId(Number(parts[2]));
    try {
      const value = await getHydraulicSection(Number(parts[3]));
      setSection(value);
      setSelectedProfileId(value.profiles.find((profile) => profile.is_active)?.id ?? value.profiles[0]?.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '断面详情加载失败');
    }
  };

  const executePreview = async () => {
    const file = files[0]?.originFileObj;
    if (!datasetVersionId || !file) return;
    setLoading(true);
    setError('');
    try {
      const geographic = sourceSrid === 4326 || sourceSrid === 4490;
      const result = await previewHydraulicImport(datasetVersionId, {
        source_crs: `EPSG:${sourceSrid}`,
        engineering_crs: `EPSG:${engineeringSrid}`,
        coordinate_mode: geographic ? 'geographic' : 'projected',
        axis_mapping: axisMapping,
        horizontal_unit: geographic ? 'degree' : 'm',
        vertical_datum: '1985国家高程基准',
        vertical_unit: 'm',
        central_meridian: CENTRAL_MERIDIANS[engineeringSrid],
        zone_width: 3,
        zone_prefix_mode: 'none',
      }, file);
      setPreview(result);
      setJobs(await listHydraulicImportJobs(datasetVersionId));
      message.success(result.job.status === 'previewed' ? '预检通过，可确认提交' : '预检完成，存在阻断问题');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '导入预检失败');
    } finally {
      setLoading(false);
    }
  };

  const executeCommit = async () => {
    if (!preview || preview.job.status !== 'previewed') return;
    setLoading(true);
    try {
      const result = await commitHydraulicImport(preview.job.job_code, preview.job.config_hash);
      setPreview((current) => current ? { ...current, job: result } : current);
      setFiles([]);
      await reload();
      message.success('河网与断面已原子同步到水动力和现有 GIS 数据结构');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '确认提交失败');
    } finally {
      setLoading(false);
    }
  };

  const executeValidation = async () => {
    if (!datasetVersionId) return;
    setLoading(true);
    try {
      setValidation(await runHydraulicDataValidation(datasetVersionId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '水动力校核失败');
    } finally {
      setLoading(false);
    }
  };

  const executeTopology = async () => {
    if (!selectedNetworkId) return;
    setLoading(true);
    try {
      const report = await buildHydraulicTopology(selectedNetworkId, {
        snap_tolerance_m: 0.5, minimum_reach_length_m: 0.1,
      });
      await reload();
      message.success(`拓扑已生成：${report.node_count} 节点、${report.reach_count} Reach`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '拓扑生成失败');
    } finally {
      setLoading(false);
    }
  };

  const executeBranchAction = async (kind: 'reverse' | 'chainage') => {
    if (!selectedBranchId) return;
    setLoading(true);
    try {
      if (kind === 'reverse') await reverseHydraulicBranch(selectedBranchId);
      else await recalculateHydraulicBranchChainage(selectedBranchId);
      await reload();
      message.success(kind === 'reverse' ? '河段流向已反转' : '桩号已按工程长度重算');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '河段操作失败');
    } finally {
      setLoading(false);
    }
  };

  const executeProfileProcess = async () => {
    if (!selectedProfileId) return;
    setLoading(true);
    try {
      await processHydraulicProfile(selectedProfileId, { vertical_step_m: 0.05 });
      if (section) setSection(await getHydraulicSection(section.id));
      message.success('断面水力查算表已生成');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '断面处理失败');
    } finally {
      setLoading(false);
    }
  };

  const executeLocateSection = async () => {
    if (!section) return;
    setLoading(true);
    try {
      const value = await locateHydraulicSection(section.id, { snap_tolerance_m: 5 });
      setSection(value);
      message.success('断面桩号与方向已计算');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '断面定位失败');
    } finally {
      setLoading(false);
    }
  };

  const download = async (kind: 'network' | 'sections' | 'native-sections') => {
    if (!datasetVersionId) return;
    try {
      if (kind === 'network') {
        saveBlob(await downloadHydraulicNetwork({ dataset_version_id: datasetVersionId, network_id: selectedNetworkId }), 'network.nwk11');
      } else {
        saveBlob(await downloadHydraulicSections({ dataset_version_id: datasetVersionId, network_id: selectedNetworkId, native: kind === 'native-sections' }), 'cross-sections.xns11');
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '文件导出失败');
    }
  };

  const downloadTemplate = async (name: 'river-network' | 'cross-section') => {
    const filename = name === 'river-network' ? 'river_network.xlsx' : 'cross_section.xlsx';
    try {
      saveBlob(await downloadHydraulicTemplate(name), filename);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '模板下载失败');
    }
  };

  const openStructureCreate = () => {
    const network = networks.find((item) => item.id === selectedNetworkId) ?? networks[0];
    const branches = network?.branches ?? [];
    const branch = branches.find((item) => item.id === selectedBranchId) ?? branches[0];
    setEditingStructure(undefined);
    structureForm.resetFields();
    structureForm.setFieldsValue({
      dataset_version_id: datasetVersionId,
      network_id: network?.id,
      branch_id: branch?.id,
      structure_type: 'weir',
      hydraulic_law_type: 'broad_crested_weir',
      operation_rule_type: 'fixed',
      status: 'draft',
    });
    setStructureModalOpen(true);
  };

  const openStructureEdit = (record: HydraulicStructureRecord) => {
    const coordinates = Array.isArray(record.location_geometry.coordinates)
      ? record.location_geometry.coordinates as number[]
      : [];
    setEditingStructure(record);
    structureForm.setFieldsValue({
      dataset_version_id: record.dataset_version_id,
      network_id: record.network_id,
      branch_id: record.branch_id,
      structure_code: record.structure_code,
      structure_name: record.structure_name,
      structure_type: record.structure_type,
      chainage_m: record.chainage_m,
      x: coordinates[0],
      y: coordinates[1],
      crest_elevation_m: record.crest_elevation_m ?? undefined,
      invert_elevation_m: record.invert_elevation_m ?? undefined,
      width_m: record.width_m ?? undefined,
      height_m: record.height_m ?? undefined,
      hydraulic_law_type: record.hydraulic_law_type,
      discharge_coefficient: Number(record.hydraulic_parameters.discharge_coefficient ?? 0.435),
      operation_rule_type: record.operation_rule_type,
      status: record.status,
    });
    setStructureModalOpen(true);
  };

  const saveStructure = async () => {
    try {
      const values = await structureForm.validateFields();
      const { discharge_coefficient: coefficient, dataset_version_id, network_id, ...mutable } = values;
      const existingHydraulicParameters = editingStructure?.hydraulic_parameters ?? {};
      const hydraulicParameters = values.structure_type === 'weir'
        ? { ...existingHydraulicParameters, discharge_coefficient: coefficient }
        : existingHydraulicParameters;
      mutable.operation_parameters = editingStructure?.operation_parameters ?? {};
      mutable.metadata = editingStructure?.metadata ?? {};
      if (editingStructure) {
        await updateHydraulicStructure(editingStructure.id, {
          ...mutable,
          hydraulic_parameters: hydraulicParameters,
        });
      } else {
        await createHydraulicStructure({
          ...mutable,
          dataset_version_id,
          network_id,
          hydraulic_parameters: hydraulicParameters,
        });
      }
      setStructureModalOpen(false);
      await reload();
      message.success(editingStructure ? '建筑物已更新' : '建筑物已创建');
    } catch (reason) {
      if (reason instanceof Error) setError(reason.message);
    }
  };

  const removeStructure = async (structureId: number) => {
    try {
      await deleteHydraulicStructure(structureId);
      await reload();
      message.success('统一建筑物已删除；关联旧资产未被删除');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '建筑物删除失败');
    }
  };

  const treeData = useMemo(() => networkTree(networks, structures), [networks, structures]);
  const totalBranches = networks.reduce((sum, item) => sum + item.branch_count, 0);
  const totalSections = networks.reduce(
    (sum, item) => sum + (item.branches ?? []).reduce((branchSum, branch) => branchSum + branch.section_count, 0),
    0,
  );
  const totalNodes = networks.reduce((sum, item) => sum + item.node_count, 0);
  const activeProfile = section?.profiles.find((profile) => profile.id === selectedProfileId)
    ?? section?.profiles.find((profile) => profile.is_active)
    ?? section?.profiles[0];
  const jobColumns: ColumnsType<HydraulicImportJobRecord> = [
    { title: '任务', dataIndex: 'job_code', width: 215 },
    { title: '文件', dataIndex: 'filename', ellipsis: true },
    { title: '格式', dataIndex: 'source_format', width: 85 },
    { title: 'EPSG', dataIndex: 'source_srid', width: 80 },
    { title: '解析器', dataIndex: 'parser_profile', width: 205, ellipsis: true },
    { title: '状态', dataIndex: 'status', width: 105, render: (value: string) => <Tag color={value === 'committed' ? 'success' : value === 'previewed' ? 'processing' : 'error'}>{value}</Tag> },
    { title: '原生校验', dataIndex: 'native_validation_status', width: 190 },
    { title: '时间', dataIndex: 'created_at', width: 175, render: (value: string) => new Date(value).toLocaleString() },
  ];
  const issueColumns: ColumnsType<HydraulicIssue> = [
    { title: '级别', dataIndex: 'severity', width: 105, render: issueTag },
    { title: '规则', dataIndex: 'code', width: 220 },
    { title: '对象', dataIndex: 'entity_ref', width: 140, render: (value) => value ?? '—' },
    { title: '说明', dataIndex: 'message' },
  ];
  const structureColumns: ColumnsType<HydraulicStructureRecord> = [
    { title: '名称', dataIndex: 'structure_name', ellipsis: true },
    { title: '类型', dataIndex: 'structure_type', width: 110 },
    { title: '河段', dataIndex: 'branch_id', width: 80 },
    { title: '桩号（m）', dataIndex: 'chainage_m', width: 120, render: (value: number) => value.toFixed(3) },
    { title: '状态', dataIndex: 'status', width: 95, render: (value: string) => <Tag>{value}</Tag> },
    {
      title: 'MASCARET 9.1.1', dataIndex: 'solver_status', width: 170,
      render: (value: string, record) => (
        <Tag title={record.solver_reason} color={value.startsWith('VERIFIED') ? 'success' : value === 'UNSUPPORTED' ? 'error' : 'warning'}>{value}</Tag>
      ),
    },
    {
      title: '操作', key: 'actions', width: 150,
      render: (_, record) => <Space>
        <Button size="small" icon={<EditOutlined />} disabled={!isMutable} onClick={() => openStructureEdit(record)}>编辑</Button>
        <Popconfirm title="删除统一建筑物？旧 Gate/Pump 资产不会随之删除。" onConfirm={() => void removeStructure(record.id)}>
          <Button size="small" danger icon={<DeleteOutlined />} disabled={!isMutable} />
        </Popconfirm>
      </Space>,
    },
  ];

  return (
    <div className="data-page hydraulic-data-page">
      <header className="data-page__header">
        <div>
          <span className="hero-kicker"><i /> HYDRO-DATA-01 / EXCHANGE</span>
          <Title level={1}>水动力数据管理</Title>
          <Paragraph>以 Dataset Version 为边界管理 Network–Node–Branch–Reach–Chainage、断面地形版本和水力查算表；坐标转换、预检、提交与模型输入均可审计。</Paragraph>
        </div>
        <Space wrap>
          <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void reload()}>刷新</Button>
          <Button disabled={!isMutable || !selectedNetworkId} onClick={() => void executeTopology()}>生成拓扑</Button>
          <Button disabled={!isMutable || !selectedBranchId} onClick={() => void executeBranchAction('reverse')}>反转河段</Button>
          <Button disabled={!isMutable || !selectedBranchId} onClick={() => void executeBranchAction('chainage')}>重算桩号</Button>
          <Button type="primary" icon={<SafetyCertificateOutlined />} onClick={() => void executeValidation()}>运行校核</Button>
        </Space>
      </header>

      {error && <Alert className="data-alert" type="error" showIcon closable message={error} onClose={() => setError('')} />}
      <Alert
        className="data-alert"
        type={isMutable ? 'info' : 'warning'}
        showIcon
        message={`当前版本：${currentVersion?.version ?? '—'} · ${datasetVersionStatusLabel(currentVersion?.status)}`}
        description={isMutable ? '草稿版本允许确认提交；预览和读取不会修改河网核心数据。' : '当前版本为只读，仍可浏览、校核和导出，但不能确认导入。'}
      />

      <Row gutter={[16, 16]} className="hydraulic-data-stats">
        <Col xs={12} md={6}><Card className="data-card"><Statistic title="水动力网络" value={networks.length} /></Card></Col>
        <Col xs={12} md={6}><Card className="data-card"><Statistic title="河段" value={totalBranches} /></Card></Col>
        <Col xs={12} md={6}><Card className="data-card"><Statistic title="节点 / 断面" value={`${totalNodes} / ${totalSections}`} /></Card></Col>
        <Col xs={12} md={6}><Card className="data-card"><Statistic title="最近导入" value={jobs[0]?.status ?? '—'} /></Card></Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={15}>
          <Card
            className="data-card"
            title="统一水工建筑物"
            extra={<Button type="primary" disabled={!isMutable || !networks.length} onClick={openStructureCreate}>创建建筑物</Button>}
          >
            <Alert
              type="info"
              showIcon
              message="可建模不等于可求解"
              description="Bridge、Culvert、Gate、Pump 等可以准确保存；提交 Standard 1D 前会按版本化能力矩阵明确阻断未验证或不支持的类型。"
              style={{ marginBottom: 12 }}
            />
            <Table rowKey="id" dataSource={structures} columns={structureColumns} pagination={{ pageSize: 6 }} scroll={{ x: 900 }} />
          </Card>
        </Col>
        <Col xs={24} xl={9}>
          <Card className="data-card" title="MASCARET 9.1.1 工程能力">
            <Table
              rowKey="feature"
              size="small"
              pagination={false}
              dataSource={engineCapabilities}
              scroll={{ y: 360 }}
              columns={[
                { title: '能力', dataIndex: 'feature' },
                {
                  title: '状态', dataIndex: 'status', width: 165,
                  render: (value: string, record: SolverCapabilityRecord) => (
                    <Tag title={record.reason} color={value.startsWith('VERIFIED') ? 'success' : value === 'UNSUPPORTED' ? 'error' : 'warning'}>{value}</Tag>
                  ),
                },
              ]}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={8}>
          <Card className="data-card hydraulic-tree-card" title="河网—河段—断面" loading={loading}>
            {treeData.length ? <Tree treeData={treeData} defaultExpandAll onSelect={(keys) => void selectTreeNode(keys)} /> : <div className="hydraulic-data-empty">该版本还没有水动力网络。</div>}
          </Card>
        </Col>
        <Col xs={24} lg={16}>
          <Card
            className="data-card"
            title={section ? `${section.section_code} · 桩号 ${section.chainage.toFixed(3)} m` : '断面距离—高程曲线'}
            extra={section && <Tag color="cyan">{activeProfile?.points.length ?? 0} 个点</Tag>}
          >
            {section && <Space wrap style={{ marginBottom: 12 }}>
              <Select
                value={activeProfile?.id}
                onChange={setSelectedProfileId}
                options={section.profiles.map((profile) => ({
                  value: profile.id,
                  label: `${profile.topography_id}${profile.is_active ? '（当前）' : ''}`,
                }))}
                style={{ minWidth: 220 }}
              />
              <Button disabled={!isMutable || !section.axis_geometry} onClick={() => void executeLocateSection()}>按轴线定位</Button>
              <Button disabled={!isMutable || !activeProfile} onClick={() => void executeProfileProcess()}>生成查算表</Button>
              {activeProfile?.processing && <Tag color="success">{activeProfile.processing.rows?.length ?? 0} 级水位</Tag>}
            </Space>}
            <SectionProfileChart section={section} profile={activeProfile} />
            {section && <Descriptions size="small" column={{ xs: 1, md: 3 }} items={[
              { key: 'branch', label: '河段', children: section.branch_code },
              { key: 'topo', label: '地形编号', children: activeProfile?.topography_id ?? '—' },
              { key: 'orientation', label: '方向', children: section.orientation_status },
              { key: 'datum', label: '高程基准', children: activeProfile?.vertical_datum ?? '—' },
              { key: 'chainage', label: '桩号来源', children: section.chainage_source },
              { key: 'snap', label: '吸附距离', children: section.snap_distance_m == null ? '—' : `${section.snap_distance_m.toFixed(3)} m` },
            ]} />}
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={14}>
          <Card className="data-card" title="文件预检与确认提交">
            <Row gutter={[12, 12]}>
              <Col xs={24} md={8}>
                <Text>源坐标系</Text>
                <Select value={sourceSrid} onChange={setSourceSrid} options={SOURCE_SRIDS.map((value) => ({ value, label: `EPSG:${value}` }))} style={{ width: '100%', marginTop: 8 }} />
                <Text style={{ display: 'block', marginTop: 8 }}>工程坐标系（中央经线随 EPSG 锁定）</Text>
                <Select value={engineeringSrid} onChange={setEngineeringSrid} options={ENGINEERING_SRIDS.map((value) => ({ value, label: `EPSG:${value} · ${CENTRAL_MERIDIANS[value]}°E` }))} style={{ width: '100%', marginTop: 8 }} />
                <Text style={{ display: 'block', marginTop: 8 }}>轴序</Text>
                <Select value={axisMapping} onChange={setAxisMapping} options={[
                  { value: 'x_easting_y_northing', label: 'X=东 / Y=北' },
                  { value: 'x_northing_y_easting', label: 'X=北 / Y=东' },
                ]} style={{ width: '100%', marginTop: 8 }} />
              </Col>
              <Col xs={24} md={16}>
                <Text>支持 .nwk11 / .xns11 / .xlsx / .csv / .geojson / .zip（SHP）/ .dxf，最大 100 MB</Text>
                <Upload.Dragger className="hydraulic-compact-uploader" beforeUpload={() => false} maxCount={1} fileList={files} onChange={({ fileList }) => setFiles(fileList)}>
                  <p className="ant-upload-drag-icon"><CloudUploadOutlined /></p>
                  <p className="ant-upload-text">点击或拖拽一个水动力文件</p>
                </Upload.Dragger>
              </Col>
            </Row>
            <Space wrap>
              <Button type="primary" loading={loading} disabled={!files[0]?.originFileObj} onClick={() => void executePreview()}>仅预检</Button>
              <Button icon={<CheckCircleOutlined />} disabled={!isMutable || preview?.job.status !== 'previewed'} onClick={() => void executeCommit()}>确认提交</Button>
              <Button icon={<FileExcelOutlined />} onClick={() => void downloadTemplate('river-network')}>河网模板</Button>
              <Button icon={<FileExcelOutlined />} onClick={() => void downloadTemplate('cross-section')}>断面模板</Button>
            </Space>
            {preview && <div className="hydraulic-preview-panel">
              <Alert
                showIcon
                type={preview.job.status === 'previewed' || preview.job.status === 'committed' ? 'success' : 'error'}
                message={`${preview.job.job_code} · ${preview.job.status}`}
                description={`河段 ${preview.job.record_counts.branches ?? 0}，断面 ${preview.job.record_counts.cross_sections ?? 0}，配置哈希 ${preview.job.config_hash}`}
              />
              <Descriptions size="small" column={1} items={[
                { key: 'pipeline', label: '转换链', children: String(preview.job.transformation_evidence.pipeline ?? '—') },
                { key: 'runtime', label: '坐标运行时', children: String(preview.job.transformation_evidence.proj_version ?? '—') },
                { key: 'hash', label: '源文件 SHA-256', children: preview.job.source_hash_sha256 },
              ]} />
              <Table rowKey={(item) => `${item.code}-${item.entity_ref ?? ''}`} size="small" pagination={false} dataSource={preview.job.issues} columns={issueColumns} scroll={{ x: 760 }} />
            </div>}
          </Card>
        </Col>
        <Col xs={24} xl={10}>
          <Card className="data-card" title="MIKE11 交换能力">
            {capabilities && <>
              <Descriptions column={1} size="small" items={[
                { key: 'profile', label: '交换档案', children: capabilities.exchange_profile },
                { key: 'xns', label: '原生 XNS11', children: capabilities.native_xns11_available ? '可用' : '外部授权环境验收' },
                { key: 'engineering', label: '工程坐标系', children: capabilities.engineering_srids.map((value) => `EPSG:${value}`).join(' / ') },
                { key: 'nwk', label: '原生 NWK11', children: '不可用（内置确定性交换子集）' },
              ]} />
              <Alert type="warning" showIcon message="能力边界" description={capabilities.limitation} />
            </>}
            <Space wrap className="hydraulic-export-actions">
              <Button icon={<DownloadOutlined />} disabled={!selectedNetworkId} onClick={() => void download('network')}>导出 NWK11</Button>
              <Button icon={<DownloadOutlined />} disabled={!selectedNetworkId} onClick={() => void download('sections')}>导出 XNS11 子集</Button>
              <Button icon={<DownloadOutlined />} disabled={!selectedNetworkId || !capabilities?.native_xns11_available} onClick={() => void download('native-sections')}>原生 XNS11</Button>
            </Space>
          </Card>
        </Col>
      </Row>

      {validation && <Card className="data-card" title={`校核结果 · ${validation.run_code}`} extra={<Tag color={validation.status === 'passed' ? 'success' : 'error'}>{validation.status}</Tag>}>
        <Row gutter={[12, 12]} className="hydraulic-validation-summary">
          <Col xs={12} md={6}><Statistic title="通过门禁" value={validation.summary.passed_gate ? '是' : '否'} /></Col>
          <Col xs={12} md={6}><Statistic title="错误" value={Number(validation.summary.error ?? 0)} /></Col>
          <Col xs={12} md={6}><Statistic title="警告" value={Number(validation.summary.warning ?? 0)} /></Col>
          <Col xs={12} md={6}><Statistic title="通过" value={Number(validation.summary.passed ?? 0)} /></Col>
        </Row>
        <Table rowKey={(item) => `${item.code}-${item.entity_ref ?? ''}`} pagination={false} dataSource={validation.results} columns={issueColumns} scroll={{ x: 760 }} />
      </Card>}

      <Card className="data-card" title="导入审计记录">
        <Table rowKey="id" loading={loading} dataSource={jobs} columns={jobColumns} scroll={{ x: 1300 }} pagination={{ pageSize: 8 }} />
      </Card>

      <Modal
        title={editingStructure ? `编辑 ${editingStructure.structure_name}` : '创建统一水工建筑物'}
        open={structureModalOpen}
        width={760}
        onCancel={() => setStructureModalOpen(false)}
        onOk={() => void saveStructure()}
        okText="保存"
      >
        <Form form={structureForm} layout="vertical">
          <Form.Item name="dataset_version_id" hidden><InputNumber /></Form.Item>
          <Form.Item name="network_id" hidden><InputNumber /></Form.Item>
          <Row gutter={12}>
            <Col xs={24} md={12}><Form.Item name="structure_code" label="编码" rules={[{ required: true }]}><Input /></Form.Item></Col>
            <Col xs={24} md={12}><Form.Item name="structure_name" label="名称" rules={[{ required: true }]}><Input /></Form.Item></Col>
            <Col xs={24} md={8}><Form.Item name="structure_type" label="类型" rules={[{ required: true }]}><Select onChange={(value) => structureForm.setFieldValue('hydraulic_law_type', value === 'weir' ? 'broad_crested_weir' : 'none')} options={['weir', 'culvert', 'bridge', 'gate', 'sluice', 'pump', 'orifice', 'dam', 'storage_link', 'compound'].map((value) => ({ value, label: value.toUpperCase() }))} /></Form.Item></Col>
            <Col xs={24} md={8}><Form.Item name="branch_id" label="河段" rules={[{ required: true }]}><Select options={networks.flatMap((network) => (network.branches ?? []).map((branch) => ({ value: branch.id, label: `${network.code} / ${branch.branch_code}` })))} /></Form.Item></Col>
            <Col xs={24} md={8}><Form.Item name="status" label="模型状态" rules={[{ required: true }]}><Select options={['draft', 'active', 'inactive', 'retired'].map((value) => ({ value, label: value }))} /></Form.Item></Col>
            <Col xs={24} md={8}><Form.Item name="chainage_m" label="桩号（m）" rules={[{ required: true }]}><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
            <Col xs={24} md={8}><Form.Item name="x" label="CGCS2000 X（经度）" rules={[{ required: true }]}><InputNumber style={{ width: '100%' }} /></Form.Item></Col>
            <Col xs={24} md={8}><Form.Item name="y" label="CGCS2000 Y（纬度）" rules={[{ required: true }]}><InputNumber style={{ width: '100%' }} /></Form.Item></Col>
            <Col xs={24} md={8}><Form.Item name="crest_elevation_m" label="堰顶/顶高程（m）"><InputNumber style={{ width: '100%' }} /></Form.Item></Col>
            <Col xs={24} md={8}><Form.Item name="invert_elevation_m" label="底高程（m）"><InputNumber style={{ width: '100%' }} /></Form.Item></Col>
            <Col xs={24} md={8}><Form.Item name="width_m" label="宽度（m）"><InputNumber min={0.001} style={{ width: '100%' }} /></Form.Item></Col>
            <Col xs={24} md={8}><Form.Item name="height_m" label="高度（m）"><InputNumber min={0.001} style={{ width: '100%' }} /></Form.Item></Col>
            <Col xs={24} md={8}><Form.Item name="discharge_coefficient" label="堰流量系数"><InputNumber min={0.001} style={{ width: '100%' }} /></Form.Item></Col>
            <Col xs={24} md={8}><Form.Item name="operation_rule_type" label="运行规则" rules={[{ required: true }]}><Select options={['fixed', 'time_series', 'water_level_controlled', 'scenario_specific'].map((value) => ({ value, label: value }))} /></Form.Item></Col>
          </Row>
          <Form.Item name="hydraulic_law_type" label="水力规律" rules={[{ required: true }]}><Input /></Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
