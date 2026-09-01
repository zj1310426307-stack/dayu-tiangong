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
  cancelHydraulicTask,
  createHydraulicTask,
  enqueueHydraulicTask,
  getHydraulicReadiness,
  getHydraulicResult,
  getSimulationCases,
  listHydraulicTasks,
  previewHydraulicModel,
  retryHydraulicTask,
  type Hydraulic1DReadinessResponse,
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
  const { datasetVersionId } = useDatasetVersion();
  const [form] = Form.useForm<SimulationTaskCreate>();
  const selectedCaseId = Form.useWatch('case_id', form);
  const [cases, setCases] = useState<Array<{ id: number; name: string }>>([]);
  const [readiness, setReadiness] = useState<Hydraulic1DReadinessResponse>();
  const [preview, setPreview] = useState<Awaited<ReturnType<typeof previewHydraulicModel>>>();
  const [readinessLoading, setReadinessLoading] = useState(false);
  const [loadingCases, setLoadingCases] = useState(true);
  const [previewing, setPreviewing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
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
          description="请切换到包含完整河网、断面、糙率及上下游边界的已发布数据版本。"
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
            duration_seconds: 3600,
            time_step_seconds: 10,
            output_interval_seconds: 60,
          }}
          onValuesChange={() => setPreview(undefined)}
          onFinish={(values) => void submit(values)}
        >
          <Row gutter={16}>
            <Col xs={24} md={12}>
              <Form.Item name="case_id" label="计算方案" rules={[{ required: true, message: '请选择计算方案' }]}>
                <Select
                  loading={loadingCases}
                  options={cases.map((item) => ({ value: item.id, label: `${item.name} · #${item.id}` }))}
                />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item name="duration_seconds" label="模拟时长（s）" rules={[{ required: true }]}>
                <InputNumber min={1} precision={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
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
