import { ArrowUpOutlined, DatabaseOutlined, SafetyCertificateOutlined } from '@ant-design/icons';
import { CesiumMap } from '../components/gis/CesiumMap';
import { StatusPanel } from '../components/StatusPanel';
import { WaterTrendChart } from '../components/WaterTrendChart';

// 组合首页态势摘要、真实空间一张图与数据库统计，保持信息层级清晰。
export function HomePage() {
  return (
    <div className="dashboard-page">
      <header className="hero-strip">
        <div>
          <span className="hero-kicker"><i /> DIGITAL TWIN WATER SYSTEM</span>
          <h1>以数字孪生，<em>驱动河网智慧调度</em></h1>
          <p>汇聚河道空间、闸泵设施与计算模型，为复杂水系提供统一的态势感知与决策底座。</p>
        </div>
        <div className="hero-meta">
          <span>PLATFORM VERSION</span>
          <strong>2.0.0 <small>PHASE 2</small></strong>
        </div>
      </header>

      <div className="dashboard-grid">
        <CesiumMap />
        <StatusPanel />
      </div>

      <div className="lower-grid">
        <section className="trend-panel panel-surface">
          <div className="panel-heading compact">
            <div>
              <span className="panel-kicker">WATER LEVEL / DEMO</span>
              <h2>24 小时水位趋势</h2>
            </div>
            <span className="trend-value"><ArrowUpOutlined /> 0.32 m</span>
          </div>
          <WaterTrendChart />
        </section>

        <section className="capability-panel panel-surface">
          <div className="panel-heading compact">
            <div>
              <span className="panel-kicker">FOUNDATION / READY</span>
              <h2>架构能力</h2>
            </div>
          </div>
          <div className="capability-list">
            <div><DatabaseOutlined /><span><strong>空间数据底座</strong><small>PostgreSQL + PostGIS</small></span></div>
            <div><SafetyCertificateOutlined /><span><strong>模块边界</strong><small>API · Service · Contract</small></span></div>
          </div>
        </section>
      </div>
    </div>
  );
}
