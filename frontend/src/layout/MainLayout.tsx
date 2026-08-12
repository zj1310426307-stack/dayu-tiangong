import { BellOutlined, MenuFoldOutlined, MenuUnfoldOutlined } from '@ant-design/icons';
import { Button, Layout, Menu, Select, Tag, Tooltip } from 'antd';
import { useMemo, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { navigationItems } from '../router';
import { useDatasetVersion } from '../context/DatasetVersionContext';

const { Header, Sider, Content } = Layout;

// 提供全站稳定骨架，并将路由状态映射为导航选中状态。
export function MainLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const { versions, datasetVersionId, loading, setDatasetVersionId } = useDatasetVersion();

  const activeItem = useMemo(
    () =>
      navigationItems.find((item) =>
        item.path === '/' ? location.pathname === '/' : location.pathname.startsWith(item.path),
      ) ?? navigationItems[0],
    [location.pathname],
  );

  return (
    <Layout className="app-shell">
      <Sider
        className="side-rail"
        width={248}
        collapsedWidth={82}
        collapsed={collapsed}
        trigger={null}
      >
        <div className="brand-mark" aria-label="大禹天工标志">
          <span className="brand-glyph">禹</span>
          {!collapsed && (
            <span className="brand-copy">
              <strong>大禹·天工</strong>
              <small>DAYU TIANGONG</small>
            </span>
          )}
        </div>

        <Menu
          className="side-menu"
          mode="inline"
          selectedKeys={[activeItem.key]}
          items={navigationItems.map((item) => ({
            key: item.key,
            icon: item.icon,
            label: item.label,
            onClick: () => navigate(item.path),
          }))}
        />

        {!collapsed && (
          <div className="side-footnote">
            <span className="signal-dot" />
            <div>
              <strong>PHASE 4</strong>
              <small>一维水动力引擎已贯通</small>
            </div>
          </div>
        )}
      </Sider>

      <Layout className="workspace">
        <Header className="top-bar">
          <div className="top-bar__left">
            <Button
              className="rail-toggle"
              type="text"
              icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={() => setCollapsed((value) => !value)}
              aria-label={collapsed ? '展开菜单' : '收起菜单'}
            />
            <span className="section-divider" />
            <div className="section-title">
              <small>{activeItem.eyebrow}</small>
              <strong>{activeItem.label}</strong>
            </div>
          </div>

          <div className="top-bar__right">
            <Select
              aria-label="当前数据版本"
              className="dataset-version-select"
              loading={loading}
              value={datasetVersionId}
              onChange={setDatasetVersionId}
              options={versions.map((item) => ({
                value: item.id,
                label: `${item.version} · ${item.name}`,
              }))}
              placeholder="选择数据版本"
            />
            <Tag className="env-tag">原型环境</Tag>
            <Tooltip title="通知中心将在后续阶段接入">
              <Button className="notification-button" type="text" icon={<BellOutlined />} />
            </Tooltip>
            <div className="clock-block">
              <strong>运行态势</strong>
              <small>ARCHITECTURE ONLINE</small>
            </div>
          </div>
        </Header>

        <Content className="main-content">
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
