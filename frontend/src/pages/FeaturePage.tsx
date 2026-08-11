import { ArrowRightOutlined, CheckCircleFilled, ClockCircleOutlined } from '@ant-design/icons';
import { Button } from 'antd';
import type { NavigationItem } from '../types/navigation';

interface FeaturePageProps {
  item: NavigationItem;
}

// 为尚未进入实现阶段的业务模块提供明确边界和统一导航体验。
export function FeaturePage({ item }: FeaturePageProps) {
  return (
    <div className="feature-page">
      <section className="feature-hero panel-surface">
        <div className="feature-icon">{item.icon}</div>
        <span className="panel-kicker">{item.eyebrow}</span>
        <h1>{item.label}</h1>
        <p>{item.description}</p>
        <div className="feature-status">
          <span><CheckCircleFilled /> 工程路由已就绪</span>
          <span><ClockCircleOutlined /> 业务能力待后续阶段接入</span>
        </div>
        <Button type="primary" ghost icon={<ArrowRightOutlined />} disabled>
          等待下一阶段
        </Button>
      </section>

      <section className="feature-contract panel-surface">
        <span className="panel-kicker">PHASE 0 BOUNDARY</span>
        <h2>当前交付边界</h2>
        <p>本页已完成独立路由、导航状态与视觉骨架，不展示虚构业务结果。后续功能将在稳定 API 契约和真实数据源具备后增量接入。</p>
      </section>
    </div>
  );
}
