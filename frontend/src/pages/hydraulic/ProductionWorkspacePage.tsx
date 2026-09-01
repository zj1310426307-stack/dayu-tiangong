import {
  AimOutlined,
  CheckCircleOutlined,
  CloudUploadOutlined,
  DownloadOutlined,
  ExperimentOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons';
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Input,
  Radio,
  Row,
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
import * as echarts from 'echarts';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  compareProductionExternal,
  commitProductionCalibrationRun,
  commitProductionProduct,
  commitProductionValidationRun,
  createProductionCalibrationSweep,
  createProductionRun,
  evaluateProductionAcceptance,
  evaluateProductionIndependence,
  evaluateProductionMetrics,
  evaluateProductionQA,
  exportProductionProductsCsv,
  exportProductionProductsGeojson,
  exportProductionProductsXlsx,
  generateProductionProducts,
  getProductionCapabilities,
  importProductionExternal,
  importProductionObservation,
  enqueueHydraulicTask,
  listProductionRuns,
  planProductionCalibration,
  previewProductionExternal,
  previewProductionSeries,
  promoteProductionCalibration,
  approveProductionRun,
  type AcceptanceEvaluation,
  type AcceptanceEvaluationRequest,
  type CalibrationPromotionRequest,
  type CalibrationRunCommitRequest,
  type CalibrationRunRecord,
  type CalibrationSweepCreateRequest,
  type ExternalComparisonRequest,
  type ExternalComparisonResult,
  type ExternalResultImportOptions,
  type HydraulicMetrics,
  type HydraulicModelQARequest,
  type HydraulicModelQAResult,
  type MetricEvaluationRequest,
  type ParameterSweepPlan,
  type ParameterSweepRequest,
  type ProductionApprovalRequest,
  type ProductionCapabilityResponse,
  type ProductionRunRecord,
  type ProductionTaskCreateRequest,
  type ResultProductBundle,
  type ResultProductCommitRequest,
  type ResultProductRecord,
  type ResultProductRequest,
  type TimeSeriesImportOptions,
  type ValidationIndependenceRequest,
  type ValidationIndependenceResult,
  type ValidationRunCommitRequest,
  type ProductionValidationRunRecord,
} from '../../api/generated/client';
import { useDatasetVersion } from '../../context/DatasetVersionContext';


const { Paragraph, Text, Title } = Typography;

