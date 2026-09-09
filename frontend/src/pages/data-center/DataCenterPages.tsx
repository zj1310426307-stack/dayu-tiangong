import {
  CheckCircleOutlined,
  CloudUploadOutlined,
  DeleteOutlined,
  EditOutlined,
  FileExcelOutlined,
  PlusOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
} from "@ant-design/icons";
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
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
  Upload,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import type { UploadFile } from "antd/es/upload/interface";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  BoundaryConditionCreate,
  BoundaryConditionRecord,
  BoundaryRatingCurveGenerateResponse,
  DatasetVersionRecord,
  GateCreate,
  GateRecord,
  HydraulicBranchRecord,
  HydraulicNetworkRecord,
  ImportResource,
  ModelParameterCreate,
  ModelParameterRecord,
  Hydraulic1DPreviewResponse,
  HydraulicSectionDetail,
  HydraulicSectionSummary,
  PumpCreate,
  PumpRecord,
  SimulationCaseCreate,
  SimulationCaseRecord,
  ValidationReport,
} from "../../api/generated/client";
import {
  datasetVersionStatusLabel,
  useDatasetVersion,
} from "../../context/DatasetVersionContext";
import {
  approveDatasetVersionForCalculation,
  createBoundaryCondition,
  createGateRecord,
  createModelParameter,
  createPumpRecord,
  createSimulationCase,
  deleteBoundaryCondition,
  deleteGateRecord,
  deleteModelParameter,
  deletePumpRecord,
  deleteSimulationCase,
  getBoundaryConditions,
  generateBoundaryRatingCurve,
  getModelParameters,
  getSimulationCases,
  getHydraulicSection,
  listGateRecords,
  listPumpRecords,
  listHydraulicNetworks,
  listRiverRecords,
  previewHydraulicModel,
  runValidation,
  updateBoundaryCondition,
  updateGateRecord,
  updateModelParameter,
  updatePumpRecord,
  updateSimulationCase,
  updateHydraulicSectionMarkers,
  detectHydraulicSectionMarkers,
  updateHydraulicMarkerWorkflow,
  batchDetectHydraulicMarkers,
  uploadDataFile,
} from "../../api/generated/client";

const { Paragraph, Text, Title } = Typography;

function DataPageHeader({
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
        <span className="hero-kicker">
          <i /> {eyebrow}
        </span>
        <Title level={1}>{title}</Title>
        <Paragraph>{description}</Paragraph>
      </div>
      {action}
    </header>
  );
}

/** 在版本身份就绪后加载远端列表，防止空版本查询意外混合多个代次。 */
function useRemoteList<T>(
  loader: () => Promise<T>,
  dependencies: readonly unknown[],
  enabled = true,
) {
  const [data, setData] = useState<T>();
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState("");
  const reload = useCallback(async () => {
    if (!enabled) {
      setData(undefined);
      setLoading(false);
      setError("");
      return;
    }
    setLoading(true);
    setError("");
    try {
      setData(await loader());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "数据加载失败");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, ...dependencies]);
  useEffect(() => {
    void reload();
  }, [reload]);
  return { data, loading, error, reload };
}

/** 明确提示当前版本的编辑能力，避免已发布版本继续展示为可写工作区。 */
function DatasetWriteNotice() {
  const { currentVersion, isMutable, loading } = useDatasetVersion();
  if (loading)
    return (
      <Alert
        className="data-alert"
        type="info"
        showIcon
        message="正在确认数据版本状态…"
      />
    );
  if (!currentVersion)
    return (
      <Alert
        className="data-alert"
        type="warning"
        showIcon
        message="尚未选择数据版本"
        description="请先在顶部选择版本，或新建可编辑草稿。"
      />
    );
  if (isMutable)
    return (
      <Alert
        className="data-alert"
        type="success"
        showIcon
        message={`当前草稿 ${currentVersion.version} 可编辑`}
        description="所有新增、修改、删除和导入都会写入当前草稿。"
      />
    );
  return (
    <Alert
      className="data-alert"
      type="info"
      showIcon
      message={`当前版本 ${currentVersion.version} 为只读`}
      description="已发布、已批准或已退役版本不可原地修改；请点击顶部“新建草稿”进入独立编辑工作区。"
    />
  );
}

function jsonText(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function coordinatesOf(geometry: Record<string, unknown>): unknown {
  return geometry.coordinates;
}

interface HydraulicRiverRow extends HydraulicBranchRecord {
  network_id: number;
  network_code: string;
  network_name: string;
  engineering_crs: string | null;
}

interface HydraulicSectionRow extends HydraulicSectionSummary {
  network_code: string;
  network_name: string;
  branch_code: string;
  river_name: string;
}

export function RiversDatabasePage() {
  const { datasetVersionId } = useDatasetVersion();
  const [search, setSearch] = useState("");
  const { data, loading, error, reload } = useRemoteList(
    () => listHydraulicNetworks(datasetVersionId!),
    [datasetVersionId],
    Boolean(datasetVersionId),
  );
  const rows = useMemo<HydraulicRiverRow[]>(
    () =>
      (data ?? []).flatMap((network) =>
        (network.branches ?? []).map((branch) => ({
          ...branch,
          network_id: network.id,
          network_code: network.code,
          network_name: network.name,
          engineering_crs: network.engineering_crs,
        })),
      ),
    [data],
  );
  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return rows;
    return rows.filter((row) =>
      [
        row.network_code,
        row.network_name,
        row.branch_code,
        row.river_name,
        row.branch_name,
      ].some((value) => value.toLowerCase().includes(term)),
    );
  }, [rows, search]);
  const columns: ColumnsType<HydraulicRiverRow> = [
    { title: "河网编码", dataIndex: "network_code", width: 135 },
    { title: "河网名称", dataIndex: "network_name", width: 150 },
    { title: "河段编码", dataIndex: "branch_code", width: 145 },
    { title: "河流名称", dataIndex: "river_name", width: 155 },
    { title: "河段名称", dataIndex: "branch_name", width: 155 },
    {
      title: "流向",
      dataIndex: "flow_direction",
      width: 95,
      render: (value: string) => (
        <Tag color={value === "unknown" ? "warning" : "cyan"}>{value}</Tag>
      ),
    },
    {
      title: "中心线角色",
      dataIndex: "centerline_role",
      width: 120,
      render: (value: string) => (
        <Tag
          color={
            value === "thalweg"
              ? "success"
              : value === "surveyed_centerline"
                ? "cyan"
                : "warning"
          }
        >
          {value === "thalweg"
            ? "深泓线"
            : value === "surveyed_centerline"
              ? "实测中心线"
              : "未确认"}
        </Tag>
      ),
    },
    {
      title: "来源修订",
      dataIndex: "source_revision",
      width: 120,
      render: (value?: string) => value ?? "未登记",
    },
    {
      title: "桩号范围",
      width: 185,
      render: (_, row) =>
        `${row.start_chainage.toFixed(3)} – ${row.end_chainage.toFixed(3)} m`,
    },
    {
      title: "长度",
      dataIndex: "length_m",
      width: 115,
      render: (value: number) => `${value.toFixed(1)} m`,
    },
    { title: "河网点", dataIndex: "vertex_count", width: 90 },
    { title: "断面", dataIndex: "section_count", width: 80 },
    {
      title: "工程坐标系",
      dataIndex: "engineering_crs",
      width: 125,
      render: (value?: string) => value ?? "未声明",
    },
  ];
  return (
    <div className="data-page">
      <DataPageHeader
        eyebrow="HYDRAULIC DATABASE / NETWORK"
        title="河道数据库"
        description="直接读取水动力数据管理的权威 Network → Branch 模型，字段与河网模板保持一致；旧 river 表仅作为兼容投影。"
        action={
          <Space>
            <Button
              icon={<FileExcelOutlined />}
              href="/api/v1/hydraulic/templates/river-network"
            >
              下载河网模板
            </Button>
            <Button type="primary" href="/data-center/hydraulic">
              进入水动力数据管理
            </Button>
          </Space>
        }
      />
      <DatasetWriteNotice />
      <Alert
        className="data-alert"
        type="info"
        showIcon
        message="统一数据真源已启用"
        description="河道中心线点须按上游到下游、桩号严格递增依次填写；当中心线定义为深泓线时，每个断面须保留最低高程深泓点。导入、坐标声明、拓扑处理和修改统一在水动力数据管理中预览后提交。"
      />
      {error && (
        <Alert className="data-alert" type="error" showIcon message={error} />
      )}
      <Card
        className="data-card"
        title={`河段清单 · ${filtered.length} 条`}
        extra={
          <Space>
            <Input.Search
              allowClear
              placeholder="河网、河流或河段"
              onChange={(event) => setSearch(event.target.value)}
            />
            <Button
              icon={<ReloadOutlined />}
              disabled={!datasetVersionId}
              onClick={() => void reload()}
            />
          </Space>
        }
      >
        <Table
          rowKey={(row) => `${row.network_id}-${row.id}`}
          loading={loading}
          columns={columns}
          dataSource={filtered}
          pagination={{ pageSize: 12 }}
          scroll={{ x: 1500 }}
        />
      </Card>
    </div>
  );
}

