import { BellOutlined, DeleteOutlined, LockOutlined, MenuFoldOutlined, MenuUnfoldOutlined, PlusOutlined, UnlockOutlined } from '@ant-design/icons';
import { Button, Form, Input, Layout, Menu, Modal, Popconfirm, Select, Tag, Tooltip, message } from 'antd';
import { useMemo, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { cloneDatasetVersion, createDatasetVersion, deleteDatasetVersion, updateDatasetVersion, type DatasetVersionCreate } from '../api/generated/client';
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
  const [deleting, setDeleting] = useState(false);
  const [changingReadOnly, setChangingReadOnly] = useState(false);
  const [cloning, setCloning] = useState(false);
  const [versionForm] = Form.useForm<DatasetVersionCreate>();
  const location = useLocation();
  const navigate = useNavigate();
  const isPublishedScenarioResults = location.pathname.startsWith('/hydraulic/scenario-results');
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

  /** 创建默认可编辑的数据版本并立即切换。 */
  const createDraft = async (values: DatasetVersionCreate) => {
    setCreating(true);
    try {
      const created = await createDatasetVersion(values);
      await refreshVersions(created.id);
      setCreateOpen(false);
      versionForm.resetFields();
      message.success(`数据版本 ${created.version} 已创建并切换`);
    } catch (reason) {
      message.error(reason instanceof Error ? reason.message : '数据版本创建失败');
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

  /** 从不可变工程版本派生新的可编辑草稿，保留清晰的版本血缘。 */
  const cloneCurrentVersion = async () => {
    if (!currentVersion) return;
    const timestamp = new Date().toISOString().replace(/\D/g, '').slice(0, 14);
    setCloning(true);
    try {
      const created = await cloneDatasetVersion(currentVersion.id, {
        version: `${currentVersion.version}-DRAFT-${timestamp}`.slice(0, 32),
        name: `${currentVersion.name} 草稿`.slice(0, 128),
        creator: 'web-operator',
        description: `基于不可变版本 ${currentVersion.version} 创建的编辑草稿`,
      });
      await refreshVersions(created.id);
      message.success(`已从 ${currentVersion.version} 创建草稿 ${created.version}`);
    } catch (reason) {
      message.error(reason instanceof Error ? reason.message : '创建派生草稿失败');
    } finally {
      setCloning(false);
    }
  };

  /** 删除当前非只读版本；后端审计引用仍是最终安全门。 */
  const deleteCurrentVersion = async () => {
    if (!currentVersion || currentVersion.status !== 'draft' || currentVersion.is_read_only) return;
    setDeleting(true);
    try {
      await deleteDatasetVersion(currentVersion.id);
      await refreshVersions();
      message.success(`数据版本 ${currentVersion.version} 已删除`);
    } catch (reason) {
      message.error(reason instanceof Error ? reason.message : '数据版本删除失败；请先清理计算、发布或派生版本引用');
    } finally {
      setDeleting(false);
    }
  };

  /** 草稿可由当前用户显式启用或解除编辑锁。 */
  const toggleReadOnly = async () => {
    if (!currentVersion) return;
    setChangingReadOnly(true);
    try {
      const next = !currentVersion.is_read_only;
      await updateDatasetVersion(currentVersion.id, { is_read_only: next });
      await refreshVersions(currentVersion.id);
      message.success(next ? `数据版本 ${currentVersion.version} 已设为只读` : `数据版本 ${currentVersion.version} 已解除只读`);
    } catch (reason) {
      message.error(reason instanceof Error ? reason.message : '只读状态更新失败');
    } finally {
      setChangingReadOnly(false);
    }
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
            {isPublishedScenarioResults ? (
              <>
                <Tag color="cyan">本地成果包</Tag>
                <Tag color="gold">未率定</Tag>
              </>
            ) : (
              <>
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
                <Tooltip title={error || '创建独立且默认可编辑的数据版本'}>
                  <Button icon={<PlusOutlined />} onClick={openCreateDraft}>新建版本</Button>
                </Tooltip>
                {currentVersion?.status === 'draft' && (
                  <Button
                    loading={changingReadOnly}
                    icon={currentVersion.is_read_only ? <UnlockOutlined /> : <LockOutlined />}
                    onClick={() => void toggleReadOnly()}
                  >
                    {currentVersion.is_read_only ? '解除只读' : '设为只读'}
                  </Button>
                )}
                {currentVersion?.status !== 'draft' && (
                  <Button loading={cloning} onClick={() => void cloneCurrentVersion()}>
                    基于此版本创建草稿
                  </Button>
                )}
                {currentVersion?.status === 'draft' && !currentVersion.is_read_only && (
                  <Popconfirm
                    title="删除当前数据版本？"
                    description={`将删除 ${currentVersion.version} 及其直属河网、断面和模型数据；被计算、发布或派生版本引用时后端会拒绝。`}
                    okText="删除版本"
                    cancelText="取消"
                    okButtonProps={{ danger: true }}
                    onConfirm={() => void deleteCurrentVersion()}
                  >
                    <Button danger loading={deleting} icon={<DeleteOutlined />}>删除版本</Button>
                  </Popconfirm>
                )}
                <Tag color={versionStatusColor(currentVersion?.status)}>
                  {datasetVersionStatusLabel(currentVersion?.status)}
                </Tag>
                {currentVersion && currentVersion.status !== 'draft' && (
                  <Tag color="red">不可原地修改</Tag>
                )}
                {currentVersion && (
                  <Tag color={currentVersion.is_read_only ? 'red' : 'green'}>
                    {currentVersion.is_read_only ? '只读' : '可编辑'}
                  </Tag>
                )}
              </>
            )}
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
        title="新建可编辑数据版本"
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
