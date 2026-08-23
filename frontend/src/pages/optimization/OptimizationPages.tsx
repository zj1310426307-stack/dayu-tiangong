import {
  AreaChartOutlined,
  ExperimentOutlined,
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
  Input,
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
import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  cancelOptimizationTask,
  createOptimizationTask,
  explainOptimizationRecommendation,
  getOptimizationCandidates,
  getOptimizationPareto,
  getOptimizationRecommendation,
  getOptimizationTask,
  getSimulationCases,
  listOptimizationTasks,
  runOptimizationTask,
  type OptimizationCandidateRecord,
  type OptimizationExplanation,
  type OptimizationTaskRecord,
  type ParetoCandidateRecord,
  type RecommendationResponse,
} from '../../api/generated/client';
import { datasetVersionStatusLabel, useDatasetVersion } from '../../context/DatasetVersionContext';

const { Paragraph, Title } = Typography;

function OptimizationHeader({ title, description, action }: { title: string; description: string; action?: React.ReactNode }) {
  return (
    <header className="data-page__header">
      <div>
        <span className="hero-kicker"><i /> MULTI-OBJECTIVE / PSO</span>
        <Title level={1}>{title}</Title>
        <Paragraph>{description}</Paragraph>
      </div>
      {action}
    </header>
  );
}

function statusTag(status: OptimizationTaskRecord['status']) {
  const colors = { pending: 'default', running: 'processing', success: 'success', failed: 'error', cancelled: 'default' } as const;
  const labels = { pending: '待运行', running: '优化中', success: '成功', failed: '失败', cancelled: '已取消' } as const;
  return <Tag color={colors[status]}>{labels[status]}</Tag>;
}

function metric(candidate: ParetoCandidateRecord | OptimizationCandidateRecord, key: string): number {
  return Number(candidate.metrics?.[key] ?? 0);
}

function objective(candidate: ParetoCandidateRecord, key: string): number {
  const values = candidate.objective_values?.values as Record<string, unknown> | undefined;
  return Number(values?.[key] ?? 0);
}