const qaTemplate = JSON.stringify({
  engineering_crs: 'EPSG:4547', horizontal_unit: 'm', vertical_datum: 'REPLACE_WITH_CONFIRMED_DATUM',
  simulation_duration_seconds: 3600, branches: [], cross_sections: [], boundaries: [],
  observations: [], structures: [],
}, null, 2);
const sweepTemplate = JSON.stringify({
  parameters: [{ group_id: 'REVIEWED_GROUP', parameter: 'manning_n', target_ids: ['SECTION_ID'], values: [0.025, 0.03] }],
  max_runs: 20,
}, null, 2);
const sweepRunTemplate = JSON.stringify({
  run_code: 'REPLACE', production_run_id: 0, actor: 'REPLACE',
  dataset: { dataset_id: 'REPLACE', event_id: 'REPLACE', station_ids: ['REPLACE'], start_time: '2026-01-01T00:00:00+08:00', end_time: '2026-01-02T00:00:00+08:00', role: 'calibration', holdout_type: 'independent_event' },
  sweep: JSON.parse(sweepTemplate),
  objective: { mode: 'water-level-focused', weights: { 'water_level.rmse': 1 } },
  metric_evidence: [{ observation_series_id: 0, cross_section_id: 0, maximum_chainage_distance_m: 0, alignment: { method: 'exact', tolerance_seconds: 0, minimum_valid_samples: 3, minimum_coverage_ratio: 0.5 } }],
}, null, 2);
const calibrationCommitTemplate = JSON.stringify({
  run_code: 'REPLACE', calibration_run_id: 0, production_run_id: 0, dataset_version_id: 0, case_id: 0, actor: 'REPLACE',
  dataset: { dataset_id: 'REPLACE', event_id: 'REPLACE', station_ids: ['REPLACE'], start_time: '2026-01-01T00:00:00+08:00', end_time: '2026-01-02T00:00:00+08:00', role: 'calibration', holdout_type: 'independent_event' },
  sweep: JSON.parse(sweepTemplate), objective: { mode: 'water-level-focused', weights: { 'water_level.rmse': 1 } },
  metric_evidence: [{ observation_series_id: 0, cross_section_id: 0, maximum_chainage_distance_m: 0, alignment: { method: 'exact', tolerance_seconds: 0, minimum_valid_samples: 3, minimum_coverage_ratio: 0.5 } }], candidates: [],
}, null, 2);
const promotionTemplate = JSON.stringify({
  calibration_run_id: 0, candidate_id: 'REPLACE', accepted_by: 'REPLACE', acceptance_reason: 'REPLACE_WITH_REVIEWED_REASON',
  acceptance_criteria: { maximum_water_level_rmse: null, maximum_discharge_rmse: null, minimum_observation_coverage: 0.5 },
}, null, 2);
const seriesTemplate = JSON.stringify({
  observed: { series_id: 'OBS', variable: 'water_level', unit: 'm', samples: [], source: 'REPLACE_WITH_SOURCE', vertical_datum: 'REPLACE' },
  simulated: { series_id: 'SIM', variable: 'water_level', unit: 'm', samples: [], source: 'DAYU_TASK', vertical_datum: 'REPLACE' },
  alignment: { method: 'exact', tolerance_seconds: 0, minimum_valid_samples: 3, minimum_coverage_ratio: 0.5 },
}, null, 2);
const independenceTemplate = JSON.stringify({ calibration: {}, validation: {} }, null, 2);
const acceptanceTemplate = JSON.stringify({ metrics: [], criteria: {}, independence: { independent: false, temporal_holdout: false, issues: [] } }, null, 2);
const validationCommitTemplate = JSON.stringify({
  validation_code: 'REPLACE', production_run_id: 0, dataset_version_id: 0, case_id: 0, calibration_run_id: 0, actor: 'REPLACE',
  calibration_dataset: {}, validation_dataset: {}, criteria: {},
  metric_evidence: [{ observation_series_id: 0, cross_section_id: 0, maximum_chainage_distance_m: 0, alignment: { method: 'exact', tolerance_seconds: 0, minimum_valid_samples: 3, minimum_coverage_ratio: 0.5 } }], mass_balance_relative_error: null,
}, null, 2);
const approvalTemplate = JSON.stringify({ run_id: 0, approved_by: 'REPLACE', approval_reason: 'REPLACE_WITH_PROFESSIONAL_SIGN_OFF' }, null, 2);
const compareTemplate = JSON.stringify({ dayu_series: [], external_series: [], alignment: { method: 'exact', tolerance_seconds: 0, minimum_valid_samples: 3, minimum_coverage_ratio: 0.5 } }, null, 2);
const resultTemplate = JSON.stringify({ project_id: 'REPLACE', model_version: 'REPLACE', project_scenario_id: 'REPLACE', afflux_threshold_m: 0.01, points: [] }, null, 2);
const resultCommitTemplate = JSON.stringify({ production_run_id: 0, product_code: 'REPLACE', actor: 'REPLACE', request: JSON.parse(resultTemplate) }, null, 2);
const runTemplate = JSON.stringify({
  run_code: 'REPLACE', qa_run_code: 'REPLACE', actor: 'REPLACE',
  task: { case_id: 0, duration_seconds: 3600, time_step_seconds: 10, output_interval_seconds: 60, engine: 'mascaret', input_schema_version: 'dayu.hydraulic-1d.input.v1', storage_level: 'full', roughness_overrides: [] },
  qa: JSON.parse(qaTemplate),
}, null, 2);
const observationImportTemplate = JSON.stringify({
  series_kind: 'observation', series_id: 'OBS-H-01', variable: 'water_level', unit: 'm', source: 'REPLACE_WITH_SOURCE',
  branch_id: 'REPLACE', chainage_m: 0, station_id: 'REPLACE', vertical_datum: 'REPLACE', time_basis: 'relative',
  column_mapping: { time: 'time', value: 'value', quality_flag: 'quality' },
}, null, 2);
const externalImportTemplate = JSON.stringify({
  external_model_name: 'MIKE11', external_model_version: 'UNKNOWN', scenario: 'REPLACE', vertical_datum: 'REPLACE', time_basis: 'relative',
  column_mapping: { branch: 'Branch', chainage: 'Chainage', time: 'Time', water_level: 'H', discharge: 'Q' },
  branch_mappings: [{ external_branch: 'REPLACE', dayu_branch: 'REPLACE', chainage_scale: 1, chainage_offset_m: 0, direction: 'same', external_origin_m: 0 }],
}, null, 2);

function parseJson<T>(value: string, label: string): T {
  try { return JSON.parse(value) as T; }
  catch { throw new Error(`${label}不是有效 JSON`); }
}

function JsonEditor({ value, onChange, rows = 14 }: { value: string; onChange: (value: string) => void; rows?: number }) {
  return <Input.TextArea className="production-json" value={value} rows={rows} onChange={(event) => onChange(event.target.value)} spellCheck={false} />;
}

function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = filename; anchor.click();
  URL.revokeObjectURL(url);
}

