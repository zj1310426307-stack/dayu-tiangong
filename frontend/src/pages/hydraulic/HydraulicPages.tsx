import {
  AreaChartOutlined,
  CheckCircleOutlined,
  PlayCircleOutlined,
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
  InputNumber,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  approveDatasetVersionForCalculation,
  cancelHydraulicTask,
  createHydraulicTask,
  enqueueHydraulicTask,
  getHydraulicReadiness,
  getHydraulicResult,
  getSimulationCases,
  listHydraulicTasks,
  listPublishedScenarioResults,
  previewHydraulicModel,
  retryHydraulicTask,
  type Hydraulic1DReadinessResponse,
  type PublishedScenarioBundle,
  type PublishedScenarioResult,
  type ScenarioResultSection,
  type SimulationResultResponse,
  type SimulationTaskCreate,
  type SimulationTaskRecord,
} from '../../api/generated/client';
import { useDatasetVersion } from '../../context/DatasetVersionContext';

const { Paragraph, Text, Title } = Typography;
const HYDRAULIC_INPUT_SCHEMA = 'dayu.hydraulic-1d.input.v1' as const;
const HYDRAULIC_ENGINE = 'mascaret' as const;

/** Render the shared title block for the Standard 1D workflow. */
function HydraulicHeader({
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

/** Convert a durable task state into a stable Chinese status label. */
function statusTag(status: SimulationTaskRecord['status']) {
  const colors = {
    pending: 'default',
    queued: 'blue',
    running: 'processing',
    cancel_requested: 'warning',
    cancelled: 'default',
    success: 'success',
    failed: 'error',
  } as const;
  const labels = {
    pending: '待入队',
    queued: '排队中',
    running: '计算中',
    cancel_requested: '取消中',
    cancelled: '已取消',
    success: '成功',
    failed: '失败',
  } as const;
  return <Tag color={colors[status]}>{labels[status]}</Tag>;
}

/** Present validation issues whether the backend returns text or structured details. */
function issueLabel(issue: unknown): string {
  if (typeof issue === 'string') return issue;
  if (issue && typeof issue === 'object') {
    const detail = issue as Record<string, unknown>;
    return [detail.code, detail.message].filter((value) => typeof value === 'string').join(' · ')
      || JSON.stringify(issue);
  }
  return String(issue);
}

/** Enforce that the optional initial water level and discharge are supplied together. */
function pairedInitialRule(peer: 'initial_water_level' | 'initial_flow', label: string) {
  return ({ getFieldValue }: { getFieldValue: (name: string) => unknown }) => ({
    validator(_: unknown, value: unknown) {
      const peerValue = getFieldValue(peer);
      const hasValue = value !== undefined && value !== null;
      const hasPeer = peerValue !== undefined && peerValue !== null;
      return hasValue === hasPeer
        ? Promise.resolve()
        : Promise.reject(new Error(`初始${label}与对应初始条件必须成对填写`));
    },
  });
}

/** Build the one supported production request without exposing solver-specific controls. */
function normalizeTaskRequest(values: SimulationTaskCreate): SimulationTaskCreate {
  return {
    case_id: values.case_id,
    calculation_mode: values.calculation_mode,
    overbank_treatment: values.overbank_treatment,
    duration_seconds: values.duration_seconds,
    time_step_seconds: values.time_step_seconds,
    output_interval_seconds: values.output_interval_seconds,
    initial_water_level: values.initial_water_level,
    initial_flow: values.initial_flow,
    engine: HYDRAULIC_ENGINE,
    input_schema_version: HYDRAULIC_INPUT_SCHEMA,
    storage_level: 'full',
  };
}

/** Configure and validate the single production Standard 1D / MASCARET route. */
export function HydraulicConfigPage() {
  const navigate = useNavigate();
  const { datasetVersionId, currentVersion, refreshVersions } = useDatasetVersion();
  const [form] = Form.useForm<SimulationTaskCreate>();
  const selectedCaseId = Form.useWatch('case_id', form);
  const [cases, setCases] = useState<Array<{ id: number; name: string }>>([]);
  const [readiness, setReadiness] = useState<Hydraulic1DReadinessResponse>();
  const [preview, setPreview] = useState<Awaited<ReturnType<typeof previewHydraulicModel>>>();
  const [readinessLoading, setReadinessLoading] = useState(false);
  const [loadingCases, setLoadingCases] = useState(true);
  const [previewing, setPreviewing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [approving, setApproving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!datasetVersionId) {
      setCases([]);
      setLoadingCases(false);
      return;
    }
    let cancelled = false;
    setLoadingCases(true);
    form.setFieldValue('case_id', undefined);
    void getSimulationCases(datasetVersionId)
      .then((items) => {
        if (cancelled) return;
        setCases(items.map((item) => ({ id: item.id, name: item.name })));
        if (items[0]) form.setFieldValue('case_id', items[0].id);
        setError('');
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : '计算方案加载失败');
      })
      .finally(() => { if (!cancelled) setLoadingCases(false); });
    return () => { cancelled = true; };
  }, [datasetVersionId, form]);

  useEffect(() => {
    setReadiness(undefined);
    setPreview(undefined);
    if (!selectedCaseId) return;
    let cancelled = false;
    setReadinessLoading(true);
    void getHydraulicReadiness(selectedCaseId)
      .then((value) => { if (!cancelled) setReadiness(value); })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : '模型就绪检查失败');
      })
      .finally(() => { if (!cancelled) setReadinessLoading(false); });
    return () => { cancelled = true; };
  }, [selectedCaseId]);

  const runPreview = async (): Promise<Awaited<ReturnType<typeof previewHydraulicModel>> | undefined> => {
    setPreviewing(true);
    setError('');
    try {
      const values = await form.validateFields();
      const result = await previewHydraulicModel(normalizeTaskRequest(values));
      setPreview(result);
      if (result.readiness.ready) message.success('MASCARET 模型映射检查通过');
      else if (result.snapshot_hash) message.info('模型映射已通过，但 MASCARET 运行时尚不可用');
      return result;
    } catch (reason) {
      setPreview(undefined);
      if (reason instanceof Error) setError(reason.message);
      return undefined;
    } finally {
      setPreviewing(false);
    }
  };

  const submit = async (values: SimulationTaskCreate) => {
    setSubmitting(true);
    setError('');
    try {
      const body = normalizeTaskRequest(values);
      const checked = await previewHydraulicModel(body);
      setPreview(checked);
      if (!checked.readiness.ready) throw new Error('模型映射未通过，请先处理阻断项');
      if (!checked.readiness.runtime_available) throw new Error(checked.readiness.runtime_detail || 'MASCARET 运行时不可用');
      const created = await createHydraulicTask(body);
      await enqueueHydraulicTask(created.id);
      message.success(`任务 #${created.id} 已进入 Standard 1D 计算队列`);
      navigate('/hydraulic/tasks');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '任务创建或入队失败');
    } finally {
      setSubmitting(false);
    }
  };

  /** Promote the current editable version after QA so the Standard 1D gate can build an authoritative snapshot. */
  const approveCurrentVersion = async () => {
    if (!datasetVersionId || currentVersion?.is_read_only) return;
    setApproving(true);
    setError('');
    try {
      await approveDatasetVersionForCalculation(datasetVersionId, {
        reviewer: 'web-operator',
        reason: '未率定 Standard 1D 方案，已完成核心校核并知悉警告',
      });
      await refreshVersions(datasetVersionId);
      setPreview(undefined);
      if (selectedCaseId) setReadiness(await getHydraulicReadiness(selectedCaseId));
      message.success('数据版本已校核并批准，可进入 Standard 1D 计算；编辑权限保持不变');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '数据版本校核并批准失败');
    } finally {
      setApproving(false);
    }
  };

  const activeReadiness = preview?.readiness ?? readiness;
  const modelBlockers = (activeReadiness?.blockers ?? []).filter(
    (item) => item.code !== 'MASCARET_RUNTIME_NOT_AVAILABLE',
  );
  const modelMappingReady = activeReadiness?.input_summary != null && modelBlockers.length === 0;
  const canRun = activeReadiness?.ready === true && activeReadiness.runtime_available === true;

  return (
    <div className="data-page hydraulic-page">
      <HydraulicHeader
        eyebrow="STANDARD 1D / MASCARET"
        title="标准一维水动力模拟"
        description="使用大禹统一河网、断面、糙率与边界数据建模，通过 MASCARET Adapter 独立运行并回写统一结果。"
        action={<Button onClick={() => navigate('/hydraulic/tasks')}>查看任务监控</Button>}
      />
      {error && <Alert className="data-alert" type="error" showIcon message={error} />}
      {!loadingCases && datasetVersionId && cases.length === 0 && (
        <Alert
          className="data-alert"
          type="warning"
          showIcon
          message="当前版本没有可运行的计算方案"
          description="请切换到包含完整河网、断面、糙率及上下游边界的已批准或已发布数据版本。"
        />
      )}
      <Card className="data-card hydraulic-config-card" title="计算参数">
        <Alert
          showIcon
          type="info"
          message="产品只提供 Standard 1D；引擎固定为 MASCARET v9.1.1，不暴露求解器私有文件或旧自研算法选项。"
        />
        <Form
          form={form}
          layout="vertical"
          className="hydraulic-form"
          initialValues={{
            engine: HYDRAULIC_ENGINE,
            input_schema_version: HYDRAULIC_INPUT_SCHEMA,
            storage_level: 'full',
            calculation_mode: 'steady',
            overbank_treatment: 'vertical_extension',
            duration_seconds: 3600,
            time_step_seconds: 10,
            output_interval_seconds: 60,
          }}
          onValuesChange={() => setPreview(undefined)}
          onFinish={(values) => void submit(values)}
        >
          <Row gutter={16}>
            <Col xs={24} md={8}>
              <Form.Item name="case_id" label="计算方案" rules={[{ required: true, message: '请选择计算方案' }]}>
                <Select
                  loading={loadingCases}
                  options={cases.map((item) => ({ value: item.id, label: `${item.name} · #${item.id}` }))}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={4}>
              <Form.Item name="calculation_mode" label="计算类型" rules={[{ required: true }]}>
                <Select options={[
                  { value: 'steady', label: '恒定流（稳态）' },
                  { value: 'unsteady', label: '非恒定流' },
                ]} />
              </Form.Item>
            </Col>
            <Col xs={24} md={4}>
              <Form.Item name="overbank_treatment" label="高水位处理" rules={[{ required: true }]}>
                <Select options={[
                  { value: 'vertical_extension', label: '全归槽（竖直岸壁）' },
                  { value: 'profile', label: '按现有断面' },
                ]} />
              </Form.Item>
            </Col>
            <Col xs={12} md={4}>
              <Form.Item name="duration_seconds" label="模拟时长（s）" rules={[{ required: true }]}>
                <InputNumber min={1} precision={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={4}>
              <Form.Item name="time_step_seconds" label="计算步长（s）" rules={[{ required: true }]}>
                <InputNumber min={0.001} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col xs={12} md={6}>
              <Form.Item name="output_interval_seconds" label="输出间隔（s）" rules={[{ required: true }]}>
                <InputNumber min={0.001} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item
                name="initial_water_level"
                label="初始水位（m，可选）"
                dependencies={['initial_flow']}
                rules={[pairedInitialRule('initial_flow', '水位')]}
              >
                <InputNumber step={0.1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item
                name="initial_flow"
                label="初始流量（m³/s，可选）"
                dependencies={['initial_water_level']}
                rules={[pairedInitialRule('initial_water_level', '流量')]}
              >
                <InputNumber step={1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Alert
            className="data-alert"
            showIcon
            type={canRun ? 'success' : modelMappingReady ? 'warning' : activeReadiness ? 'error' : 'info'}
            message={readinessLoading
              ? '正在检查 Standard 1D 就绪状态'
              : canRun
                ? `模型映射已就绪 · ${activeReadiness.engine_id ?? HYDRAULIC_ENGINE} ${activeReadiness.engine_version ?? 'v9.1.1'}`
                : modelMappingReady
                  ? '模型映射已通过，等待 MASCARET 运行时'
                : '请选择计算方案并处理模型阻断项'}
            description={activeReadiness && (
              <Space direction="vertical" size={2}>
                <Text type={activeReadiness.runtime_available ? 'success' : 'warning'}>
                  运行时：{activeReadiness.runtime_available ? '可用' : '不可用'} · {activeReadiness.runtime_detail}
                </Text>
                {(activeReadiness.blockers ?? []).map((item, index) => (
                  <Text type="danger" key={`blocker-${index}`}>{issueLabel(item)}</Text>
                ))}
                {(activeReadiness.warnings ?? []).map((item, index) => (
                  <Text type="warning" key={`warning-${index}`}>{issueLabel(item)}</Text>
                ))}
                {activeReadiness.blockers?.some((item) => item.code === 'DAYU_DATASET_NOT_AUTHORITATIVE') && (
                  <Button
                    type="primary"
                    size="small"
                    icon={<SafetyCertificateOutlined />}
                    loading={approving}
                    disabled={!currentVersion || currentVersion.is_read_only}
                    onClick={() => void approveCurrentVersion()}
                  >
                    校核并批准当前版本
                  </Button>
                )}
                {preview?.snapshot_hash && <Text type="secondary">冻结输入：{preview.snapshot_hash}</Text>}
              </Space>
            )}
          />
          {activeReadiness?.input_summary && (
            <Card size="small" title="输入摘要">
              <pre className="hydraulic-diagnostics">{JSON.stringify(activeReadiness.input_summary, null, 2)}</pre>
            </Card>
          )}
          {activeReadiness?.runtime_identity && (
            <Card size="small" title="MASCARET 运行时身份">
              <Descriptions
                size="small"
                column={2}
                items={[
                  { key: 'version', label: '官方版本', children: String(activeReadiness.runtime_identity.upstream_tag ?? activeReadiness.engine_version) },
                  { key: 'commit', label: '源码提交', children: String(activeReadiness.runtime_identity.upstream_commit ?? '未验证') },
                  { key: 'source-tree', label: '源码树哈希', children: String(activeReadiness.runtime_identity.source_tree_sha256 ?? '未验证') },
                  { key: 'mode', label: '运行方式', children: String(activeReadiness.runtime_identity.runtime_mode ?? '未知') },
                  { key: 'platform', label: '平台', children: `${String(activeReadiness.runtime_identity.platform ?? '未知')} / ${String(activeReadiness.runtime_identity.architecture ?? '未知')}` },
                  { key: 'hash', label: '可执行文件哈希', children: String(activeReadiness.runtime_identity.executable_hash ?? activeReadiness.runtime_identity.container_digest ?? '未验证') },
                  { key: 'build', label: '构建时间', children: String(activeReadiness.runtime_identity.build_timestamp ?? '未记录') },
                ]}
              />
            </Card>
          )}
          <Space wrap>
            <Button
              icon={<SafetyCertificateOutlined />}
              loading={previewing}
              disabled={!selectedCaseId}
              onClick={() => void runPreview()}
            >
              检查模型映射
            </Button>
            <Button
              type="primary"
              size="large"
              icon={<PlayCircleOutlined />}
              htmlType="submit"
              loading={submitting}
              disabled={!datasetVersionId || cases.length === 0 || !canRun}
            >
              创建并运行模拟
            </Button>
          </Space>
        </Form>
      </Card>
    </div>
  );
}

/** Show the generic durable lifecycle without old solver-specific counters. */
export function HydraulicTasksPage() {
  const navigate = useNavigate();
  const { datasetVersionId } = useDatasetVersion();
  const [tasks, setTasks] = useState<SimulationTaskRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const requestSequenceRef = useRef(0);

  const reload = useCallback(async () => {
    const requestSequence = ++requestSequenceRef.current;
    if (!datasetVersionId) {
      setTasks([]);
      setLoading(false);
      setError('');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const nextTasks = await listHydraulicTasks({ dataset_version_id: datasetVersionId });
      if (requestSequence === requestSequenceRef.current) setTasks(nextTasks);
    } catch (reason) {
      if (requestSequence === requestSequenceRef.current) {
        setError(reason instanceof Error ? reason.message : '任务列表加载失败');
      }
    } finally {
      if (requestSequence === requestSequenceRef.current) setLoading(false);
    }
  }, [datasetVersionId]);

  useEffect(() => {
    requestSequenceRef.current += 1;
    setTasks([]);
    setError('');
  }, [datasetVersionId]);

  useEffect(() => {
    void reload();
    const timer = window.setInterval(() => void reload(), 5000);
    return () => window.clearInterval(timer);
  }, [reload]);

  const columns: ColumnsType<SimulationTaskRecord> = [
    { title: '任务', dataIndex: 'id', width: 90, render: (value: number) => `#${value}` },
    { title: '方案 ID', dataIndex: 'case_id', width: 100 },
    {
      title: '引擎',
      key: 'engine',
      width: 220,
      render: (_, task) => (
        <Space direction="vertical" size={0}>
          <Text>Standard 1D</Text>
          <Text type="secondary">{task.solver_id ?? HYDRAULIC_ENGINE} {task.engine_version ?? 'v9.1.1'} · {task.runtime_adapter_id ?? '—'}</Text>
        </Space>
      ),
    },
    { title: '输入 Schema', dataIndex: 'input_schema_version', width: 220, render: (value: string | null) => value ?? '—' },
    { title: '状态', dataIndex: 'status', width: 110, render: statusTag },
    { title: '进度', dataIndex: 'progress', width: 180, render: (value: number) => <Progress percent={value} size="small" /> },
    { title: '阶段', dataIndex: 'execution_phase', width: 150, render: (value: string | null) => value ?? '—' },
    { title: '执行尝试', dataIndex: 'execution_attempt_count', width: 100 },
    { title: '投递尝试', dataIndex: 'delivery_attempt_count', width: 100 },
    { title: '人工重试', dataIndex: 'manual_retry_count', width: 100 },
    { title: '基础设施重试', dataIndex: 'infrastructure_retry_count', width: 125 },
    { title: '心跳', dataIndex: 'heartbeat_time', width: 190, render: (value: string | null) => value ? new Date(value).toLocaleString() : '—' },
    { title: '创建时间', dataIndex: 'created_time', width: 190, render: (value: string) => new Date(value).toLocaleString() },
    { title: '错误信息', dataIndex: 'error_message', width: 300, ellipsis: true, render: (value: string | null) => value || '—' },
    {
      title: '操作',
      key: 'actions',
      fixed: 'right',
      width: 220,
      render: (_, task) => (
        <Space>
          {task.status === 'pending' && (
            <Button size="small" icon={<PlayCircleOutlined />} onClick={async () => { await enqueueHydraulicTask(task.id); await reload(); }}>入队</Button>
          )}
          {['queued', 'running'].includes(task.status) && (
            <Button size="small" danger onClick={async () => { await cancelHydraulicTask(task.id); await reload(); }}>取消</Button>
          )}
          {task.retry_eligible && (
            <Button size="small" title={task.retry_block_reason ?? undefined} onClick={async () => { await retryHydraulicTask(task.id); await reload(); }}>重试</Button>
          )}
          {task.status === 'success' && (
            <Button size="small" icon={<AreaChartOutlined />} onClick={() => navigate(`/hydraulic/results?taskId=${task.id}`)}>结果</Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div className="data-page hydraulic-page">
      <HydraulicHeader
        eyebrow="STANDARD 1D / TASKS"
        title="Standard 1D 任务监控"
        description="跟踪 MASCARET 任务的排队、执行、取消、成功与失败状态，保留冻结输入和运行来源。"
        action={(
          <Space>
            <Button type="primary" onClick={() => navigate('/hydraulic/config')}>新建模拟</Button>
            <Button icon={<ReloadOutlined />} onClick={() => void reload()} />
          </Space>
        )}
      />
      {error && <Alert className="data-alert" type="error" showIcon message={error} />}
      <Card className="data-card">
        <Table rowKey="id" loading={loading} dataSource={tasks} columns={columns} pagination={{ pageSize: 12 }} scroll={{ x: 2250 }} />
      </Card>
    </div>
  );
}

interface HydraulicChartSeries {
  time: number[];
  water_level: number[];
  flow: number[];
  velocity: number[];
}

/** Draw the three primary solver-neutral time series with a lazily loaded chart runtime. */
function HydraulicResultChart({ result }: { result?: HydraulicChartSeries }) {
  const element = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!element.current || !result) return undefined;
    let disposed = false;
    let dispose: (() => void) | undefined;
    void import('echarts').then((echarts) => {
      if (disposed || !element.current) return;
      const container = element.current;
      echarts.getInstanceByDom(container)?.dispose();
      const chart = echarts.init(container);
      const labels = result.time.map((value) => `${Math.round(value)}s`);
      chart.setOption({
        animationDuration: 450,
        tooltip: { trigger: 'axis' },
        legend: { top: 2, textStyle: { color: '#86a8ba' }, data: ['水位', '流量', '流速'] },
        grid: [
          { left: 58, right: 30, top: 45, height: '20%' },
          { left: 58, right: 30, top: '39%', height: '20%' },
          { left: 58, right: 30, top: '70%', height: '20%' },
        ],
        xAxis: [0, 1, 2].map((index) => ({
          type: 'category',
          gridIndex: index,
          data: labels,
          axisLabel: { color: '#628196', show: index === 2 },
          axisLine: { lineStyle: { color: 'rgba(102,145,168,.24)' } },
        })),
        yAxis: [
          { type: 'value', gridIndex: 0, name: '水位 / m' },
          { type: 'value', gridIndex: 1, name: '流量 / m³/s' },
          { type: 'value', gridIndex: 2, name: '流速 / m/s' },
        ].map((axis) => ({
          ...axis,
          nameTextStyle: { color: '#7898aa' },
          axisLabel: { color: '#628196' },
          splitLine: { lineStyle: { color: 'rgba(100,151,183,.10)' } },
        })),
        series: [
          { name: '水位', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: result.water_level, smooth: true, showSymbol: false, lineStyle: { color: '#2fe6d6', width: 2 } },
          { name: '流量', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: result.flow, smooth: true, showSymbol: false, lineStyle: { color: '#38a8ff', width: 2 } },
          { name: '流速', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: result.velocity, smooth: true, showSymbol: false, lineStyle: { color: '#a291ff', width: 2 } },
        ],
      });
      const resize = () => chart.resize();
      window.addEventListener('resize', resize);
      dispose = () => {
        window.removeEventListener('resize', resize);
        chart.dispose();
      };
    });
    return () => {
      disposed = true;
      dispose?.();
    };
  }, [result]);

  return <div ref={element} className="hydraulic-result-chart" />;
}

const scenarioColors = ['#2fe6d6', '#38a8ff', '#f3b85b', '#a291ff'];

/** Draw the upstream-to-downstream riverbed, water surfaces, and selected velocity profile. */
function ScenarioLongitudinalChart({
  bundle,
  selectedScenario,
}: {
  bundle: PublishedScenarioBundle;
  selectedScenario: PublishedScenarioResult;
}) {
  const element = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!element.current) return undefined;
    let disposed = false;
    let dispose: (() => void) | undefined;
    void import('echarts').then((echarts) => {
      if (disposed || !element.current) return;
      const container = element.current;
      echarts.getInstanceByDom(container)?.dispose();
      const chart = echarts.init(container);
      const reference = bundle.scenarios[0].section_summary;
      const waterSeries = bundle.scenarios.map((scenario, index) => {
        const selected = scenario.scenario_id === selectedScenario.scenario_id;
        return {
          name: scenario.label,
          type: 'line',
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: scenario.section_summary.map((section) => [section.chainage_m, section.final_water_level_m]),
          showSymbol: selected,
          symbolSize: selected ? 7 : 4,
          smooth: false,
          z: selected ? 5 : 3,
          lineStyle: { color: scenarioColors[index % scenarioColors.length], width: selected ? 4 : 2, opacity: selected ? 1 : 0.48 },
          itemStyle: { color: scenarioColors[index % scenarioColors.length] },
          areaStyle: selected ? { color: 'rgba(47,230,214,.08)' } : undefined,
        };
      });
      chart.setOption({
        animationDuration: 600,
        tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
        legend: { top: 4, textStyle: { color: '#9bb7c6' } },
        grid: [
          { left: 62, right: 34, top: 56, height: '48%' },
          { left: 62, right: 34, top: '72%', height: '19%' },
        ],
        xAxis: [0, 1].map((gridIndex) => ({
          type: 'value',
          gridIndex,
          min: 0,
          name: '上游 → 下游桩号 / m',
          axisLabel: { color: '#7898aa' },
          axisLine: { lineStyle: { color: 'rgba(102,145,168,.28)' } },
        })),
        yAxis: [
          {
            type: 'value', gridIndex: 0, name: '1985 高程 / m', scale: true,
            nameTextStyle: { color: '#9bb7c6' }, axisLabel: { color: '#7898aa' }, splitLine: { lineStyle: { color: 'rgba(100,151,183,.10)' } },
          },
          {
            type: 'value', gridIndex: 1, name: '流速 / m/s', min: 0,
            nameTextStyle: { color: '#9bb7c6' }, axisLabel: { color: '#7898aa' }, splitLine: { lineStyle: { color: 'rgba(100,151,183,.10)' } },
          },
        ],
        series: [
          {
            name: '河底深泓高程', type: 'line', xAxisIndex: 0, yAxisIndex: 0,
            data: reference.map((section) => [section.chainage_m, section.bed_min_m]),
            showSymbol: false, lineStyle: { color: '#8a735f', width: 3 }, areaStyle: { color: 'rgba(117,86,59,.20)' }, z: 2,
          },
          ...waterSeries,
          {
            name: `${selectedScenario.label} 流速`, type: 'bar', xAxisIndex: 1, yAxisIndex: 1,
            data: selectedScenario.section_summary.map((section) => [section.chainage_m, section.final_velocity_ms]),
            barMaxWidth: 18, itemStyle: { color: '#38a8ff', borderRadius: [4, 4, 0, 0] },
          },
        ],
      });
      const resize = () => chart.resize();
      window.addEventListener('resize', resize);
      dispose = () => {
        window.removeEventListener('resize', resize);
        chart.dispose();
      };
    });
    return () => {
      disposed = true;
      dispose?.();
    };
  }, [bundle, selectedScenario]);

  return <div ref={element} className="scenario-longitudinal-chart" />;
}