export function OptimizationHomePage() {
  const navigate = useNavigate();
  const { versions, datasetVersionId, setDatasetVersionId } = useDatasetVersion();
  const [form] = Form.useForm();
  const [cases, setCases] = useState<Array<{ id: number; name: string; dataset_version_id: number }>>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!datasetVersionId) {
      setCases([]);
      return;
    }
    form.setFieldValue('dataset_version_id', datasetVersionId);
    form.setFieldValue('simulation_case_id', undefined);
    void getSimulationCases(datasetVersionId)
      .then((caseRows) => {
        setCases(caseRows);
        if (caseRows[0]) form.setFieldValue('simulation_case_id', caseRows[0].id);
        setError('');
      })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : '模型数据加载失败'));
  }, [datasetVersionId, form]);

  const create = async (values: Record<string, number | string>) => {
    setSubmitting(true);
    setError('');
    try {
      const created = await createOptimizationTask({
        name: String(values.name),
        dataset_version_id: Number(values.dataset_version_id),
        simulation_case_id: Number(values.simulation_case_id),
        objective_config: {
          version: 'dayu.objectives.v1',
          weights: {
            flood_risk: Number(values.flood_risk),
            energy_cost: Number(values.energy_cost),
            operation_cost: Number(values.operation_cost),
          },
          warning_level: values.warning_level ? Number(values.warning_level) : null,
          guarantee_level: values.guarantee_level ? Number(values.guarantee_level) : null,
        },
        algorithm_config: {
          particle_count: Number(values.particle_count),
          max_iterations: Number(values.max_iterations),
          duration_seconds: Number(values.duration_seconds),
          time_step_seconds: 10,
          output_interval_seconds: 60,
        },
      });
      await runOptimizationTask(created.id);
      message.success(`优化任务 #${created.id} 已进入异步队列`);
      navigate(`/optimization/tasks/${created.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '优化任务创建失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="data-page optimization-page">
      <OptimizationHeader
        title="多目标调度优化"
        description="自动生成完整闸泵调度候选，经 Phase 4 水动力仿真、硬约束检查与 Pareto 排序后交由人工复核。"
        action={<Button onClick={() => navigate('/optimization/tasks')}>任务列表</Button>}
      />
      <Alert className="dispatch-notice" showIcon type="warning" icon={<SafetyCertificateOutlined />} message="仅生成仿真推荐，不连接 PLC / SCADA，不向真实设备下发命令。" />
      {error && <Alert className="data-alert" type="error" showIcon message={error} />}
      <Card className="data-card optimization-config-card" title="PSO 任务配置">
        <Form form={form} layout="vertical" initialValues={{ name: `联合调度优化-${new Date().toLocaleDateString()}`, flood_risk: 0.5, energy_cost: 0.3, operation_cost: 0.2, particle_count: 4, max_iterations: 3, duration_seconds: 600 }} onFinish={(values) => void create(values)}>
          <Row gutter={16}>
            <Col xs={24} md={8}><Form.Item name="name" label="任务名称" rules={[{ required: true }]}><Input /></Form.Item></Col>
            <Col xs={12} md={8}><Form.Item name="dataset_version_id" label="数据版本" rules={[{ required: true }]}><Select onChange={setDatasetVersionId} options={versions.map((item) => ({ value: item.id, label: `${item.name} · #${item.id} · ${datasetVersionStatusLabel(item.status)}` }))} /></Form.Item></Col>
            <Col xs={12} md={8}><Form.Item name="simulation_case_id" label="计算方案" rules={[{ required: true }]}><Select options={cases.map((item) => ({ value: item.id, label: `${item.name} · #${item.id}` }))} /></Form.Item></Col>
          </Row>
          <Row gutter={16}>
            <Col xs={8} md={4}><Form.Item name="flood_risk" label="防洪 W1"><InputNumber min={0} step={0.1} style={{ width: '100%' }} /></Form.Item></Col>
            <Col xs={8} md={4}><Form.Item name="energy_cost" label="能耗 W2"><InputNumber min={0} step={0.1} style={{ width: '100%' }} /></Form.Item></Col>
            <Col xs={8} md={4}><Form.Item name="operation_cost" label="操作 W3"><InputNumber min={0} step={0.1} style={{ width: '100%' }} /></Form.Item></Col>
            <Col xs={12} md={4}><Form.Item name="warning_level" label="警戒水位（m）"><InputNumber style={{ width: '100%' }} /></Form.Item></Col>
            <Col xs={12} md={4}><Form.Item name="guarantee_level" label="保证水位（m）"><InputNumber style={{ width: '100%' }} /></Form.Item></Col>
          </Row>
          <Row gutter={16}>
            <Col xs={8} md={6}><Form.Item name="particle_count" label="粒子数"><InputNumber min={2} max={40} precision={0} style={{ width: '100%' }} /></Form.Item></Col>
            <Col xs={8} md={6}><Form.Item name="max_iterations" label="迭代数"><InputNumber min={1} max={25} precision={0} style={{ width: '100%' }} /></Form.Item></Col>
            <Col xs={8} md={6}><Form.Item name="duration_seconds" label="仿真时长（s）"><InputNumber min={60} precision={0} style={{ width: '100%' }} /></Form.Item></Col>
          </Row>
          <Button type="primary" size="large" icon={<PlayCircleOutlined />} htmlType="submit" loading={submitting} disabled={!datasetVersionId || cases.length === 0}>创建并运行优化</Button>
        </Form>
      </Card>
    </div>
  );
}

export function OptimizationTasksPage() {
  const navigate = useNavigate();
  const { datasetVersionId } = useDatasetVersion();
  const [tasks, setTasks] = useState<OptimizationTaskRecord[]>([]);
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
    try {
      const nextTasks = await listOptimizationTasks({ dataset_version_id: datasetVersionId });
      if (requestSequence === requestSequenceRef.current) {
        setTasks(nextTasks);
        setError('');
      }
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
  useEffect(() => { void reload(); const timer = window.setInterval(() => void reload(), 4000); return () => window.clearInterval(timer); }, [reload]);
  const columns: ColumnsType<OptimizationTaskRecord> = [
    { title: '任务', dataIndex: 'id', width: 80, render: (value: number) => `#${value}` },
    { title: '名称', dataIndex: 'name', ellipsis: true },
    { title: '算法', dataIndex: 'algorithm', width: 80, render: () => <Tag color="cyan">PSO</Tag> },
    { title: '状态', dataIndex: 'status', width: 100, render: statusTag },
    { title: '进度', dataIndex: 'progress', width: 170, render: (value: number) => <Progress size="small" percent={value} /> },
    { title: '迭代', dataIndex: 'current_generation', width: 80 },
    { title: '候选', dataIndex: 'candidate_count', width: 80 },
    { title: '最佳分', dataIndex: 'best_score', width: 110, render: (value: number | null) => value === null ? '—' : value.toFixed(5) },
    { title: '操作', width: 170, render: (_, task) => <Space><Button size="small" onClick={() => navigate(`/optimization/tasks/${task.id}`)}>详情</Button>{task.status === 'running' && <Button size="small" danger onClick={async () => { await cancelOptimizationTask(task.id); await reload(); }}>取消</Button>}</Space> },
  ];
  return <div className="data-page optimization-page"><OptimizationHeader title="优化任务监控" description="跟踪迭代进度、当前最优分、候选数量与最终 Pareto 前沿。" action={<Space><Button type="primary" onClick={() => navigate('/optimization')}>新建优化</Button><Button icon={<ReloadOutlined />} onClick={() => void reload()} /></Space>} />{error && <Alert className="data-alert" type="error" showIcon message={error} />}<Card className="data-card"><Table rowKey="id" loading={loading} dataSource={tasks} columns={columns} scroll={{ x: 1050 }} /></Card></div>;
}

function ParetoChart({ items }: { items: ParetoCandidateRecord[] }) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!element.current) return undefined;
    const container = element.current;
    let cancelled = false;
    let dispose: (() => void) | undefined;
    void import('echarts').then((echarts) => {
      if (cancelled) return;
      echarts.getInstanceByDom(container)?.dispose();
      const chart = echarts.init(container);
      chart.setOption({
        tooltip: { formatter: (params: { data: [number, number, number, number] }) => `候选 #${params.data[3]}<br/>防洪 ${params.data[0].toFixed(4)}<br/>能耗 ${params.data[1].toFixed(4)}<br/>操作 ${params.data[2].toFixed(4)}` },
        grid: { left: 62, right: 28, top: 24, bottom: 55 },
        xAxis: { name: '防洪风险', nameLocation: 'middle', nameGap: 34, axisLabel: { color: '#7898aa' }, splitLine: { lineStyle: { color: 'rgba(100,151,183,.1)' } } },
        yAxis: { name: '能耗成本', axisLabel: { color: '#7898aa' }, splitLine: { lineStyle: { color: 'rgba(100,151,183,.1)' } } },
        visualMap: { min: 0, max: Math.max(...items.map((item) => objective(item, 'operation_cost')), 1), dimension: 2, orient: 'horizontal', left: 'center', bottom: 0, text: ['操作高', '操作低'], textStyle: { color: '#7898aa' }, inRange: { color: ['#2fe6d6', '#38a8ff', '#a291ff'] } },
        series: [{ type: 'scatter', symbolSize: 17, data: items.map((item) => [objective(item, 'flood_risk'), objective(item, 'energy_cost'), objective(item, 'operation_cost'), item.id]) }],
      });
      const resize = () => chart.resize(); window.addEventListener('resize', resize); dispose = () => { window.removeEventListener('resize', resize); chart.dispose(); };
    });
    return () => { cancelled = true; dispose?.(); };
  }, [items]);
  return <div ref={element} className="optimization-pareto-chart" />;
}