function ProductionChart({ rows, title }: { rows: Array<Record<string, unknown>>; title: string }) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!host.current) return undefined;
    const chart = echarts.init(host.current);
    const time = rows.map((row) => Number(row.time_seconds));
    const dayu = rows.map((row) => row.dayu_value ?? row.simulated_value ?? null);
    const reference = rows.map((row) => row.external_value ?? row.observed_value ?? null);
    chart.setOption({
      backgroundColor: 'transparent',
      title: { text: title, textStyle: { color: '#d9f7f4', fontSize: 14 } },
      tooltip: { trigger: 'axis' }, legend: { textStyle: { color: '#86a8ba' } },
      xAxis: { type: 'category', name: 't (s)', data: time, axisLabel: { color: '#86a8ba' } },
      yAxis: { type: 'value', axisLabel: { color: '#86a8ba' }, splitLine: { lineStyle: { color: 'rgba(134,168,186,.15)' } } },
      series: [
        { name: 'Dayu / Simulated', type: 'line', showSymbol: false, data: dayu },
        { name: 'Observed / External', type: 'line', showSymbol: false, data: reference },
      ],
    });
    const resize = () => chart.resize();
    window.addEventListener('resize', resize);
    return () => { window.removeEventListener('resize', resize); chart.dispose(); };
  }, [rows, title]);
  return <div className="production-chart" ref={host} />;
}

function DataTab({ capabilities }: { capabilities?: ProductionCapabilityResponse }) {
  const { datasetVersionId } = useDatasetVersion();
  const [kind, setKind] = useState<'observation' | 'external'>('observation');
  const [options, setOptions] = useState(observationImportTemplate);
  const [file, setFile] = useState<File>();
  const [actor, setActor] = useState('');
  const [resultCode, setResultCode] = useState('');
  const [preview, setPreview] = useState<Record<string, unknown>>();
  const [busy, setBusy] = useState(false);

  const changeKind = (value: 'observation' | 'external') => {
    setKind(value); setOptions(value === 'observation' ? observationImportTemplate : externalImportTemplate); setPreview(undefined);
  };
  const runPreview = async () => {
    if (!file) return message.warning('请先选择 CSV 或 XLSX 文件');
    setBusy(true);
    try {
      const value = kind === 'observation'
        ? await previewProductionSeries(parseJson<TimeSeriesImportOptions>(options, '导入映射'), file)
        : await previewProductionExternal(parseJson<ExternalResultImportOptions>(options, '导入映射'), file);
      setPreview(value as unknown as Record<string, unknown>); message.success('预览完成，尚未写入数据库');
    } catch (reason) { message.error(reason instanceof Error ? reason.message : '预览失败'); }
    finally { setBusy(false); }
  };
  const commit = async () => {
    if (!file || !datasetVersionId || !actor.trim() || !preview) return message.warning('需完成预览并填写数据版本与操作人');
    setBusy(true);
    try {
      if (kind === 'observation') await importProductionObservation(datasetVersionId, actor.trim(), parseJson<TimeSeriesImportOptions>(options, '导入映射'), file);
      else {
        if (!resultCode.trim()) throw new Error('外部结果需要 result code');
        await importProductionExternal(datasetVersionId, resultCode.trim(), actor.trim(), parseJson<ExternalResultImportOptions>(options, '导入映射'), file);
      }
      message.success('完整文件及来源哈希已写入审计数据库');
    } catch (reason) { message.error(reason instanceof Error ? reason.message : '导入失败'); }
    finally { setBusy(false); }
  };
  const issues = Array.isArray(preview?.issues) ? preview.issues as Array<Record<string, unknown>> : [];
  return <Space direction="vertical" size="large" style={{ width: '100%' }}>
    <Alert type="warning" showIcon message="真实项目资料尚未进入受控工作区" description={capabilities?.real_project_reason ?? '本页只提供生产导入框架；预览数据不会自动成为工程验收证据。'} />
    <Card title="Preview → Issues → Import">
      <Space direction="vertical" style={{ width: '100%' }}>
        <Radio.Group value={kind} onChange={(event) => changeKind(event.target.value)} options={[{ label: '观测 H/Q', value: 'observation' }, { label: 'MIKE11 / 外部结果', value: 'external' }]} />
        <Upload.Dragger accept=".csv,.xlsx" maxCount={1} beforeUpload={(next) => { setFile(next); setPreview(undefined); return false; }} onRemove={() => { setFile(undefined); setPreview(undefined); }}>
          <p className="ant-upload-drag-icon"><CloudUploadOutlined /></p><p>选择合法导出的 CSV / XLSX；先预览，不会立即写库</p>
        </Upload.Dragger>
        <JsonEditor value={options} onChange={setOptions} rows={12} />
        <Row gutter={12}>
          <Col span={kind === 'external' ? 8 : 12}><Input value={actor} onChange={(event) => setActor(event.target.value)} placeholder="操作人 / 审核人标识" /></Col>
          {kind === 'external' && <Col span={8}><Input value={resultCode} onChange={(event) => setResultCode(event.target.value)} placeholder="外部结果 code" /></Col>}
          <Col span={kind === 'external' ? 8 : 12}><Space><Button loading={busy} onClick={() => void runPreview()}>1. Preview</Button><Button type="primary" disabled={!preview} loading={busy} onClick={() => void commit()}>3. Import</Button></Space></Col>
        </Row>
      </Space>
    </Card>
    {preview && <Card title={`2. Issues · ${String(preview.row_count ?? 0)} rows`}><Table size="small" pagination={false} rowKey={(_, index) => String(index)} dataSource={issues} columns={[{ title: '级别', dataIndex: 'severity' }, { title: '代码', dataIndex: 'code' }, { title: '说明', dataIndex: 'message' }]} /><pre className="hydraulic-diagnostics">{JSON.stringify(preview, null, 2)}</pre></Card>}
  </Space>;
}

