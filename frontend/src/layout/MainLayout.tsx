import { BellOutlined, MenuFoldOutlined, MenuUnfoldOutlined, PlusOutlined } from '@ant-design/icons';
import { Button, Form, Input, Layout, Menu, Modal, Select, Tag, Tooltip, message } from 'antd';
import { useMemo, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { createDatasetVersion, type DatasetVersionCreate } from '../api/generated/client';
import { navigationItems } from '../router';
import { datasetVersionStatusLabel, useDatasetVersion } from '../context/DatasetVersionContext';

const { Header, Sider, Content } = Layout;

/** 用一致的颜色表达版本生命周期，不把只读状态伪装成普通标签。 */
function versionStatusColor(status?: string): string {
  if (status === 'draft') return 'gold';
  if (status === 'published') return 'success';
  if (status === 'retired' || status === 'rejected') return 'default';
  return 'processing';
}

// 提供全站稳定骨架，并将路由状态映射为导航选中状态。
export function MainLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [versionForm] = Form.useForm<DatasetVersionCreate>();
  const location = useLocation();
  const navigate = useNavigate();
  const {
    versions,
    datasetVersionId,
    currentVersion,
    loading,
    error,
    setDatasetVersionId,
    refreshVersions,
  } = useDatasetVersion();

  const activeItem = useMemo(
    () =>
      navigationItems.find((item) =>
        item.path === '/' ? location.pathname === '/' : location.pathname.startsWith(item.path),
      ) ?? navigationItems[0],
    [location.pathname],
  );

  /** 创建可编辑草稿并立即切换，打通发布版本到编辑工作区的正式入口。 */
  const createDraft = async (values: DatasetVersionCreate) => {
    setCreating(true);
    try {
      const created = await createDatasetVersion(values);
      await refreshVersions(created.id);
      setCreateOpen(false);
      versionForm.resetFields();
      message.success(`草稿 ${created.version} 已创建并切换`);
    } catch (reason) {
      message.error(reason instanceof Error ? reason.message : '草稿创建失败');
    } finally {
      setCreating(false);
    }
  };

  /** 给草稿表单生成可修改的唯一建议值，避免用户手工拼接版本号。 */
  const openCreateDraft = () => {
    const timestamp = new Date().toISOString().replace(/\D/g, '').slice(0, 14);
    versionForm.setFieldsValue({
      version: `DRAFT-${timestamp}`,
      name: '数据维护草稿',
      creator: 'web-operator',
      description: '由大禹天工 Web 工作台创建的可编辑数据版本',
    });
    setCreateOpen(true);
  };

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
                label: `${item.version} · ${item.name} · ${datasetVersionStatusLabel(item.status)}`,
              }))}
              placeholder="选择数据版本"
            />
            <Tooltip title={error || '创建独立的可编辑草稿；已发布版本始终保持只读'}>
              <Button icon={<PlusOutlined />} onClick={openCreateDraft}>新建草稿</Button>
            </Tooltip>
            <Tag color={versionStatusColor(currentVersion?.status)}>
              {datasetVersionStatusLabel(currentVersion?.status)}
            </Tag>
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

      <Modal
        open={createOpen}
        title="新建可编辑数据草稿"
        onCancel={() => setCreateOpen(false)}
        onOk={() => versionForm.submit()}
        confirmLoading={creating}
        destroyOnHidden
      >
        <Form form={versionForm} layout="vertical" onFinish={(values) => void createDraft(values)}>
          <Form.Item name="version" label="版本编码" rules={[{ required: true, message: '请输入版本编码' }]}>
            <Input maxLength={32} />
          </Form.Item>
          <Form.Item name="name" label="草稿名称" rules={[{ required: true, message: '请输入草稿名称' }]}>
            <Input maxLength={128} />
          </Form.Item>
          <Form.Item name="creator" label="创建者" rules={[{ required: true, message: '请输入创建者' }]}>
            <Input maxLength={64} />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </Layout>
  );
}