type CandidateSeries = {
  time?: number[];
  water_level?: number[];
  flow?: number[];
  gates?: Array<{ time_seconds?: number; actual_value?: number }>;
  pumps?: Array<{ time_seconds?: number; actual_value?: number }>;
};

function aggregateStructures(rows: CandidateSeries['gates']): { time: number[]; value: number[] } {
  const grouped = new Map<number, number[]>();
  for (const row of rows ?? []) {
    const time = Number(row.time_seconds ?? 0);
    grouped.set(time, [...(grouped.get(time) ?? []), Number(row.actual_value ?? 0)]);
  }
  const time = [...grouped.keys()].sort((left, right) => left - right);
  return { time, value: time.map((item) => (grouped.get(item) ?? []).reduce((sum, value) => sum + value, 0)) };
}

function CandidateComparisonChart({ items }: { items: ParetoCandidateRecord[] }) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!element.current) return undefined;
    const container = element.current;
    let cancelled = false;
    let dispose: (() => void) | undefined;
    void import('echarts').then((echarts) => {
      if (cancelled) return;
      echarts.getInstanceByDom(container)?.dispose();
      const chart = echarts.init(container);
      const colors = ['#2fe6d6', '#38a8ff', '#a291ff', '#ffc85c'];
      const series = items.flatMap((item, index) => {
        const data = (item.metrics?.comparison_series ?? {}) as CandidateSeries;
        const gates = aggregateStructures(data.gates);
        const pumps = aggregateStructures(data.pumps);
        const color = colors[index % colors.length];
        return [
          { name: `#${item.id} 水位`, type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: (data.time ?? []).map((time, row) => [time, data.water_level?.[row] ?? null]), showSymbol: false, lineStyle: { color } },
          { name: `#${item.id} 流量`, type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: (data.time ?? []).map((time, row) => [time, data.flow?.[row] ?? null]), showSymbol: false, lineStyle: { color } },
          { name: `#${item.id} 闸门`, type: 'line', step: 'end', xAxisIndex: 2, yAxisIndex: 2, data: gates.time.map((time, row) => [time, gates.value[row]]), showSymbol: false, lineStyle: { color } },
          { name: `#${item.id} 泵站`, type: 'line', step: 'end', xAxisIndex: 3, yAxisIndex: 3, data: pumps.time.map((time, row) => [time, pumps.value[row]]), showSymbol: false, lineStyle: { color } },
        ];
      });
      chart.setOption({
        tooltip: { trigger: 'axis' },
        legend: { top: 0, textStyle: { color: '#7898aa' } },
        grid: [{ left: 56, right: '53%', top: 55, height: 180 }, { left: '53%', right: 25, top: 55, height: 180 }, { left: 56, right: '53%', top: 285, height: 180 }, { left: '53%', right: 25, top: 285, height: 180 }],
        xAxis: [0, 1, 2, 3].map((gridIndex) => ({ type: 'value', gridIndex, name: 't / s', axisLabel: { color: '#648397' }, splitLine: { lineStyle: { color: 'rgba(100,151,183,.1)' } } })),
        yAxis: [
          { type: 'value', gridIndex: 0, name: '水位 / m' },
          { type: 'value', gridIndex: 1, name: '流量 / m³/s' },
          { type: 'value', gridIndex: 2, name: '闸门总开度 / m' },
          { type: 'value', gridIndex: 3, name: '泵站总机组数' },
        ].map((axis) => ({ ...axis, nameTextStyle: { color: '#7898aa' }, axisLabel: { color: '#648397' }, splitLine: { lineStyle: { color: 'rgba(100,151,183,.1)' } } })),
        series,
      });
      const resize = () => chart.resize(); window.addEventListener('resize', resize); dispose = () => { window.removeEventListener('resize', resize); chart.dispose(); };
    });
    return () => { cancelled = true; dispose?.(); };
  }, [items]);
  return <div ref={element} className="optimization-comparison-chart" />;
}

