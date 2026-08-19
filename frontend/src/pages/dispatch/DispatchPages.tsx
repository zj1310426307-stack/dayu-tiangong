import {
  AimOutlined,
  CopyOutlined,
  FileProtectOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  StopOutlined,
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
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  cancelDispatchRun,
  cloneDispatchPlan,
  createDispatchAction,
  createDispatchPlan,
  createDispatchRule,
  createDispatchRun,
  deleteDispatchAction,
  deleteDispatchRule,
  freezeDispatchPlan,
  getDispatchComparison,
  getDispatchEvents,
  getDispatchNodes,
  getDispatchPlan,
  getDispatchRun,
  getDispatchStructures,
  getHydraulicTask,
  getSimulationCases,
  listDispatchActions,
  listDispatchPlans,
  listDispatchRules,
  listDispatchRuns,
  listGateRecords,
  listPumpRecords,
  retryDispatchRun,
  updateDispatchPlan,
  validateDispatchPlan,
  type DispatchActionCreate,
  type DispatchActionRecord,
  type DispatchComparison,
  type DispatchPlanCreate,
  type DispatchPlanRecord,
  type DispatchRuleCreate,
  type DispatchRuleRecord,
  type DispatchRunRecord,
  type GateRecord,
  type PumpRecord,
  type SimulationTaskRecord,
  type DispatchValidationReport,
} from '../../api/generated/client';
import { useDatasetVersion } from '../../context/DatasetVersionContext';

const { Paragraph, Text, Title } = Typography;
const SIMULATION_NOTICE = '仿真方案 / 未下发真实设备 / DEMO DATA 不得作为工程审定成果';
const DISPATCH_WINDOW_HOURS = 24;
const DISPATCH_MILESTONES_HOURS = [0, 6, 12, 24] as const;

type StructureKind = 'gate' | 'pump';
type StructureMetricKey = 'actual_value' | 'flow' | 'energy_kwh';

interface StructureMetricPanel {
  kind: StructureKind;
  metric: StructureMetricKey;
  title: string;
  unit: string;
}

interface LatestStructureStatus {
  key: string;
  label: string;
  status: string;
  actuator: string;
  flow?: number;
  controlSource: string;
  regime: string;
  timeHours: number;
}

interface StructureCoverage {
  key: string;
  label: string;
  times: number[];
  startHours: number;
  endHours: number;
}

const STRUCTURE_METRIC_PANELS: StructureMetricPanel[] = [
  { kind: 'gate', metric: 'actual_value', title: '闸门开度', unit: 'm' },
  { kind: 'gate', metric: 'flow', title: '闸门流量', unit: 'm³/s' },
  { kind: 'pump', metric: 'flow', title: '泵站流量', unit: 'm³/s' },
  { kind: 'pump', metric: 'energy_kwh', title: '泵站累计能耗', unit: 'kWh' },
];

function DispatchHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <>
      <header className="data-page__header">
        <div>
          <span className="hero-kicker"><i /> {eyebrow}</span>
          <Title level={1}>{title}</Title>
          <Paragraph>{description}</Paragraph>
        </div>
        {action}
      </header>
      <Alert className="dispatch-notice" type="warning" showIcon message={SIMULATION_NOTICE} />
    </>
  );
}

const statusColor: Record<string, string> = {
  draft: 'default', validated: 'processing', frozen: 'cyan', archived: 'default',
  pending: 'default', queued: 'blue', running: 'processing', cancel_requested: 'warning',
  cancelled: 'default', success: 'success', failed: 'error',
};
function stateTag(value: string) {
  return <Tag color={statusColor[value] ?? 'default'}>{value}</Tag>;
}
function localTime(value: string | null) {
  return value ? new Date(value).toLocaleString() : '—';
}
function errorText(reason: unknown, fallback: string) {
  return reason instanceof Error ? reason.message : fallback;
}

