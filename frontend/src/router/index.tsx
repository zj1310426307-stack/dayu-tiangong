import {
  ApartmentOutlined,
  AimOutlined,
  AppstoreOutlined,
  BulbOutlined,
  ControlOutlined,
  DatabaseOutlined,
  DeploymentUnitOutlined,
  ExperimentOutlined,
  FileDoneOutlined,
  GlobalOutlined,
  ImportOutlined,
  PartitionOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { Button, Result } from 'antd';
import { lazy, Suspense } from 'react';
import { createBrowserRouter, Navigate, useRouteError } from 'react-router-dom';
import { MainLayout } from '../layout/MainLayout';
import type { NavigationItem } from '../types/navigation';
import { DatasetVersionProvider } from '../context/DatasetVersionContext';

// 地图页面按路由动态加载，避免非地图功能提前下载 OpenLayers 地图代码。
const HomePage = lazy(() =>
  import('../pages/HomePage').then((module) => ({ default: module.HomePage })),
);
const GisPage = lazy(() =>
  import('../pages/GisPage').then((module) => ({ default: module.GisPage })),
);
const RiversDatabasePage = lazy(() => import('../pages/data-center/DataCenterPages').then((module) => ({ default: module.RiversDatabasePage })));
const CrossSectionsDatabasePage = lazy(() => import('../pages/data-center/DataCenterPages').then((module) => ({ default: module.CrossSectionsDatabasePage })));
const GatesDatabasePage = lazy(() => import('../pages/data-center/DataCenterPages').then((module) => ({ default: module.GatesDatabasePage })));
const PumpsDatabasePage = lazy(() => import('../pages/data-center/DataCenterPages').then((module) => ({ default: module.PumpsDatabasePage })));
const DataImportPage = lazy(() => import('../pages/data-center/DataCenterPages').then((module) => ({ default: module.DataImportPage })));
const DataValidationPage = lazy(() => import('../pages/data-center/DataCenterPages').then((module) => ({ default: module.DataValidationPage })));
const ModelDataPage = lazy(() => import('../pages/data-center/DataCenterPages').then((module) => ({ default: module.ModelDataPage })));
const HydraulicDataPage = lazy(() => import('../pages/hydraulic-data/HydraulicDataPage').then((module) => ({ default: module.HydraulicDataPage })));
const HydraulicConfigPage = lazy(() => import('../pages/hydraulic/HydraulicPages').then((module) => ({ default: module.HydraulicConfigPage })));
const HydraulicTasksPage = lazy(() => import('../pages/hydraulic/HydraulicPages').then((module) => ({ default: module.HydraulicTasksPage })));
const HydraulicResultsPage = lazy(() => import('../pages/hydraulic/HydraulicPages').then((module) => ({ default: module.HydraulicResultsPage })));
const ProductionWorkspacePage = lazy(() => import('../pages/hydraulic/ProductionWorkspacePage').then((module) => ({ default: module.ProductionWorkspacePage })));
const DispatchPlanListPage = lazy(() => import('../pages/dispatch/DispatchPages').then((module) => ({ default: module.DispatchPlanListPage })));
const DispatchPlanEditorPage = lazy(() => import('../pages/dispatch/DispatchPages').then((module) => ({ default: module.DispatchPlanEditorPage })));
const DispatchRunListPage = lazy(() => import('../pages/dispatch/DispatchPages').then((module) => ({ default: module.DispatchRunListPage })));
const DispatchRunDetailPage = lazy(() => import('../pages/dispatch/DispatchPages').then((module) => ({ default: module.DispatchRunDetailPage })));
const OptimizationHomePage = lazy(() => import('../pages/optimization/OptimizationPages').then((module) => ({ default: module.OptimizationHomePage })));
const OptimizationTasksPage = lazy(() => import('../pages/optimization/OptimizationPages').then((module) => ({ default: module.OptimizationTasksPage })));
const OptimizationTaskDetailPage = lazy(() => import('../pages/optimization/OptimizationPages').then((module) => ({ default: module.OptimizationTaskDetailPage })));
const AIAssistantPage = lazy(() => import('../pages/ai/AIAssistantPage').then((module) => ({ default: module.AIAssistantPage })));

// 在动态页面代码到达前提供可感知状态，避免首次进入地图时出现空白区域。
function RouteLoading({ label }: { label: string }) {
  return (
    <div className="route-loading" role="status" aria-live="polite">
      <span className="route-loading__pulse" />
      <strong>{label}</strong>
    </div>
  );
}

/** 捕获路由渲染和动态代码块加载错误，提供可见原因与恢复入口。 */
function RouteErrorPage() {
  const error = useRouteError();
  const detail = error instanceof Error ? error.message : '页面资源加载失败或当前模块发生异常。';
  return (
    <Result
      status="error"
      title="模块加载失败"
      subTitle={detail}
      extra={[
        <Button key="reload" type="primary" onClick={() => window.location.reload()}>重新加载</Button>,
        <Button key="home" onClick={() => window.location.assign('/')}>返回首页</Button>,
      ]}
    />
  );
}

// 导航元数据是菜单和路由的单一来源，防止后续模块扩展时出现名称漂移。
export const navigationItems: NavigationItem[] = [
  {
    key: 'home',
    label: '首页',
    path: '/',
    icon: <AppstoreOutlined />,
    eyebrow: 'COMMAND CENTER',
    description: '查看河网运行态势、核心资产和平台能力入口。',
  },
  {
    key: 'gis',
    label: 'GIS 一张图',
    path: '/gis',
    icon: <GlobalOutlined />,
    eyebrow: 'SPATIAL TWIN',
    description: '承载 OpenLayers 河网、设施与专题图层。',
  },
  {
    key: 'hydraulic-data',
    label: '水动力数据管理',
    path: '/data-center/hydraulic',
    icon: <ApartmentOutlined />,
    eyebrow: 'HYDRAULIC EXCHANGE',
    description: '管理河网、桩号、断面剖面与 MIKE11 交换。',
  },
  {
    key: 'data-rivers',
    label: '河道数据库',
    path: '/data-center/rivers',
    icon: <DeploymentUnitOutlined />,
    eyebrow: 'HYDRAULIC DATABASE',
    description: '管理版本化河道、空间线和河网拓扑。',
  },
  {
    key: 'data-sections',
    label: '横断面数据库',
    path: '/data-center/cross-sections',
    icon: <PartitionOutlined />,
    eyebrow: 'SECTION PROFILES',
    description: '管理桩号、剖面高程点、糙率与测量日期。',
  },
  {
    key: 'data-gates',
    label: '闸门数据库',
    path: '/data-center/gates',
    icon: <ControlOutlined />,
    eyebrow: 'GATE ASSETS',
    description: '管理闸门设计参数和空间位置。',
  },
  {
    key: 'data-pumps',
    label: '泵站数据库',
    path: '/data-center/pumps',
    icon: <ThunderboltOutlined />,
    eyebrow: 'PUMP ASSETS',
    description: '管理泵站流量、扬程、功率与效率曲线。',
  },
  {
    key: 'data-imports',
    label: '数据导入',
    path: '/data-center/imports',
    icon: <ImportOutlined />,
    eyebrow: 'DATA PIPELINE',
    description: '导入 Excel、CSV 与 GeoJSON 数据。',
  },
  {
    key: 'data-validation',
    label: '数据校验',
    path: '/data-center/validation',
    icon: <FileDoneOutlined />,
    eyebrow: 'QUALITY GATE',
    description: '运行空间、水力、建筑物与拓扑完整性检查。',
  },
  {
    key: 'model-data',
    label: '模型数据',
    path: '/data-center/model-data',
    icon: <DatabaseOutlined />,
    eyebrow: 'MODEL INPUT',
    description: '管理版本、边界条件、参数和计算方案。',
  },
  {
    key: 'dispatch',
    label: '闸泵调度',
    path: '/dispatch',
    icon: <ControlOutlined />,
    eyebrow: 'GATE & PUMP',
    description: '编排闸门与泵站的联合调度过程。',
  },
  {
    key: 'hydraulic',
    label: '水动力模拟',
    path: '/hydraulic',
    icon: <AimOutlined />,
    eyebrow: 'STANDARD 1D',
    description: '通过 MASCARET Adapter 配置并运行标准一维水动力模型。',
  },
  {
    key: 'hydraulic-production',
    label: '水动力生产工作台',
    path: '/hydraulic/production',
    icon: <SafetyCertificateOutlined />,
    eyebrow: 'PRODUCTION 1D',
    description: '完成工程数据、QA、率定验证、外部对比与成果输出闭环。',
  },
  {
    key: 'optimization',
    label: '优化分析',
    path: '/optimization',
    icon: <ExperimentOutlined />,
    eyebrow: 'OPTIMIZATION',
    description: '运行 PSO 多目标调度、Pareto 分析与人工推荐。',
  },
  {
    key: 'ai',
    label: 'AI 助手',
    path: '/ai-assistant',
    icon: <BulbOutlined />,
    eyebrow: 'WATER INTELLIGENCE',
    description: '连接水利知识与调度辅助决策能力。',
  },
];

// 由导航元数据生成占位页路由，当前首页仍拥有独立的态势看板实现。
export const appRouter = createBrowserRouter([
  {
    path: '/',
    element: <DatasetVersionProvider><MainLayout /></DatasetVersionProvider>,
    errorElement: <RouteErrorPage />,
    children: [
      {
        index: true,
        element: (
          <Suspense fallback={<RouteLoading label="正在加载态势中心…" />}>
            <HomePage />
          </Suspense>
        ),
      },
      {
        path: 'gis',
        element: (
          <Suspense fallback={<RouteLoading label="正在加载 GIS 空间底座…" />}>
            <GisPage />
          </Suspense>
        ),
      },
      { path: 'rivers', element: <Navigate to="/data-center/rivers" replace /> },
      { path: 'data-center/rivers', element: <Suspense fallback={<RouteLoading label="正在加载河道数据库…" />}><RiversDatabasePage /></Suspense> },
      { path: 'data-center/cross-sections', element: <Suspense fallback={<RouteLoading label="正在加载横断面数据库…" />}><CrossSectionsDatabasePage /></Suspense> },
      { path: 'data-center/gates', element: <Suspense fallback={<RouteLoading label="正在加载闸门数据库…" />}><GatesDatabasePage /></Suspense> },
      { path: 'data-center/pumps', element: <Suspense fallback={<RouteLoading label="正在加载泵站数据库…" />}><PumpsDatabasePage /></Suspense> },
      { path: 'data-center/imports', element: <Suspense fallback={<RouteLoading label="正在加载数据导入中心…" />}><DataImportPage /></Suspense> },
      { path: 'data-center/validation', element: <Suspense fallback={<RouteLoading label="正在加载数据校验中心…" />}><DataValidationPage /></Suspense> },
      { path: 'data-center/model-data', element: <Suspense fallback={<RouteLoading label="正在加载模型数据…" />}><ModelDataPage /></Suspense> },
      { path: 'data-center/hydraulic', element: <Suspense fallback={<RouteLoading label="正在加载水动力数据管理…" />}><HydraulicDataPage /></Suspense> },
      { path: 'hydraulic', element: <Navigate to="/hydraulic/config" replace /> },
      { path: 'hydraulic/config', element: <Suspense fallback={<RouteLoading label="正在加载水动力配置…" />}><HydraulicConfigPage /></Suspense> },
      { path: 'hydraulic/tasks', element: <Suspense fallback={<RouteLoading label="正在加载模拟任务…" />}><HydraulicTasksPage /></Suspense> },
      { path: 'hydraulic/results', element: <Suspense fallback={<RouteLoading label="正在加载模拟结果…" />}><HydraulicResultsPage /></Suspense> },
      { path: 'hydraulic/production', element: <Suspense fallback={<RouteLoading label="正在加载生产工作台…" />}><ProductionWorkspacePage /></Suspense> },
      { path: 'dispatch', element: <Navigate to="/dispatch/plans" replace /> },
      { path: 'dispatch/plans', element: <Suspense fallback={<RouteLoading label="正在加载调度计划…" />}><DispatchPlanListPage /></Suspense> },
      { path: 'dispatch/plans/:planId', element: <Suspense fallback={<RouteLoading label="正在加载计划编辑器…" />}><DispatchPlanEditorPage /></Suspense> },
      { path: 'dispatch/runs', element: <Suspense fallback={<RouteLoading label="正在加载运行中心…" />}><DispatchRunListPage /></Suspense> },
      { path: 'dispatch/runs/:runId', element: <Suspense fallback={<RouteLoading label="正在加载运行结果…" />}><DispatchRunDetailPage /></Suspense> },
      { path: 'optimization', element: <Suspense fallback={<RouteLoading label="正在加载优化配置…" />}><OptimizationHomePage /></Suspense> },
      { path: 'optimization/tasks', element: <Suspense fallback={<RouteLoading label="正在加载优化任务…" />}><OptimizationTasksPage /></Suspense> },
      { path: 'optimization/tasks/:taskId', element: <Suspense fallback={<RouteLoading label="正在加载 Pareto 结果…" />}><OptimizationTaskDetailPage /></Suspense> },
      { path: 'ai', element: <Navigate to="/ai-assistant" replace /> },
      { path: 'ai-assistant', element: <Suspense fallback={<RouteLoading label="正在加载 AI 水利助手…" />}><AIAssistantPage /></Suspense> },
    ],
  },
]);