function SectionProfileChart({
  section,
}: {
  section?: HydraulicSectionDetail;
}) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!element.current || !section) return undefined;
    let disposed = false;
    let dispose: (() => void) | undefined;
    void import("echarts").then((echarts) => {
      if (disposed || !element.current) return;
      const container = element.current;
      echarts.getInstanceByDom(container)?.dispose();
      const chart = echarts.init(container);
      const profile =
        section.profiles.find((item) => item.is_active) ?? section.profiles[0];
      // Render every persisted survey point in point order.  Do not smooth,
      // sample, or synthesize points because the preview is an audit surface.
      const profilePoints = [...(profile?.points ?? [])].sort(
        (left, right) => left.sequence - right.sequence,
      );
      const points = profilePoints.map((point) => [
        point.distance,
        point.elevation,
      ]);
      const thalweg = profilePoints
        .filter((point) => point.marker_type === "thalweg")
        .map((point) => [point.distance, point.elevation]);
      const marker1 = profilePoints
        .filter(
          (point) =>
            point.marker_type === "left_levee" ||
            point.marker_type === "left_bank",
        )
        .map((point) => [point.distance, point.elevation]);
      const marker3 = profilePoints
        .filter(
          (point) =>
            point.marker_type === "right_levee" ||
            point.marker_type === "right_bank",
        )
        .map((point) => [point.distance, point.elevation]);
      const marker2 = profilePoints
        .filter(
          (point) =>
            point.marker_type === "main_channel" ||
            point.marker_type === "thalweg",
        )
        .map((point) => [point.distance, point.elevation]);
      const processedPoints = profile?.marker_workflow?.processed_points ?? [];
      const processed = processedPoints.map((point) => [
        point.offset,
        point.elevation,
      ]);
      const virtual = processedPoints
        .filter((point) => point.virtual)
        .map((point) => [point.offset, point.elevation]);
      const activeExtent =
        marker1[0] && marker3[0]
          ? [
              [
                { name: "Marker 1–3 有效范围", xAxis: marker1[0][0] },
                { xAxis: marker3[0][0] },
              ],
            ]
          : [];
      chart.setOption({
        grid: { left: 45, right: 20, top: 24, bottom: 38 },
        tooltip: { trigger: "axis" },
        xAxis: {
          type: "value",
          name: "横距 / m",
          axisLabel: { color: "#7891a4" },
          splitLine: { lineStyle: { color: "rgba(100,151,183,.12)" } },
        },
        yAxis: {
          type: "value",
          name: "高程 / m",
          axisLabel: { color: "#7891a4" },
          splitLine: { lineStyle: { color: "rgba(100,151,183,.12)" } },
        },
        series: [
          {
            name: `完整断面（${points.length} 点）`,
            type: "line",
            data: points,
            smooth: false,
            showSymbol: true,
            symbolSize: 6,
            lineStyle: { color: "#2fe6d6", width: 3 },
            areaStyle: { color: "rgba(47,230,214,.12)" },
            markArea: {
              silent: true,
              itemStyle: { color: "rgba(92, 196, 255, .10)" },
              data: activeExtent,
            },
          },
          {
            name: "深泓点",
            type: "scatter",
            data: thalweg,
            symbolSize: 13,
            itemStyle: {
              color: "#ffc85c",
              borderColor: "#fff2c2",
              borderWidth: 2,
            },
          },
          {
            name: "Marker 2 主槽",
            type: "scatter",
            data: marker2,
            symbolSize: 13,
            itemStyle: {
              color: "#ffd54f",
              borderColor: "#fff2c2",
              borderWidth: 2,
            },
          },
          {
            name: "Marker 1 左堤防",
            type: "scatter",
            data: marker1,
            symbol: "triangle",
            symbolSize: 15,
            itemStyle: { color: "#5cc4ff" },
          },
          {
            name: "Marker 3 右堤防",
            type: "scatter",
            data: marker3,
            symbol: "triangle",
            symbolRotate: 180,
            symbolSize: 15,
            itemStyle: { color: "#ff8f70" },
          },
          {
            name: "Processed Geometry",
            type: "line",
            data: processed,
            showSymbol: false,
            lineStyle: { color: "#5cc4ff", width: 2, type: "dashed" },
          },
          {
            name: "Virtual Extension",
            type: "scatter",
            data: virtual,
            symbol: "diamond",
            symbolSize: 16,
            itemStyle: { color: "#ff4d4f" },
          },
        ],
      });
      dispose = () => chart.dispose();
    });
    return () => {
      disposed = true;
      dispose?.();
    };
  }, [section]);
  return <div className="section-profile-chart" ref={element} />;
}