export function DispatchPlanListPage() {
  const navigate = useNavigate();
  const { datasetVersionId } = useDatasetVersion();
  const [plans, setPlans] = useState<DispatchPlanRecord[]>([]);
  const [cases, setCases] = useState<Array<{ id: number; name: string }>>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm<DispatchPlanCreate>();

  const reload = useCallback(async () => {
    if (!datasetVersionId) return;
    setLoading(true);
    setError('');
    try {
      const [page, caseRows] = await Promise.all([
        listDispatchPlans({ dataset_version_id: datasetVersionId, limit: 200 }),
        getSimulationCases(datasetVersionId),
      ]);
      setPlans(page.items);
      setCases(caseRows.map((item) => ({ id: item.id, name: item.name })));
    } catch (reason) {
      setError(errorText(reason, '调度计划加载失败'));
    } finally {
      setLoading(false);
    }
  }, [datasetVersionId]);

  useEffect(() => { void reload(); }, [reload]);

  const create = async (values: DispatchPlanCreate) => {
    if (!datasetVersionId) return;
    try {
      const plan = await createDispatchPlan({
        ...values,
        dataset_version_id: datasetVersionId,
        evaluation_config: {
          warning_level: Number((values.evaluation_config as { warning_level?: number })?.warning_level ?? 200),
        },
      });
      setOpen(false);
      form.resetFields();
      navigate(`/dispatch/plans/${plan.id}?datasetVersionId=${datasetVersionId}`);
    } catch (reason) {
      message.error(errorText(reason, '计划创建失败'));
    }
  };

  const operate = async (plan: DispatchPlanRecord, action: 'validate' | 'freeze' | 'clone' | 'run' | 'archive') => {
    try {
      if (action === 'validate') {
        const report = await validateDispatchPlan(plan.id);
        report.valid ? message.success('计划校验通过') : message.error(report.errors.join('；'));
      } else if (action === 'freeze') {
        await freezeDispatchPlan(plan.id); message.success('计划已冻结并生成 SHA-256');
      } else if (action === 'clone') {
        const clone = await cloneDispatchPlan(plan.id);
        navigate(`/dispatch/plans/${clone.id}?datasetVersionId=${datasetVersionId}`); return;
      } else if (action === 'run') {
        const run = await createDispatchRun(plan.id);
        navigate(`/dispatch/runs/${run.id}?datasetVersionId=${datasetVersionId}`); return;
      } else {
        await updateDispatchPlan(plan.id, { status: 'archived' }); message.success('计划已归档');
      }
      await reload();
    } catch (reason) {
      message.error(errorText(reason, '操作失败'));
    }
  };

  const columns: ColumnsType<DispatchPlanRecord> = [
    { title: '计划', dataIndex: 'name', width: 190, render: (value, row) => <Button type="link" onClick={() => navigate(`/dispatch/plans/${row.id}?datasetVersionId=${datasetVersionId}`)}>{value}</Button> },
    { title: '版本', dataIndex: 'version', width: 75, render: (value) => `v${value}` },
    { title: '数据版本', dataIndex: 'dataset_version_id', width: 100 },
    { title: '计算方案', dataIndex: 'simulation_case_id', width: 100 },
    { title: '状态', dataIndex: 'status', width: 105, render: stateTag },
    { title: '动作', dataIndex: 'action_count', width: 75 },
    { title: '规则', dataIndex: 'rule_count', width: 75 },
    { title: '创建时间', dataIndex: 'created_time', width: 170, render: localTime },
    { title: '冻结时间', dataIndex: 'frozen_time', width: 170, render: localTime },
    {
      title: '操作', key: 'actions', width: 330, fixed: 'right', render: (_, row) => (
        <Space size={4} wrap>
          {row.status !== 'archived' && <Button size="small" onClick={() => navigate(`/dispatch/plans/${row.id}?datasetVersionId=${datasetVersionId}`)}>查看/编辑</Button>}
          {row.status === 'draft' && <Button size="small" onClick={() => void operate(row, 'validate')}>校验</Button>}
          {row.status === 'validated' && <Button size="small" icon={<FileProtectOutlined />} onClick={() => void operate(row, 'freeze')}>冻结</Button>}
          <Button size="small" icon={<CopyOutlined />} onClick={() => void operate(row, 'clone')}>克隆</Button>
          {row.status === 'frozen' && <Button size="small" type="primary" icon={<PlayCircleOutlined />} onClick={() => void operate(row, 'run')}>运行</Button>}
          {row.status === 'frozen' && <Button size="small" onClick={() => void operate(row, 'archive')}>归档</Button>}
        </Space>
      ),
    },
  ];

  return (
    <div className="data-page dispatch-page">
      <DispatchHeader
        eyebrow="DISPATCH / VERSIONED PLANS"
        title="闸泵联合调度计划"
        description="计划按数据版本管理，经过校验和冻结后才能排队运行；冻结版本只能克隆迭代。"
        action={<Space><Button onClick={() => navigate(`/dispatch/runs?datasetVersionId=${datasetVersionId}`)}>运行中心</Button><Button type="primary" icon={<PlusOutlined />} disabled={!cases.length} onClick={() => { form.setFieldsValue({ simulation_case_id: cases[0]?.id, duration_seconds: 7200, storage_level: 'key_sections', evaluation_config: { warning_level: 200 } }); setOpen(true); }}>新建计划</Button></Space>}
      />
      {error && <Alert className="data-alert" type="error" showIcon message={error} />}
      {!loading && datasetVersionId && cases.length === 0 && !error && (
        <Alert
          className="data-alert"
          type="warning"
          showIcon
          message={`数据版本 #${datasetVersionId} 暂无计算方案`}
          description="请在顶部切换到包含模型数据的版本，或先在草稿版本的“模型数据”中配置参数、边界条件和计算方案；未绑定方案时不会创建不可运行的调度计划。"
        />
      )}
      <Card className="data-card" title={`当前数据版本 · ${datasetVersionId ?? '—'}`} extra={<Button icon={<ReloadOutlined />} onClick={() => void reload()} />}>
        <Table rowKey="id" loading={loading} dataSource={plans} columns={columns} scroll={{ x: 1500 }} pagination={{ pageSize: 12 }} />
      </Card>
      <Modal open={open} title="新建调度计划" onCancel={() => setOpen(false)} onOk={() => form.submit()} destroyOnHidden>
        <Form form={form} layout="vertical" onFinish={(values) => void create(values)}>
          <Form.Item name="name" label="计划名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="simulation_case_id" label="计算方案" rules={[{ required: true }]}><Select options={cases.map((item) => ({ value: item.id, label: item.name }))} /></Form.Item>
          <Row gutter={12}><Col span={12}><Form.Item name="duration_seconds" label="仿真时长（s）" rules={[{ required: true }]}><InputNumber min={1} style={{ width: '100%' }} /></Form.Item></Col><Col span={12}><Form.Item name="storage_level" label="结果存储"><Select options={['summary', 'key_sections', 'full'].map((value) => ({ value, label: value }))} /></Form.Item></Col></Row>
          <Form.Item name={['evaluation_config', 'warning_level']} label="警戒水位（m）"><InputNumber style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="description" label="说明"><Input.TextArea rows={3} /></Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

type ActionForm = DispatchActionCreate & { asset_id: number };
type RuleForm = Omit<DispatchRuleCreate, 'action_template'> & {
  structure_type: 'gate' | 'pump';
  structure_id: number;
  command_type: DispatchActionCreate['command_type'];
  target_value: number;
};

export function DispatchPlanEditorPage() {
  const navigate = useNavigate();
  const { planId = '' } = useParams();
  const id = Number(planId);
  const { datasetVersionId } = useDatasetVersion();
  const [plan, setPlan] = useState<DispatchPlanRecord>();
  const [actions, setActions] = useState<DispatchActionRecord[]>([]);
  const [rules, setRules] = useState<DispatchRuleRecord[]>([]);
  const [gates, setGates] = useState<GateRecord[]>([]);
  const [pumps, setPumps] = useState<PumpRecord[]>([]);
  const [report, setReport] = useState<DispatchValidationReport>();
  const [error, setError] = useState('');
  const [actionOpen, setActionOpen] = useState(false);
  const [ruleOpen, setRuleOpen] = useState(false);
  const [actionForm] = Form.useForm<ActionForm>();
  const [ruleForm] = Form.useForm<RuleForm>();
  const watchedActionType = Form.useWatch('structure_type', actionForm) ?? 'gate';
  const watchedRuleType = Form.useWatch('structure_type', ruleForm) ?? 'gate';

  const reload = useCallback(async () => {
    if (!id) return;
    try {
      const record = await getDispatchPlan(id);
      if (datasetVersionId && record.dataset_version_id !== datasetVersionId) {
        throw new Error('计划与当前数据版本不一致，请切换数据版本');
      }
      const [actionRows, ruleRows, gatePage, pumpPage] = await Promise.all([
        listDispatchActions(id), listDispatchRules(id),
        listGateRecords({ dataset_version_id: record.dataset_version_id, limit: 200 }),
        listPumpRecords({ dataset_version_id: record.dataset_version_id, limit: 200 }),
      ]);
      setPlan(record); setActions(actionRows); setRules(ruleRows);
      setGates(gatePage.items); setPumps(pumpPage.items); setError('');
    } catch (reason) { setError(errorText(reason, '计划加载失败')); }
  }, [datasetVersionId, id]);
  useEffect(() => { void reload(); }, [reload]);
  const editable = plan?.status === 'draft' || plan?.status === 'validated';

  const submitAction = async (values: ActionForm) => {
    const { asset_id, ...rest } = values;
    const payload: DispatchActionCreate = {
      ...rest,
      gate_id: values.structure_type === 'gate' ? asset_id : null,
      pump_id: values.structure_type === 'pump' ? asset_id : null,
    };
    await createDispatchAction(id, payload);
    setActionOpen(false); actionForm.resetFields(); await reload();
  };
  const submitRule = async (values: RuleForm) => {
    const { structure_type, structure_id, command_type, target_value, ...rule } = values;
    await createDispatchRule(id, {
      ...rule,
      action_template: { structure_type, structure_id, command_type, target_value },
    });
    setRuleOpen(false); ruleForm.resetFields(); await reload();
  };
  const validate = async () => { const value = await validateDispatchPlan(id); setReport(value); await reload(); };
  const freeze = async () => { await freezeDispatchPlan(id); message.success('冻结成功'); await reload(); };
  const run = async () => { const value = await createDispatchRun(id); navigate(`/dispatch/runs/${value.id}?datasetVersionId=${datasetVersionId}`); };

  const actionColumns: ColumnsType<DispatchActionRecord> = [
    { title: '时刻（s）', dataIndex: 'time_seconds', width: 100 },
    { title: '设施', width: 130, render: (_, row) => `${row.structure_type} #${row.gate_id ?? row.pump_id}` },
    { title: '命令', dataIndex: 'command_type', width: 180 },
    { title: '目标值', dataIndex: 'target_value', width: 100 },
    { title: '插值', dataIndex: 'interpolation', width: 90 },
    { title: '优先级', dataIndex: 'priority', width: 80 },
    { title: '备注', dataIndex: 'note' },
    { title: '操作', width: 80, render: (_, row) => editable && <Button danger size="small" onClick={async () => { await deleteDispatchAction(row.id); await reload(); }}>删除</Button> },
  ];
  const ruleColumns: ColumnsType<DispatchRuleRecord> = [
    { title: '规则', dataIndex: 'name', width: 150 },
    { title: '条件', render: (_, row) => `${row.observation_type}${row.observation_object_id ? ` #${row.observation_object_id}` : ''} ${row.operator} ${row.threshold}` },
    { title: '滞回', dataIndex: 'hysteresis', width: 80 },
    { title: '保持/冷却（s）', width: 130, render: (_, row) => `${row.minimum_hold_seconds} / ${row.cooldown_seconds}` },
    { title: '优先级', dataIndex: 'priority', width: 80 },
    { title: '动作模板', dataIndex: 'action_template', render: (value) => <code>{JSON.stringify(value)}</code> },
    { title: '操作', width: 80, render: (_, row) => editable && <Button danger size="small" onClick={async () => { await deleteDispatchRule(row.id); await reload(); }}>删除</Button> },
  ];

  return (
    <div className="data-page dispatch-page">
      <DispatchHeader
        eyebrow="DISPATCH / PLAN EDITOR"
        title={plan ? `${plan.name} · v${plan.version}` : '调度计划编辑器'}
        description="人工动作和白名单阈值规则在冻结前可编辑；计划命令只进入仿真求解器。"
        action={<Space><Button onClick={() => navigate(`/dispatch/plans?datasetVersionId=${datasetVersionId}`)}>返回列表</Button>{plan?.status === 'validated' && <Button icon={<FileProtectOutlined />} onClick={() => void freeze()}>冻结</Button>}{plan?.status === 'frozen' && <Button type="primary" icon={<PlayCircleOutlined />} onClick={() => void run()}>运行</Button>}</Space>}
      />
      {error && <Alert className="data-alert" type="error" showIcon message={error} />}
      {plan && <>
        <Card className="data-card" title="基本信息" extra={stateTag(plan.status)}>
          <Descriptions column={3} items={[
            { key: 'dataset', label: '数据版本', children: plan.dataset_version_id },
            { key: 'case', label: '计算方案', children: plan.simulation_case_id },
            { key: 'duration', label: '时长', children: `${plan.duration_seconds} s` },
            { key: 'storage', label: '存储级别', children: plan.storage_level },
            { key: 'hash', label: '冻结 SHA-256', children: plan.frozen_snapshot_hash ? <Text copyable>{plan.frozen_snapshot_hash}</Text> : '—' },
            { key: 'time', label: '冻结时间', children: localTime(plan.frozen_time) },
          ]} />
        </Card>
        <div className="dispatch-timeline" aria-label="动作时间轴">
          <span>0 s</span>
          <div>{actions.map((item) => <i key={item.id} title={`${item.structure_type} #${item.gate_id ?? item.pump_id} @ ${item.time_seconds}s`} style={{ left: `${Math.min(100, item.time_seconds / plan.duration_seconds * 100)}%` }} />)}</div>
          <span>{plan.duration_seconds} s</span>
        </div>
        <Card className="data-card" title="人工动作时间轴" extra={editable && <Button icon={<PlusOutlined />} onClick={() => { actionForm.setFieldsValue({ sequence: actions.length + 1, time_seconds: 0, structure_type: 'gate', command_type: 'gate_opening_m', target_value: 0, interpolation: 'step', priority: 10 }); setActionOpen(true); }}>新增动作</Button>}><Table rowKey="id" dataSource={actions} columns={actionColumns} pagination={false} scroll={{ x: 900 }} /></Card>
        <Card className="data-card" title="白名单阈值规则" extra={editable && <Button icon={<PlusOutlined />} onClick={() => { ruleForm.setFieldsValue({ enabled: true, observation_type: 'elapsed_time', operator: '>=', threshold: 0, hysteresis: 0, minimum_hold_seconds: 0, cooldown_seconds: 0, priority: 5, structure_type: 'gate', command_type: 'gate_opening_m', target_value: 0 }); setRuleOpen(true); }}>新增规则</Button>}><Table rowKey="id" dataSource={rules} columns={ruleColumns} pagination={false} scroll={{ x: 1000 }} /></Card>
        <Row gutter={16}>
          <Col xs={24} lg={12}><Card className="data-card" title="闸门约束摘要"><Table rowKey="id" size="small" pagination={false} dataSource={gates} columns={[{ title: '设施', dataIndex: 'name' }, { title: '状态', dataIndex: 'status', render: stateTag }, { title: '宽×高（m）', render: (_, row) => `${row.width} × ${row.height}` }, { title: '最大流量', dataIndex: 'max_flow' }, { title: '定位', render: (_, row) => <Button size="small" icon={<AimOutlined />} onClick={() => navigate(`/gis?datasetVersionId=${datasetVersionId}&selectedAsset=gate:${row.id}`)}>GIS</Button> }]} /></Card></Col>
          <Col xs={24} lg={12}><Card className="data-card" title="泵站约束摘要"><Table rowKey="id" size="small" pagination={false} dataSource={pumps} columns={[{ title: '设施', dataIndex: 'name' }, { title: '状态', dataIndex: 'status', render: stateTag }, { title: '设计流量', dataIndex: 'design_flow' }, { title: '扬程（m）', dataIndex: 'head' }, { title: '功率（kW）', dataIndex: 'power' }, { title: '定位', render: (_, row) => <Button size="small" icon={<AimOutlined />} onClick={() => navigate(`/gis?datasetVersionId=${datasetVersionId}&selectedAsset=pump:${row.id}`)}>GIS</Button> }]} /></Card></Col>
        </Row>
        <Card className="data-card" title="计划校验报告" extra={editable && <Button type="primary" icon={<SafetyCertificateOutlined />} onClick={() => void validate()}>运行校验</Button>}>
          {report ? <Alert type={report.valid ? 'success' : 'error'} showIcon message={report.valid ? '校验通过，可冻结' : '校验未通过'} description={[...report.errors, ...report.warnings].join('；') || '未发现问题'} /> : <div className="data-empty">运行校验后显示拓扑、跨版本、命令和规则检查结果。</div>}
        </Card>
      </>}
      <Modal open={actionOpen} title="新增人工动作" onCancel={() => setActionOpen(false)} onOk={() => actionForm.submit()} destroyOnHidden>
        <Form form={actionForm} layout="vertical" onFinish={(values) => void submitAction(values)}>
          <Row gutter={12}><Col span={12}><Form.Item name="structure_type" label="设施类型" rules={[{ required: true }]}><Select options={[{ value: 'gate', label: '闸门' }, { value: 'pump', label: '泵站' }]} /></Form.Item></Col><Col span={12}><Form.Item name="asset_id" label="设施" rules={[{ required: true }]}><Select options={(watchedActionType === 'gate' ? gates : pumps).map((item) => ({ value: item.id, label: item.name }))} /></Form.Item></Col></Row>
          <Row gutter={12}><Col span={12}><Form.Item name="time_seconds" label="时刻（s）" rules={[{ required: true }]}><InputNumber min={0} max={plan?.duration_seconds} style={{ width: '100%' }} /></Form.Item></Col><Col span={12}><Form.Item name="sequence" label="序号" rules={[{ required: true }]}><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col></Row>
          <Form.Item name="command_type" label="命令（单位由命令确定）" rules={[{ required: true }]}><Select options={(watchedActionType === 'gate' ? ['gate_opening_m', 'gate_opening_ratio'] : ['pump_enabled', 'pump_unit_count', 'pump_target_flow']).map((value) => ({ value, label: value }))} /></Form.Item>
          <Row gutter={12}><Col span={12}><Form.Item name="target_value" label="目标值" rules={[{ required: true }]}><InputNumber style={{ width: '100%' }} /></Form.Item></Col><Col span={12}><Form.Item name="priority" label="优先级"><InputNumber style={{ width: '100%' }} /></Form.Item></Col></Row>
          <Form.Item name="interpolation" label="插值"><Select options={['step', 'linear'].map((value) => ({ value, label: value }))} /></Form.Item><Form.Item name="note" label="备注"><Input /></Form.Item>
        </Form>
      </Modal>
      <Modal open={ruleOpen} title="新增受控阈值规则" onCancel={() => setRuleOpen(false)} onOk={() => ruleForm.submit()} width={720} destroyOnHidden>
        <Form form={ruleForm} layout="vertical" onFinish={(values) => void submitRule(values)}>
          <Form.Item name="name" label="规则名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Row gutter={12}><Col span={10}><Form.Item name="observation_type" label="观测类型" rules={[{ required: true }]}><Select options={['elapsed_time', 'node_water_level', 'section_water_level', 'gate_head_difference', 'pump_intake_level'].map((value) => ({ value, label: value }))} /></Form.Item></Col><Col span={7}><Form.Item name="observation_object_id" label="观测对象 ID"><InputNumber style={{ width: '100%' }} /></Form.Item></Col><Col span={7}><Form.Item name="operator" label="操作符"><Select options={['>', '>=', '<', '<='].map((value) => ({ value, label: value }))} /></Form.Item></Col></Row>
          <Row gutter={12}><Col span={6}><Form.Item name="threshold" label="阈值"><InputNumber style={{ width: '100%' }} /></Form.Item></Col><Col span={6}><Form.Item name="hysteresis" label="滞回"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col><Col span={6}><Form.Item name="minimum_hold_seconds" label="保持（s）"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col><Col span={6}><Form.Item name="cooldown_seconds" label="冷却（s）"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col></Row>
          <Row gutter={12}><Col span={8}><Form.Item name="structure_type" label="动作设施类型"><Select options={[{ value: 'gate', label: '闸门' }, { value: 'pump', label: '泵站' }]} /></Form.Item></Col><Col span={8}><Form.Item name="structure_id" label="动作设施"><Select options={(watchedRuleType === 'gate' ? gates : pumps).map((item) => ({ value: item.id, label: item.name }))} /></Form.Item></Col><Col span={8}><Form.Item name="priority" label="优先级"><InputNumber style={{ width: '100%' }} /></Form.Item></Col></Row>
          <Row gutter={12}><Col span={12}><Form.Item name="command_type" label="执行命令"><Select options={(watchedRuleType === 'gate' ? ['gate_opening_m', 'gate_opening_ratio'] : ['pump_enabled', 'pump_unit_count', 'pump_target_flow']).map((value) => ({ value, label: value }))} /></Form.Item></Col><Col span={12}><Form.Item name="target_value" label="命令目标值"><InputNumber style={{ width: '100%' }} /></Form.Item></Col></Row>
        </Form>
      </Modal>
    </div>
  );
}

export function DispatchRunListPage() {
  const navigate = useNavigate();
  const { datasetVersionId } = useDatasetVersion();
  const [runs, setRuns] = useState<DispatchRunRecord[]>([]);
  const [plans, setPlans] = useState<DispatchPlanRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [runPage, planPage] = await Promise.all([
        listDispatchRuns({ limit: 200 }),
        listDispatchPlans({ dataset_version_id: datasetVersionId, limit: 200 }),
      ]);
      const ids = new Set(planPage.items.map((item) => item.id));
      setPlans(planPage.items); setRuns(runPage.items.filter((item) => ids.has(item.plan_id)));
    } finally { setLoading(false); }
  }, [datasetVersionId]);
  useEffect(() => { void reload(); const timer = window.setInterval(() => void reload(), 5000); return () => window.clearInterval(timer); }, [reload]);
  const planName = (id: number) => plans.find((item) => item.id === id)?.name ?? `#${id}`;
  const columns: ColumnsType<DispatchRunRecord> = [
    { title: '运行', dataIndex: 'id', width: 85, render: (value) => `#${value}` },
    { title: '计划', dataIndex: 'plan_id', render: (value) => planName(value) },
    { title: '状态', dataIndex: 'status', width: 130, render: stateTag },
    { title: '进度', dataIndex: 'progress', width: 180, render: (value) => <Progress percent={value} size="small" /> },
    { title: '基准任务', dataIndex: 'baseline_task_id', width: 100 },
    { title: '调度任务', dataIndex: 'controlled_task_id', width: 100 },
    { title: '创建时间', dataIndex: 'created_time', width: 180, render: localTime },
    { title: '错误', dataIndex: 'error_message', ellipsis: true },
    { title: '操作', width: 200, render: (_, row) => <Space><Button size="small" onClick={() => navigate(`/dispatch/runs/${row.id}?datasetVersionId=${datasetVersionId}`)}>详情</Button>{['queued', 'running'].includes(row.status) && <Button size="small" danger onClick={async () => { await cancelDispatchRun(row.id); await reload(); }}>取消</Button>}{['failed', 'cancelled'].includes(row.status) && <Button size="small" onClick={async () => { const value = await retryDispatchRun(row.id); navigate(`/dispatch/runs/${value.id}?datasetVersionId=${datasetVersionId}`); }}>重试</Button>}</Space> },
  ];
  return <div className="data-page dispatch-page"><DispatchHeader eyebrow="DISPATCH / ASYNC RUNS" title="调度运行中心" description="基准与调度任务通过 Celery/Redis 异步执行；页面轮询数据库状态，不在浏览器请求中等待求解。" action={<Space><Button onClick={() => navigate(`/dispatch/plans?datasetVersionId=${datasetVersionId}`)}>计划列表</Button><Button icon={<ReloadOutlined />} onClick={() => void reload()} /></Space>} /><Card className="data-card"><Table rowKey="id" loading={loading} dataSource={runs} columns={columns} scroll={{ x: 1250 }} /></Card></div>;
}