/** Present locally published engineering results without implying calibration or production approval. */
export function HydraulicScenarioResultsPage() {
  const navigate = useNavigate();
  const [bundles, setBundles] = useState<PublishedScenarioBundle[]>([]);
  const [bundleId, setBundleId] = useState('');
  const [scenarioId, setScenarioId] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    listPublishedScenarioResults()
      .then((items) => {
        if (cancelled) return;
        setBundles(items);
        setBundleId((current) => current || items[0]?.bundle_id || '');
        setScenarioId((current) => current || items[0]?.scenarios[0]?.scenario_id || '');
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : '方案成果加载失败');
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const bundle = useMemo(
    () => bundles.find((item) => item.bundle_id === bundleId) ?? bundles[0],
    [bundleId, bundles],
  );
  const selectedScenario = useMemo(
    () => bundle?.scenarios.find((item) => item.scenario_id === scenarioId) ?? bundle?.scenarios[0],
    [bundle, scenarioId],
  );

  /** Keep scenario selection valid when the operator switches result bundles. */
  const changeBundle = (value: string) => {
    const next = bundles.find((item) => item.bundle_id === value);
    setBundleId(value);
    setScenarioId(next?.scenarios[0]?.scenario_id ?? '');
  };

  const columns: ColumnsType<ScenarioResultSection> = [
    { title: '断面', dataIndex: 'cross_section_id', fixed: 'left', width: 85 },
    { title: '桩号 (m)', dataIndex: 'chainage_m', width: 110, render: (value: number) => value.toFixed(1) },
    { title: '深泓高程 (m)', dataIndex: 'bed_min_m', width: 125, render: (value: number) => value.toFixed(3) },
    { title: '水位 (m)', dataIndex: 'final_water_level_m', width: 105, render: (value: number) => value.toFixed(3) },
    { title: '水深 (m)', dataIndex: 'final_depth_m', width: 105, render: (value: number) => value.toFixed(3) },
    { title: '流量 (m³/s)', dataIndex: 'final_discharge_m3s', width: 125, render: (value: number) => value.toFixed(3) },
    { title: '流速 (m/s)', dataIndex: 'final_velocity_ms', width: 115, render: (value: number) => value.toFixed(3) },
    { title: '过流面积 (m²)', dataIndex: 'flow_area_m2', width: 130, render: (value: number) => value.toFixed(2) },
  ];

  return (
    <div className="data-page hydraulic-page scenario-results-page">
      <HydraulicHeader
        eyebrow="PUBLISHED SCENARIO RESULTS"
        title="工程方案成果"
        description="沿河道上游到下游查看已发布的准恒定水面线、河底高程、流速与数值质量证据。"
        action={<Space><Button onClick={() => navigate('/hydraulic/results')}>任务结果</Button><Button onClick={() => navigate(`/gis?scenarioBundleId=${encodeURIComponent(bundle?.bundle_id ?? '')}&scenarioId=${encodeURIComponent(selectedScenario?.scenario_id ?? '')}`)}>GIS 一张图</Button></Space>}
      />
      {error && <Alert className="data-alert" type="error" showIcon message={error} />}
      {!loading && !bundle && <Alert type="info" showIcon message="暂无已发布方案成果" description="请先把受控成果包放入平台本地运行存储。" />}
      <Card className="data-card scenario-selector" loading={loading}>
        <Row gutter={[18, 18]} align="middle">
          <Col xs={24} lg={9}>
            <Text type="secondary">成果包</Text>
            <Select className="hydraulic-select" value={bundle?.bundle_id} onChange={changeBundle} options={bundles.map((item) => ({ value: item.bundle_id, label: item.title }))} />
          </Col>
          <Col xs={24} lg={9}>
            <Text type="secondary">计算工况</Text>
            <Select className="hydraulic-select" value={selectedScenario?.scenario_id} onChange={setScenarioId} options={bundle?.scenarios.map((item) => ({ value: item.scenario_id, label: `${item.label} · Q ${item.q_m3s} m³/s` })) ?? []} />
          </Col>
          <Col xs={24} lg={6} className="scenario-classification">
            <Tag color="gold">未率定方案计算</Tag>
            <Tag color="success">数值 QA 通过</Tag>
          </Col>
        </Row>
      </Card>
      {bundle && selectedScenario && (
        <>
          <Alert
            className="data-alert"
            type="warning"
            showIcon
            message="成果边界说明"
            description="本成果仅为未率定方案计算：三工况通过时间收敛、质量平衡和沿程流量一致性检查；尚未完成实测资料率定、独立验证、MIKE11 交叉验证或生产工程定级。"
          />
          <Card className="data-card" title="案例工程文件" style={{ marginBottom: 16 }}>
            <Text type="secondary">每个步骤的输入、规范化 DTO、交换文件、成果包和 GIS 图层均保存在平台受控案例目录。</Text>
            <Space wrap style={{ marginTop: 12 }}>
              {[
                ['01_river_database_import_gaominghe_EPSG4547.xlsx', '河道数据库导入'],
                ['02_cross_section_database_import_gaominghe_1985_Marker1-3.xlsx', '横断面数据库导入'],
                ['03_normalized_payload.json', '规范化输入'],
                ['04_network.nwk11', 'NWK11'],
                ['05_cross_sections.xns11', 'XNS11'],
                ['case_manifest.json', '步骤索引'],
                ['spatial.geojson', 'GIS 图层'],
              ].map(([filename, label]) => <Button key={filename} size="small" href={`/api/v1/model/scenario-results/${encodeURIComponent(bundle.bundle_id)}/artifacts/${encodeURIComponent(filename)}`} target="_blank">{label}</Button>)}
            </Space>
          </Card>
          <Row gutter={[16, 16]} className="hydraulic-stats scenario-kpis">
            <Col xs={12} md={8} xl={4}><Card className="data-card"><Statistic title="上游流量" value={selectedScenario.q_m3s} precision={2} suffix="m³/s" /></Card></Col>
            <Col xs={12} md={8} xl={4}><Card className="data-card"><Statistic title="下游水位" value={selectedScenario.downstream_h_m} precision={3} suffix="m" /></Card></Col>
            <Col xs={12} md={8} xl={4}><Card className="data-card"><Statistic title="上游水位" value={selectedScenario.upstream_water_level_m} precision={3} suffix="m" /></Card></Col>
            <Col xs={12} md={8} xl={4}><Card className="data-card"><Statistic title="最高水位" value={selectedScenario.maximum_water_level_m} precision={3} suffix="m" /></Card></Col>
            <Col xs={12} md={8} xl={4}><Card className="data-card"><Statistic title="最大流速" value={selectedScenario.maximum_velocity_ms} precision={3} suffix="m/s" /></Card></Col>
            <Col xs={12} md={8} xl={4}><Card className="data-card"><Statistic prefix={<CheckCircleOutlined />} title="质量平衡误差" value={selectedScenario.mass_balance_residual * 100} precision={4} suffix="%" /></Card></Col>
          </Row>
          <Card
            className="data-card scenario-chart-card"
            title={`${bundle.river_name} · 沿程水面线与流速`}
            extra={<Space><Tag color="cyan">DM1 → DM22</Tag><Tag>{selectedScenario.section_summary.length} 个断面</Tag></Space>}
          >
            <ScenarioLongitudinalChart bundle={bundle} selectedScenario={selectedScenario} />
          </Card>
          <Row gutter={[16, 16]}>
            <Col xs={24} xl={14}>
              <Card className="data-card" title={`${selectedScenario.label} · 断面成果表`}>
                <Table rowKey="cross_section_id" size="small" columns={columns} dataSource={selectedScenario.section_summary} pagination={false} scroll={{ x: 900, y: 470 }} />
              </Card>
            </Col>
            <Col xs={24} xl={10}>
              <Card className="data-card" title="模型与数据口径">
                <Descriptions column={1} size="small" items={[
                  { key: 'crs', label: '平面坐标', children: String(bundle.input.source_crs ?? '—') },
                  { key: 'datum', label: '高程基准', children: '1985 国家高程基准 · MIKE11 Datum 0.000 m' },
                  { key: 'roughness', label: '综合糙率', children: `n = ${String(bundle.physical_assumptions.manning_n ?? '—')}` },
                  { key: 'boundary', label: '边界条件', children: `${selectedScenario.q_m3s} m³/s（上游） / ${selectedScenario.downstream_h_m} m（下游）` },
                  { key: 'overbank', label: '漫滩处理', children: '全归槽 · 首末测点近竖直边墙' },
                  { key: 'solver', label: '求解器', children: `${String(bundle.runtime_provenance.engine_name ?? 'MASCARET')} ${String(bundle.runtime_provenance.engine_version ?? 'v9.1.1')}` },
                  { key: 'mode', label: '计算模式', children: '恒定 Q/H 边界时间推进至准恒定' },
                  { key: 'duration', label: '计算时长', children: `${(selectedScenario.duration_seconds / 3600).toFixed(1)} h` },
                  { key: 'mesh', label: '计算网格', children: `${selectedScenario.mesh_spacing_m.toFixed(0)} m` },
                  { key: 'digest', label: '成果摘要', children: <Text code copyable>{(bundle.source_digest ?? '').slice(0, 16)}…</Text> },
                ]} />
              </Card>
              <Card className="data-card" title="数值门禁">
                <Descriptions column={1} size="small" items={[
                  { key: 'temporal', label: '时间收敛', children: <Tag color={selectedScenario.quality_gate.temporal_converged ? 'success' : 'error'}>{selectedScenario.quality_gate.temporal_converged ? '通过' : '未通过'}</Tag> },
                  { key: 'balance', label: '质量平衡', children: `${(selectedScenario.quality_gate.mass_balance_residual * 100).toFixed(6)}% ≤ ${(selectedScenario.quality_gate.mass_balance_tolerance * 100).toFixed(3)}%` },
                  { key: 'flow-span', label: '沿程流量差', children: `${selectedScenario.quality_gate.final_discharge_span_m3s.toFixed(4)} ≤ ${selectedScenario.quality_gate.final_discharge_span_tolerance_m3s.toFixed(1)} m³/s` },
                  { key: 'acceptance', label: '综合结论', children: <Tag color={selectedScenario.quality_gate.passed ? 'success' : 'error'}>{selectedScenario.quality_gate.passed ? 'PASS' : 'FAIL'}</Tag> },
                ]} />
              </Card>
            </Col>
          </Row>
        </>
      )}
    </div>
  );
}

/** Read a unified result and expose no MASCARET-native output format to the UI. */
export function HydraulicResultsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const { datasetVersionId } = useDatasetVersion();
  const [tasks, setTasks] = useState<SimulationTaskRecord[]>([]);
  const [tasksLoaded, setTasksLoaded] = useState(false);
  const [result, setResult] = useState<SimulationResultResponse>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const taskId = Number(searchParams.get('taskId') || 0);
  const sectionId = Number(searchParams.get('sectionId') || 0);

  useEffect(() => {
    let cancelled = false;
    setTasks([]);
    setTasksLoaded(false);
    setResult(undefined);
    if (!datasetVersionId) {
      setLoading(false);
      setTasksLoaded(true);
      return () => { cancelled = true; };
    }
    void listHydraulicTasks({ dataset_version_id: datasetVersionId })
      .then((items) => {
        if (cancelled) return;
        const successful = items.filter((item) => item.status === 'success');
        setTasks(successful);
        const selectedTaskExists = successful.some((item) => item.id === taskId);
        if (!selectedTaskExists && (successful[0] || taskId)) {
          setSearchParams((current) => {
            const next = new URLSearchParams(current);
            if (successful[0]) next.set('taskId', String(successful[0].id));
            else next.delete('taskId');
            next.delete('sectionId');
            return next;
          }, { replace: true });
        }
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : '任务加载失败');
      })
      .finally(() => { if (!cancelled) setTasksLoaded(true); });
    return () => { cancelled = true; };
  }, [datasetVersionId, setSearchParams, taskId]);

  useEffect(() => {
    if (!tasksLoaded) {
      setLoading(true);
      return;
    }
    if (!taskId) {
      setResult(undefined);
      setLoading(false);
      return;
    }
    if (!tasks.some((item) => item.id === taskId)) {
      setResult(undefined);
      setError('当前任务不属于所选数据版本');
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError('');
    void getHydraulicResult(taskId, sectionId || undefined)
      .then((value) => {
        if (cancelled) return;
        setResult(value);
        const firstSectionId = value.available_sections[0]?.section_id;
        if (!sectionId && firstSectionId) {
          setSearchParams((current) => {
            const next = new URLSearchParams(current);
            next.set('sectionId', String(firstSectionId));
            return next;
          }, { replace: true });
        }
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : '结果加载失败');
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [sectionId, setSearchParams, taskId, tasks, tasksLoaded]);

  const selectedTask = useMemo(() => tasks.find((item) => item.id === taskId), [taskId, tasks]);
  const latestIndex = result ? result.time.length - 1 : -1;
  const latest = latestIndex >= 0 && result ? {
    waterLevel: result.water_level[latestIndex],
    depth: result.depth[latestIndex],
    flow: result.flow[latestIndex],
    velocity: result.velocity[latestIndex],
    flowArea: result.flow_area[latestIndex],
    wetArea: result.wet_area[latestIndex],
    hydraulicRadius: result.hydraulic_radius[latestIndex],
    topWidth: result.top_width[latestIndex],
    froude: result.froude_number[latestIndex],
  } : undefined;
  const boundaryWarnings = result?.diagnostics && Array.isArray(result.diagnostics.boundary_control_warnings)
    ? result.diagnostics.boundary_control_warnings
    : [];
  const chartResult = result ? {
    time: result.time,
    water_level: result.water_level,
    flow: result.flow,
    velocity: result.velocity,
  } : undefined;

  const changeTask = (value: number) => {
    const next = new URLSearchParams(searchParams);
    next.set('taskId', String(value));
    next.delete('sectionId');
    setSearchParams(next);
  };
  const changeSection = (value: number) => {
    const next = new URLSearchParams(searchParams);
    next.set('sectionId', String(value));
    setSearchParams(next);
  };

  return (
    <div className="data-page hydraulic-page">
      <HydraulicHeader
        eyebrow="UNIFIED HYDRAULIC RESULT"
        title="Standard 1D 模拟结果"
        description="按任务和横断面查看大禹统一结果；页面不直接读取 MASCARET 原生文件。"
        action={<Space><Button onClick={() => navigate('/gis')}>返回 GIS</Button><Button onClick={() => navigate('/hydraulic/tasks')}>任务监控</Button></Space>}
      />
      {error && <Alert className="data-alert" type="error" showIcon message={error} />}
      {!taskId && !loading && (
        <Alert showIcon type="info" message="暂无成功任务，请先创建并运行模拟。" action={<Button onClick={() => navigate('/hydraulic/config')}>新建模拟</Button>} />
      )}
      {taskId > 0 && (
        <>
          <Card className="data-card" loading={loading}>
            <Row gutter={[16, 16]} align="bottom">
              <Col xs={24} md={8}>
                <Text type="secondary">成功任务</Text>
                <Select
                  className="hydraulic-select"
                  value={taskId}
                  onChange={changeTask}
                  options={tasks.map((task) => ({ value: task.id, label: `任务 #${task.id} · ${new Date(task.created_time).toLocaleString()}` }))}
                />
              </Col>
              <Col xs={24} md={8}>
                <Text type="secondary">横断面</Text>
                <Select
                  className="hydraulic-select"
                  value={result?.section_id ?? undefined}
                  onChange={changeSection}
                  options={result?.available_sections
                    .map((item) => ({ value: item.section_id, label: `${item.section_code} · ${item.chainage_m.toFixed(1)} m` })) ?? []}
                />
              </Col>
              <Col xs={24} md={8}>
                <Descriptions size="small" column={1} items={[
                  { key: 'status', label: '状态', children: selectedTask ? statusTag(selectedTask.status) : <Tag>—</Tag> },
                  { key: 'engine', label: '引擎', children: result ? `Standard 1D · ${result.engine} ${result.engine_version}` : selectedTask ? `Standard 1D · ${selectedTask.solver_id ?? HYDRAULIC_ENGINE} ${selectedTask.engine_version ?? 'v9.1.1'}` : '—' },
                  { key: 'scenario', label: '模拟 / 情景', children: result ? `${result.simulation_id} / ${result.scenario_id}` : '—' },
                  { key: 'branch', label: '河段 / 桩号', children: result ? `#${result.branch_id} / ${result.chainage_m.toFixed(1)} m` : '—' },
                  { key: 'section', label: '当前断面', children: result?.section_code ?? '—' },
                ]} />
              </Col>
            </Row>
          </Card>
          {result && (
            <>
              {boundaryWarnings.length > 0 && (
                <Alert
                  className="data-alert"
                  type="warning"
                  showIcon
                  message="稳态计算存在未被控制的边界"
                  description="MASCARET 已完成数值求解，但某个端点边界在当前流态下未能控制结果；请结合 Froude 数和断面能力复核边界组合。详情见下方运行与结果诊断。"
                />
              )}
              <Row gutter={[16, 16]} className="hydraulic-stats">
                <Col xs={12} md={8} xl={6}><Card className="data-card"><Statistic prefix={<CheckCircleOutlined />} title="末时刻水位" value={latest?.waterLevel} precision={3} suffix="m" /></Card></Col>
                <Col xs={12} md={8} xl={6}><Card className="data-card"><Statistic title="末时刻水深" value={latest?.depth ?? undefined} precision={3} suffix="m" /></Card></Col>
                <Col xs={12} md={8} xl={6}><Card className="data-card"><Statistic title="末时刻流量" value={latest?.flow} precision={3} suffix="m³/s" /></Card></Col>
                <Col xs={12} md={8} xl={6}><Card className="data-card"><Statistic title="末时刻流速" value={latest?.velocity} precision={3} suffix="m/s" /></Card></Col>
                <Col xs={12} md={8} xl={6}><Card className="data-card"><Statistic title="过流面积" value={latest?.flowArea ?? undefined} precision={3} suffix="m²" /></Card></Col>
                <Col xs={12} md={8} xl={6}><Card className="data-card"><Statistic title="湿面积" value={latest?.wetArea ?? undefined} precision={3} suffix="m²" /></Card></Col>
                <Col xs={12} md={8} xl={6}><Card className="data-card"><Statistic title="水力半径" value={latest?.hydraulicRadius ?? undefined} precision={3} suffix="m" /></Card></Col>
                <Col xs={12} md={8} xl={6}><Card className="data-card"><Statistic title="水面宽" value={latest?.topWidth ?? undefined} precision={3} suffix="m" /></Card></Col>
                <Col xs={12} md={8} xl={6}><Card className="data-card"><Statistic title="Froude 数" value={latest?.froude ?? undefined} precision={4} /></Card></Col>
              </Row>
              <Card className="data-card" title={`${result.section_code} · 时序曲线`} extra={<Tag color="cyan">{result.time.length} 个输出时刻</Tag>}>
                <HydraulicResultChart result={chartResult} />
              </Card>
              <Card className="data-card" title="运行与结果诊断">
                <pre className="hydraulic-diagnostics">{JSON.stringify(result.diagnostics, null, 2)}</pre>
              </Card>
            </>
          )}
        </>
      )}
    </div>
  );
}