export function CrossSectionsDatabasePage() {
  const { datasetVersionId, currentVersion, isMutable } = useDatasetVersion();
  const [selectedRow, setSelectedRow] = useState<HydraulicSectionRow>();
  const [selected, setSelected] = useState<HydraulicSectionDetail>();
  const [detailLoading, setDetailLoading] = useState(false);
  const [marker1Sequence, setMarker1Sequence] = useState<number>();
  const [marker2Sequence, setMarker2Sequence] = useState<number>();
  const [marker3Sequence, setMarker3Sequence] = useState<number>();
  const [lockMarker1, setLockMarker1] = useState(true);
  const [lockMarker2, setLockMarker2] = useState(true);
  const [lockMarker3, setLockMarker3] = useState(true);
  const [reviewOnly, setReviewOnly] = useState(false);
  const [markerSaving, setMarkerSaving] = useState(false);
  const [workflowSaving, setWorkflowSaving] = useState(false);
  const [markerDetectionMode, setMarkerDetectionMode] = useState<
    "FULL_EXTENT" | "MIKE11_COMPATIBLE"
  >("MIKE11_COMPATIBLE");
  const [activeExtentMode, setActiveExtentMode] = useState<
    "FULL_EXTENT" | "MARKER_EXTENT"
  >("FULL_EXTENT");
  const [overbankTreatment, setOverbankTreatment] = useState<
    "REAL_GEOMETRY" | "VERTICAL_EXTENSION"
  >("REAL_GEOMETRY");
  const [extensionTopElevation, setExtensionTopElevation] = useState<number>();
  const [designMaxWaterLevel, setDesignMaxWaterLevel] = useState<number>();
  const [safetyFreeboard, setSafetyFreeboard] = useState(0);
  const { data, loading, error, reload } = useRemoteList(
    () => listHydraulicNetworks(datasetVersionId!),
    [datasetVersionId],
    Boolean(datasetVersionId),
  );
  const rows = useMemo<HydraulicSectionRow[]>(
    () =>
      (data ?? []).flatMap((network) =>
        (network.branches ?? []).flatMap((branch) =>
          (branch.sections ?? []).map((section) => ({
            ...section,
            network_code: network.code,
            network_name: network.name,
            branch_code: branch.branch_code,
            river_name: branch.river_name,
          })),
        ),
      ),
    [data],
  );
  useEffect(() => {
    setSelectedRow(undefined);
    setSelected(undefined);
    setMarker1Sequence(undefined);
    setMarker2Sequence(undefined);
    setMarker3Sequence(undefined);
    setLockMarker1(true);
    setLockMarker2(true);
    setLockMarker3(true);
    setReviewOnly(false);
    setActiveExtentMode("FULL_EXTENT");
    setOverbankTreatment("REAL_GEOMETRY");
    setExtensionTopElevation(undefined);
    setDesignMaxWaterLevel(undefined);
    setSafetyFreeboard(0);
  }, [datasetVersionId]);
  const selectSection = async (row: HydraulicSectionRow) => {
    setSelectedRow(row);
    setDetailLoading(true);
    try {
      const detail = await getHydraulicSection(row.id);
      setSelected(detail);
      const profile =
        detail.profiles.find((item) => item.is_active) ?? detail.profiles[0];
      setMarker1Sequence(
        profile?.points.find(
          (point) =>
            point.marker_type === "left_levee" ||
            point.marker_type === "left_bank",
        )?.sequence,
      );
      setMarker2Sequence(
        profile?.points.find(
          (point) =>
            point.marker_type === "main_channel" ||
            point.marker_type === "thalweg",
        )?.sequence,
      );
      setMarker3Sequence(
        profile?.points.find(
          (point) =>
            point.marker_type === "right_levee" ||
            point.marker_type === "right_bank",
        )?.sequence,
      );
      const workflow = profile?.marker_workflow;
      if (workflow) {
        const markers = new Map(
          (workflow.markers ?? []).map((marker) => [marker.type, marker]),
        );
        setLockMarker1(markers.get("M1")?.locked ?? true);
        setLockMarker2(markers.get("M2")?.locked ?? true);
        setLockMarker3(markers.get("M3")?.locked ?? true);
        setMarkerDetectionMode(
          workflow.marker_detection_mode === "FULL_EXTENT"
            ? "FULL_EXTENT"
            : "MIKE11_COMPATIBLE",
        );
        setActiveExtentMode(
          workflow.active_extent_mode === "MARKER_EXTENT"
            ? "MARKER_EXTENT"
            : "FULL_EXTENT",
        );
        setOverbankTreatment(
          workflow.overbank_treatment === "VERTICAL_EXTENSION"
            ? "VERTICAL_EXTENSION"
            : "REAL_GEOMETRY",
        );
        setExtensionTopElevation(
          workflow.extension_top_elevation_m ?? undefined,
        );
        setDesignMaxWaterLevel(workflow.design_max_water_level_m ?? undefined);
        setSafetyFreeboard(workflow.safety_freeboard_m);
      }
    } catch (reason) {
      message.error(
        reason instanceof Error ? reason.message : "断面详情加载失败",
      );
    } finally {
      setDetailLoading(false);
    }
  };
  const columns: ColumnsType<HydraulicSectionRow> = [
    { title: "ID", dataIndex: "section_code", width: 145 },
    { title: "TOPOID", dataIndex: "topography_id", width: 135 },
    {
      title: "里程",
      dataIndex: "chainage",
      width: 125,
      render: (value: number) => `${value.toFixed(3)} m`,
    },
    { title: "river_name", dataIndex: "branch_code", width: 145 },
    { title: "河流名称", dataIndex: "river_name", width: 145 },
    { title: "剖面点", dataIndex: "point_count", width: 90 },
    { title: "历史剖面", dataIndex: "profile_count", width: 95 },
    {
      title: "断面方向",
      dataIndex: "orientation_status",
      width: 105,
      render: (value: string) => (
        <Tag color={value === "confirmed" ? "success" : "warning"}>{value}</Tag>
      ),
    },
    {
      title: "Marker 复核",
      dataIndex: "marker_review_status",
      width: 120,
      render: (value: string) => (
        <Tag color={value === "NEEDS_REVIEW" ? "warning" : "success"}>
          {value}
        </Tag>
      ),
    },
  ];
  const activeProfile =
    selected?.profiles.find((profile) => profile.is_active) ??
    selected?.profiles[0];
  const thalwegPoints =
    activeProfile?.points.filter((point) => point.marker_type === "thalweg") ??
    [];
  const markerOptions = (activeProfile?.points ?? []).map((point) => ({
    value: point.sequence,
    label: `${point.sequence} · 横距 ${point.distance.toFixed(3)} m · 高程 ${point.elevation.toFixed(3)} m`,
  }));
  const markerByType = new Map(
    (activeProfile?.marker_workflow?.markers ?? []).map((marker) => [
      marker.type,
      marker,
    ]),
  );
  const visibleRows = reviewOnly
    ? rows.filter((row) => row.marker_review_status === "NEEDS_REVIEW")
    : rows;
  const saveMarkers = async () => {
    if (!selected) return;
    if (!isMutable) {
      message.warning(
        `当前版本 ${currentVersion?.version ?? ""} 为只读，请在顶部选择或新建草稿后再设置 Marker 1/3`,
      );
      return;
    }
    if (
      marker1Sequence !== undefined &&
      marker3Sequence !== undefined &&
      marker1Sequence >= marker3Sequence
    ) {
      message.warning("Marker 1 的横断面点序必须小于 Marker 3");
      return;
    }
    if (
      marker2Sequence !== undefined &&
      marker1Sequence !== undefined &&
      marker2Sequence <= marker1Sequence
    ) {
      message.warning("Marker 2 的点序必须位于 Marker 1 与 Marker 3 之间");
      return;
    }
    if (
      marker2Sequence !== undefined &&
      marker3Sequence !== undefined &&
      marker2Sequence >= marker3Sequence
    ) {
      message.warning("Marker 2 的点序必须位于 Marker 1 与 Marker 3 之间");
      return;
    }
    setMarkerSaving(true);
    try {
      const detail = await updateHydraulicSectionMarkers(selected.id, {
        marker1_sequence: marker1Sequence ?? null,
        marker2_sequence: marker2Sequence ?? null,
        marker3_sequence: marker3Sequence ?? null,
        lock_marker1: lockMarker1,
        lock_marker2: lockMarker2,
        lock_marker3: lockMarker3,
        actor: "web-operator",
      });
      setSelected(detail);
      message.success(
        "Marker 1/2/3 已保存；该断面的空间交点将按 Marker 2 重新派生",
      );
    } catch (reason) {
      const detail =
        reason instanceof Error ? reason.message : "Marker 1/3 保存失败";
      if (/published.*immutable|immutable.*published/i.test(detail)) {
        message.warning("当前数据版本已发布且不可修改，请切换到草稿后重试");
      } else {
        message.error(detail);
      }
    } finally {
      setMarkerSaving(false);
    }
  };
  /** 自动识别只更新 Marker/Processed 层，原始 Station/Elevation 不变。 */
  const autoDetectMarkers = async (
    force = false,
    mode: "FULL_EXTENT" | "MIKE11_COMPATIBLE" = markerDetectionMode,
  ) => {
    if (!selected || !isMutable) return;
    setMarkerSaving(true);
    try {
      const detail = await detectHydraulicSectionMarkers(selected.id, {
        mode,
        force,
      });
      setSelected(detail);
      const profile =
        detail.profiles.find((item) => item.is_active) ?? detail.profiles[0];
      setMarker1Sequence(
        profile?.points.find((point) => point.marker_type === "left_levee")
          ?.sequence,
      );
      setMarker2Sequence(
        profile?.points.find((point) => point.marker_type === "main_channel")
          ?.sequence,
      );
      setMarker3Sequence(
        profile?.points.find((point) => point.marker_type === "right_levee")
          ?.sequence,
      );
      const markers = new Map(
        (profile?.marker_workflow?.markers ?? []).map((marker) => [
          marker.type,
          marker,
        ]),
      );
      setLockMarker1(markers.get("M1")?.locked ?? false);
      setLockMarker2(markers.get("M2")?.locked ?? false);
      setLockMarker3(markers.get("M3")?.locked ?? false);
      const needsReview =
        profile?.marker_workflow?.review_status === "NEEDS_REVIEW";
      message[needsReview ? "warning" : "success"](
        needsReview
          ? "候选已生成，请复核警告后再用于计算"
          : "控制点自动识别完成",
      );
    } catch (reason) {
      message.error(reason instanceof Error ? reason.message : "自动识别失败");
    } finally {
      setMarkerSaving(false);
    }
  };
  /** 批量识别在后端执行，默认保留锁定和高优先级 Marker。 */
  const batchDetect = async () => {
    if (!datasetVersionId || !isMutable) return;
    setMarkerSaving(true);
    try {
      const result = await batchDetectHydraulicMarkers({
        dataset_version_id: datasetVersionId,
        mode: markerDetectionMode,
        force: false,
      });
      message.success(
        `批量完成：${result.detected}/${result.total_sections}，待复核 ${result.needs_review}，失败 ${result.failed}，锁定跳过 ${result.locked_skipped}，方向未知 ${result.unknown_orientation}`,
      );
      if (selectedRow) await selectSection(selectedRow);
    } catch (reason) {
      message.error(reason instanceof Error ? reason.message : "批量识别失败");
    } finally {
      setMarkerSaving(false);
    }
  };
  /** 保存有效范围和全归槽假设，并刷新独立 Processed Geometry。 */
  const saveWorkflow = async () => {
    if (!activeProfile || !isMutable) return;
    setWorkflowSaving(true);
    try {
      const workflow = await updateHydraulicMarkerWorkflow(activeProfile.id, {
        active_extent_mode: activeExtentMode,
        overbank_treatment: overbankTreatment,
        extension_top_elevation_m: extensionTopElevation ?? null,
        design_max_water_level_m: designMaxWaterLevel ?? null,
        safety_freeboard_m: safetyFreeboard,
      });
      setSelected((current) =>
        current
          ? {
              ...current,
              profiles: current.profiles.map((profile) =>
                profile.id === activeProfile.id
                  ? { ...profile, marker_workflow: workflow }
                  : profile,
              ),
            }
          : current,
      );
      message.success("水力有效断面已重新生成；Raw Geometry 未修改");
    } catch (reason) {
      message.error(
        reason instanceof Error ? reason.message : "断面处理配置保存失败",
      );
    } finally {
      setWorkflowSaving(false);
    }
  };
  return (
    <div className="data-page">
      <DataPageHeader
        eyebrow="HYDRAULIC DATABASE / SECTIONS"
        title="横断面数据库"
        description="直接读取标准化 Profile / Point 数据；导入列固定为 ID、TOPOID、里程、偏移、高程、river_name。"
        action={
          <Space>
            <Button
              icon={<FileExcelOutlined />}
              href="/api/v1/hydraulic/templates/cross-section"
            >
              下载横断面模板
            </Button>
            <Button type="primary" href="/data-center/hydraulic">
              导入与校核
            </Button>
          </Space>
        }
      />
      <DatasetWriteNotice />
      <Alert
        className="data-alert"
        type="info"
        showIcon
        message="MIKE11 风格断面定位已启用"
        description="水力计算使用 Station/Offset + Elevation；空间展示按 Branch 中心线+Chainage 派生，实测断面 XY 只是可选且优先的 Survey Geometry。0 点为下游视向左岸，Station 递增至右岸。"
      />
      {error && (
        <Alert className="data-alert" type="error" showIcon message={error} />
      )}
      <div className="data-split">
        <Card
          className="data-card"
          title={`断面清单 · ${visibleRows.length}/${rows.length} 条`}
          extra={
            <Space>
              <span>仅待复核</span>
              <Switch checked={reviewOnly} onChange={setReviewOnly} />
              <Button
                icon={<ReloadOutlined />}
                disabled={!datasetVersionId}
                onClick={() => void reload()}
              />
            </Space>
          }
        >
          <Table
            rowKey="id"
            loading={loading}
            columns={columns}
            dataSource={visibleRows}
            pagination={{ pageSize: 10 }}
            scroll={{ x: 1050 }}
            rowClassName={(row) =>
              row.id === selectedRow?.id ? "ant-table-row-selected" : ""
            }
            onRow={(row) => ({ onClick: () => void selectSection(row) })}
          />
        </Card>
        <Card
          loading={detailLoading}
          className="data-card profile-card"
          title="断面剖面预览"
        >
          {selected ? (
            <>
              <Descriptions
                column={1}
                size="small"
                items={[
                  {
                    key: "name",
                    label: "断面",
                    children: selected.section_name,
                  },
                  {
                    key: "branch",
                    label: "river_name",
                    children: selected.branch_code,
                  },
                  {
                    key: "station",
                    label: "里程",
                    children: `${selected.chainage.toFixed(3)} m`,
                  },
                  {
                    key: "topography",
                    label: "TOPOID",
                    children: activeProfile?.topography_id ?? "—",
                  },
                  {
                    key: "datum",
                    label: "高程基准",
                    children: activeProfile?.vertical_datum ?? "—",
                  },
                  {
                    key: "spatial",
                    label: "空间几何",
                    children: `${selected.spatial_geometry_source} / ${selected.spatial_geometry_status}`,
                  },
                  {
                    key: "anchor",
                    label: "Branch 交点 Station",
                    children:
                      selected.branch_intersection_station == null
                        ? "—"
                        : `${selected.branch_intersection_station.toFixed(3)} m (${selected.anchor_source})`,
                  },
                  {
                    key: "thalweg",
                    label: "深泓点",
                    children: thalwegPoints.length
                      ? thalwegPoints
                          .map(
                            (point) =>
                              `${point.distance.toFixed(3)} / ${point.elevation.toFixed(3)} m`,
                          )
                          .join("；")
                      : "未标记",
                  },
                  {
                    key: "roughness",
                    label: "默认糙率",
                    children: activeProfile?.default_manning_n ?? "—",
                  },
                  {
                    key: "points",
                    label: "偏移/高程点数",
                    children: activeProfile?.points.length ?? 0,
                  },
                ]}
              />
              <Alert
                style={{ marginTop: 12 }}
                type="success"
                showIcon
                message={`完整剖面：按点序绘制 ${activeProfile?.points.length ?? 0} 个导入点`}
                description="预览不抽稀、不补点、不使用平滑曲线；折线逐点连接，点数与当前活动剖面的入库点数一致。"
              />
              <Card
                size="small"
                title="MIKE11 风格 Marker 1/2/3"
                style={{ marginTop: 12 }}
              >
                <Alert
                  type={isMutable ? "info" : "warning"}
                  showIcon
                  message={
                    isMutable
                      ? "M1 = 左堤，M2 = 主槽低点，M3 = 右堤"
                      : `当前版本 ${currentVersion?.version ?? ""} 为只读，Marker 仅可查看`
                  }
                  description={
                    isMutable
                      ? "自动识别只生成候选；复杂河段应结合测量成果、堤防轴线、DEM、GIS 和现场调查复核。"
                      : "已发布、已批准或已退役版本不可原地修改；请切换草稿。"
                  }
                />
                <Space wrap style={{ marginTop: 12 }}>
                  <Select
                    disabled={!isMutable}
                    value={markerDetectionMode}
                    onChange={setMarkerDetectionMode}
                    options={[
                      { value: "FULL_EXTENT", label: "FULL_EXTENT" },
                      {
                        value: "MIKE11_COMPATIBLE",
                        label: "MIKE11 Compatible",
                      },
                    ]}
                  />
                  <Button
                    disabled={!isMutable}
                    loading={markerSaving}
                    onClick={() => void autoDetectMarkers()}
                  >
                    自动识别控制点
                  </Button>
                  <Popconfirm
                    title="重新自动识别会覆盖当前 Marker（包括已锁定项），是否继续？"
                    onConfirm={() => void autoDetectMarkers(true)}
                  >
                    <Button disabled={!isMutable} loading={markerSaving}>
                      重新自动识别
                    </Button>
                  </Popconfirm>
                  <Popconfirm
                    title="恢复导入默认将使用首点/最低点/末点并覆盖当前 Marker，是否继续？"
                    onConfirm={() => void autoDetectMarkers(true, "FULL_EXTENT")}
                  >
                    <Button disabled={!isMutable} loading={markerSaving}>
                      恢复导入默认
                    </Button>
                  </Popconfirm>
                  <Button
                    disabled={!isMutable}
                    loading={markerSaving}
                    onClick={() => void batchDetect()}
                  >
                    批量识别
                  </Button>
                </Space>
                <Space wrap style={{ marginTop: 12 }}>
                  <span>M1</span>
                  <Select
                    allowClear
                    disabled={!isMutable}
                    value={marker1Sequence}
                    options={markerOptions}
                    placeholder="选择左岸点"
                    onChange={setMarker1Sequence}
                    style={{ minWidth: 190 }}
                  />
                  <span>锁定</span>
                  <Switch
                    disabled={!isMutable}
                    checked={lockMarker1}
                    onChange={setLockMarker1}
                  />
                  <span>M2</span>
                  <Select
                    allowClear
                    disabled={!isMutable}
                    value={marker2Sequence}
                    options={markerOptions}
                    placeholder="选择主槽点"
                    onChange={setMarker2Sequence}
                    style={{ minWidth: 190 }}
                  />
                  <span>锁定</span>
                  <Switch
                    disabled={!isMutable}
                    checked={lockMarker2}
                    onChange={setLockMarker2}
                  />
                  <span>M3</span>
                  <Select
                    allowClear
                    disabled={!isMutable}
                    value={marker3Sequence}
                    options={markerOptions}
                    placeholder="选择右岸点"
                    onChange={setMarker3Sequence}
                    style={{ minWidth: 190 }}
                  />
                  <span>锁定</span>
                  <Switch
                    disabled={!isMutable}
                    checked={lockMarker3}
                    onChange={setLockMarker3}
                  />
                  <Button
                    type="primary"
                    disabled={!isMutable}
                    loading={markerSaving}
                    onClick={() => void saveMarkers()}
                  >
                    人工保存
                  </Button>
                </Space>
                <Descriptions
                  size="small"
                  column={1}
                  style={{ marginTop: 12 }}
                  items={(["M1", "M2", "M3"] as const).map((type) => {
                    const marker = markerByType.get(type);
                    return {
                      key: type,
                      label: type,
                      children: marker
                        ? `Offset ${marker.offset.toFixed(3)} m / Elevation ${marker.elevation.toFixed(3)} m / ${marker.source} / confidence ${marker.confidence.toFixed(2)} / ${marker.review_status} / ${marker.locked ? "LOCKED" : "UNLOCKED"}`
                        : "未设置",
                    };
                  })}
                />
                {activeProfile?.marker_workflow?.warnings.length ? (
                  <Alert
                    style={{ marginTop: 12 }}
                    type="warning"
                    showIcon
                    message="需要人工复核"
                    description={activeProfile.marker_workflow.warnings.join(
                      "、",
                    )}
                  />
                ) : null}
              </Card>
              <Card
                size="small"
                title="水力有效断面与全归槽"
                style={{ marginTop: 12 }}
              >
                <Alert
                  type="warning"
                  showIcon
                  message="全归槽是水动力计算边界假设，不代表实际洪水不会漫堤或发生堤外淹没。"
                />
                <Space wrap style={{ marginTop: 12 }}>
                  <span>有效范围</span>
                  <Select
                    disabled={!isMutable}
                    value={activeExtentMode}
                    onChange={setActiveExtentMode}
                    options={[
                      { value: "FULL_EXTENT", label: "完整断面" },
                      { value: "MARKER_EXTENT", label: "M1–M3" },
                    ]}
                  />
                  <span>岸外处理</span>
                  <Select
                    disabled={!isMutable}
                    value={overbankTreatment}
                    onChange={setOverbankTreatment}
                    options={[
                      { value: "REAL_GEOMETRY", label: "真实断面" },
                      {
                        value: "VERTICAL_EXTENSION",
                        label: "全归槽 / Vertical Extension",
                      },
                    ]}
                  />
                  {overbankTreatment === "VERTICAL_EXTENSION" ? (
                    <>
                      <span>虚拟顶部高程</span>
                      <InputNumber
                        disabled={!isMutable}
                        value={extensionTopElevation}
                        onChange={(value) =>
                          setExtensionTopElevation(value ?? undefined)
                        }
                      />
                      <span>设计最高水位</span>
                      <InputNumber
                        disabled={!isMutable}
                        value={designMaxWaterLevel}
                        onChange={(value) =>
                          setDesignMaxWaterLevel(value ?? undefined)
                        }
                      />
                      <span>安全余高</span>
                      <InputNumber
                        min={0}
                        disabled={!isMutable}
                        value={safetyFreeboard}
                        onChange={(value) => setSafetyFreeboard(value ?? 0)}
                      />
                    </>
                  ) : null}
                  <Button
                    type="primary"
                    disabled={!isMutable}
                    loading={workflowSaving}
                    onClick={() => void saveWorkflow()}
                  >
                    生成 Processed Geometry
                  </Button>
                </Space>
                <Text type="secondary">
                  红色菱形为计算虚拟边界；不会修改或删除任何 Raw Survey Point。
                </Text>
              </Card>
              <SectionProfileChart section={selected} />
            </>
          ) : (
            <div className="data-empty">从左侧选择一个横断面</div>
          )}
        </Card>
      </div>
    </div>
  );
}