function ComparisonChart({ comparison }: { comparison?: DispatchComparison }) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!element.current || !comparison) return undefined;
    let dispose: (() => void) | undefined;
    void import('echarts').then((echarts) => {
      if (!element.current) return;
      const chart = echarts.init(element.current);
      chart.setOption({
        tooltip: { trigger: 'axis' }, legend: { textStyle: { color: '#86a8ba' } },
        grid: { left: 60, right: 55, top: 45, bottom: 42 },
        xAxis: { type: 'category', data: comparison.time.map((item) => `${item}s`), axisLabel: { color: '#628196' } },
        yAxis: [{ type: 'value', name: '水位 / m' }, { type: 'value', name: '差值 / m' }],
        series: [
          { name: '基准水位', type: 'line', data: comparison.baseline_water_level, showSymbol: false, lineStyle: { color: '#38a8ff' } },
          { name: '调度水位', type: 'line', data: comparison.controlled_water_level, showSymbol: false, lineStyle: { color: '#2fe6d6' } },
          { name: '差值', type: 'bar', yAxisIndex: 1, data: comparison.difference, itemStyle: { color: '#a291ff' } },
        ],
      });
      const resize = () => chart.resize(); window.addEventListener('resize', resize);
      dispose = () => { window.removeEventListener('resize', resize); chart.dispose(); };
    });
    return () => dispose?.();
  }, [comparison]);
  return <div ref={element} className="dispatch-comparison-chart" />;
}