export function OptimizationTaskDetailPage() {
  const navigate = useNavigate();
  const taskId = Number(useParams().taskId);
  const { datasetVersionId } = useDatasetVersion();
  const [task, setTask] = useState<OptimizationTaskRecord>();
  const [candidates, setCandidates] = useState<OptimizationCandidateRecord[]>([]);
  const [pareto, setPareto] = useState<ParetoCandidateRecord[]>([]);
  const [recommendation, setRecommendation] = useState<RecommendationResponse>();
  const [explanation, setExplanation] = useState<OptimizationExplanation>();
  const [error, setError] = useState('');
  const requestSequenceRef = useRef(0);
  const reload = useCallback(async () => {
    const requestSequence = ++requestSequenceRef.current;
    if (!datasetVersionId) return;
    try {
      const nextTask = await getOptimizationTask(taskId);
      if (nextTask.dataset_version_id !== datasetVersionId) {
        if (requestSequence === requestSequenceRef.current) {
          setTask(undefined);
          setCandidates([]);
          setPareto([]);
          setRecommendation(undefined);
          setExplanation(undefined);
          setError('当前优化任务不属于所选数据版本');
        }
        return;
      }
      const nextCandidates = await getOptimizationCandidates(taskId);
      let nextPareto: ParetoCandidateRecord[] = [];
      let nextRecommendation: RecommendationResponse | undefined;
      let nextExplanation: OptimizationExplanation | undefined;
      if (nextTask.status === 'success') {
        const [front, recommended, explained] = await Promise.all([getOptimizationPareto(taskId), getOptimizationRecommendation(taskId), explainOptimizationRecommendation(taskId)]);
        nextPareto = front;
        nextRecommendation = recommended;
        nextExplanation = explained;
      }
      if (requestSequence !== requestSequenceRef.current) return;
      setTask(nextTask);
      setCandidates(nextCandidates);
      setPareto(nextPareto);
      setRecommendation(nextRecommendation);
      setExplanation(nextExplanation);
      setError('');
    } catch (reason) {
      if (requestSequence === requestSequenceRef.current) {
        setError(reason instanceof Error ? reason.message : '优化详情加载失败');
      }
    }
  }, [datasetVersionId, taskId]);
  useEffect(() => {
    requestSequenceRef.current += 1;
    setTask(undefined);
    setCandidates([]);
    setPareto([]);
    setRecommendation(undefined);
    setExplanation(undefined);
    setError('');
  }, [datasetVersionId, taskId]);
  useEffect(() => { void reload(); const timer = window.setInterval(() => void reload(), 4000); return () => window.clearInterval(timer); }, [reload]);
  const bestByGeneration = [...new Set(candidates.map((item) => item.generation))].map((generation) => ({ generation, score: Math.min(...candidates.filter((item) => item.generation === generation).map((item) => item.score ?? Number.POSITIVE_INFINITY)) }));
  const recommendationCandidate = recommendation?.candidate;
  const columns: ColumnsType<OptimizationCandidateRecord> = [
    { title: '候选', dataIndex: 'id', width: 80, render: (value: number) => `#${value}` },
    { title: '代 / 粒子', width: 100, render: (_, item) => `${item.generation} / ${item.candidate_index}` },
    { title: '总分', dataIndex: 'score', width: 110, render: (value: number | null) => value === null ? '—' : value.toFixed(5) },
    { title: '约束', dataIndex: 'valid', width: 90, render: (value: boolean) => value ? <Tag color="success">有效</Tag> : <Tag color="error">无效</Tag> },
    { title: '最大水位', width: 110, render: (_, item) => metric(item, 'network_maximum_water_level').toFixed(3) },
    { title: '能耗 kWh', width: 110, render: (_, item) => metric(item, 'pump_total_energy_kwh').toFixed(2) },
    { title: '闸门动作', width: 90, render: (_, item) => metric(item, 'gate_action_count') },
    { title: '仿真任务', dataIndex: 'simulation_task_id', width: 100, render: (value: number | null) => value ? `#${value}` : '—' },
  ];
  return (
    <div className="data-page optimization-page">
      <OptimizationHeader title={task?.name ?? `优化任务 #${taskId}`} description="候选 → Phase 4 仿真 → 目标评分 → Pareto 分层 → 人工推荐。" action={<Space><Button onClick={() => navigate('/optimization/tasks')}>返回任务</Button><Button icon={<ReloadOutlined />} onClick={() => void reload()} /></Space>} />
      {error && <Alert className="data-alert" type="error" showIcon message={error} />}
      {task && <><Row gutter={16} className="optimization-stats"><Col xs={12} md={6}><Card className="data-card"><Statistic prefix={<ExperimentOutlined />} title="状态" value={task.status} formatter={() => statusTag(task.status)} /></Card></Col><Col xs={12} md={6}><Card className="data-card"><Statistic title="当前迭代" value={task.current_generation} /></Card></Col><Col xs={12} md={6}><Card className="data-card"><Statistic title="候选数量" value={task.candidate_count} /></Card></Col><Col xs={12} md={6}><Card className="data-card"><Statistic title="当前最佳分" value={task.best_score ?? 0} precision={5} /></Card></Col></Row><Card className="data-card" title="收敛监控" extra={<Tag>{task.algorithm_version}</Tag>}><Progress percent={task.progress} status={task.status === 'failed' ? 'exception' : task.status === 'success' ? 'success' : 'active'} /><div className="optimization-convergence">{bestByGeneration.map((item) => <span key={item.generation}>第 {item.generation} 代 <strong>{Number.isFinite(item.score) ? item.score.toFixed(5) : '—'}</strong></span>)}</div><Descriptions size="small" column={{ xs: 1, md: 2 }} items={[{ key: 'hash', label: '输入快照', children: <code>{task.input_snapshot_hash}</code> }, { key: 'converged', label: '收敛条件', children: task.converged ? '提前收敛' : '达到迭代上限或仍在运行' }]} /></Card></>}
      {recommendationCandidate && <Alert className="optimization-recommendation" type="success" showIcon icon={<AreaChartOutlined />} message={`推荐候选 #${recommendationCandidate.id} · 总分 ${recommendationCandidate.score?.toFixed(5)}`} description={<><p>{explanation?.summary}</p><Space wrap>{explanation?.factors.map((item) => <Tag key={item}>{item}</Tag>)}</Space><p><strong>仅供人工复核：</strong>{recommendation?.notice}</p></>} />}
      {pareto.length > 0 && <Row gutter={16}><Col xs={24} lg={14}><Card className="data-card" title="Pareto 前沿 · 防洪风险 × 能耗成本" extra={<Tag color="cyan">颜色 = 操作成本</Tag>}><ParetoChart items={pareto} /></Card></Col><Col xs={24} lg={10}><Card className="data-card" title="方案对比"><Table rowKey="id" size="small" pagination={false} dataSource={pareto} scroll={{ x: 600 }} columns={[{ title: '方案', dataIndex: 'id', render: (value: number) => `#${value}` }, { title: '最高水位', render: (_, item) => metric(item, 'network_maximum_water_level').toFixed(2) }, { title: '最大流量', render: (_, item) => metric(item, 'network_maximum_flow').toFixed(1) }, { title: '能耗', render: (_, item) => metric(item, 'pump_total_energy_kwh').toFixed(1) }, { title: '闸动作', render: (_, item) => metric(item, 'gate_action_count') }, { title: '泵启停', render: (_, item) => `${metric(item, 'pump_start_count')}/${metric(item, 'pump_stop_count')}` }]} /></Card></Col></Row>}
      {pareto.some((item) => item.metrics?.comparison_series) && <Card className="data-card" title="候选时序对比 · 水位 / 流量 / 闸门 / 泵站"><CandidateComparisonChart items={pareto.slice(0, 4)} /></Card>}
      <Card className="data-card" title="全部候选及仿真链路"><Table rowKey="id" dataSource={candidates} columns={columns} scroll={{ x: 950 }} pagination={{ pageSize: 12 }} /></Card>
    </div>
  );
}
