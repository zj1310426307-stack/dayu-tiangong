import {
  AreaChartOutlined,
  CheckCircleOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
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
  cancelHydraulicTask,
  createHydraulicTask,
  downloadHydraulicV4Artifact,
  enqueueHydraulicTask,
  getHydraulicResult,
  getHydraulicV4Events,
  getHydraulicV4Gates,
  getHydraulicV4Pumps,
  getHydraulicV4Section,
  getHydraulicV4Summary,
  getModelInputV4Readiness,
  getSimulationCases,
  listDispatchPlans,
  listHydraulicTasks,
  listHydraulicV4Sections,
  retryHydraulicTask,
  type SimulationResultResponse,
  type SimulationTaskCreate,
  type SimulationTaskRecord,
  type DispatchPlanRecord,
  type V4ArtifactManifest,
  type V4ControlEventRecord,
  type V4GateResultRecord,
  type V4PumpResultRecord,
  type V4ReadinessResponse,
  type V4ResultSummary,
  type V4SectionResultResponse,
} from '../../api/generated/client';
import { useDatasetVersion } from '../../context/DatasetVersionContext';

const { Paragraph, Text, Title } = Typography;
const D1_SOLVER_ID = 'saint-venant-fv-hll-ssp-rk2-d1-v1';
const RETRY_BLOCKED_ARTIFACT_STATUSES = new Set([
  'prepared',
  'publishing',
  'reconciliation_required',
  'orphaned',
]);

function canRetryTask(task: SimulationTaskRecord): boolean {
  return task.retry_eligible === true
    && !RETRY_BLOCKED_ARTIFACT_STATUSES.has(task.artifact_status ?? '');
}

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

function statusTag(status: SimulationTaskRecord['status']) {
  const colors = { pending: 'default', queued: 'blue', running: 'processing', cancel_requested: 'warning', cancelled: 'default', success: 'success', failed: 'error' } as const;
  const labels = { pending: '待入队', queued: '排队中', running: '计算中', cancel_requested: '取消中', cancelled: '已取消', success: '成功', failed: '失败' } as const;
  return <Tag color={colors[status]}>{labels[status]}</Tag>;
}