/** Read a finite numeric field from an untyped structure-result row. */
function finiteRowNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

/** Summarize the latest persisted sample and its last auditable dispatch source per asset. */
function buildLatestStructureStatuses(
  rows: Array<Record<string, unknown>>,
  events: Array<Record<string, unknown>>,
): LatestStructureStatus[] {
  const latestRows = new Map<string, Record<string, unknown>>();
  rows.forEach((row) => {
    if (row.structure_type !== 'gate' && row.structure_type !== 'pump') return;
    const structureId = finiteRowNumber(row.structure_id);
    const timeSeconds = finiteRowNumber(row.time_seconds);
    if (structureId === undefined || timeSeconds === undefined) return;
    const key = `${row.structure_type}-${structureId}`;
    const previousTime = finiteRowNumber(latestRows.get(key)?.time_seconds) ?? -1;
    if (timeSeconds >= previousTime) latestRows.set(key, row);
  });

  const latestSources = new Map<string, { timeSeconds: number; label: string }>();
  events.forEach((event) => {
    if (event.structure_type !== 'gate' && event.structure_type !== 'pump') return;
    const structureId = finiteRowNumber(event.structure_id);
    const timeSeconds = finiteRowNumber(event.time_seconds);
    if (structureId === undefined || timeSeconds === undefined) return;
    const key = `${event.structure_type}-${structureId}`;
    const previous = latestSources.get(key);
    if (previous && previous.timeSeconds > timeSeconds) return;
    const sourceType = typeof event.source_type === 'string' ? event.source_type : '';
    const sourceLabel = sourceType === 'rule' ? '控制规则' : sourceType === 'manual' ? '计划动作' : sourceType;
    latestSources.set(key, {
      timeSeconds,
      label: sourceLabel ? `本次调度/${sourceLabel}` : '本次调度',
    });
  });

  return [...latestRows.entries()].map(([key, row]) => {
    const kind = row.structure_type as StructureKind;
    const structureId = finiteRowNumber(row.structure_id) as number;
    const actual = finiteRowNumber(row.actual_value);
    const timeSeconds = finiteRowNumber(row.time_seconds) as number;
    return {
      key,
      label: `${kind === 'gate' ? '闸门' : '泵站'} #${structureId}`,
      status: actual === undefined ? '无状态' : actual > 1.0e-6 ? (kind === 'gate' ? '开启' : '运行') : (kind === 'gate' ? '关闭' : '停止'),
      actuator: actual === undefined ? '—' : kind === 'gate' ? `${actual.toFixed(3)} m` : `${actual.toFixed(0)} 台`,
      flow: finiteRowNumber(row.flow),
      controlSource: latestSources.get(key)?.label ?? '固定输入',
      regime: typeof row.regime === 'string' && row.regime ? row.regime : '—',
      timeHours: timeSeconds / 3600,
    };
  }).sort((left, right) => left.label.localeCompare(right.label, 'zh-CN'));
}