function QATab() {
  const navigate = useNavigate();
  const [input, setInput] = useState(qaTemplate);
  const [result, setResult] = useState<HydraulicModelQAResult>();
  const [busy, setBusy] = useState(false);
  const run = async () => { setBusy(true); try { setResult(await evaluateProductionQA(parseJson<HydraulicModelQARequest>(input, 'QA 输入'))); } catch (reason) { message.error(reason instanceof Error ? reason.message : 'QA 失败'); } finally { setBusy(false); } };
  return <Space direction="vertical" size="large" style={{ width: '100%' }}>
    <Alert type="info" showIcon message="统一 QA 规则由后端拥有；ERROR 会同时阻断正式任务创建和 Worker 执行。" />
    <Card title="模型 QA 输入"><JsonEditor value={input} onChange={setInput} /><Button style={{ marginTop: 12 }} type="primary" icon={<SafetyCertificateOutlined />} loading={busy} onClick={() => void run()}>运行 QA</Button></Card>
    {result && <Card title={<Space>QA 结果 <Tag color={result.run_allowed ? 'success' : 'error'}>{result.run_allowed ? '允许正式运行' : '阻断运行'}</Tag></Space>}>
      <Descriptions items={[{ key: 'rules', label: 'Ruleset', children: result.ruleset_version }, { key: 'errors', label: 'Errors', children: result.error_count }, { key: 'warnings', label: 'Warnings', children: result.warning_count }]} />
      <Table rowKey={(_, index) => String(index)} dataSource={result.issues} columns={[{ title: '级别', dataIndex: 'severity', render: (value: string) => <Tag color={value === 'ERROR' ? 'error' : value === 'WARNING' ? 'warning' : 'blue'}>{value}</Tag> }, { title: '类别', dataIndex: 'category' }, { title: '实体', render: (_, row) => `${row.entity_type} ${row.entity_id ?? ''}` }, { title: '说明', dataIndex: 'message' }, { title: 'GIS', render: (_, row) => <Button size="small" disabled={!row.location} icon={<AimOutlined />} onClick={() => navigate(`/gis?qa_entity=${encodeURIComponent(row.entity_id ?? '')}`)}>定位</Button> }]} />
    </Card>}
  </Space>;
}