type StructureKind = "gate" | "pump";
type StructureRecord = GateRecord | PumpRecord;
interface StructureFormValues {
  dataset_version_id: number;
  river_id: number;
  name: string;
  code: string;
  status: "online" | "offline" | "maintenance" | "fault";
  control_mode: string;
  longitude: number;
  latitude: number;
  gate_type?: string;
  opening_direction?: string;
  width?: number;
  height?: number;
  max_flow?: number;
  bottom_elevation?: number;
  design_flow?: number;
  head?: number;
  power?: number;
  efficiency_curve_json?: string;
}

function StructureDatabasePage({ kind }: { kind: StructureKind }) {
  const isGate = kind === "gate";
  const { datasetVersionId, isMutable } = useDatasetVersion();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<StructureRecord>();
  const [form] = Form.useForm<StructureFormValues>();
  const { data, loading, error, reload } = useRemoteList(
    async () => {
      const response = isGate
        ? await listGateRecords({
            dataset_version_id: datasetVersionId,
            limit: 500,
          })
        : await listPumpRecords({
            dataset_version_id: datasetVersionId,
            limit: 500,
          });
      return { ...response, items: response.items as StructureRecord[] };
    },
    [datasetVersionId, isGate],
    Boolean(datasetVersionId),
  );
  const rivers = useRemoteList(
    () =>
      listRiverRecords({ dataset_version_id: datasetVersionId, limit: 500 }),
    [datasetVersionId],
    Boolean(datasetVersionId),
  );
  const showEditor = (record?: StructureRecord) => {
    if (!datasetVersionId || !isMutable) {
      message.warning("请选择可编辑的草稿版本");
      return;
    }
    setEditing(record);
    const coords = record ? coordinatesOf(record.geometry) : [120.1, 30.25];
    const point = Array.isArray(coords) ? coords : [120.1, 30.25];
    const values: Partial<StructureFormValues> = record
      ? {
          dataset_version_id: record.dataset_version_id,
          river_id: record.river_id,
          name: record.name,
          code: "gate_code" in record ? record.gate_code : record.pump_code,
          status: record.status,
          control_mode: record.control_mode,
          longitude: Number(point[0]),
          latitude: Number(point[1]),
        }
      : {
          dataset_version_id: datasetVersionId,
          river_id: rivers.data?.items[0]?.id,
          status: "offline",
          control_mode: "local",
          longitude: 120.1,
          latitude: 30.25,
        };
    if (record && "gate_code" in record)
      Object.assign(values, {
        gate_type: record.gate_type,
        opening_direction: record.opening_direction,
        width: record.width,
        height: record.height,
        max_flow: record.max_flow,
        bottom_elevation: record.bottom_elevation,
      });
    if (record && "pump_code" in record)
      Object.assign(values, {
        design_flow: record.design_flow,
        head: record.head,
        power: record.power,
        efficiency_curve_json: jsonText(record.efficiency_curve.points),
      });
    if (!record && isGate)
      Object.assign(values, {
        gate_type: "节制闸",
        opening_direction: "vertical",
      });
    if (!record && !isGate)
      Object.assign(values, {
        efficiency_curve_json: "[[0, 0], [0.5, 0.78], [1, 0.84]]",
      });
    form.setFieldsValue(values);
    setOpen(true);
  };
  const submit = async (values: StructureFormValues) => {
    try {
      const geometry = {
        type: "Point",
        coordinates: [values.longitude, values.latitude],
      };
      if (isGate) {
        const payload: GateCreate = {
          dataset_version_id: values.dataset_version_id,
          river_id: values.river_id,
          name: values.name,
          gate_code: values.code,
          gate_type: values.gate_type!,
          opening_direction: values.opening_direction!,
          control_mode: values.control_mode,
          width: values.width!,
          height: values.height!,
          max_flow: values.max_flow!,
          bottom_elevation: values.bottom_elevation!,
          status: values.status,
          geometry,
        };
        if (editing) {
          const { dataset_version_id: _, ...updates } = payload;
          await updateGateRecord(editing.id, updates);
        } else await createGateRecord(payload);
      } else {
        const payload: PumpCreate = {
          dataset_version_id: values.dataset_version_id,
          river_id: values.river_id,
          name: values.name,
          pump_code: values.code,
          design_flow: values.design_flow!,
          head: values.head!,
          power: values.power!,
          efficiency_curve: {
            points: JSON.parse(values.efficiency_curve_json!) as Array<
              Array<number>
            >,
          },
          control_mode: values.control_mode,
          status: values.status,
          geometry,
        };
        if (editing) {
          const { dataset_version_id: _, ...updates } = payload;
          await updatePumpRecord(editing.id, updates);
        } else await createPumpRecord(payload);
      }
      setOpen(false);
      message.success(`${isGate ? "闸门" : "泵站"}已保存`);
      await reload();
    } catch (reason) {
      message.error(reason instanceof Error ? reason.message : "保存失败");
    }
  };
  const rows = data?.items ?? [];
  const columns: ColumnsType<StructureRecord> = [
    {
      title: "编码",
      key: "code",
      render: (_, record) =>
        "gate_code" in record ? record.gate_code : record.pump_code,
    },
    { title: "名称", dataIndex: "name" },
    { title: "河道 ID", dataIndex: "river_id", width: 95 },
    isGate
      ? {
          title: "类型",
          key: "type",
          width: 105,
          render: (_, record) =>
            "gate_type" in record ? record.gate_type : "-",
        }
      : {
          title: "设计流量",
          key: "flow",
          width: 115,
          render: (_, record) =>
            "design_flow" in record ? `${record.design_flow} m³/s` : "-",
        },
    isGate
      ? {
          title: "孔口尺寸",
          key: "size",
          width: 120,
          render: (_, record) =>
            "width" in record ? `${record.width} × ${record.height} m` : "-",
        }
      : {
          title: "扬程 / 功率",
          key: "head",
          width: 140,
          render: (_, record) =>
            "head" in record ? `${record.head} m / ${record.power} kW` : "-",
        },
    { title: "控制", dataIndex: "control_mode", width: 100 },
    {
      title: "状态",
      dataIndex: "status",
      width: 115,
      render: (value?: string) => (
        <Tag
          color={
            value === "online"
              ? "success"
              : value === "fault"
                ? "error"
                : "default"
          }
        >
          {value}
        </Tag>
      ),
    },
    {
      title: "操作",
      key: "actions",
      width: 130,
      render: (_, record) => (
        <Space>
          <Button
            type="text"
            icon={<EditOutlined />}
            disabled={!isMutable}
            onClick={() => showEditor(record)}
          />
          <Popconfirm
            disabled={!isMutable}
            title={`确认删除该${isGate ? "闸门" : "泵站"}？`}
            onConfirm={async () => {
              if (isGate) await deleteGateRecord(record.id);
              else await deletePumpRecord(record.id);
              await reload();
            }}
          >
            <Button
              danger
              type="text"
              icon={<DeleteOutlined />}
              disabled={!isMutable}
            />
          </Popconfirm>
        </Space>
      ),
    },
  ];
  return (
    <div className="data-page">
      <DataPageHeader
        eyebrow={`HYDRAULIC DATABASE / ${isGate ? "GATES" : "PUMPS"}`}
        title={`${isGate ? "闸门" : "泵站"}数据库`}
        description={`维护${isGate ? "闸门尺寸、过流能力、底板高程" : "设计流量、扬程、功率和效率曲线"}及空间位置。`}
        action={
          <Button
            type="primary"
            icon={<PlusOutlined />}
            disabled={!isMutable || !rivers.data?.items.length}
            onClick={() => showEditor()}
          >
            新增{isGate ? "闸门" : "泵站"}
          </Button>
        }
      />
      <DatasetWriteNotice />
      {error && (
        <Alert className="data-alert" type="error" showIcon message={error} />
      )}
      <Card
        className="data-card"
        title={`${isGate ? "闸门" : "泵站"}清单 · ${rows.length} 条`}
      >
        <Table
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={rows}
          pagination={{ pageSize: 12 }}
          scroll={{ x: 900 }}
        />
      </Card>
      <Modal
        open={open}
        title={`${editing ? "编辑" : "新增"}${isGate ? "闸门" : "泵站"}`}
        width={760}
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
        destroyOnHidden
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={(values) => void submit(values)}
        >
          <Row gutter={12}>
            <Col span={6}>
              <Form.Item
                name="dataset_version_id"
                label="版本 ID"
                rules={[{ required: true }]}
              >
                <InputNumber min={1} disabled />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item
                name="river_id"
                label="所属河道"
                rules={[{ required: true }]}
              >
                <Select
                  loading={rivers.loading}
                  options={(rivers.data?.items ?? []).map((river) => ({
                    value: river.id,
                    label: `${river.code} · ${river.name}`,
                  }))}
                />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item
                name="code"
                label="设施编码"
                rules={[{ required: true }]}
              >
                <Input />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item
                name="name"
                label="设施名称"
                rules={[{ required: true }]}
              >
                <Input />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item
                name="control_mode"
                label="控制方式"
                rules={[{ required: true }]}
              >
                <Select
                  options={[
                    { value: "local", label: "就地" },
                    { value: "remote", label: "远程" },
                    { value: "automatic", label: "自动" },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="status"
                label="状态"
                rules={[{ required: true }]}
              >
                <Select
                  options={["online", "offline", "maintenance", "fault"].map(
                    (value) => ({ value, label: value }),
                  )}
                />
              </Form.Item>
            </Col>
            <Col span={4}>
              <Form.Item
                name="longitude"
                label="经度"
                rules={[{ required: true }]}
              >
                <InputNumber />
              </Form.Item>
            </Col>
            <Col span={4}>
              <Form.Item
                name="latitude"
                label="纬度"
                rules={[{ required: true }]}
              >
                <InputNumber />
              </Form.Item>
            </Col>
          </Row>
          {isGate ? (
            <>
              <Row gutter={12}>
                <Col span={6}>
                  <Form.Item
                    name="gate_type"
                    label="闸门类型"
                    rules={[{ required: true }]}
                  >
                    <Input />
                  </Form.Item>
                </Col>
                <Col span={6}>
                  <Form.Item
                    name="opening_direction"
                    label="启闭方向"
                    rules={[{ required: true }]}
                  >
                    <Input />
                  </Form.Item>
                </Col>
                <Col span={6}>
                  <Form.Item
                    name="width"
                    label="宽度（m）"
                    rules={[{ required: true }]}
                  >
                    <InputNumber min={0.01} />
                  </Form.Item>
                </Col>
                <Col span={6}>
                  <Form.Item
                    name="height"
                    label="高度（m）"
                    rules={[{ required: true }]}
                  >
                    <InputNumber min={0.01} />
                  </Form.Item>
                </Col>
              </Row>
              <Row gutter={12}>
                <Col span={12}>
                  <Form.Item
                    name="max_flow"
                    label="最大流量（m³/s）"
                    rules={[{ required: true }]}
                  >
                    <InputNumber min={0} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item
                    name="bottom_elevation"
                    label="底板高程（m）"
                    rules={[{ required: true }]}
                  >
                    <InputNumber style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
              </Row>
            </>
          ) : (
            <>
              <Row gutter={12}>
                <Col span={8}>
                  <Form.Item
                    name="design_flow"
                    label="设计流量（m³/s）"
                    rules={[{ required: true }]}
                  >
                    <InputNumber min={0} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item
                    name="head"
                    label="扬程（m）"
                    rules={[{ required: true }]}
                  >
                    <InputNumber min={0} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item
                    name="power"
                    label="功率（kW）"
                    rules={[{ required: true }]}
                  >
                    <InputNumber min={0} />
                  </Form.Item>
                </Col>
              </Row>
              <Form.Item
                name="efficiency_curve_json"
                label="效率曲线 [流量比, 效率]"
                rules={[{ required: true }]}
              >
                <Input.TextArea rows={4} />
              </Form.Item>
            </>
          )}
        </Form>
      </Modal>
    </div>
  );
}

export const GatesDatabasePage = () => <StructureDatabasePage kind="gate" />;
export const PumpsDatabasePage = () => <StructureDatabasePage kind="pump" />;

export function DataImportPage() {
  const { datasetVersionId, isMutable } = useDatasetVersion();
  const [resource, setResource] = useState<ImportResource>("rivers");
  const [kind, setKind] = useState<"excel" | "csv" | "geojson">("excel");
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [result, setResult] =
    useState<Awaited<ReturnType<typeof uploadDataFile>>>();
  const [loading, setLoading] = useState(false);
  const usesHydraulicWorkflow =
    resource === "rivers" || resource === "cross_sections";
  const hydraulicTemplate =
    resource === "rivers" ? "river-network" : "cross-section";
  const upload = async () => {
    const origin = files[0]?.originFileObj;
    if (!origin) {
      message.warning("请先选择文件");
      return;
    }
    if (!datasetVersionId || !isMutable) {
      message.warning("请选择可编辑的草稿版本");
      return;
    }
    setLoading(true);
    try {
      const response = await uploadDataFile(
        kind,
        resource,
        datasetVersionId,
        origin,
      );
      setResult(response);
      if (response.status === "success")
        message.success(`成功导入 ${response.imported_count} 条`);
    } catch (reason) {
      message.error(reason instanceof Error ? reason.message : "导入失败");
    } finally {
      setLoading(false);
    }
  };
  return (
    <div className="data-page">
      <DataPageHeader
        eyebrow="DATA PIPELINE / IMPORT"
        title="数据导入中心"
        description="河网与横断面统一走水动力预览/提交链路；闸门与泵站继续使用通用原子批量导入。"
      />
      <DatasetWriteNotice />
      <Row gutter={18}>
        <Col xs={24} lg={15}>
          <Card className="data-card" title="上传数据文件">
            <Row gutter={14}>
              <Col span={8}>
                <Text>资源类型</Text>
                <Select
                  value={resource}
                  onChange={(value) => {
                    setResource(value);
                    setFiles([]);
                    setResult(undefined);
                  }}
                  style={{ width: "100%", marginTop: 8 }}
                  options={[
                    { value: "rivers", label: "河道 / 河网" },
                    { value: "cross_sections", label: "横断面" },
                    { value: "gates", label: "闸门" },
                    { value: "pumps", label: "泵站" },
                  ]}
                />
              </Col>
              <Col span={8}>
                <Text>文件格式</Text>
                <Select
                  value={usesHydraulicWorkflow ? "excel" : kind}
                  disabled={usesHydraulicWorkflow}
                  onChange={setKind}
                  style={{ width: "100%", marginTop: 8 }}
                  options={[
                    { value: "excel", label: "Excel .xlsx" },
                    { value: "csv", label: "CSV UTF-8" },
                    { value: "geojson", label: "GeoJSON" },
                  ]}
                />
              </Col>
              <Col span={8}>
                <Text>当前数据版本</Text>
                <InputNumber
                  min={1}
                  value={datasetVersionId}
                  disabled
                  style={{ width: "100%", marginTop: 8 }}
                />
              </Col>
            </Row>
            {usesHydraulicWorkflow ? (
              <Alert
                className="data-alert"
                type="info"
                showIcon
                message="请使用水动力数据管理导入"
                description="河网和断面必须声明坐标系、先预览质量问题，再以同一预览哈希原子提交；通用导入入口不会绕过这些门禁。"
              />
            ) : (
              <Upload.Dragger
                className="data-uploader"
                beforeUpload={() => false}
                maxCount={1}
                fileList={files}
                disabled={!isMutable}
                onChange={({ fileList }) => setFiles(fileList)}
              >
                <p className="ant-upload-drag-icon">
                  <CloudUploadOutlined />
                </p>
                <p className="ant-upload-text">点击或拖拽文件到这里</p>
                <p className="ant-upload-hint">
                  单文件不超过 20 MB；失败批次不会写入部分数据
                </p>
              </Upload.Dragger>
            )}
            <Space wrap>
              {usesHydraulicWorkflow ? (
                <Button type="primary" href="/data-center/hydraulic">
                  进入水动力导入与校核
                </Button>
              ) : (
                <Button
                  type="primary"
                  loading={loading}
                  disabled={!isMutable || !files[0]?.originFileObj}
                  onClick={() => void upload()}
                >
                  开始校验并导入
                </Button>
              )}
              <Button
                icon={<FileExcelOutlined />}
                href={
                  usesHydraulicWorkflow
                    ? `/api/v1/hydraulic/templates/${hydraulicTemplate}`
                    : `/api/v1/import/templates/${resource}`
                }
              >
                下载 Excel 模板
              </Button>
            </Space>
          </Card>
        </Col>
        <Col xs={24} lg={9}>
          <Card className="data-card" title="最近一次导入结果">
            {result ? (
              <>
                <Alert
                  type={result.status === "success" ? "success" : "error"}
                  showIcon
                  message={
                    result.status === "success"
                      ? `已导入 ${result.imported_count} 条`
                      : "导入未写入"
                  }
                  description={`存档：${result.stored_filename}`}
                />
                <div className="import-issues">
                  {result.errors.map((issue) => (
                    <Alert
                      key={`${issue.row}-${issue.message}`}
                      type="error"
                      message={`第 ${issue.row} 行：${issue.message}`}
                    />
                  ))}
                </div>
              </>
            ) : (
              <div className="data-empty">
                {usesHydraulicWorkflow
                  ? "水动力导入的预览、问题和提交结果统一显示在水动力数据管理。"
                  : "完成一次导入后，这里会显示数量和逐行错误。"}
              </div>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
}

export function DataValidationPage() {
  const { datasetVersionId } = useDatasetVersion();
  const [report, setReport] = useState<ValidationReport>();
  const [loading, setLoading] = useState(false);
  const execute = async () => {
    if (!datasetVersionId) return;
    setLoading(true);
    try {
      setReport(await runValidation(datasetVersionId));
    } catch (reason) {
      message.error(reason instanceof Error ? reason.message : "校验失败");
    } finally {
      setLoading(false);
    }
  };
  const columns: ColumnsType<ValidationReport["items"][number]> = [
    { title: "规则", dataIndex: "code", width: 250 },
    { title: "类别", dataIndex: "category", width: 100 },
    {
      title: "结果",
      dataIndex: "severity",
      width: 100,
      render: (value: string) => (
        <Tag
          color={
            value === "passed"
              ? "success"
              : value === "warning"
                ? "warning"
                : "error"
          }
        >
          {value}
        </Tag>
      ),
    },
    { title: "说明", dataIndex: "message" },
    { title: "数量", dataIndex: "count", width: 80 },
  ];
  return (
    <div className="data-page">
      <DataPageHeader
        eyebrow="QUALITY GATE / VALIDATION"
        title="数据校验中心"
        description="在进入水动力模型前，自动检查空间几何、水力断面、建筑物参数、拓扑与模型配置完整性。"
        action={
          <Space>
            <InputNumber
              min={1}
              value={datasetVersionId}
              disabled
              addonBefore="当前版本 ID"
            />
            <Button
              type="primary"
              icon={<SafetyCertificateOutlined />}
              loading={loading}
              disabled={!datasetVersionId}
              onClick={() => void execute()}
            >
              运行校验
            </Button>
          </Space>
        }
      />
      {report ? (
        <>
          <Row gutter={16} className="quality-stats">
            <Col span={6}>
              <Card className="data-card">
                <Statistic
                  title="模型就绪"
                  value={report.summary.is_model_ready ? "是" : "否"}
                  prefix={
                    report.summary.is_model_ready ? (
                      <CheckCircleOutlined />
                    ) : undefined
                  }
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card className="data-card">
                <Statistic
                  title="错误规则"
                  value={report.summary.errors}
                  valueStyle={{
                    color: report.summary.errors ? "#ff6b68" : "#2fe6d6",
                  }}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card className="data-card">
                <Statistic title="警告规则" value={report.summary.warnings} />
              </Card>
            </Col>
            <Col span={6}>
              <Card className="data-card">
                <Statistic title="通过规则" value={report.summary.passed} />
              </Card>
            </Col>
          </Row>
          <Card
            className="data-card"
            title={`校验报告 · ${new Date(report.checked_time).toLocaleString()}`}
          >
            <Progress
              percent={Math.round(
                (report.summary.passed / Math.max(report.items.length, 1)) *
                  100,
              )}
              status={report.summary.errors ? "exception" : "success"}
            />
            <Table
              rowKey="code"
              columns={columns}
              dataSource={report.items}
              pagination={false}
              scroll={{ x: 820 }}
            />
          </Card>
        </>
      ) : (
        <Card className="data-card">
          <div className="data-empty">
            选择数据版本并运行校验，结果将按错误、警告和通过分类展示。
          </div>
        </Card>
      )}
    </div>
  );
}

interface ModelParameterFormValues {
  parameter_type: string;
  parameter_name: string;
  value: number;
  unit: string;
  description?: string;
}

interface BoundaryFormValues {
  name: string;
  boundary_type: BoundaryConditionCreate["boundary_type"];
  hydraulic_node_id?: number;
  branch_id?: number;
  chainage_m?: number;
  values_json: string;
  unit: string;
  description?: string;
  source_discharge_boundary_id?: number;
  rating_curve_friction_slope?: number;
}

interface HydraulicEndpointOption {
  value: number;
  label: string;
  disabled?: boolean;
}

/**
 * Build unambiguous topology endpoint choices for one hydraulic boundary type.
 *
 * The backend binds endpoint boundaries by authoritative node ID. Presenting the
 * branch-relative direction and stable node code prevents operators from copying
 * opaque numeric IDs from a separate screen. A node used by multiple branches in
 * the same direction remains visible for diagnosis but is disabled because the
 * backend intentionally rejects that ambiguous binding.
 */
function hydraulicEndpointOptions(
  networks: HydraulicNetworkRecord[],
  boundaryType: BoundaryConditionCreate["boundary_type"] | undefined,
): HydraulicEndpointOption[] {
  if (
    boundaryType !== "upstream_discharge" &&
    boundaryType !== "downstream_water_level"
  )
    return [];
  const direction =
    boundaryType === "upstream_discharge" ? "上游" : "下游";
  const nodes = new Map(
    networks.flatMap((network) => network.nodes ?? []).map((node) => [node.id, node]),
  );
  const branchesByNode = new Map<number, string[]>();
  networks.forEach((network) => {
    (network.branches ?? []).forEach((branch) => {
      const nodeId =
        boundaryType === "upstream_discharge"
          ? branch.upstream_node_id
          : branch.downstream_node_id;
      if (nodeId == null) return;
      const branches = branchesByNode.get(nodeId) ?? [];
      branches.push(`${network.code}/${branch.branch_code}`);
      branchesByNode.set(nodeId, branches);
    });
  });
  return [...branchesByNode.entries()]
    .sort(([left], [right]) => left - right)
    .map(([nodeId, branches]) => {
      const node = nodes.get(nodeId);
      const ambiguous = branches.length !== 1;
      return {
        value: nodeId,
        label: `${direction} · ${node?.node_code ?? "节点编码缺失"} · ID ${nodeId} · ${branches.join("、")}${ambiguous ? " · 多河段共用，不可唯一绑定" : ""}`,
        disabled: ambiguous || node == null,
      };
    });
}

interface SimulationCaseFormValues {
  name: string;
  description?: string;
  boundary_condition_ids: number[];
}

/** 提供模型参数、边界条件与计算方案的草稿编辑，以及任意版本的只读快照。 */
export function ModelDataPage() {
  const { versions, datasetVersionId, isMutable, refreshVersions } =
    useDatasetVersion();
  const [snapshot, setSnapshot] = useState<Hydraulic1DPreviewResponse>();
  const [parameterOpen, setParameterOpen] = useState(false);
  const [parameterEditing, setParameterEditing] =
    useState<ModelParameterRecord>();
  const [boundaryOpen, setBoundaryOpen] = useState(false);
  const [boundaryEditing, setBoundaryEditing] =
    useState<BoundaryConditionRecord>();
  const [caseOpen, setCaseOpen] = useState(false);
  const [caseEditing, setCaseEditing] = useState<SimulationCaseRecord>();
  const [submitting, setSubmitting] = useState(false);
  const [ratingCurveLoading, setRatingCurveLoading] = useState(false);
  const [ratingCurvePreview, setRatingCurvePreview] =
    useState<BoundaryRatingCurveGenerateResponse>();
  const [approvingVersionId, setApprovingVersionId] = useState<number>();
  const [parameterForm] = Form.useForm<ModelParameterFormValues>();
  const [boundaryForm] = Form.useForm<BoundaryFormValues>();
  const [caseForm] = Form.useForm<SimulationCaseFormValues>();
  const boundaryType = Form.useWatch("boundary_type", boundaryForm);
  const hydraulicNetworks = useRemoteList(
    () => listHydraulicNetworks(datasetVersionId!),
    [datasetVersionId],
    Boolean(datasetVersionId),
  );
  const parameters = useRemoteList(
    () => getModelParameters(datasetVersionId),
    [datasetVersionId],
    Boolean(datasetVersionId),
  );
  const boundaries = useRemoteList(
    () => getBoundaryConditions(datasetVersionId),
    [datasetVersionId],
    Boolean(datasetVersionId),
  );
  const cases = useRemoteList(
    () => getSimulationCases(datasetVersionId),
    [datasetVersionId],
    Boolean(datasetVersionId),
  );
  const endpointOptions = useMemo(
    () => hydraulicEndpointOptions(hydraulicNetworks.data ?? [], boundaryType),
    [boundaryType, hydraulicNetworks.data],
  );

  useEffect(() => setSnapshot(undefined), [datasetVersionId]);

  /** 执行删除并统一反馈数据库约束或生命周期错误。 */
  const removeRecord = async (
    action: () => Promise<void>,
    label: string,
    reload: () => Promise<void>,
  ) => {
    try {
      await action();
      await reload();
      message.success(`${label}已删除`);
    } catch (reason) {
      message.error(
        reason instanceof Error ? reason.message : `${label}删除失败`,
      );
    }
  };

  /** 打开模型参数编辑器；标识字段创建后保持稳定。 */
  const editParameter = (record?: ModelParameterRecord) => {
    if (!datasetVersionId || !isMutable) return;
    setParameterEditing(record);
    parameterForm.setFieldsValue(
      record
        ? {
            parameter_type: record.parameter_type,
            parameter_name: record.parameter_name,
            value: record.value,
            unit: record.unit,
            description: record.description ?? undefined,
          }
        : { parameter_type: "hydraulic", unit: "—", value: 0 },
    );
    setParameterOpen(true);
  };

  /** 保存当前草稿的模型参数。 */
  const saveParameter = async (values: ModelParameterFormValues) => {
    if (!datasetVersionId || !isMutable) return;
    setSubmitting(true);
    try {
      if (parameterEditing) {
        await updateModelParameter(parameterEditing.id, {
          value: values.value,
          unit: values.unit,
          description: values.description,
        });
      } else {
        const payload: ModelParameterCreate = {
          dataset_version_id: datasetVersionId,
          ...values,
        };
        await createModelParameter(payload);
      }
      setParameterOpen(false);
      parameterForm.resetFields();
      await parameters.reload();
      message.success("模型参数已保存");
    } catch (reason) {
      message.error(
        reason instanceof Error ? reason.message : "模型参数保存失败",
      );
    } finally {
      setSubmitting(false);
    }
  };

  /** 打开边界条件编辑器，并用可审查 JSON 呈现定值或时间序列。 */
  const editBoundary = (record?: BoundaryConditionRecord) => {
    if (!datasetVersionId || !isMutable) return;
    setBoundaryEditing(record);
    setRatingCurvePreview(undefined);
    const storedValues = record?.values as Record<string, unknown> | undefined;
    boundaryForm.setFieldsValue(
      record
        ? {
            name: record.name,
            boundary_type: record.boundary_type,
            hydraulic_node_id: record.hydraulic_node_id ?? undefined,
            branch_id: record.branch_id ?? undefined,
            chainage_m: record.chainage_m ?? undefined,
            values_json: jsonText(record.values),
            unit: record.unit,
            description: record.description ?? undefined,
            source_discharge_boundary_id:
              typeof storedValues?.source_discharge_boundary_id === "number"
                ? storedValues.source_discharge_boundary_id
                : undefined,
            rating_curve_friction_slope:
              typeof storedValues?.friction_slope === "number"
                ? storedValues.friction_slope
                : undefined,
          }
        : {
            boundary_type: "upstream_discharge",
            values_json: '{\n  "mode": "constant",\n  "value": 0\n}',
            unit: "m³/s",
          },
    );
    setBoundaryOpen(true);
  };

  /** Generate a traceable downstream Q-H curve and place its JSON in the editor. */
  const generateRatingCurve = async () => {
    if (!datasetVersionId || boundaryType !== "downstream_water_level") return;
    try {
      await boundaryForm.validateFields([
        "hydraulic_node_id",
        "source_discharge_boundary_id",
        "rating_curve_friction_slope",
      ]);
      const hydraulicNodeId = boundaryForm.getFieldValue("hydraulic_node_id");
      const sourceBoundaryId = boundaryForm.getFieldValue(
        "source_discharge_boundary_id",
      );
      const frictionSlope = boundaryForm.getFieldValue(
        "rating_curve_friction_slope",
      );
      setRatingCurveLoading(true);
      const preview = await generateBoundaryRatingCurve({
        dataset_version_id: datasetVersionId,
        hydraulic_node_id: hydraulicNodeId,
        source_discharge_boundary_id: sourceBoundaryId,
        friction_slope: frictionSlope,
        vertical_step_m: 0.05,
        maximum_depth_m: 50,
      });
      boundaryForm.setFieldsValue({
        values_json: jsonText(preview.values),
        unit: "m",
      });
      setRatingCurvePreview(preview);
      message.success(
        `已由 ${preview.cross_section_code} 生成关系曲线，下游水位 ${preview.resolved_water_level_m.toFixed(3)} m`,
      );
    } catch (reason) {
      if (reason instanceof Error) message.error(reason.message);
    } finally {
      setRatingCurveLoading(false);
    }
  };

  /** 保存边界条件并拒绝非对象 JSON。 */
  const saveBoundary = async (values: BoundaryFormValues) => {
    if (!datasetVersionId || !isMutable) return;
    setSubmitting(true);
    try {
      const parsed: unknown = JSON.parse(values.values_json);
      if (
        typeof parsed !== "object" ||
        parsed === null ||
        Array.isArray(parsed)
      )
        throw new Error("边界值必须是 JSON 对象");
      const payload: BoundaryConditionCreate = {
        dataset_version_id: datasetVersionId,
        name: values.name,
        boundary_type: values.boundary_type,
        hydraulic_node_id:
          values.boundary_type === "lateral_inflow"
            ? undefined
            : values.hydraulic_node_id,
        branch_id:
          values.boundary_type === "lateral_inflow"
            ? values.branch_id
            : undefined,
        chainage_m:
          values.boundary_type === "lateral_inflow"
            ? values.chainage_m
            : undefined,
        values: parsed as Record<string, unknown>,
        unit: values.unit,
        description: values.description,
      };
      if (boundaryEditing) {
        const { dataset_version_id: _, ...updates } = payload;
        await updateBoundaryCondition(boundaryEditing.id, updates);
      } else {
        await createBoundaryCondition(payload);
      }
      setBoundaryOpen(false);
      boundaryForm.resetFields();
      await boundaries.reload();
      message.success("边界条件已保存");
    } catch (reason) {
      message.error(
        reason instanceof Error ? reason.message : "边界条件保存失败",
      );
    } finally {
      setSubmitting(false);
    }
  };

  /** 打开计算方案编辑器，并限制边界来源为当前版本。 */
  const editCase = (record?: SimulationCaseRecord) => {
    if (!datasetVersionId || !isMutable) return;
    setCaseEditing(record);
    caseForm.setFieldsValue(
      record
        ? {
            name: record.name,
            description: record.description ?? undefined,
            boundary_condition_ids: record.boundary_condition_ids?.length
              ? record.boundary_condition_ids
              : [record.boundary_condition_id],
          }
        : {
            boundary_condition_ids: boundaries.data?.[0]
              ? [boundaries.data[0].id]
              : [],
          },
    );
    setCaseOpen(true);
  };

  /** 保存计算方案并同时提交主边界和完整边界组。 */
  const saveCase = async (values: SimulationCaseFormValues) => {
    if (
      !datasetVersionId ||
      !isMutable ||
      values.boundary_condition_ids.length === 0
    )
      return;
    setSubmitting(true);
    try {
      const payload: SimulationCaseCreate = {
        dataset_version_id: datasetVersionId,
        name: values.name,
        description: values.description,
        boundary_condition_id: values.boundary_condition_ids[0],
        boundary_condition_ids: values.boundary_condition_ids,
      };
      if (caseEditing) {
        const { dataset_version_id: _, ...updates } = payload;
        await updateSimulationCase(caseEditing.id, updates);
      } else {
        await createSimulationCase(payload);
      }
      setCaseOpen(false);
      caseForm.resetFields();
      await cases.reload();
      message.success("计算方案已保存");
    } catch (reason) {
      message.error(
        reason instanceof Error ? reason.message : "计算方案保存失败",
      );
    } finally {
      setSubmitting(false);
    }
  };

  /** 用核心 QA 与真实 Standard 1D 映射校核草稿，通过后冻结为权威计算版本。 */
  const approveForCalculation = async (record: DatasetVersionRecord) => {
    setApprovingVersionId(record.id);
    try {
      await approveDatasetVersionForCalculation(record.id, {
        reviewer: "web-operator",
        reason: "核心数据校核和全部 Standard 1D 方案映射通过，冻结用于计算",
      });
      await refreshVersions(record.id);
      message.success(`${record.version} 已校核并冻结，可用于一维水动力计算`);
    } catch (reason) {
      message.error(
        reason instanceof Error ? reason.message : "数据版本校核冻结失败",
      );
    } finally {
      setApprovingVersionId(undefined);
    }
  };

  const tabs = [
    {
      key: "versions",
      label: `数据版本 ${versions.length}`,
      children: (
        <Table
          rowKey="id"
          dataSource={versions}
          pagination={false}
          columns={[
            { title: "版本", dataIndex: "version" },
            { title: "名称", dataIndex: "name" },
            {
              title: "状态",
              dataIndex: "status",
              render: (value: string) => (
                <Tag
                  color={
                    value === "draft"
                      ? "gold"
                      : value === "approved" || value === "published"
                        ? "success"
                        : "default"
                  }
                >
                  {datasetVersionStatusLabel(value)}
                </Tag>
              ),
            },
            { title: "创建者", dataIndex: "creator" },
            {
              title: "创建时间",
              dataIndex: "created_time",
              render: (value: string) => new Date(value).toLocaleString(),
            },
            {
              title: "计算发布",
              width: 150,
              render: (_, record: DatasetVersionRecord) =>
                record.status === "draft" ? (
                  <Popconfirm
                    title="校核并冻结该数据版本？"
                    description="将检查全部数据规则和计算方案映射；通过后版本不可再编辑。"
                    okText="校核并冻结"
                    cancelText="取消"
                    onConfirm={() => approveForCalculation(record)}
                  >
                    <Button
                      type="primary"
                      size="small"
                      icon={<SafetyCertificateOutlined />}
                      loading={approvingVersionId === record.id}
                    >
                      校核并冻结
                    </Button>
                  </Popconfirm>
                ) : (
                  <Text type="secondary">已冻结</Text>
                ),
            },
          ]}
        />
      ),
    },
    {
      key: "parameters",
      label: `模型参数 ${parameters.data?.length ?? 0}`,
      children: (
        <Table
          rowKey="id"
          loading={parameters.loading}
          dataSource={parameters.data ?? []}
          pagination={false}
          title={() => (
            <Button
              type="primary"
              icon={<PlusOutlined />}
              disabled={!isMutable}
              onClick={() => editParameter()}
            >
              新增模型参数
            </Button>
          )}
          columns={[
            { title: "类型", dataIndex: "parameter_type" },
            { title: "参数", dataIndex: "parameter_name" },
            { title: "数值", dataIndex: "value" },
            { title: "单位", dataIndex: "unit" },
            {
              title: "操作",
              width: 130,
              render: (_, record: ModelParameterRecord) => (
                <Space>
                  <Button
                    type="text"
                    icon={<EditOutlined />}
                    disabled={!isMutable}
                    onClick={() => editParameter(record)}
                  />
                  <Popconfirm
                    disabled={!isMutable}
                    title="确认删除该参数？"
                    onConfirm={() =>
                      removeRecord(
                        () => deleteModelParameter(record.id),
                        "模型参数",
                        parameters.reload,
                      )
                    }
                  >
                    <Button
                      type="text"
                      danger
                      icon={<DeleteOutlined />}
                      disabled={!isMutable}
                    />
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      ),
    },
    {
      key: "boundaries",
      label: `边界条件 ${boundaries.data?.length ?? 0}`,
      children: (
        <Table
          rowKey="id"
          loading={boundaries.loading}
          dataSource={boundaries.data ?? []}
          pagination={false}
          title={() => (
            <Button
              type="primary"
              icon={<PlusOutlined />}
              disabled={!isMutable}
              onClick={() => editBoundary()}
            >
              新增边界条件
            </Button>
          )}
          columns={[
            { title: "名称", dataIndex: "name" },
            { title: "类型", dataIndex: "boundary_type" },
            {
              title: "水力位置",
              render: (_, record: BoundaryConditionRecord) =>
                record.boundary_type === "lateral_inflow"
                  ? `Branch #${record.branch_id ?? "—"} · ${record.chainage_m ?? "—"} m`
                  : `Node #${record.hydraulic_node_id ?? "—"}`,
            },
            { title: "单位", dataIndex: "unit" },
            {
              title: "操作",
              width: 130,
              render: (_, record: BoundaryConditionRecord) => (
                <Space>
                  <Button
                    type="text"
                    icon={<EditOutlined />}
                    disabled={!isMutable}
                    onClick={() => editBoundary(record)}
                  />
                  <Popconfirm
                    disabled={!isMutable}
                    title="确认删除该边界？"
                    onConfirm={() =>
                      removeRecord(
                        () => deleteBoundaryCondition(record.id),
                        "边界条件",
                        boundaries.reload,
                      )
                    }
                  >
                    <Button
                      type="text"
                      danger
                      icon={<DeleteOutlined />}
                      disabled={!isMutable}
                    />
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      ),
    },
    {
      key: "cases",
      label: `计算方案 ${cases.data?.length ?? 0}`,
      children: (
        <Table
          rowKey="id"
          loading={cases.loading}
          dataSource={cases.data ?? []}
          pagination={false}
          title={() => (
            <Button
              type="primary"
              icon={<PlusOutlined />}
              disabled={!isMutable || !boundaries.data?.length}
              onClick={() => editCase()}
            >
              新增计算方案
            </Button>
          )}
          columns={[
            { title: "名称", dataIndex: "name" },
            { title: "数据版本", dataIndex: "dataset_version_id" },
            {
              title: "边界条件",
              dataIndex: "boundary_condition_ids",
              render: (value: number[]) => value.join(", "),
            },
            {
              title: "操作",
              width: 270,
              render: (_, record: SimulationCaseRecord) => (
                <Space>
                  <Button
                    onClick={async () => {
                      try {
                        setSnapshot(
                          await previewHydraulicModel({ case_id: record.id }),
                        );
                      } catch (reason) {
                        message.error(
                          reason instanceof Error
                            ? reason.message
                            : "模型输入预览失败",
                        );
                      }
                    }}
                  >
                    查看模型输入
                  </Button>
                  <Button
                    type="text"
                    icon={<EditOutlined />}
                    disabled={!isMutable}
                    onClick={() => editCase(record)}
                  />
                  <Popconfirm
                    disabled={!isMutable}
                    title="确认删除该方案？"
                    onConfirm={() =>
                      removeRecord(
                        () => deleteSimulationCase(record.id),
                        "计算方案",
                        cases.reload,
                      )
                    }
                  >
                    <Button
                      type="text"
                      danger
                      icon={<DeleteOutlined />}
                      disabled={!isMutable}
                    />
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      ),
    },
  ];
  const summary = snapshot?.readiness.input_summary;
  const inputCounts = summary
    ? [
        { label: "河段", value: Number(summary.branch_count ?? 0) },
        { label: "断面", value: Number(summary.section_count ?? 0) },
        { label: "边界", value: Number(summary.boundary_count ?? 0) },
        { label: "建筑物", value: Number(summary.structure_count ?? 0) },
      ]
    : [];

  return (
    <div className="data-page">
      <DataPageHeader
        eyebrow="PHASE 3 HANDOFF / MODEL DATA"
        title="模型数据管理"
        description="草稿可维护参数、边界条件和计算方案；已发布版本只生成可追溯模型输入快照。"
      />
      <DatasetWriteNotice />
      <Card className="data-card">
        <Tabs items={tabs} />
      </Card>
      {snapshot && (
        <Card
          className="data-card model-snapshot"
          title={`Standard 1D 输入预览 · ${String(summary?.scenario_id ?? `Case #${snapshot.readiness.case_id}`)}`}
          extra={
            <Tag
              color={
                snapshot.readiness.ready
                  ? "success"
                  : snapshot.snapshot_hash
                    ? "warning"
                    : "error"
              }
            >
              {String(summary?.schema_version ?? "未生成")}
            </Tag>
          }
        >
          <Row gutter={12}>
            {inputCounts.map((item) => (
              <Col key={item.label} span={6}>
                <Statistic title={item.label} value={item.value} />
              </Col>
            ))}
          </Row>
          <Descriptions
            className="snapshot-meta"
            column={2}
            items={[
              {
                key: "dataset",
                label: "数据版本 ID",
                children: String(summary?.dataset_version_id ?? "—"),
              },
              {
                key: "engine",
                label: "引擎",
                children: `${snapshot.readiness.engine_id ?? "mascaret"} ${snapshot.readiness.engine_version ?? "v9.1.1"}`,
              },
              {
                key: "runtime",
                label: "运行时",
                children: snapshot.readiness.runtime_available
                  ? "可用"
                  : snapshot.readiness.runtime_detail,
              },
              {
                key: "hash",
                label: "冻结输入哈希",
                children: snapshot.snapshot_hash ?? "—",
              },
            ]}
          />
        </Card>
      )}

      <Modal
        open={parameterOpen}
        title={parameterEditing ? "编辑模型参数" : "新增模型参数"}
        onCancel={() => setParameterOpen(false)}
        onOk={() => parameterForm.submit()}
        confirmLoading={submitting}
        destroyOnHidden
      >
        <Form
          form={parameterForm}
          layout="vertical"
          onFinish={(values) => void saveParameter(values)}
        >
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item
                name="parameter_type"
                label="参数类型"
                rules={[{ required: true }]}
              >
                <Input disabled={Boolean(parameterEditing)} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="parameter_name"
                label="参数名称"
                rules={[{ required: true }]}
              >
                <Input disabled={Boolean(parameterEditing)} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="value" label="数值" rules={[{ required: true }]}>
                <InputNumber style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="unit" label="单位" rules={[{ required: true }]}>
                <Input />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={boundaryOpen}
        title={boundaryEditing ? "编辑边界条件" : "新增边界条件"}
        onCancel={() => setBoundaryOpen(false)}
        onOk={() => boundaryForm.submit()}
        confirmLoading={submitting}
        destroyOnHidden
        width={680}
      >
        <Form
          form={boundaryForm}
          layout="vertical"
          onFinish={(values) => void saveBoundary(values)}
        >
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="name" label="名称" rules={[{ required: true }]}>
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="boundary_type"
                label="边界类型"
                rules={[{ required: true }]}
              >
                <Select
                  onChange={(value: BoundaryFormValues["boundary_type"]) => {
                    setRatingCurvePreview(undefined);
                    boundaryForm.setFieldsValue({
                      hydraulic_node_id: undefined,
                      branch_id: undefined,
                      chainage_m: undefined,
                      source_discharge_boundary_id: undefined,
                      rating_curve_friction_slope: undefined,
                      unit: value === "downstream_water_level" ? "m" : "m³/s",
                    });
                  }}
                  options={[
                    { value: "upstream_discharge", label: "上游流量" },
                    { value: "downstream_water_level", label: "下游水位" },
                    { value: "lateral_inflow", label: "侧向入流" },
                  ]}
                />
              </Form.Item>
            </Col>
          </Row>
          {boundaryType === "lateral_inflow" ? (
            <Row gutter={12}>
              <Col span={12}>
                <Form.Item
                  preserve={false}
                  name="branch_id"
                  label="水力河段 ID"
                  rules={[{ required: true }]}
                >
                  <InputNumber
                    min={1}
                    precision={0}
                    style={{ width: "100%" }}
                  />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item
                  preserve={false}
                  name="chainage_m"
                  label="定向桩号（m）"
                  rules={[{ required: true }]}
                >
                  <InputNumber min={0} style={{ width: "100%" }} />
                </Form.Item>
              </Col>
            </Row>
          ) : (
            <Form.Item
              preserve={false}
              name="hydraulic_node_id"
              label="水力端点"
              rules={[{ required: true }]}
              extra={
                hydraulicNetworks.error ||
                "只列出当前数据版本拓扑中与边界类型一致的上游/下游端点。"
              }
            >
              <Select
                showSearch
                optionFilterProp="label"
                loading={hydraulicNetworks.loading}
                status={hydraulicNetworks.error ? "error" : undefined}
                placeholder={
                  boundaryType === "upstream_discharge"
                    ? "选择上游端点"
                    : "选择下游端点"
                }
                options={endpointOptions}
                notFoundContent={
                  hydraulicNetworks.loading
                    ? "正在加载拓扑节点…"
                    : "当前版本没有可绑定的定向端点"
                }
              />
            </Form.Item>
          )}
          {boundaryType === "downstream_water_level" && (
            <Card size="small" title="自动生成水位—流量关系曲线" style={{ marginBottom: 16 }}>
              <Row gutter={12}>
                <Col span={14}>
                  <Form.Item
                    name="source_discharge_boundary_id"
                    label="对应上游流量边界"
                    rules={[{ required: true, message: "请选择上游流量边界" }]}
                  >
                    <Select
                      showSearch
                      optionFilterProp="label"
                      placeholder="选择本方案采用的上游流量"
                      options={(boundaries.data ?? [])
                        .filter((item) => item.boundary_type === "upstream_discharge")
                        .map((item) => ({
                          value: item.id,
                          label: `${item.name} · ID ${item.id}`,
                        }))}
                    />
                  </Form.Item>
                </Col>
                <Col span={10}>
                  <Form.Item
                    name="rating_curve_friction_slope"
                    label="摩阻坡降（可选）"
                    rules={[{ type: "number", min: 0.000000001, max: 1 }]}
                    extra="留空时由末两个断面深泓高程推算"
                  >
                    <InputNumber style={{ width: "100%" }} precision={8} />
                  </Form.Item>
                </Col>
              </Row>
              <Button
                type="primary"
                loading={ratingCurveLoading}
                onClick={() => void generateRatingCurve()}
              >
                根据下游断面自动生成
              </Button>
              {ratingCurvePreview && (
                <Alert
                  style={{ marginTop: 12 }}
                  type="warning"
                  showIcon
                  message={`生成完成：${ratingCurvePreview.curve.length} 点，H=${ratingCurvePreview.resolved_water_level_m.toFixed(3)} m`}
                  description={`${ratingCurvePreview.cross_section_code} · 坡降 ${ratingCurvePreview.friction_slope.toPrecision(6)} · ${(ratingCurvePreview.warnings ?? []).join("；")}`}
                />
              )}
            </Card>
          )}
          <Form.Item name="unit" label="单位" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item
            name="values_json"
            label="边界值 JSON"
            rules={[{ required: true }]}
            extra="支持定值、时间序列或上方生成的 Q–H 关系曲线；水力位置由独立字段保存。"
          >
            <Input.TextArea rows={6} />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={caseOpen}
        title={caseEditing ? "编辑计算方案" : "新增计算方案"}
        onCancel={() => setCaseOpen(false)}
        onOk={() => caseForm.submit()}
        confirmLoading={submitting}
        destroyOnHidden
      >
        <Form
          form={caseForm}
          layout="vertical"
          onFinish={(values) => void saveCase(values)}
        >
          <Form.Item name="name" label="方案名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item
            name="boundary_condition_ids"
            label="边界条件"
            rules={[{ required: true, type: "array", min: 1 }]}
          >
            <Select
              mode="multiple"
              options={(boundaries.data ?? []).map((boundary) => ({
                value: boundary.id,
                label: `${boundary.name} · ${boundary.boundary_type}`,
              }))}
            />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
