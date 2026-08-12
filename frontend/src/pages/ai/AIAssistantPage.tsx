import {
  BookOutlined,
  DownloadOutlined,
  FileSearchOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  SendOutlined,
  ToolOutlined,
  UploadOutlined,
  UserOutlined,
} from '@ant-design/icons';
import {
  Alert,
  Avatar,
  Button,
  Card,
  Col,
  Collapse,
  Descriptions,
  Input,
  InputNumber,
  List,
  Row,
  Segmented,
  Space,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  chatWithAI,
  generateAIReport,
  listAIKnowledgeDocuments,
  listAIToolLogs,
  searchAIKnowledge,
  uploadAIKnowledgeDocument,
} from '../../api/generated/client';
import type {
  AIChatResponse,
  AIContext,
  AIToolCallLogRecord,
  KnowledgeDocumentRecord,
  KnowledgeSearchItem,
  ReportGenerateResponse,
  SourceCitation,
} from '../../api/generated/client';


const QUICK_QUESTIONS = [
  '分析当前洪水风险',
  '解释最新优化方案',
  '生成调度报告',
  '查询闸泵状态',
];

type ConversationItem = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sources?: SourceCitation[];
  tools?: string[];
  safety?: string;
};

function numericValue(value: number | string | null): number | undefined {
  return value === null || value === '' ? undefined : Number(value);
}

function CitationList({ sources }: { sources: SourceCitation[] }) {
  return (
    <div className="ai-citations">
      {sources.map((source) => (
        <div key={`${source.reference}-${source.version}`}>
          <FileSearchOutlined />
          <div>
            <strong>{source.title}</strong>
            <span>{source.reference} · {source.version}</span>
            {source.excerpt && <small>{source.excerpt}</small>}
          </div>
        </div>
      ))}
    </div>
  );
}

function ConversationMessage({ item }: { item: ConversationItem }) {
  return (
    <article className={`ai-message ai-message--${item.role}`}>
      <Avatar icon={item.role === 'assistant' ? <RobotOutlined /> : <UserOutlined />} />
      <div className="ai-message__body">
        <div className="ai-message__meta">
          <strong>{item.role === 'assistant' ? '大禹 AI 助手' : '工程师'}</strong>
          {item.safety && <Tag color={item.safety === 'allowed' ? 'success' : 'warning'}>{item.safety}</Tag>}
        </div>
        <Typography.Paragraph>{item.content}</Typography.Paragraph>
        {item.tools && item.tools.length > 0 && (
          <Space wrap className="ai-tools-used">
            <ToolOutlined />
            {item.tools.map((tool) => <Tag key={tool}>{tool}</Tag>)}
          </Space>
        )}
        {item.sources && item.sources.length > 0 && (
          <Collapse
            ghost
            size="small"
            items={[{ key: 'sources', label: `依据来源（${item.sources.length}）`, children: <CitationList sources={item.sources} /> }]}
          />
        )}
      </div>
    </article>
  );
}

