/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, Select, DatePicker, Button, message, Row, Col, Divider } from 'antd';
import { CopyOutlined } from '@ant-design/icons';
import { http } from 'libs';
import history from 'libs/history';
import moment from 'moment';
import store from './store';
import SystemSelect from './components/SystemSelect';

const { Option } = Select;
const { TextArea } = Input;

/**
 * 新建升级申请弹窗（轻量建单入口）
 *
 * 只负责"建单"，不承载升级执行过程：
 *   基本信息（标题/系统/类型/负责人/计划时间/升级单号只读）
 *   升级说明（升级内容/影响范围/风险说明/回退方案摘要）
 *   初始化配置（升级方案/步骤模板）
 *
 * 保存：
 *   仅保存          -> 关闭弹窗 + 刷新列表
 *   保存并进入工作台 -> 关闭弹窗 + 刷新列表 + 跳转工作台
 *
 * 标题自动生成：{升级系统} - {升级类型} - {计划升级日期}
 *   用户手动修改后锁定；清空标题后恢复自动生成。
 */

function BasicInfoFields({ upgradeNo }) {
  return (
    <>
      <div style={{ fontWeight: 600, marginBottom: 12, color: '#262626' }}>基本信息</div>
      <Row gutter={16}>
        <Col span={24}>
          <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
            <Input placeholder="根据系统/类型/计划日期自动生成，可手动修改" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="system" label="升级系统" rules={[{ required: true, message: '请选择或输入系统' }]}>
            <SystemSelect />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="upgrade_type" label="升级类型" rules={[{ required: true, message: '请选择升级类型' }]}>
            <Select placeholder="请选择升级类型">
              <Option value="功能升级">功能升级</Option>
              <Option value="Bug修复">Bug修复</Option>
              <Option value="安全补丁">安全补丁</Option>
              <Option value="性能优化">性能优化</Option>
            </Select>
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="owner" label="负责人" rules={[{ required: true, message: '请输入负责人' }]}>
            <Input placeholder="请输入负责人" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="upgrade_time" label="计划升级时间" rules={[{ required: true, message: '请选择计划升级时间' }]}>
            <DatePicker showTime style={{ width: '100%' }} placeholder="请选择计划升级时间" />
          </Form.Item>
        </Col>
        <Col span={24}>
          <Form.Item name="upgrade_no" label="升级单号">
            <Input
              placeholder="保存后自动生成"
              disabled
              addonAfter={upgradeNo ? (
                <CopyOutlined
                  onClick={() => {
                    if (navigator.clipboard) {
                      navigator.clipboard.writeText(upgradeNo);
                      message.success('已复制单号');
                    }
                  }}
                  style={{ cursor: 'pointer' }}
                  title="复制单号"
                />
              ) : null}
            />
          </Form.Item>
        </Col>
      </Row>
    </>
  );
}

function UpgradeDescFields() {
  return (
    <>
      <div style={{ fontWeight: 600, marginBottom: 12, color: '#262626' }}>升级说明</div>
      <Form.Item name="upgrade_content" label="升级内容" rules={[{ required: true, message: '请输入升级内容' }]}>
        <TextArea rows={3} placeholder="说明这次要升级什么" />
      </Form.Item>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="impact_scope" label="影响范围">
            <TextArea rows={2} placeholder="说明影响哪些系统、模块、用户或服务（选填）" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="risk_desc" label="风险说明">
            <TextArea rows={2} placeholder="说明停机、兼容性、数据、回退等风险（选填）" />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="rollback_plan" label="回退方案摘要">
        <TextArea rows={2} placeholder="简要说明发生问题时如何回退（选填）" />
      </Form.Item>
    </>
  );
}

function InitConfigFields({ selectedPlan, onApplyPlan, onClearPlan }) {
  return (
    <>
      <div style={{ fontWeight: 600, marginBottom: 12, color: '#262626' }}>初始化配置</div>
      <Form.Item
        label="升级方案/步骤模板"
        tooltip="选择后保存时自动初始化该升级单的步骤清单；不选则创建空步骤清单，后续在升级工作台维护"
      >
        <Select
          allowClear
          placeholder="选择方案以初始化步骤清单（选填）"
          value={selectedPlan?.id}
          onChange={(v) => v ? onApplyPlan(v) : onClearPlan()}
          onClear={onClearPlan}
        >
          {store.plans.map(p => (
            <Option key={p.id} value={p.id}>
              {p.is_default ? '⭐ ' : ''}{p.name}{p.step_count ? ` (${p.step_count}步)` : ''}
            </Option>
          ))}
        </Select>
      </Form.Item>
    </>
  );
}