/** Group one persisted structure metric by asset for the fixed 24-hour review window. */
function buildStructureMetricSeries(
  rows: Array<Record<string, unknown>>,
  panel: StructureMetricPanel,
  expectedStepHours: number,
) {
  const grouped = new Map<number, Array<[number, number]>>();
  rows.forEach((row) => {
    if (row.structure_type !== panel.kind) return;
    const structureId = finiteRowNumber(row.structure_id);
    const timeSeconds = finiteRowNumber(row.time_seconds);
    const metricValue = finiteRowNumber(row[panel.metric]);
    if (structureId === undefined || timeSeconds === undefined || metricValue === undefined) return;
    const timeHours = timeSeconds / 3600;
    if (timeHours < 0 || timeHours > DISPATCH_WINDOW_HOURS) return;
    const values = grouped.get(structureId) ?? [];
    values.push([timeHours, metricValue]);
    grouped.set(structureId, values);
  });
  return [...grouped.entries()]
    .sort(([left], [right]) => left - right)
    .map(([structureId, data]) => {
      const ordered = data.sort(([left], [right]) => left - right);
      const sparse: Array<[number, number | null]> = [];
      ordered.forEach(([timeHours, value], index) => {
        const previous = ordered[index - 1];
        if (previous && timeHours - previous[0] > expectedStepHours * 1.5) {
          sparse.push([
            previous[0] + Math.min(expectedStepHours, (timeHours - previous[0]) / 2),
            null,
          ]);
        }
        sparse.push([timeHours, value]);
      });
      return {
        name: `${panel.kind === 'gate' ? '闸门' : '泵站'} #${structureId} · ${panel.title}`,
        data: sparse,
      };
    });
}