export function AIAssistantPage() {
  const [question, setQuestion] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [messages, setMessages] = useState<ConversationItem[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content: '我是大禹·天工水利工程助手。请选择业务上下文后提问；所有工程结论都会展示来源，且不具有真实设备控制权限。',
      safety: 'boundary-notice',
    },
  ]);
  const [datasetVersionId, setDatasetVersionId] = useState<number | null>(null);
  const [simulationTaskId, setSimulationTaskId] = useState<number | null>(null);
  const [optimizationTaskId, setOptimizationTaskId] = useState<number | null>(null);
  const [riverId, setRiverId] = useState<number | null>(null);
  const [documents, setDocuments] = useState<KnowledgeDocumentRecord[]>([]);
  const [logs, setLogs] = useState<AIToolCallLogRecord[]>([]);
  const [knowledgeQuery, setKnowledgeQuery] = useState('');
  const [knowledgeItems, setKnowledgeItems] = useState<KnowledgeSearchItem[]>([]);
  const [report, setReport] = useState<ReportGenerateResponse>();
  const [reportLoading, setReportLoading] = useState(false);
  const [uploadCategory, setUploadCategory] = useState('engineering');

  const context = useMemo<AIContext>(() => ({
    dataset_version_id: numericValue(datasetVersionId),
    river_id: numericValue(riverId),
    simulation_task_id: numericValue(simulationTaskId),
    optimization_task_id: numericValue(optimizationTaskId),
    knowledge_document_ids: [],
  }), [datasetVersionId, optimizationTaskId, riverId, simulationTaskId]);

  const reloadSideData = useCallback(async () => {
    try {
      const [nextDocuments, nextLogs] = await Promise.all([
        listAIKnowledgeDocuments(),
        listAIToolLogs(12),
      ]);
      setDocuments(nextDocuments);
      setLogs(nextLogs);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'AI 辅助数据加载失败');
    }
  }, []);

  useEffect(() => { void reloadSideData(); }, [reloadSideData]);

  const ask = async (prompt = question) => {
    const trimmed = prompt.trim();
    if (!trimmed || submitting) return;
    const userMessage: ConversationItem = { id: `u-${Date.now()}`, role: 'user', content: trimmed };
    setMessages((items) => [...items, userMessage]);
    setQuestion('');
    setSubmitting(true);
    setError('');
    try {
      const response: AIChatResponse = await chatWithAI({ question: trimmed, user: 'engineer', context });
      setMessages((items) => [...items, {
        id: `a-${response.conversation_id}`,
        role: 'assistant',
        content: response.answer,
        sources: response.sources,
        tools: response.tools_used,
        safety: response.safety_status,
      }]);
      await reloadSideData();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'AI 回答生成失败');
    } finally {
      setSubmitting(false);
    }
  };

  const createReport = async () => {
    setReportLoading(true);
    setError('');
    try {
      const generated = await generateAIReport({ user: 'engineer', context });
      setReport(generated);
      message.success(`报告 #${generated.report_id} 已生成`);
      await reloadSideData();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '报告生成失败');
    } finally {
      setReportLoading(false);
    }
  };

  const runKnowledgeSearch = async () => {
    if (!knowledgeQuery.trim()) return;
    try {
      setKnowledgeItems((await searchAIKnowledge(knowledgeQuery, 6)).items);
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '知识检索失败');
    }
  };

  return (
    <div className="data-page ai-page">
      <header className="data-page__header">
        <div>
          <span className="hero-kicker"><i />WATER INTELLIGENCE · GROUNDED RAG</span>
          <h1>AI 水利助手</h1>
          <p>基于知识库、仿真与 Pareto 结果进行只读解释；回答附来源，报告保留模型版本和输入快照。</p>
        </div>
        <Tag color="cyan" icon={<SafetyCertificateOutlined />}>execution_authorized = false</Tag>
      </header>
      <Alert className="dispatch-notice" type="warning" showIcon message="AI 不能修改调度方案、评分或模型结果，不能控制闸泵，也不能替代人工审批。" />
      {error && <Alert className="data-alert" type="error" closable onClose={() => setError('')} showIcon message={error} />}

      <Row gutter={16}>
        <Col xs={24} xl={16}>
          <Card className="data-card ai-chat-card" title={<Space><RobotOutlined />工程辅助对话</Space>}>
            <div className="ai-quick-questions">
              {QUICK_QUESTIONS.map((item) => <Button key={item} size="small" onClick={() => item === '生成调度报告' ? void createReport() : void ask(item)}>{item}</Button>)}
            </div>
            <div className="ai-conversation" aria-live="polite">
              {messages.map((item) => <ConversationMessage key={item.id} item={item} />)}
              {submitting && <div className="ai-thinking"><span />正在检索证据并执行安全检查…</div>}
            </div>
            <div className="ai-composer">
              <Input.TextArea
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onPressEnter={(event) => { if (!event.shiftKey) { event.preventDefault(); void ask(); } }}
                autoSize={{ minRows: 3, maxRows: 7 }}
                maxLength={2000}
                placeholder="例如：为什么推荐最新方案？（Enter 发送，Shift+Enter 换行）"
              />
              <Button type="primary" icon={<SendOutlined />} loading={submitting} onClick={() => void ask()}>发送</Button>
            </div>
          </Card>
        </Col>
        <Col xs={24} xl={8}>
          <Card className="data-card ai-context-card" title="业务上下文（可选）">
            <div className="ai-context-grid">
              <label>数据版本 ID<InputNumber min={1} value={datasetVersionId} onChange={setDatasetVersionId} placeholder="默认最新" /></label>
              <label>河道 ID<InputNumber min={1} value={riverId} onChange={setRiverId} placeholder="全部河道" /></label>
              <label>仿真任务 ID<InputNumber min={1} value={simulationTaskId} onChange={setSimulationTaskId} placeholder="默认最新成功" /></label>
              <label>优化任务 ID<InputNumber min={1} value={optimizationTaskId} onChange={setOptimizationTaskId} placeholder="默认最新成功" /></label>
            </div>
          </Card>
          <Card className="data-card ai-report-card" title="智能报告" extra={<FileSearchOutlined />}>
            <p>生成《闸泵联合调度分析报告》，包含项目概况、工况、模型、优化、风险、措施和来源。</p>
            <Button block type="primary" loading={reportLoading} onClick={() => void createReport()}>生成 Markdown + PDF</Button>
            {report && <Space wrap className="ai-report-links"><Button icon={<DownloadOutlined />} href={report.markdown_url}>Markdown</Button><Button icon={<DownloadOutlined />} href={report.pdf_url}>PDF</Button></Space>}
          </Card>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col xs={24} xl={14}>
          <Card className="data-card" title={<Space><BookOutlined />水利知识库</Space>} extra={<Tag>{documents.length} 份文档</Tag>}>
            <Space.Compact block>
              <Input value={knowledgeQuery} onChange={(event) => setKnowledgeQuery(event.target.value)} onPressEnter={() => void runKnowledgeSearch()} placeholder="检索规范、模型解释、调度经验或工程案例" />
              <Button icon={<FileSearchOutlined />} onClick={() => void runKnowledgeSearch()}>检索</Button>
            </Space.Compact>
            <div className="ai-upload-row">
              <Segmented value={uploadCategory} onChange={(value) => setUploadCategory(String(value))} options={[{ label: '规范', value: 'regulations' }, { label: '水动力', value: 'hydraulic' }, { label: '调度', value: 'dispatch' }, { label: '工程', value: 'engineering' }, { label: '模板', value: 'templates' }]} />
              <Upload
                accept=".pdf,.docx,.md,.txt"
                showUploadList={false}
                beforeUpload={(file) => { void uploadAIKnowledgeDocument(file, uploadCategory, `upload-${file.lastModified}`).then(async () => { message.success(`${file.name} 已入库`); await reloadSideData(); }).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : '知识上传失败')); return false; }}
              >
                <Button icon={<UploadOutlined />}>上传知识</Button>
              </Upload>
            </div>
            {knowledgeItems.length > 0 ? (
              <List<KnowledgeSearchItem>
                className="ai-knowledge-list"
                dataSource={knowledgeItems}
                renderItem={(item) => (
                  <List.Item><List.Item.Meta title={`${item.document_name} · ${item.location}`} description={<><Tag>{item.category}</Tag><span>{item.content}</span></>} /><code>{item.score.toFixed(3)}</code></List.Item>
                )}
              />
            ) : (
              <List<KnowledgeDocumentRecord>
                className="ai-knowledge-list"
                dataSource={documents.slice(0, 6)}
                locale={{ emptyText: '知识库为空；容器种子会导入五类项目基线资料。' }}
                renderItem={(item) => (
                  <List.Item><List.Item.Meta title={item.name} description={`${item.category} · ${item.version} · ${item.chunk_count} 个片段`} /></List.Item>
                )}
              />
            )}
          </Card>
        </Col>
        <Col xs={24} xl={10}>
          <Card className="data-card" title={<Space><ToolOutlined />工具调用审计</Space>} extra={<Tag>只读白名单</Tag>}>
            <List
              className="ai-tool-log-list"
              dataSource={logs}
              locale={{ emptyText: '尚无工具调用' }}
              renderItem={(item) => (
                <List.Item>
                  <Descriptions size="small" column={1} items={[
                    { key: 'tool', label: '工具', children: <code>{item.tool_name}</code> },
                    { key: 'conversation', label: '会话', children: item.conversation_id ? `#${item.conversation_id}` : '报告任务' },
                    { key: 'duration', label: '耗时', children: `${item.duration_ms} ms` },
                    { key: 'time', label: '时间', children: new Date(item.time).toLocaleString() },
                  ]} />
                </List.Item>
              )}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