export function HydraulicConfigPage() {
  const navigate = useNavigate();
  const { datasetVersionId } = useDatasetVersion();
  const [form] = Form.useForm<SimulationTaskCreate>();
  const schemaVersion = Form.useWatch('input_schema_version', form) ?? 'dayu.model-input.v3';
  const selectedCaseId = Form.useWatch('case_id', form);
  const selectedPlanId = Form.useWatch('dispatch_plan_id', form);
  const [cases, setCases] = useState<Array<{ id: number; name: string }>>([]);
  const [plans, setPlans] = useState<DispatchPlanRecord[]>([]);
  const [readiness, setReadiness] = useState<V4ReadinessResponse>();
  const [readinessLoading, setReadinessLoading] = useState(false);
  const [loadingCases, setLoadingCases] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!datasetVersionId) {
      setCases([]);
      setPlans([]);
      setLoadingCases(false);
      return;
    }
    setLoadingCases(true);
    form.setFieldValue('case_id', undefined);
    void getSimulationCases(datasetVersionId)
      .then((items) => {
        setCases(items.map((item) => ({ id: item.id, name: item.name })));
        if (items[0]) form.setFieldValue('case_id', items[0].id);
        setError('');
      })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : '计算方案加载失败'))
      .finally(() => setLoadingCases(false));
    void listDispatchPlans({ dataset_version_id: datasetVersionId, status: 'frozen', limit: 100 })
      .then((page) => setPlans(page.items.filter((item) => item.status === 'frozen')))
      .catch(() => setPlans([]));
  }, [datasetVersionId, form]);

  useEffect(() => {
    setReadiness(undefined);
    if (schemaVersion !== 'dayu.model-input.v4' || !selectedCaseId || !selectedPlanId) return;
    let cancelled = false;
    setReadinessLoading(true);
    void getModelInputV4Readiness(selectedCaseId, selectedPlanId)
      .then((value) => { if (!cancelled) setReadiness(value); })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : 'v4 readiness 检查失败');
      })
      .finally(() => { if (!cancelled) setReadinessLoading(false); });
    return () => { cancelled = true; };
  }, [schemaVersion, selectedCaseId, selectedPlanId]);

  const submit = async (values: SimulationTaskCreate) => {
    setSubmitting(true);
    setError('');
    try {
      const body: SimulationTaskCreate = schemaVersion === 'dayu.model-input.v4'
        ? {
            case_id: values.case_id,
            input_schema_version: 'dayu.model-input.v4',
            solver_id: D1_SOLVER_ID,
            dispatch_plan_id: values.dispatch_plan_id,
            execution_mode: 'validation',
            storage_level: values.storage_level ?? 'full',
          }
        : { ...values, input_schema_version: 'dayu.model-input.v3', dispatch_plan_id: undefined };
      const created = await createHydraulicTask(body);
      await enqueueHydraulicTask(created.id);
      message.success(`任务 #${created.id} 已进入 Celery/Redis 队列`);
      navigate('/hydraulic/tasks');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '任务创建或运行失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="data-page hydraulic-page">
      <HydraulicHeader
        eyebrow="SAINT-VENANT / CONFIGURATION"
        title="水动力模拟配置"
        description="基于已版本化的河网、断面、糙率和边界条件创建可追溯的一维非恒定流任务。"
        action={<Button onClick={() => navigate('/hydraulic/tasks')}>查看任务监控</Button>}
      />
      {error && <Alert className="data-alert" type="error" showIcon message={error} />}
      {!loadingCases && datasetVersionId && cases.length === 0 && (
        <Alert className="data-alert" type="warning" showIcon message="当前版本没有可运行的计算方案" description="请切换到包含模型参数和边界条件的已发布版本，或先在草稿中完善模型数据。" />
      )}
      <Card className="data-card hydraulic-config-card" title="计算参数">
        <Alert
          showIcon
          type="info"
          message="空间坐标统一为 CGCS2000 / EPSG:4490；网格距离采用断面桩号与河段米制长度。"
        />
        <Form
          form={form}
          layout="vertical"
          className="hydraulic-form"
          initialValues={{
            input_schema_version: 'dayu.model-input.v3',
            storage_level: 'full',
            duration_seconds: 3600,
            time_step_seconds: 60,
            output_interval_seconds: 300,
            cfl_number: 0.75,
            initial_water_level: 10.8,
            initial_flow: 60,
            minimum_depth: 0.05,
          }}
          onFinish={(values) => void submit(values)}
        >
          <Row gutter={16}>
            <Col xs={24} md={12}>
              <Form.Item name="input_schema_version" label="求解器路线" rules={[{ required: true }]}>
                <Select options={[
                  { value: 'dayu.model-input.v3', label: 'Legacy v3 · 河网连续性/Manning' },
                  { value: 'dayu.model-input.v4', label: 'Saint-Venant D1 v4（受限验证）' },
                ]} />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item name="case_id" label="计算方案" rules={[{ required: true, message: '请选择计算方案' }]}>
                <Select
                  loading={loadingCases}
                  options={cases.map((item) => ({ value: item.id, label: `${item.name} · #${item.id}` }))}
                />
              </Form.Item>
            </Col>
            {schemaVersion === 'dayu.model-input.v4' && (
              <Col xs={24} md={12}>
                <Form.Item name="dispatch_plan_id" label="冻结调度方案" rules={[{ required: true, message: 'v4 必须选择冻结调度方案' }]}>
                  <Select options={plans
                    .filter((item) => !selectedCaseId || item.simulation_case_id === selectedCaseId)
                    .map((item) => ({ value: item.id, label: `${item.name} · v${item.version} · #${item.id}` }))} />
                </Form.Item>
              </Col>
            )}
            {schemaVersion !== 'dayu.model-input.v4' && <Col xs={12} md={6}>
              <Form.Item name="duration_seconds" label="模拟时长（s）" rules={[{ required: true }]}>
                <InputNumber min={1} precision={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>}
            {schemaVersion !== 'dayu.model-input.v4' && <Col xs={12} md={6}>
              <Form.Item name="time_step_seconds" label="请求步长（s）" rules={[{ required: true }]}>
                <InputNumber min={0.001} style={{ width: '100%' }} />
              </Form.Item>
            </Col>}
          </Row>
          {schemaVersion !== 'dayu.model-input.v4' && <Row gutter={16}>
            <Col xs={12} md={6}>
              <Form.Item name="output_interval_seconds" label="输出间隔（s）" rules={[{ required: true }]}>
                <InputNumber min={0.001} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item name="cfl_number" label="CFL 系数" rules={[{ required: true }]}>
                <InputNumber min={0.01} max={1} step={0.05} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item name="initial_water_level" label="初始水位（m）">
                <InputNumber step={0.1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item name="initial_flow" label="初始流量（m³/s）">
                <InputNumber step={1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>}
          {schemaVersion !== 'dayu.model-input.v4' && <Row gutter={16}>
            <Col xs={12} md={6}>
              <Form.Item name="minimum_depth" label="最小水深（m）" rules={[{ required: true }]}>
                <InputNumber min={0.001} step={0.01} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>}
          {schemaVersion === 'dayu.model-input.v4' && (
            <Alert
              className="data-alert"
              showIcon
              type={readiness?.ready ? 'success' : readiness ? 'error' : 'info'}
              message={readiness?.ready ? 'D1 v4 readiness 通过' : readinessLoading ? '正在检查 v4 readiness' : '请选择工况与冻结调度方案'}
              description={readiness ? (
                <Space direction="vertical" size={2}>
                  <Text>solver: {readiness.solver_id}</Text>
                  <Text>capability: {readiness.capability_id}</Text>
                  {readiness.errors.map((item) => <Text type="danger" key={`${item.code}-${item.field_path}`}>{item.code} · {item.message}</Text>)}
                  <Text type="secondary">单 Branch · 全湿 · 正向严格亚临界 · 1 Gate · 1 external Pump · 仅验证用途 · 非生产率定</Text>
                </Space>
              ) : undefined}
            />
          )}
          <Button
            type="primary"
            size="large"
            icon={<PlayCircleOutlined />}
            htmlType="submit"
            loading={submitting}
            disabled={!datasetVersionId || cases.length === 0 || (schemaVersion === 'dayu.model-input.v4' && !readiness?.ready)}
          >
            创建并运行模拟
          </Button>
        </Form>
      </Card>
    </div>
  );
}

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

  const enqueuePending = async (task: SimulationTaskRecord) => {
    await enqueueHydraulicTask(task.id);
    await reload();
  };

  const columns: ColumnsType<SimulationTaskRecord> = [
    { title: '任务', dataIndex: 'id', width: 90, render: (value: number) => `#${value}` },
    { title: '方案 ID', dataIndex: 'case_id', width: 100 },
    { title: 'Schema', dataIndex: 'input_schema_version', width: 150, render: (value: string | null) => value?.replace('dayu.model-input.', 'v') ?? '—' },
    { title: '求解器 / 能力', key: 'solver', width: 260, render: (_, task) => <Space direction="vertical" size={0}><Text>{task.solver_id ?? 'legacy default'}</Text><Text type="secondary">{task.capability_id ?? '—'}</Text></Space> },
    {
      title: '运行构建',
      key: 'runtime-build',
      width: 230,
      render: (_, task) => (
        <Space direction="vertical" size={0}>
          <Space size={4}>
            <Tag color={task.build_verified ? 'success' : 'warning'}>{task.build_verified ? '已验证' : '开发构建'}</Tag>
            <Text>{task.build_mode ?? '—'}</Text>
          </Space>
          <Text type="secondary" title={task.solver_build_id ?? undefined}>
            {task.engine_commit?.slice(0, 12) ?? '—'} · {task.solver_build_id?.slice(-12) ?? '—'}
          </Text>
        </Space>
      ),
    },
    { title: '状态', dataIndex: 'status', width: 110, render: statusTag },
    { title: '进度', dataIndex: 'progress', width: 180, render: (value: number) => <Progress percent={value} size="small" /> },
    { title: '阶段', dataIndex: 'execution_phase', width: 150, render: (value: string | null) => value ?? '—' },
    { title: '模拟时刻 / CFL', key: 'runtime', width: 160, render: (_, task) => `${task.current_simulation_time?.toFixed(1) ?? '—'} s / ${task.current_cfl?.toFixed(3) ?? '—'}` },
    { title: '接受步', dataIndex: 'accepted_step_count', width: 100 },
    { title: '执行尝试', key: 'execution-attempts', width: 100, dataIndex: 'execution_attempt_count' },
    { title: '投递尝试', key: 'delivery-attempts', width: 100, dataIndex: 'delivery_attempt_count' },
    { title: '人工重试', key: 'manual-retries', width: 100, dataIndex: 'manual_retry_count' },
    { title: '基础设施重试', key: 'infrastructure-retries', width: 125, dataIndex: 'infrastructure_retry_count' },
    { title: '数值重试', key: 'numerical-retries', width: 100, dataIndex: 'numerical_retry_count' },
    { title: '数值重试分类', key: 'retry-breakdown', width: 230, render: (_, task) => `CFL ${task.cfl_reduction_count} · 正性 ${task.positivity_retry_count} · 事件 ${task.event_refinement_count} · 闸 ${task.gate_solver_retry_count} · 泵 ${task.pump_solver_retry_count}` },
    {
      title: '重试资格',
      key: 'retry-eligibility',
      width: 220,
      render: (_, task) => {
        const artifactStateBlocksRetry = RETRY_BLOCKED_ARTIFACT_STATUSES.has(task.artifact_status ?? '');
        const eligible = canRetryTask(task);
        return (
          <Space direction="vertical" size={0}>
            <Tag color={eligible ? 'success' : 'default'}>{eligible ? '可重试' : '不可重试'}</Tag>
            {task.retry_block_reason && <Text type="secondary">{task.retry_block_reason}</Text>}
            {artifactStateBlocksRetry && !task.retry_block_reason && (
              <Text type="secondary">Artifact {task.artifact_status} 阶段不可重试</Text>
            )}
          </Space>
        );
      },
    },
    { title: '心跳', dataIndex: 'heartbeat_time', width: 190, render: (value: string | null) => value ? new Date(value).toLocaleString() : '—' },
    { title: '创建时间', dataIndex: 'created_time', width: 190, render: (value: string) => new Date(value).toLocaleString() },
    { title: '错误信息', dataIndex: 'error_message', ellipsis: true, render: (value: string | null) => value || '—' },
    {
      title: '操作',
      key: 'actions',
      width: 210,
      render: (_, task) => (
        <Space>
          {task.status === 'pending' && <Button size="small" icon={<PlayCircleOutlined />} onClick={() => void enqueuePending(task)}>入队</Button>}
          {['queued', 'running'].includes(task.status) && <Button size="small" danger onClick={async () => { await cancelHydraulicTask(task.id); await reload(); }}>取消</Button>}
          {canRetryTask(task) && <Button size="small" onClick={async () => { await retryHydraulicTask(task.id); await reload(); }}>重试</Button>}
          {task.status === 'success' && <Button size="small" icon={<AreaChartOutlined />} onClick={() => navigate(`/hydraulic/results?taskId=${task.id}`)}>结果</Button>}
        </Space>
      ),
    },
  ];

  return (
    <div className="data-page hydraulic-page">
      <HydraulicHeader
        eyebrow="SIMULATION TASKS / MONITOR"
        title="模拟任务监控"
        description="任务状态按 pending → running → success / failed 持久化，可追踪开始时间、完成时间和失败原因。"
        action={<Space><Button type="primary" onClick={() => navigate('/hydraulic/config')}>新建模拟</Button><Button icon={<ReloadOutlined />} onClick={() => void reload()} /></Space>}
      />
      {error && <Alert className="data-alert" type="error" showIcon message={error} />}
      <Card className="data-card">
        <Table rowKey="id" loading={loading} dataSource={tasks} columns={columns} pagination={{ pageSize: 12 }} scroll={{ x: 3100 }} />
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
          type: 'category', gridIndex: index, data: labels,
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

export function HydraulicResultsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const { datasetVersionId } = useDatasetVersion();
  const [tasks, setTasks] = useState<SimulationTaskRecord[]>([]);
  const [tasksLoaded, setTasksLoaded] = useState(false);
  const [result, setResult] = useState<SimulationResultResponse>();
  const [v4Result, setV4Result] = useState<V4SectionResultResponse>();
  const [v4Gates, setV4Gates] = useState<V4GateResultRecord[]>([]);
  const [v4Pumps, setV4Pumps] = useState<V4PumpResultRecord[]>([]);
  const [v4Events, setV4Events] = useState<V4ControlEventRecord[]>([]);
  const [v4Summary, setV4Summary] = useState<V4ResultSummary>();
  const [downloadingArtifactId, setDownloadingArtifactId] = useState<number>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const taskId = Number(searchParams.get('taskId') || 0);
  const sectionId = Number(searchParams.get('sectionId') || 0);

  useEffect(() => {
    let cancelled = false;
    setTasks([]);
    setTasksLoaded(false);
    setResult(undefined);
    setV4Result(undefined);
    setV4Gates([]);
    setV4Pumps([]);
    setV4Events([]);
    setV4Summary(undefined);
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
    const task = tasks.find((item) => item.id === taskId);
    const request = task?.input_schema_version === 'dayu.model-input.v4'
      ? (async () => {
          const options = await listHydraulicV4Sections(taskId);
          const resolvedSectionId = sectionId || options[0]?.hydraulic_cross_section_id;
          if (!resolvedSectionId) throw new Error('v4 任务没有可用断面结果');
          if (!sectionId) {
            setSearchParams((current) => {
              const next = new URLSearchParams(current);
              next.set('sectionId', String(resolvedSectionId));
              return next;
            }, { replace: true });
          }
          const [section, gates, pumps, events, summary] = await Promise.all([
            getHydraulicV4Section(taskId, resolvedSectionId),
            getHydraulicV4Gates(taskId),
            getHydraulicV4Pumps(taskId),
            getHydraulicV4Events(taskId),
            getHydraulicV4Summary(taskId),
          ]);
          if (!cancelled) {
            setResult(undefined);
            setV4Result(section);
            setV4Gates(gates);
            setV4Pumps(pumps);
            setV4Events(events);
            setV4Summary(summary);
          }
        })()
      : getHydraulicResult(taskId, sectionId || undefined)
          .then((value) => {
            if (!cancelled) {
              setV4Result(undefined);
              setResult(value);
            }
          });
    void request
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : '结果加载失败');
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [sectionId, setSearchParams, taskId, tasks, tasksLoaded]);

  const selectedTask = useMemo(() => tasks.find((item) => item.id === taskId), [taskId, tasks]);
  const latestValues = result ? {
    stage: result.water_level.at(-1), flow: result.flow.at(-1), velocity: result.velocity.at(-1),
  } : v4Result ? {
    stage: v4Result.water_level_m.at(-1), flow: v4Result.flow_m3s.at(-1), velocity: v4Result.velocity_m_s.at(-1),
  } : undefined;
  const chartResult: HydraulicChartSeries | undefined = result
    ? { time: result.time, water_level: result.water_level, flow: result.flow, velocity: result.velocity }
    : v4Result
      ? { time: v4Result.time_seconds, water_level: v4Result.water_level_m, flow: v4Result.flow_m3s, velocity: v4Result.velocity_m_s }
      : undefined;

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

  const downloadArtifact = async (artifact: V4ArtifactManifest) => {
    if (artifact.status !== 'published') return;
    setDownloadingArtifactId(artifact.id);
    try {
      const blob = await downloadHydraulicV4Artifact(taskId, artifact.id);
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = objectUrl;
      anchor.download = artifact.storage_key.split('/').at(-1) || `${artifact.artifact_type}-${artifact.id}`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (reason) {
      message.error(reason instanceof Error ? reason.message : 'Artifact 下载失败');
    } finally {
      setDownloadingArtifactId(undefined);
    }
  };

  return (
    <div className="data-page hydraulic-page">
      <HydraulicHeader
        eyebrow="HYDRAULIC RESULTS / TIMESERIES"
        title="水动力模拟结果"
        description="按计算任务和真实横断面查看水位、流量与流速时序；GIS 选中断面可直接联动到本页。"
        action={<Space><Button onClick={() => navigate('/gis')}>返回 GIS</Button><Button onClick={() => navigate('/hydraulic/tasks')}>任务监控</Button></Space>}
      />
      {error && <Alert className="data-alert" type="error" showIcon message={error} />}
      {!taskId && !loading && <Alert showIcon type="info" message="暂无成功任务，请先创建并运行模拟。" action={<Button onClick={() => navigate('/hydraulic/config')}>新建模拟</Button>} />}
      {taskId && (
        <>
          <Card className="data-card" loading={loading}>
            <Row gutter={[16, 16]} align="bottom">
              <Col xs={24} md={8}>
                <Text type="secondary">成功任务</Text>
                <Select className="hydraulic-select" value={taskId} onChange={changeTask} options={tasks.map((task) => ({ value: task.id, label: `任务 #${task.id} · ${new Date(task.created_time).toLocaleString()}` }))} />
              </Col>
              <Col xs={24} md={8}>
                <Text type="secondary">横断面</Text>
                <Select
                  className="hydraulic-select"
                  value={result?.section_id ?? v4Result?.hydraulic_cross_section_id ?? undefined}
                  onChange={changeSection}
                  options={result
                    ? result.available_sections.filter((item) => item.section_id !== null).map((item) => ({ value: item.section_id as number, label: `${item.section_code} · ${item.station.toFixed(1)} m` }))
                    : v4Result?.available_sections.map((item) => ({ value: item.hydraulic_cross_section_id, label: `${item.section_code} · ${item.chainage_m.toFixed(1)} m` })) ?? []}
                />
              </Col>
              <Col xs={24} md={8}>
                <Descriptions size="small" column={1} items={[
                  { key: 'status', label: '状态', children: selectedTask ? statusTag(selectedTask.status) : <Tag>—</Tag> },
                  { key: 'schema', label: 'Schema', children: selectedTask?.input_schema_version ?? '—' },
                  { key: 'section', label: '当前断面', children: result?.section_code ?? v4Result?.section_code ?? '—' },
                ]} />
              </Col>
            </Row>
          </Card>
          {(result || v4Result) && (
            <>
              <Row gutter={16} className="hydraulic-stats">
                <Col xs={24} md={8}><Card className="data-card"><Statistic prefix={<CheckCircleOutlined />} title="末时刻水位" value={latestValues?.stage} precision={3} suffix="m" /></Card></Col>
                <Col xs={24} md={8}><Card className="data-card"><Statistic title="末时刻流量" value={latestValues?.flow} precision={3} suffix="m³/s" /></Card></Col>
                <Col xs={24} md={8}><Card className="data-card"><Statistic title="末时刻流速" value={latestValues?.velocity} precision={3} suffix="m/s" /></Card></Col>
              </Row>
              <Card className="data-card" title={`${result?.section_code ?? v4Result?.section_code} · 时序曲线`} extra={<Tag color="cyan">{chartResult?.time.length} 个输出时刻</Tag>}>
                <HydraulicResultChart result={chartResult} />
              </Card>
              {v4Result && (
                <>
                  <Alert
                    className="data-alert"
                    type="warning"
                    showIcon
                    message="Saint-Venant D1 v4 受限验证结果"
                    description="单 Branch、全湿、正向严格亚临界、1 个 completed-interface Gate、1 个 external Pump；非生产率定或水利决策依据。"
                  />
                  <Card className="data-card" title="Gate 输出">
                    <Table
                      rowKey={(row) => `${row.canonical_gate_id}-${row.time_seconds}`}
                      size="small"
                      dataSource={v4Gates}
                      pagination={{ pageSize: 8 }}
                      scroll={{ x: 1050 }}
                      columns={[
                        { title: 't / s', dataIndex: 'time_seconds' },
                        { title: '开度 / m', dataIndex: 'opening_m' },
                        { title: 'Q / m³/s', dataIndex: 'flow_m3s' },
                        { title: '上游 H / m', dataIndex: 'upstream_stage_m' },
                        { title: '下游 H / m', dataIndex: 'downstream_stage_m' },
                        { title: '水头损失 / m', dataIndex: 'head_loss_m' },
                        { title: '流态', dataIndex: 'regime' },
                      ]}
                    />
                  </Card>
                  <Card className="data-card" title="External Pump 输出">
                    <Table
                      rowKey={(row) => `${row.canonical_pump_id}-${row.time_seconds}`}
                      size="small"
                      dataSource={v4Pumps}
                      pagination={{ pageSize: 8 }}
                      scroll={{ x: 1500 }}
                      columns={[
                        { title: 't / s', dataIndex: 'time_seconds' },
                        { title: '状态', dataIndex: 'control_state', render: (value: string) => <Tag color={value === 'on' ? 'green' : 'default'}>{value.toUpperCase()}</Tag> },
                        { title: '机组', dataIndex: 'running_units' },
                        { title: 'Q / m³/s', dataIndex: 'flow_m3s' },
                        { title: '源 H / m', dataIndex: 'source_stage_m' },
                        { title: '出口 H / m', dataIndex: 'outlet_stage_m' },
                        { title: 'Pump head / m', dataIndex: 'pump_head_m' },
                        { title: 'System head / m', dataIndex: 'system_head_m' },
                        { title: '效率', dataIndex: 'efficiency' },
                        { title: '输入功率 / kW', dataIndex: 'input_power_kw' },
                        { title: '累计能耗 / kWh', dataIndex: 'cumulative_energy_kwh' },
                        { title: '迭代', dataIndex: 'iterations' },
                      ]}
                    />
                  </Card>
                  <Card className="data-card" title="控制事件时间轴">
                    <Table
                      rowKey={(row) => `${row.structure_type}-${row.canonical_structure_id}-${row.time_seconds}-${row.event_type}`}
                      size="small"
                      pagination={false}
                      dataSource={v4Events}
                      columns={[
                        { title: 't / s', dataIndex: 'time_seconds' },
                        { title: '结构', dataIndex: 'structure_type' },
                        { title: '权威 ID', dataIndex: 'canonical_structure_id' },
                        { title: '事件', dataIndex: 'event_type' },
                        { title: '原因', dataIndex: 'reason' },
                      ]}
                    />
                  </Card>
                  <Card className="data-card" title="Result v3 / Artifact">
                    <Space direction="vertical">
                      <Text>result schema: {v4Summary?.result_schema_version}</Text>
                      {v4Summary?.artifacts.map((artifact) => {
                        const downloadable = artifact.status === 'published';
                        return (
                          <Space key={artifact.id}>
                            <Button
                              type="link"
                              disabled={!downloadable}
                              loading={downloadingArtifactId === artifact.id}
                              onClick={() => void downloadArtifact(artifact)}
                            >
                              {artifact.artifact_type} · {artifact.record_count} records · SHA-256 {artifact.sha256.slice(0, 16)}…
                            </Button>
                            <Tag color={downloadable ? 'success' : 'default'}>{artifact.status}</Tag>
                          </Space>
                        );
                      })}
                    </Space>
                  </Card>
                </>
              )}
              <Card className="data-card" title="稳定性诊断">
                <pre className="hydraulic-diagnostics">{JSON.stringify(result?.diagnostics ?? v4Summary?.provenance, null, 2)}</pre>
              </Card>
            </>
          )}
        </>
      )}
    </div>
  );
}