function CalibrationTab() {
  const [sweep, setSweep] = useState(sweepTemplate);
  const [sweepRun, setSweepRun] = useState(sweepRunTemplate);
  const [plan, setPlan] = useState<ParameterSweepPlan>();
  const [commitInput, setCommitInput] = useState(calibrationCommitTemplate);
  const [promotionInput, setPromotionInput] = useState(promotionTemplate);
  const [calibrationRecord, setCalibrationRecord] = useState<CalibrationRunRecord>();
  const [series, setSeries] = useState(seriesTemplate);
  const [metrics, setMetrics] = useState<HydraulicMetrics>();
  const [chartRows, setChartRows] = useState<Array<Record<string, unknown>>>([]);
  const planSweep = async () => { try { setPlan(await planProductionCalibration(parseJson<ParameterSweepRequest>(sweep, '率定范围'))); } catch (reason) { message.error(reason instanceof Error ? reason.message : '计划失败'); } };
  const createSweep = async () => { try { const created = await createProductionCalibrationSweep(parseJson<CalibrationSweepCreateRequest>(sweepRun, '率定运行')); await Promise.all(created.candidates.filter((item) => item.task_id != null).map((item) => enqueueHydraulicTask(item.task_id!))); setPlan({ total_candidates: created.candidates.length, max_runs: created.candidates.length, candidates: created.candidates }); message.success(`${created.candidates.length} 个候选已通过现有 Job Manager 入队`); } catch (reason) { message.error(reason instanceof Error ? reason.message : '候选任务创建失败'); } };
  const commitCalibration = async () => { try { const record = await commitProductionCalibrationRun(parseJson<CalibrationRunCommitRequest>(commitInput, '率定证据')); setCalibrationRecord(record); message.success(`率定运行 ${record.run_code} 已持久化`); } catch (reason) { message.error(reason instanceof Error ? reason.message : '率定证据提交失败'); } };
  const promoteCalibration = async () => { try { const parsed = parseJson<CalibrationPromotionRequest & { calibration_run_id: number }>(promotionInput, '参数晋升'); const { calibration_run_id: calibrationRunId, ...body } = parsed; const promoted = await promoteProductionCalibration(calibrationRunId, body); if (promoted.production_run.task_id != null) await enqueueHydraulicTask(promoted.production_run.task_id); setCalibrationRecord(promoted.calibration); message.success('已创建带 QA 封套的正式重跑任务并入队'); } catch (reason) { message.error(reason instanceof Error ? reason.message : '参数晋升失败'); } };
  const score = async () => { try { const body = parseJson<MetricEvaluationRequest>(series, 'H/Q 序列'); setMetrics(await evaluateProductionMetrics(body)); const observed = new Map(body.observed.samples.map((sample) => [sample.time_seconds, sample.value])); setChartRows(body.simulated.samples.map((sample) => ({ time_seconds: sample.time_seconds, simulated_value: sample.value, observed_value: observed.get(sample.time_seconds) ?? null }))); } catch (reason) { message.error(reason instanceof Error ? reason.message : '指标计算失败'); } };
  const columns: ColumnsType<ParameterSweepPlan['candidates'][number]> = [
    { title: 'Candidate', dataIndex: 'candidate_id' },
    { title: 'Manning n / overrides', dataIndex: 'overrides', render: (value) => JSON.stringify(value) },
    { title: 'MAE', render: (_, row) => row.metrics?.[0]?.mae ?? '—', sorter: (a, b) => (a.metrics?.[0]?.mae ?? Infinity) - (b.metrics?.[0]?.mae ?? Infinity) },
    { title: 'RMSE', render: (_, row) => row.metrics?.[0]?.rmse ?? '—' }, { title: 'NSE', render: (_, row) => row.metrics?.[0]?.nse ?? '—' },
    { title: 'Peak Error', render: (_, row) => row.metrics?.[0]?.peak_value_error ?? '—' }, { title: 'Peak Time Error', render: (_, row) => row.metrics?.[0]?.peak_time_error_seconds ?? '—' },
    { title: 'Status', dataIndex: 'status' },
  ];
  return <Row gutter={[18, 18]}><Col xs={24} xl={12}><Card title="受控参数扫描"><JsonEditor value={sweep} onChange={setSweep} rows={12} /><Button style={{ marginTop: 12 }} icon={<ExperimentOutlined />} onClick={() => void planSweep()}>仅预览候选</Button></Card></Col><Col xs={24} xl={12}><Card title="Observed vs Simulated · H(t) / Q(t)"><JsonEditor value={series} onChange={setSeries} rows={12} /><Button style={{ marginTop: 12 }} onClick={() => void score()}>计算指标并绘图</Button>{metrics && <Descriptions size="small" items={[{ key: 'mae', label: 'MAE', children: metrics.mae ?? '—' }, { key: 'rmse', label: 'RMSE', children: metrics.rmse ?? '—' }, { key: 'nse', label: 'NSE', children: metrics.nse ?? '—' }, { key: 'r2', label: 'R²', children: metrics.r_squared ?? '—' }]} />}{chartRows.length > 0 && <ProductionChart rows={chartRows} title={metrics?.variable === 'discharge' ? 'Q(t)' : 'H(t)'} />}</Card></Col><Col span={24}><Card title="自动创建 Scenario Override → Task → Queue"><JsonEditor value={sweepRun} onChange={setSweepRun} rows={13} /><Button style={{ marginTop: 12 }} type="primary" icon={<ExperimentOutlined />} onClick={() => void createSweep()}>创建并入队有界候选</Button></Card></Col>{plan && <Col span={24}><Card title={`${plan.total_candidates} candidates · 不自动覆盖权威参数`}><Table rowKey="candidate_id" dataSource={plan.candidates} columns={columns} /></Card></Col>}<Col xs={24} xl={12}><Card title="回收候选结果与排名"><JsonEditor value={commitInput} onChange={setCommitInput} rows={14} /><Button style={{ marginTop: 12 }} onClick={() => void commitCalibration()}>持久化率定证据</Button>{calibrationRecord && <Tag color="blue" style={{ marginLeft: 12 }}>{calibrationRecord.status}</Tag>}</Card></Col><Col xs={24} xl={12}><Card title="审核后晋升参数"><Alert type="warning" showIcon message="晋升不改写原模型，而是创建新的冻结快照和正式重跑任务。" /><JsonEditor value={promotionInput} onChange={setPromotionInput} rows={9} /><Button style={{ marginTop: 12 }} type="primary" onClick={() => void promoteCalibration()}>晋升并启动正式重跑</Button></Card></Col></Row>;
}