export default observer(function CreateUpgradeModal() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [selectedPlan, setSelectedPlan] = useState(null);
  const [upgradeNo, setUpgradeNo] = useState('');
  const [titleTouched, setTitleTouched] = useState(false);

  useEffect(() => {
    // 打开时加载建单所需数据
    store.fetchNextUpgradeNo().then(no => { if (no) setUpgradeNo(no); });
    store.fetchPlans();
    store.fetchSystems();
    store.fetchFilterOptions();
  }, []);

  // 标题自动生成
  function buildTitle(allValues) {
    const parts = [];
    if (allValues.system) parts.push(allValues.system);
    if (allValues.upgrade_type) parts.push(allValues.upgrade_type);
    if (allValues.upgrade_time) {
      const t = allValues.upgrade_time;
      parts.push(t && t.format ? t.format('YYYY-MM-DD') : String(t));
    }
    return parts.filter(Boolean).join(' - ');
  }

  function onValuesChange(changed, all) {
    if ('title' in changed) {
      const v = changed.title;
      // 用户手动修改标题后锁定；清空标题则恢复自动生成
      if (v === '' || v == null) {
        setTitleTouched(false);
        form.setFieldsValue({ title: buildTitle(all) });
      } else {
        setTitleTouched(true);
      }
      return;
    }
    if (!titleTouched && ('system' in changed || 'upgrade_type' in changed || 'upgrade_time' in changed)) {
      form.setFieldsValue({ title: buildTitle(all) });
    }
  }

  function handleApplyPlan(planId) {
    store.fetchPlanDetail(planId).then(plan => {
      if (!plan) { message.error('获取方案失败'); return; }
      setSelectedPlan(plan);
      const values = {};
      if (plan.system) values.system = plan.system;
      if (plan.upgrade_type) values.upgrade_type = plan.upgrade_type;
      if (plan.version) values.version = plan.version;
      if (plan.owner) values.owner = plan.owner;
      form.setFieldsValue(values);
      // 方案预填后重新生成标题（若用户未手动编辑过标题）
      if (!titleTouched) {
        form.setFieldsValue({ title: buildTitle(form.getFieldsValue()) });
      }
      const stepCount = (plan.steps || []).length;
      message.info(`已应用方案「${plan.name}」基本信息${stepCount ? `，保存后将自动生成 ${stepCount} 个步骤` : ''}`);
    });
  }

  function doSave(redirectMode) {
    form.validateFields().then(values => {
      setLoading(true);
      const formData = { ...values };
      if (formData.upgrade_time) {
        formData.upgrade_time = formData.upgrade_time.format('YYYY-MM-DD HH:mm:ss');
      }
      // 新建：升级单号由后端自动生成，状态由后端默认"处理中"，前端不传
      delete formData.upgrade_no;
      delete formData.status;

      http.post('/api/upgrade/records/create/', formData)
        .then((res) => {
          if (selectedPlan && res && res.id) {
            return store.applyPlan(selectedPlan.id, res.id)
              .then((applyRes) => {
                message.success(`创建成功，已应用方案「${selectedPlan.name}」${applyRes.created_count} 个步骤`);
                return res;
              })
              .catch(() => {
                message.warning('创建成功，方案步骤应用失败，可在工作台中手动应用');
                return res;
              });
          }
          message.success('创建成功');
          return res;
        })
        .then((res) => {
          store.hideCreateForm();
          store.fetchRecords();
          if (redirectMode === 'workbench' && res && res.id) {
            history.push(`/upgrade/workbench/${res.id}`);
          }
        })
        .catch(() => {})
        .finally(() => setLoading(false));
    }).catch(() => {});
  }

  function handleCancel() {
    store.hideCreateForm();
  }

  return (
    <Modal
      visible
      width={860}
      maskClosable={false}
      title="新建升级申请"
      onCancel={handleCancel}
      bodyStyle={{ maxHeight: '70vh', overflowY: 'auto', paddingRight: 8 }}
      footer={[
        <Button key="cancel" onClick={handleCancel}>取消</Button>,
        <Button key="save" loading={loading} onClick={() => doSave('list')}>仅保存</Button>,
        <Button key="saveWorkbench" type="primary" loading={loading} onClick={() => doSave('workbench')}>
          保存并进入工作台
        </Button>,
      ]}
    >
      <Form form={form} layout="vertical" onValuesChange={onValuesChange}>
        <BasicInfoFields upgradeNo={upgradeNo} />
        <Divider style={{ margin: '8px 0 16px' }} />
        <UpgradeDescFields />
        <Divider style={{ margin: '8px 0 16px' }} />
        <InitConfigFields
          selectedPlan={selectedPlan}
          onApplyPlan={handleApplyPlan}
          onClearPlan={() => setSelectedPlan(null)}
        />
      </Form>
    </Modal>
  );
});