/** Keep coverage and milestones attributable to every returned structure. */
function buildStructureCoverage(rows: Array<Record<string, unknown>>): StructureCoverage[] {
  const grouped = new Map<string, { label: string; times: Set<number> }>();
  rows.forEach((row) => {
    if (row.structure_type !== 'gate' && row.structure_type !== 'pump') return;
    const structureId = finiteRowNumber(row.structure_id);
    const timeSeconds = finiteRowNumber(row.time_seconds);
    if (structureId === undefined || timeSeconds === undefined) return;
    const timeHours = timeSeconds / 3600;
    if (timeHours < 0 || timeHours > DISPATCH_WINDOW_HOURS) return;
    const key = `${row.structure_type}-${structureId}`;
    const current = grouped.get(key) ?? {
      label: `${row.structure_type === 'gate' ? '闸门' : '泵站'} #${structureId}`,
      times: new Set<number>(),
    };
    current.times.add(timeHours);
    grouped.set(key, current);
  });
  return [...grouped.entries()].map(([key, value]) => {
    const times = [...value.times].sort((left, right) => left - right);
    return {
      key,
      label: value.label,
      times,
      startHours: times[0],
      endHours: times[times.length - 1],
    };
  }).sort((left, right) => left.label.localeCompare(right.label, 'zh-CN'));
}

/** Prefer the frozen output cadence; otherwise use a conservative observed cadence. */
function structureSamplingStepHours(
  rows: Array<Record<string, unknown>>,
  tasks: SimulationTaskRecord[],
  controlledTaskId: number | null,
): number {
  const controlled = tasks.find((task) => task.id === controlledTaskId);
  const configuredSeconds = finiteRowNumber(controlled?.config.output_interval_seconds);
  if (configuredSeconds !== undefined && configuredSeconds > 0) return configuredSeconds / 3600;
  const coverage = buildStructureCoverage(rows);
  const deltas = coverage.flatMap((item) => item.times.slice(1).map(
    (timeHours, index) => timeHours - item.times[index],
  )).filter((value) => value > 1.0e-9);
  return deltas.length ? Math.min(6, ...deltas) : 6;
}

/** Render gate opening/flow and pump flow/energy without synthesizing missing hours. */
function StructureOperationChart({
  rows,
  expectedStepHours,
}: {
  rows: Array<Record<string, unknown>>;
  expectedStepHours: number;
}) {
  const element = useRef<HTMLDivElement>(null);
  const panelSeries = useMemo(
    () => STRUCTURE_METRIC_PANELS.map(
      (panel) => buildStructureMetricSeries(rows, panel, expectedStepHours),
    ),
    [expectedStepHours, rows],
  );
  const hasData = panelSeries.some((series) => series.length > 0);

  useEffect(() => {
    if (!element.current || !hasData) return undefined;
    let disposed = false;
    let disposeChart: (() => void) | undefined;
    void import('echarts').then((echarts) => {
      if (disposed || !element.current) return;
      const chart = echarts.init(element.current);
      const gridTops = ['10%', '32%', '54%', '76%'];
      const series = panelSeries.flatMap((items, panelIndex) => items.map((item, itemIndex) => ({
        name: item.name,
        type: 'line',
        xAxisIndex: panelIndex,
        yAxisIndex: panelIndex,
        data: item.data,
        connectNulls: false,
        showSymbol: false,
        smooth: STRUCTURE_METRIC_PANELS[panelIndex].metric !== 'actual_value',
        step: STRUCTURE_METRIC_PANELS[panelIndex].metric === 'actual_value' ? 'end' : false,
        lineStyle: { width: 2 },
        markLine: itemIndex === 0 ? {
          silent: true,
          symbol: 'none',
          label: { show: false },
          lineStyle: { color: 'rgba(120, 168, 190, 0.2)', type: 'dashed' },
          data: DISPATCH_MILESTONES_HOURS.map((hour) => ({ xAxis: hour })),
        } : undefined,
      })));
      chart.setOption({
        animationDuration: 450,
        tooltip: { trigger: 'axis', valueFormatter: (value: unknown) => typeof value === 'number' ? value.toFixed(3) : String(value ?? '—') },
        legend: { type: 'scroll', top: 2, textStyle: { color: '#86a8ba' } },
        grid: gridTops.map((top) => ({ left: 72, right: 36, top, height: '14%' })),
        xAxis: STRUCTURE_METRIC_PANELS.map((_, index) => ({
          type: 'value',
          gridIndex: index,
          min: 0,
          max: DISPATCH_WINDOW_HOURS,
          interval: 6,
          axisLabel: {
            color: '#628196',
            formatter: (value: number) => DISPATCH_MILESTONES_HOURS.includes(value as 0 | 6 | 12 | 24) ? `${value}h` : '',
          },
          axisLine: { lineStyle: { color: 'rgba(102,145,168,.24)' } },
          splitLine: { lineStyle: { color: 'rgba(100,151,183,.08)' } },
        })),
        yAxis: STRUCTURE_METRIC_PANELS.map((panel, index) => ({
          type: 'value',
          gridIndex: index,
          name: `${panel.title} / ${panel.unit}`,
          nameTextStyle: { color: '#7898aa' },
          axisLabel: { color: '#628196' },
          splitLine: { lineStyle: { color: 'rgba(100,151,183,.10)' } },
        })),
        series,
      });
      const resize = () => chart.resize();
      window.addEventListener('resize', resize);
      disposeChart = () => {
        window.removeEventListener('resize', resize);
        chart.dispose();
      };
    });
    return () => {
      disposed = true;
      disposeChart?.();
    };
  }, [hasData, panelSeries]);

  if (!hasData) return <div className="data-empty">当前运行没有可用的闸泵时序结果。</div>;
  return <div ref={element} className="dispatch-structure-chart" role="img" aria-label="24 小时闸门开度、闸门流量、泵站流量和累计能耗曲线" />;
}

