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
  enqueueHydraulicTask,
  getHydraulicResult,
  getSimulationCases,
  listHydraulicTasks,
  retryHydraulicTask,
  type SimulationResultResponse,
  type SimulationTaskCreate,
  type SimulationTaskRecord,
} from '../../api/generated/client';
import { useDatasetVersion } from '../../context/DatasetVersionContext';

const { Paragraph, Text, Title } = Typography;

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
  const [cases, setCases] = useState<Array<{ id: number; name: string }>>([]);
  const [loadingCases, setLoadingCases] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!datasetVersionId) {
      setCases([]);
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
  }, [datasetVersionId, form]);

  const submit = async (values: SimulationTaskCreate) => {
    setSubmitting(true);
    setError('');
    try {
      const created = await createHydraulicTask({ ...values, input_schema_version: 'dayu.model-input.v3' });
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
              <Form.Item name="time_step_seconds" label="请求步长（s）" rules={[{ required: true }]}>
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
          </Row>
          <Row gutter={16}>
            <Col xs={12} md={6}>
              <Form.Item name="minimum_depth" label="最小水深（m）" rules={[{ required: true }]}>
                <InputNumber min={0.001} step={0.01} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Button
            type="primary"
            size="large"
            icon={<PlayCircleOutlined />}
            htmlType="submit"
            loading={submitting}
            disabled={!datasetVersionId || cases.length === 0}
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
  const [tasks, setTasks] = useState<SimulationTaskRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const reload = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setTasks(await listHydraulicTasks());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '任务列表加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

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
    { title: '状态', dataIndex: 'status', width: 110, render: statusTag },
    { title: '进度', dataIndex: 'progress', width: 180, render: (value: number) => <Progress percent={value} size="small" /> },
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
          {['failed', 'cancelled'].includes(task.status) && <Button size="small" onClick={async () => { await retryHydraulicTask(task.id); await reload(); }}>重试</Button>}
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
        <Table rowKey="id" loading={loading} dataSource={tasks} columns={columns} pagination={{ pageSize: 12 }} scroll={{ x: 980 }} />
      </Card>
    </div>
  );
}

function HydraulicResultChart({ result }: { result?: SimulationResultResponse }) {
  const element = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!element.current || !result) return undefined;
    let dispose: (() => void) | undefined;
    void import('echarts').then((echarts) => {
      if (!element.current) return;
      const chart = echarts.init(element.current);
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
    return () => dispose?.();
  }, [result]);

  return <div ref={element} className="hydraulic-result-chart" />;
}

export function HydraulicResultsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<SimulationTaskRecord[]>([]);
  const [result, setResult] = useState<SimulationResultResponse>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const taskId = Number(searchParams.get('taskId') || 0);
  const sectionId = Number(searchParams.get('sectionId') || 0);

  useEffect(() => {
    void listHydraulicTasks()
      .then((items) => {
        const successful = items.filter((item) => item.status === 'success');
        setTasks(successful);
        if (!taskId && successful[0]) {
          const next = new URLSearchParams(searchParams);
          next.set('taskId', String(successful[0].id));
          setSearchParams(next, { replace: true });
        }
      })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : '任务加载失败'));
  }, [searchParams, setSearchParams, taskId]);

  useEffect(() => {
    if (!taskId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError('');
    void getHydraulicResult(taskId, sectionId || undefined)
      .then(setResult)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : '结果加载失败'))
      .finally(() => setLoading(false));
  }, [sectionId, taskId]);

  const selectedTask = useMemo(() => tasks.find((item) => item.id === taskId), [taskId, tasks]);
  const latestValues = result ? {
    stage: result.water_level.at(-1), flow: result.flow.at(-1), velocity: result.velocity.at(-1),
  } : undefined;

  const changeTask = (value: number) => {
    const next = new URLSearchParams();
    next.set('taskId', String(value));
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
                <Select className="hydraulic-select" value={result?.section_id ?? undefined} onChange={changeSection} options={result?.available_sections.filter((item) => item.section_id !== null).map((item) => ({ value: item.section_id as number, label: `${item.section_code} · ${item.station.toFixed(1)} m` })) ?? []} />
              </Col>
              <Col xs={24} md={8}>
                <Descriptions size="small" column={1} items={[
                  { key: 'status', label: '状态', children: selectedTask ? statusTag(selectedTask.status) : <Tag>—</Tag> },
                  { key: 'section', label: '当前断面', children: result?.section_code ?? '—' },
                ]} />
              </Col>
            </Row>
          </Card>
          {result && (
            <>
              <Row gutter={16} className="hydraulic-stats">
                <Col xs={24} md={8}><Card className="data-card"><Statistic prefix={<CheckCircleOutlined />} title="末时刻水位" value={latestValues?.stage} precision={3} suffix="m" /></Card></Col>
                <Col xs={24} md={8}><Card className="data-card"><Statistic title="末时刻流量" value={latestValues?.flow} precision={3} suffix="m³/s" /></Card></Col>
                <Col xs={24} md={8}><Card className="data-card"><Statistic title="末时刻流速" value={latestValues?.velocity} precision={3} suffix="m/s" /></Card></Col>
              </Row>
              <Card className="data-card" title={`${result.section_code} · 时序曲线`} extra={<Tag color="cyan">{result.time.length} 个输出时刻</Tag>}>
                <HydraulicResultChart result={result} />
              </Card>
              <Card className="data-card" title="稳定性诊断">
                <pre className="hydraulic-diagnostics">{JSON.stringify(result.diagnostics, null, 2)}</pre>
              </Card>
            </>
          )}
        </>
      )}
    </div>
  );
}