function ValidationTab() {
  const [independenceInput, setIndependenceInput] = useState(independenceTemplate);
  const [acceptanceInput, setAcceptanceInput] = useState(acceptanceTemplate);
  const [commitInput, setCommitInput] = useState(validationCommitTemplate);
  const [approvalInput, setApprovalInput] = useState(approvalTemplate);
  const [independence, setIndependence] = useState<ValidationIndependenceResult>();
  const [acceptance, setAcceptance] = useState<AcceptanceEvaluation>();
  const [validationRecord, setValidationRecord] = useState<ProductionValidationRunRecord>();
  const commitValidation = async () => { try { const record = await commitProductionValidationRun(parseJson<ValidationRunCommitRequest>(commitInput, '正式验证证据')); setValidationRecord(record); message.success(`验证 ${record.validation_code}: ${record.status}`); } catch (reason) { message.error(reason instanceof Error ? reason.message : '正式验证提交失败'); } };
  const approve = async () => { try { const parsed = parseJson<ProductionApprovalRequest & { run_id: number }>(approvalInput, '专业批准'); const { run_id: runId, ...body } = parsed; const run = await approveProductionRun(runId, body); message.success(`${run.run_code} 已进入 ${run.model_state}`); } catch (reason) { message.error(reason instanceof Error ? reason.message : '专业批准失败'); } };
  return <Row gutter={[18, 18]}><Col xs={24} xl={12}><Card title="Calibration / Validation 数据独立性"><JsonEditor value={independenceInput} onChange={setIndependenceInput} /><Button style={{ marginTop: 12 }} onClick={() => void evaluateProductionIndependence(parseJson<ValidationIndependenceRequest>(independenceInput, '数据窗口')).then(setIndependence).catch((reason: unknown) => message.error(reason instanceof Error ? reason.message : '检查失败'))}>检查独立性</Button>{independence && <Alert style={{ marginTop: 12 }} type={independence.independent ? 'success' : independence.temporal_holdout ? 'warning' : 'error'} showIcon message={independence.independent ? '独立事件证据' : independence.temporal_holdout ? '仅时间留出' : '不能声明独立验证'} />}</Card></Col><Col xs={24} xl={12}><Card title="项目验收标准"><JsonEditor value={acceptanceInput} onChange={setAcceptanceInput} /><Button style={{ marginTop: 12 }} onClick={() => void evaluateProductionAcceptance(parseJson<AcceptanceEvaluationRequest>(acceptanceInput, '验收标准')).then(setAcceptance).catch((reason: unknown) => message.error(reason instanceof Error ? reason.message : '验收计算失败'))}>评估模型状态</Button>{acceptance && <Alert style={{ marginTop: 12 }} type={acceptance.criteria_passed ? 'success' : 'warning'} showIcon message={acceptance.model_state} description="软件只评估标准；正式批准仍要求专业人员签署。" />}</Card></Col><Col xs={24} xl={12}><Card title="持久化独立验证"><JsonEditor value={commitInput} onChange={setCommitInput} rows={15} /><Button style={{ marginTop: 12 }} type="primary" onClick={() => void commitValidation()}>提交验证证据</Button>{validationRecord && <Tag color={validationRecord.status === 'passed' ? 'success' : 'warning'} style={{ marginLeft: 12 }}>{validationRecord.status}</Tag>}</Card></Col><Col xs={24} xl={12}><Card title="专业人员最终批准"><Alert type="warning" showIcon message="只有已持久化通过的独立验证，才允许从 VALIDATED 进入 PRODUCTION_APPROVED。" /><JsonEditor value={approvalInput} onChange={setApprovalInput} rows={7} /><Button style={{ marginTop: 12 }} danger onClick={() => void approve()}>记录专业批准</Button></Card></Col></Row>;
}

