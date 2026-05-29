/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, Select, DatePicker, Button, message, Tabs, Progress, Tag, Popconfirm, Switch, Tooltip, Space } from 'antd';
import { PlusOutlined, CheckCircleOutlined, CloseCircleOutlined, CopyOutlined } from '@ant-design/icons';
import { http, hasPermission } from 'libs';
import moment from 'moment';
import store from './store';

const { Option } = Select;
const { TabPane } = Tabs;
const { TextArea } = Input;

export default observer(function () {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [viewMode, setViewMode] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState(null);
  const [upgradeNo, setUpgradeNo] = useState('');

  // 步骤清单相关状态
  const [recordSteps, setRecordSteps] = useState([]);
  const [stepStats, setStepStats] = useState({ total: 0, completed: 0, skipped: 0, pending: 0, progress: 0 });
  const [addStepVisible, setAddStepVisible] = useState(false);
  const [addStepForm] = Form.useForm();

  function fetchRecordSteps() {
    if (store.record.id) {
      http.get(`/api/upgrade/records/${store.record.id}/steps/`)
        .then(res => {
          setRecordSteps(res.steps || []);
          setStepStats(res.stats || { total: 0, completed: 0, skipped: 0, pending: 0, progress: 0 });
        })
        .catch(() => {
          setRecordSteps([]);
          setStepStats({ total: 0, completed: 0, skipped: 0, pending: 0, progress: 0 });
        });
    }
  }

  useEffect(() => {
    if (store.record.id) {
      fetchRecordSteps();
      if (store.record.isViewMode || !hasPermission('upgrade.upgrade.edit')) {
        setViewMode(true);
      } else {
        setViewMode(false);
      }
    } else {
      // 新建模式：获取自动生成的升级单号
      store.fetchNextUpgradeNo().then(no => {
        if (no) setUpgradeNo(no);
      });
      // 加载模板列表
      store.fetchTemplates();
      // 加载清单列表
      store.fetchChecklists();
    }
  }, [store.record.id]);

  // 模板选择处理
  function handleTemplateSelect(templateId) {
    const template = store.templates.find(t => t.id === templateId);
    if (!template) return;
    setSelectedTemplate(template);
    const values = {};
    if (template.system) values.system = template.system;
    if (template.upgrade_type) values.upgrade_type = template.upgrade_type;
    if (template.version) values.version = template.version;
    if (template.owner) values.owner = template.owner;
    if (template.status) values.status = template.status;
    form.setFieldsValue(values);
    message.info(`已应用模板「${template.name}」`);
  }

  // 应用清单到升级表单
  function handleApplyChecklist(checklistId) {
    if (!store.record.id) return;
    const checklist = store.checklists.find(c => c.id === checklistId);
    if (!checklist) return;

    http.post(`/api/upgrade/checklists/${checklistId}/apply/`, { upgrade_id: store.record.id })
      .then(res => {
        message.success(`已应用清单「${checklist.name}」，添加 ${res.created_count} 个步骤`);
        fetchRecordSteps();
      })
      .catch(() => {
        message.error('应用清单失败');
      });
  }

  // 更新步骤状态
  function handleStepAction(step, action) {
    http.put(`/api/upgrade/record-steps/${step.id}/update/`, { action })
      .then(() => {
        const actionText = action === 'complete' ? '完成' : action === 'skip' ? '跳过' : '重置';
        message.success(`步骤已标记为${actionText}`);
        fetchRecordSteps();
        // 步骤状态变更后刷新记录状态（可能自动更新为已完成）
        store.fetchRecords();
      });
  }

  // 删除步骤
  function handleDeleteStep(step) {
    http.delete(`/api/upgrade/record-steps/${step.id}/delete/`)
      .then(() => {
        message.success('步骤已删除');
        fetchRecordSteps();
        // 删除步骤后刷新记录状态
        store.fetchRecords();
      });
  }

  // 手动添加步骤
  function handleAddStep(values) {
    http.post(`/api/upgrade/records/${store.record.id}/steps/add/`, values)
      .then(() => {
        message.success('步骤添加成功');
        setAddStepVisible(false);
        addStepForm.resetFields();
        fetchRecordSteps();
      });
  }

  // 清空所有步骤
  function handleClearSteps() {
    http.delete(`/api/upgrade/records/${store.record.id}/steps/clear/`)
      .then(() => {
        message.success('已清空所有步骤');
        fetchRecordSteps();
      });
  }

  function handleSubmit() {
    setLoading(true);
    const formData = form.getFieldsValue();

    if (formData.upgrade_time) {
      formData.upgrade_time = formData.upgrade_time.format('YYYY-MM-DD HH:mm:ss');
    }

    const url = store.record.id
      ? `/api/upgrade/records/${store.record.id}/update/`
      : '/api/upgrade/records/create/';
    const httpMethod = store.record.id ? 'put' : 'post';

    http[httpMethod](url, formData)
      .then(() => {
        message.success('操作成功');
        store.formVisible = false;
        store.fetchRecords();
      }, () => setLoading(false));
  }

  const info = store.record;

  // 步骤状态标签
  function StepStatusTag({ status }) {
    const map = {
      pending: { color: 'default', icon: null, text: '待执行' },
      completed: { color: 'success', icon: <CheckCircleOutlined />, text: '已完成' },
      skipped: { color: 'warning', icon: <CloseCircleOutlined />, text: '已跳过' },
    };
    const cfg = map[status] || map.pending;
    return <Tag color={cfg.color} icon={cfg.icon}>{cfg.text}</Tag>;
  }

  // 查看模式
  if (viewMode) {
    return (
      <Modal
        visible
        width={900}
        title="升级表单详情"
        footer={[<Button key="close" onClick={() => store.formVisible = false}>关闭</Button>]}
        onCancel={() => store.formVisible = false}>
        <Tabs defaultActiveKey="basic">
          <TabPane tab="基本信息" key="basic">
            <div style={{ padding: '0 0 16px 0' }}>
              <div><strong>升级单号：</strong>{info.upgrade_no}</div>
              <div><strong>系统：</strong>{info.system}</div>
              <div><strong>升级类型：</strong>{info.upgrade_type}</div>
              <div><strong>版本：</strong>{info.version}</div>
              <div><strong>升级时间：</strong>{info.upgrade_time}</div>
              <div><strong>状态：</strong>{info.status}</div>
              <div><strong>负责人：</strong>{info.owner}</div>
            </div>
          </TabPane>
          <TabPane tab={`步骤清单 (${stepStats.completed}/${stepStats.total})`} key="steps">
            {stepStats.total > 0 && (
              <div style={{ marginBottom: 16 }}>
                <Progress
                  percent={stepStats.progress}
                  status={stepStats.progress === 100 ? 'success' : 'active'}
                  format={() => `${stepStats.completed}/${stepStats.total} 已完成`}
                />
              </div>
            )}
            {recordSteps.map(step => (
              <div key={step.id} style={{
                display: 'flex', alignItems: 'center', padding: '8px 12px',
                borderBottom: '1px solid #f0f0f0', gap: 12
              }}>
                <span style={{ color: '#999', minWidth: 24 }}>{step.sequence}.</span>
                <StepStatusTag status={step.status} />
                <span style={{ flex: 1, textDecoration: step.status === 'completed' ? 'line-through' : 'none' }}>
                  {step.title}
                </span>
                {step.is_required && <Tag color="blue" style={{ marginRight: 0 }}>必选</Tag>}
                {step.description && (
                  <Tooltip title={step.description}>
                    <span style={{ color: '#999', cursor: 'help' }}>备注</span>
                  </Tooltip>
                )}
                {step.completed_by && <span style={{ color: '#999', fontSize: 12 }}>{step.completed_by} {step.completed_at}</span>}
                {step.remark && <span style={{ color: '#666', fontSize: 12 }}>备注: {step.remark}</span>}
              </div>
            ))}
            {recordSteps.length === 0 && <div style={{ textAlign: 'center', color: '#999' }}>暂无步骤</div>}
          </TabPane>
        </Tabs>
      </Modal>
    );
  }

  // 编辑/新建模式
  const initialValues = {...info};
  if (initialValues.upgrade_time) {
    initialValues.upgrade_time = moment(initialValues.upgrade_time);
  }
  if (!store.record.id && upgradeNo) {
    initialValues.upgrade_no = upgradeNo;
  }

  return (
    <Modal
      visible
      width={900}
      maskClosable={false}
      title={store.record.id ? '编辑升级表单' : '新建升级表单'}
      onCancel={() => store.formVisible = false}
      confirmLoading={loading}
      onOk={handleSubmit}>
      <Tabs defaultActiveKey="basic">
        <TabPane tab="基本信息" key="basic">
          <Form form={form} initialValues={initialValues} labelCol={{span: 5}} wrapperCol={{span: 14}}>
            <Form.Item name="upgrade_no" label="升级单号">
              <Input
                placeholder="自动生成"
                disabled
                addonAfter={!store.record.id && upgradeNo ? (
                  <CopyOutlined
                    onClick={() => {
                      if (navigator.clipboard) {
                        navigator.clipboard.writeText(upgradeNo);
                      }
                      message.success('已复制单号');
                    }}
                    style={{ cursor: 'pointer' }}
                    title="复制单号"
                  />
                ) : null}
              />
            </Form.Item>

            {!store.record.id && store.templates.length > 0 && (
              <Form.Item label="使用模板">
                <Select
                  allowClear
                  placeholder="选择模板快速填充（可选）"
                  value={selectedTemplate?.id}
                  onChange={handleTemplateSelect}
                  onClear={() => setSelectedTemplate(null)}
                  style={{ width: '100%' }}
                >
                  {store.templates.map(t => (
                    <Option key={t.id} value={t.id}>
                      {t.is_default ? `⭐ ${t.name}` : t.name}
                      {t.system ? ` (${t.system})` : ''}
                    </Option>
                  ))}
                </Select>
              </Form.Item>
            )}

            <Form.Item required name="system" label="系统" rules={[{required: true, message: '请选择或输入系统'}]}>
              <Select
                showSearch
                allowClear
                placeholder="请选择或输入系统"
                filterOption={(input, option) =>
                  option.children?.toLowerCase().indexOf(input.toLowerCase()) >= 0
                }
              >
                {store.filterOptions.systems.map(item => (
                  <Option value={item} key={item}>{item}</Option>
                ))}
              </Select>
            </Form.Item>

            <Form.Item required name="upgrade_type" label="升级类型" rules={[{required: true, message: '请选择升级类型'}]}>
              <Select placeholder="请选择升级类型">
                <Option value="功能升级">功能升级</Option>
                <Option value="Bug修复">Bug修复</Option>
                <Option value="安全补丁">安全补丁</Option>
                <Option value="性能优化">性能优化</Option>
              </Select>
            </Form.Item>
            <Form.Item required name="version" label="版本" rules={[{required: true, message: '请输入版本'}]}>
              <Input placeholder="请输入版本，如 v1.2.0"/>
            </Form.Item>
            <Form.Item required name="upgrade_time" label="升级时间" rules={[{required: true, message: '请选择升级时间'}]}>
              <DatePicker showTime style={{width: '100%'}} placeholder="请选择升级时间"/>
            </Form.Item>
            <Form.Item required name="status" label="状态" rules={[{required: true, message: '请选择状态'}]}>
              <Select placeholder="请选择状态">
                <Option value="处理中">处理中</Option>
                <Option value="已完成">已完成</Option>
              </Select>
            </Form.Item>
            <Form.Item required name="owner" label="负责人" rules={[{required: true, message: '请输入负责人'}]}>
              <Input placeholder="请输入负责人"/>
            </Form.Item>
          </Form>
        </TabPane>

        {store.record.id && (
          <TabPane tab={`步骤清单 (${stepStats.completed}/${stepStats.total})`} key="steps">
            {/* 进度条 */}
            {stepStats.total > 0 && (
              <div style={{ marginBottom: 16 }}>
                <Progress
                  percent={stepStats.progress}
                  status={stepStats.progress === 100 ? 'success' : 'active'}
                  format={() => `${stepStats.completed}/${stepStats.total} 已完成`}
                />
              </div>
            )}

            {/* 操作栏 */}
            <div style={{ marginBottom: 16, display: 'flex', gap: 8 }}>
              {store.checklists.length > 0 && (
                <Select
                  style={{ width: 240 }}
                  placeholder="选择清单应用到本次升级"
                  allowClear
                  onChange={handleApplyChecklist}
                >
                  {store.checklists.map(c => (
                    <Option key={c.id} value={c.id}>
                      {c.is_default ? '⭐ ' : ''}{c.name} ({c.step_count}步)
                    </Option>
                  ))}
                </Select>
              )}
              <Button icon={<PlusOutlined/>} onClick={() => setAddStepVisible(true)}>
                手动添加步骤
              </Button>
              {recordSteps.length > 0 && hasPermission('upgrade.upgrade.step_del') && (
                <Popconfirm title="确定清空所有步骤？" onConfirm={handleClearSteps}>
                  <Button danger>清空步骤</Button>
                </Popconfirm>
              )}
            </div>

            {/* 步骤列表 */}
            {recordSteps.map(step => (
              <div key={step.id} style={{
                display: 'flex', alignItems: 'center', padding: '10px 12px',
                borderBottom: '1px solid #f0f0f0', gap: 12,
                backgroundColor: step.status === 'completed' ? '#f6ffed' :
                  step.status === 'skipped' ? '#fff7e6' : 'transparent'
              }}>
                <span style={{ color: '#999', minWidth: 24, fontWeight: 'bold' }}>{step.sequence}.</span>
                <StepStatusTag status={step.status} />
                <span style={{
                  flex: 1,
                  textDecoration: step.status === 'completed' ? 'line-through' : 'none',
                  color: step.status !== 'pending' ? '#999' : '#333'
                }}>
                  {step.title}
                </span>
                {step.is_required && <Tag color="blue">必选</Tag>}
                {step.description && (
                  <Tooltip title={step.description}>
                    <span style={{ color: '#1890ff', cursor: 'help', fontSize: 12 }}>详情</span>
                  </Tooltip>
                )}
                {step.completed_by && (
                  <span style={{ color: '#999', fontSize: 12 }}>{step.completed_by} {step.completed_at}</span>
                )}
                {/* 操作按钮 */}
                <Space size={4}>
                  {step.status === 'pending' && (
                    <>
                      <Button
                        size="small"
                        type="link"
                        icon={<CheckCircleOutlined />}
                        onClick={() => handleStepAction(step, 'complete')}
                      >
                        完成
                      </Button>
                      <Button
                        size="small"
                        type="link"
                        onClick={() => handleStepAction(step, 'skip')}
                      >
                        跳过
                      </Button>
                    </>
                  )}
                  {step.status !== 'pending' && hasPermission('upgrade.upgrade.step_reset') && (
                    <Button
                      size="small"
                      type="link"
                      onClick={() => handleStepAction(step, 'reset')}
                    >
                      重置
                    </Button>
                  )}
                  {hasPermission('upgrade.upgrade.step_del') && (
                    <Button
                      size="small"
                      type="link"
                      danger
                      onClick={() => handleDeleteStep(step)}
                    >
                      删除
                    </Button>
                  )}
                </Space>
              </div>
            ))}
            {recordSteps.length === 0 && (
              <div style={{ textAlign: 'center', color: '#999', padding: 32 }}>
                暂无步骤，可通过上方选择清单快速应用，或手动添加步骤
              </div>
            )}
          </TabPane>
        )}
      </Tabs>

      {/* 手动添加步骤弹窗 */}
      <Modal
        title="添加步骤"
        visible={addStepVisible}
        onCancel={() => { setAddStepVisible(false); addStepForm.resetFields(); }}
        onOk={() => addStepForm.validateFields().then(handleAddStep)}
        width={500}
      >
        <Form form={addStepForm} labelCol={{ span: 5 }} wrapperCol={{ span: 17 }}>
          <Form.Item name="title" label="步骤标题" rules={[{ required: true, message: '请输入步骤标题' }]}>
            <Input placeholder="请输入步骤标题" />
          </Form.Item>
          <Form.Item name="description" label="步骤描述">
            <TextArea rows={3} placeholder="步骤描述（选填）" />
          </Form.Item>
          <Form.Item name="is_required" label="是否必执行" valuePropName="checked" initialValue={true}>
            <Switch checkedChildren="必选" unCheckedChildren="可选" />
          </Form.Item>
        </Form>
      </Modal>
    </Modal>
  );
})