export function DispatchRunDetailPage() {
  const navigate = useNavigate();
  const { runId = '' } = useParams();
  const id = Number(runId);
  const { datasetVersionId } = useDatasetVersion();
  const [run, setRun] = useState<DispatchRunRecord>();
  const [tasks, setTasks] = useState<SimulationTaskRecord[]>([]);
  const [comparison, setComparison] = useState<DispatchComparison>();
  const [events, setEvents] = useState<Array<Record<string, unknown>>>([]);
  const [structures, setStructures] = useState<Array<Record<string, unknown>>>([]);
  const [nodes, setNodes] = useState<Array<Record<string, unknown>>>([]);
  const [resultRunId, setResultRunId] = useState<number>();
  const [error, setError] = useState('');
  const activeRunIdRef = useRef(id);
  const requestSequenceRef = useRef(0);
  activeRunIdRef.current = id;
  const clearResultData = useCallback(() => {
    setComparison(undefined);
    setEvents([]);
    setStructures([]);
    setNodes([]);
    setResultRunId(undefined);
  }, []);
  const reload = useCallback(async () => {
    const requestedRunId = id;
    const requestSequence = ++requestSequenceRef.current;
    const isCurrent = () => (
      activeRunIdRef.current === requestedRunId
      && requestSequenceRef.current === requestSequence
    );
    try {
      const value = await getDispatchRun(id);
      const taskRows = await Promise.all([value.baseline_task_id, value.controlled_task_id].filter((item): item is number => item !== null).map((taskId) => getHydraulicTask(taskId)));
      if (!isCurrent()) return;
      setRun(value);
      setTasks(taskRows);
      if (value.status === 'success') {
        const [compare, eventRows, structureRows, nodeRows] = await Promise.all([getDispatchComparison(id), getDispatchEvents(id), getDispatchStructures(id), getDispatchNodes(id)]);
        if (!isCurrent()) return;
        setComparison(compare); setEvents(eventRows); setStructures(structureRows); setNodes(nodeRows);
        setResultRunId(requestedRunId);
      } else clearResultData();
      setError('');
    } catch (reason) {
      if (!isCurrent()) return;
      setRun(undefined);
      setTasks([]);
      clearResultData();
      setError(errorText(reason, '运行详情加载失败'));
    }
  }, [clearResultData, id]);
  useEffect(() => {
    requestSequenceRef.current += 1;
    setRun(undefined);
    setTasks([]);
    clearResultData();
    setError('');
  }, [clearResultData, id]);
  const currentRun = run?.id === id ? run : undefined;
  const currentComparison = resultRunId === id ? comparison : undefined;
  useEffect(() => { void reload(); if (currentRun?.status === 'success' || currentRun?.status === 'failed' || currentRun?.status === 'cancelled') return undefined; const timer = window.setInterval(() => void reload(), 3000); return () => window.clearInterval(timer); }, [currentRun?.status, reload]);
  const metrics = currentComparison?.metrics ?? currentRun?.metrics ?? {};
  const metricKeys = ['network_maximum_water_level', 'maximum_level_reduction', 'pump_total_energy_kwh', 'gate_action_count', 'global_balance_residual', 'maximum_node_balance_residual'];
  const structureCoverage = useMemo(() => buildStructureCoverage(structures), [structures]);
  const structureCoverageStartHours = structureCoverage.length
    ? Math.max(...structureCoverage.map((item) => item.startHours)) : 0;
  const structureCoverageEndHours = structureCoverage.length
    ? Math.min(...structureCoverage.map((item) => item.endHours)) : 0;
  const structureCoverageHours = Math.max(0, structureCoverageEndHours - structureCoverageStartHours);
  const expectedStructureStepHours = useMemo(
    () => structureSamplingStepHours(structures, tasks, currentRun?.controlled_task_id ?? null),
    [currentRun?.controlled_task_id, structures, tasks],
  );
  const milestoneCoveredByAll = (hour: number) => structureCoverage.length > 0
    && structureCoverage.every((item) => item.times.some(
      (value) => Math.abs(value - hour) <= 1.0e-6,
    ));
  const structureCoverageIsComplete = (item: StructureCoverage) => (
    item.startHours <= 1.0e-6
    && item.endHours >= DISPATCH_WINDOW_HOURS - 1.0e-6
    && DISPATCH_MILESTONES_HOURS.every((hour) => item.times.some(
      (value) => Math.abs(value - hour) <= 1.0e-6,
    ))
    && item.times.slice(1).every((timeHours, index) => (
      timeHours - item.times[index] <= expectedStructureStepHours * 1.5
    ))
  );
  const hasFullStructureCoverage = structureCoverage.length > 0
    && structureCoverage.every(structureCoverageIsComplete);
  const incompleteStructures = structureCoverage
    .filter((item) => !structureCoverageIsComplete(item))
    .map((item) => item.label);
  const latestStructureStatuses = useMemo(
    () => buildLatestStructureStatuses(structures, events),
    [events, structures],
  );
  return (
    <div className="data-page dispatch-page">
      <DispatchHeader eyebrow="DISPATCH / RUN DETAIL" title={`调度运行 #${id}`} description="对齐查看基准与调度工况、结构物执行、规则审计、能耗和质量平衡。" action={<Space><Button onClick={() => navigate(`/dispatch/runs?datasetVersionId=${datasetVersionId}`)}>运行中心</Button><Button icon={<AimOutlined />} onClick={() => navigate(`/gis?datasetVersionId=${datasetVersionId}&dispatchRunId=${id}&time=0`)}>GIS 联动</Button></Space>} />
      {error && <Alert className="data-alert" type="error" showIcon message={error} />}
      {currentRun && <>
        <Card className="data-card" title="运行状态" extra={stateTag(currentRun.status)}><Row gutter={[16, 16]}><Col xs={24} md={8}><Progress percent={currentRun.progress} status={currentRun.status === 'failed' ? 'exception' : currentRun.status === 'success' ? 'success' : 'active'} /></Col><Col xs={24} md={16}><Descriptions column={2} items={[{ key: 'baseline', label: '基准任务', children: currentRun.baseline_task_id }, { key: 'controlled', label: '调度任务', children: currentRun.controlled_task_id }, { key: 'start', label: '开始', children: localTime(currentRun.start_time) }, { key: 'end', label: '结束', children: localTime(currentRun.end_time) }]} /></Col></Row>{currentRun.error_message && <Alert type="error" showIcon message={currentRun.error_message} />}</Card>
        <Card className="data-card" title="Worker 心跳与数值进度"><Table rowKey="id" pagination={false} dataSource={tasks} columns={[{ title: '任务', dataIndex: 'id' }, { title: '状态', dataIndex: 'status', render: stateTag }, { title: 'Worker', dataIndex: 'worker_id' }, { title: '心跳', dataIndex: 'heartbeat_time', render: localTime }, { title: '当前模拟时间（s）', dataIndex: 'current_simulation_time' }, { title: '当前 CFL', dataIndex: 'current_cfl' }, { title: '快照 SHA-256', dataIndex: 'input_snapshot_hash', ellipsis: true }]} scroll={{ x: 1050 }} /></Card>
        {currentComparison && <>
          <Row gutter={[16, 16]} className="dispatch-metrics">{metricKeys.map((key) => <Col key={key} xs={12} md={8} xl={4}><Card className="data-card"><Statistic title={key} value={typeof metrics[key] === 'number' ? metrics[key] as number : String(metrics[key] ?? '—')} precision={typeof metrics[key] === 'number' ? 5 : undefined} /></Card></Col>)}</Row>
          <Card className="data-card" title={`基准 / 调度水位与差值 · ${currentComparison.section_code ?? '关键断面'}`}><ComparisonChart comparison={currentComparison} /></Card>
          <Card className="data-card" title="闸泵当前运行状态" extra={<Text type="secondary">以每座设施最后一个持久化时刻为准</Text>}>
            {latestStructureStatuses.length ? <Table rowKey="key" size="small" pagination={false} dataSource={latestStructureStatuses} scroll={{ x: 900 }} columns={[
              { title: '设施', dataIndex: 'label', width: 130 },
              { title: '当前状态', dataIndex: 'status', width: 110, render: (value: string) => <Tag color={['开启', '运行'].includes(value) ? 'success' : value === '无状态' ? 'default' : 'warning'}>{value}</Tag> },
              { title: '开度 / 运行机组', dataIndex: 'actuator', width: 145 },
              { title: '流量（m³/s）', dataIndex: 'flow', width: 125, render: (value?: number) => value === undefined ? '—' : value.toFixed(3) },
              { title: '控制模式 / 来源', dataIndex: 'controlSource', width: 180 },
              { title: '流态', dataIndex: 'regime', width: 120 },
              { title: '结果时刻', dataIndex: 'timeHours', width: 110, render: (value: number) => `${value.toFixed(2)} h` },
            ]} /> : <div className="data-empty">当前运行没有可用的闸泵状态结果。</div>}
          </Card>
          <Card className="data-card" title="24 小时闸泵运行曲线" extra={<Tag color={hasFullStructureCoverage ? 'success' : 'warning'}>全部设施共同覆盖 {structureCoverageHours.toFixed(2)} / 24 h</Tag>}>
            <div className="dispatch-milestones" aria-label="0、6、12、24 小时调度里程碑">
              {DISPATCH_MILESTONES_HOURS.map((hour) => {
                const covered = milestoneCoveredByAll(hour);
                return <div key={hour} className={covered ? 'is-covered' : ''}><strong>{hour}h</strong><span>{covered ? '结果已覆盖' : '尚未覆盖'}</span></div>;
              })}
            </div>
            {!hasFullStructureCoverage && <Alert className="data-alert" type="warning" showIcon message="24 小时结果不完整" description={`全部返回设施的共同结果范围为 ${structureCoverageStartHours.toFixed(2)}–${structureCoverageEndHours.toFixed(2)} h；未覆盖全部里程碑：${incompleteStructures.join('、') || '无有效设施结果'}。空缺时段显式断线，不做插值或伪造补齐。`} />}
            <StructureOperationChart rows={structures} expectedStepHours={expectedStructureStepHours} />
          </Card>
          <Tabs items={[
            { key: 'structures', label: `闸泵状态 ${structures.length}`, children: <Table rowKey={(row) => `${row.structure_type}-${row.structure_id}-${row.time_seconds}`} dataSource={structures} pagination={{ pageSize: 10 }} scroll={{ x: 1200 }} columns={[{ title: '时刻（s）', dataIndex: 'time_seconds' }, { title: '设施', render: (_, row) => `${row.structure_type} #${row.structure_id}` }, { title: '请求', dataIndex: 'requested_value' }, { title: '实际', dataIndex: 'actual_value' }, { title: '流量（m³/s）', dataIndex: 'flow' }, { title: '功率（kW）', dataIndex: 'power_kw' }, { title: '累计能耗（kWh）', dataIndex: 'energy_kwh' }, { title: '流态', dataIndex: 'regime' }, { title: '约束', dataIndex: 'constraint_flags', render: (value) => JSON.stringify(value) }]} /> },
            { key: 'events', label: `调度审计 ${events.length}`, children: <Table rowKey={(row) => String(row.id)} dataSource={events} pagination={{ pageSize: 10 }} scroll={{ x: 1200 }} columns={[{ title: '时刻（s）', dataIndex: 'time_seconds' }, { title: '来源', dataIndex: 'source_type' }, { title: '设施', render: (_, row) => `${row.structure_type} #${row.structure_id}` }, { title: '请求命令', dataIndex: 'requested_command', render: (value) => <code>{JSON.stringify(value)}</code> }, { title: '实际命令', dataIndex: 'applied_command', render: (value) => <code>{JSON.stringify(value)}</code> }, { title: '结果', dataIndex: 'outcome', render: stateTag }, { title: '原因', dataIndex: 'reason' }]} /> },
            { key: 'nodes', label: `节点结果 ${nodes.length}`, children: <Table rowKey={(row) => `${row.node_id}-${row.time_seconds}`} dataSource={nodes} pagination={{ pageSize: 10 }} columns={[{ title: '节点', dataIndex: 'node_id' }, { title: '时刻（s）', dataIndex: 'time_seconds' }, { title: '水位（m）', dataIndex: 'water_level' }, { title: '入流', dataIndex: 'inflow' }, { title: '出流', dataIndex: 'outflow' }, { title: '源汇', dataIndex: 'source_sink' }, { title: '残差', dataIndex: 'balance_residual' }]} /> },
            { key: 'balance', label: '质量平衡与诊断', children: <pre className="hydraulic-diagnostics">{JSON.stringify(currentComparison.diagnostics, null, 2)}</pre> },
          ]} />
        </>}
      </>}
    </div>
  );
}