function CompareTab() {
  const [input, setInput] = useState(compareTemplate);
  const [result, setResult] = useState<ExternalComparisonResult>();
  const run = async () => { try { setResult(await compareProductionExternal(parseJson<ExternalComparisonRequest>(input, '外部对比输入'))); } catch (reason) { message.error(reason instanceof Error ? reason.message : '对比失败'); } };
  const rows = (result?.time_series ?? []) as Array<Record<string, unknown>>;
  return <Space direction="vertical" size="large" style={{ width: '100%' }}><Alert type="info" showIcon message="MIKE11 是参考对比，不是真值；平台不会为了贴合外部模型自动改参数。" /><Card title="显式 Branch / chainage / H-Q 对比"><JsonEditor value={input} onChange={setInput} /><Button style={{ marginTop: 12 }} type="primary" onClick={() => void run()}>运行交叉对比</Button></Card>{result && <Tabs items={[{ key: 'profile', label: 'Longitudinal profile', children: <Table rowKey={(_, index) => String(index)} dataSource={result.longitudinal} columns={[{ title: 'Branch', dataIndex: 'branch_id' }, { title: 'Chainage', dataIndex: 'chainage_m' }, { title: 'Dayu max H', dataIndex: 'dayu_max_water_level' }, { title: 'External max H', dataIndex: 'external_max_water_level' }, { title: 'Difference', dataIndex: 'difference_water_level' }]} /> }, { key: 'series', label: 'Time series', children: <><ProductionChart rows={rows} title="Dayu vs External H(t) / Q(t)" /><Table rowKey={(_, index) => String(index)} dataSource={result.time_series} columns={[{ title: 'Branch', dataIndex: 'branch_id' }, { title: 'Chainage', dataIndex: 'chainage_m' }, { title: 'Variable', dataIndex: 'variable' }, { title: 'Time', dataIndex: 'time_seconds' }, { title: 'Dayu', dataIndex: 'dayu_value' }, { title: 'External', dataIndex: 'external_value' }]} /></> }, { key: 'difference', label: 'Difference table', children: <Table rowKey={(_, index) => String(index)} dataSource={result.time_series} columns={[{ title: 'Branch', dataIndex: 'branch_id' }, { title: 'Chainage', dataIndex: 'chainage_m' }, { title: 'Variable', dataIndex: 'variable' }, { title: 'Time', dataIndex: 'time_seconds' }, { title: 'Difference', dataIndex: 'difference' }]} /> }]} />}</Space>;
}

function ResultsTab() {
  const navigate = useNavigate();
  const [input, setInput] = useState(resultTemplate);
  const [commitInput, setCommitInput] = useState(resultCommitTemplate);
  const [bundle, setBundle] = useState<ResultProductBundle>();
  const [record, setRecord] = useState<ResultProductRecord>();
  const body = () => parseJson<ResultProductRequest>(input, '结果点');
  const generate = async () => { try { setBundle(await generateProductionProducts(body())); } catch (reason) { message.error(reason instanceof Error ? reason.message : '产品生成失败'); } };
  const runExport = async (kind: 'csv' | 'xlsx' | 'geojson') => { try { const blob = kind === 'csv' ? await exportProductionProductsCsv(body()) : kind === 'xlsx' ? await exportProductionProductsXlsx(body()) : await exportProductionProductsGeojson(body()); download(blob, `hydraulic-products.${kind}`); } catch (reason) { message.error(reason instanceof Error ? reason.message : '导出失败'); } };
  const commit = async () => { try { const stored = await commitProductionProduct(parseJson<ResultProductCommitRequest>(commitInput, '结果产品证据')); setRecord(stored); message.success(`产品 ${stored.product_code} 已按内容哈希持久化`); } catch (reason) { message.error(reason instanceof Error ? reason.message : '产品持久化失败'); } };
  return <Space direction="vertical" size="large" style={{ width: '100%' }}><Card title="统一结果产品"><JsonEditor value={input} onChange={setInput} /><Space style={{ marginTop: 12 }}><Button type="primary" onClick={() => void generate()}>生成产品</Button>{(['csv', 'xlsx', 'geojson'] as const).map((kind) => <Button key={kind} icon={<DownloadOutlined />} onClick={() => void runExport(kind)}>{kind.toUpperCase()}</Button>)}</Space></Card>{bundle && <><Row gutter={16}><Col span={6}><Statistic title="Maximum Water Level" value={Math.max(...bundle.max_envelope.map((row) => Number(row.maximum_water_level_m)))} suffix="m" /></Col><Col span={6}><Statistic title="Maximum Discharge" value={Math.max(...bundle.max_envelope.map((row) => Number(row.maximum_discharge_m3s)))} suffix="m³/s" /></Col><Col span={6}><Statistic title="Maximum Velocity" value={Math.max(...bundle.max_envelope.map((row) => Number(row.maximum_velocity_m_s)))} suffix="m/s" /></Col><Col span={6}><Statistic title="Maximum Afflux" value={Number(bundle.maximum_afflux?.maximum_afflux_m ?? 0)} suffix="m" /></Col></Row><Card title="Key Section Table"><Button icon={<AimOutlined />} onClick={() => navigate('/gis')}>GIS 联动</Button><Table rowKey={(_, index) => String(index)} dataSource={bundle.key_section_table} columns={[{ title: 'CrossSection', dataIndex: 'cross_section_id' }, { title: 'Chainage', dataIndex: 'chainage_m' }, { title: 'Bed', dataIndex: 'bed_elevation_m' }, { title: 'Baseline Hmax', dataIndex: 'baseline_hmax_m' }, { title: 'Project Hmax', dataIndex: 'project_hmax_m' }, { title: 'ΔH', dataIndex: 'delta_h_m' }, { title: 'Qmax', dataIndex: 'qmax_m3s' }, { title: 'Vmax', dataIndex: 'vmax_m_s' }, { title: 'Peak Time', dataIndex: 'peak_time_seconds' }]} /></Card></>}<Card title="将结果束绑至正式运行"><JsonEditor value={commitInput} onChange={setCommitInput} rows={12} /><Button style={{ marginTop: 12 }} onClick={() => void commit()}>持久化结果产品</Button>{record && <Text code style={{ marginLeft: 12 }}>{record.product_hash}</Text>}</Card></Space>;
}

function RunTab() {
  const navigate = useNavigate();
  const { datasetVersionId } = useDatasetVersion();
  const [input, setInput] = useState(runTemplate);
  const [runs, setRuns] = useState<ProductionRunRecord[]>([]);
  const [busy, setBusy] = useState(false);
  const reload = () => void listProductionRuns(datasetVersionId).then(setRuns).catch(() => undefined);
  useEffect(reload, [datasetVersionId]);
  const create = async () => {
    setBusy(true);
    try {
      const run = await createProductionRun(parseJson<ProductionTaskCreateRequest>(input, '正式运行输入'));
      if (run.task_id != null) await enqueueHydraulicTask(run.task_id);
      message.success(`正式运行 ${run.run_code} 已通过双重 QA 并进入队列`);
      reload();
    } catch (reason) { message.error(reason instanceof Error ? reason.message : '正式运行创建失败'); }
    finally { setBusy(false); }
  };
  return <Space direction="vertical" size="large" style={{ width: '100%' }}><Alert type="warning" showIcon message="只有本入口创建的任务带有与冻结快照绑定的 Production QA 封套；普通模拟不产生生产批准状态。" /><Card title="Model / Scenario / Production Run"><Space style={{ marginBottom: 12 }}><Button onClick={() => navigate('/hydraulic/config')}>查看模型与工况预览</Button><Button type="primary" loading={busy} onClick={() => void create()}>通过 QA 并创建正式任务</Button></Space><JsonEditor value={input} onChange={setInput} rows={18} /></Card><Card title="正式运行记录"><Table rowKey="id" dataSource={runs} columns={[{ title: 'Run', dataIndex: 'run_code' }, { title: 'Dataset', dataIndex: 'dataset_version_id' }, { title: 'Case', dataIndex: 'case_id' }, { title: 'Task', dataIndex: 'task_id' }, { title: 'QA', dataIndex: 'qa_run_code' }, { title: 'State', dataIndex: 'model_state', render: (value: string) => <Tag color="blue">{value}</Tag> }, { title: 'Snapshot', dataIndex: 'input_snapshot_hash', ellipsis: true }]} /></Card></Space>;
}

export function ProductionWorkspacePage() {
  const [capabilities, setCapabilities] = useState<ProductionCapabilityResponse>();
  useEffect(() => { void getProductionCapabilities().then(setCapabilities).catch(() => undefined); }, []);
  const items = useMemo(() => [
    { key: 'data', label: 'Data', children: <DataTab capabilities={capabilities} /> },
    { key: 'qa', label: 'QA', children: <QATab /> },
    { key: 'calibration', label: 'Calibration', children: <CalibrationTab /> },
    { key: 'validation', label: 'Validation', children: <ValidationTab /> },
    { key: 'run', label: 'Model / Run', children: <RunTab /> },
    { key: 'compare', label: 'Compare', children: <CompareTab /> },
    { key: 'results', label: 'Results', children: <ResultsTab /> },
  ], [capabilities]);
  return <div className="data-page hydraulic-page production-workspace"><header className="data-page__header"><div><span className="hero-kicker"><i /> PRODUCTION 1D</span><Title level={1}>水动力生产工作台</Title><Paragraph>从工程数据预览、统一 QA、率定与独立验证，到外部模型对比和结果产品。所有正式状态均由后端证据驱动。</Paragraph></div><Tag icon={<CheckCircleOutlined />} color={capabilities?.real_project_status === 'DATA_NOT_AVAILABLE' ? 'warning' : 'success'}>{capabilities?.real_project_status ?? 'LOADING'}</Tag></header><Tabs items={items} destroyInactiveTabPane={false} /></div>;
}
