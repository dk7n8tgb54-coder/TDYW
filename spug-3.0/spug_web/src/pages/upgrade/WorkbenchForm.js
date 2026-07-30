/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect, useState, forwardRef, useImperativeHandle } from 'react';
import { observer } from 'mobx-react';
import {
  Form, Input, Select, AutoComplete, DatePicker, Button, message, Progress, Tag, Popconfirm,
  Switch, Tooltip, Space, Timeline, Empty, Row, Col, Collapse, Divider, Dropdown,
  Menu, Modal, Card
} from 'antd';
import { 
  PlusOutlined, CheckCircleOutlined, 
  PrinterOutlined, DeleteOutlined, PaperClipOutlined, DownOutlined 
} from '@ant-design/icons';
import { AttachmentManager } from 'components';
import { http, hasPermission } from 'libs';
import moment from 'moment';
import store from './store';
import { getActionColor, computeStepFlowState, renderFlowNode, STATUS_TAG_COLOR, StepStatusTag, groupStepsByPhase } from './shared';
import SystemSelect from './components/SystemSelect';

const { Option } = Select;
const { TextArea } = Input;
const { Panel } = Collapse;

const WorkbenchForm = forwardRef(function WorkbenchForm({ isNew, recordId, onSaveStart, onSaveEnd, onSaveSuccess, onSaveError }, ref) {
  const [form] = Form.useForm();
  const [selectedPlan, setSelectedPlan] = useState(null);
  
  // 状态时间线 - 异常事件记录
  
  // 添加步骤
  const [addStepVisible, setAddStepVisible] = useState(false);
  const [addStepForm] = Form.useForm();

  // 标题是否已被用户手动编辑（一旦手动修改，不再自动覆盖）
  const [titleTouched, setTitleTouched] = useState(false);

  // 编辑模式下方案下拉框受控值（操作后重置）
  const [planSelectValue, setPlanSelectValue] = useState(undefined);

  // 根据升级系统/类型/计划日期自动生成标题
  function recomputeTitle(allValues) {
    if (titleTouched) return;
    const parts = [];
    if (allValues.system) parts.push(allValues.system);
    if (allValues.upgrade_type) parts.push(allValues.upgrade_type);
    if (allValues.upgrade_time) {
      const t = allValues.upgrade_time;
      parts.push(t.format ? t.format('YYYY-MM-DD') : String(t));
    }
    form.setFieldsValue({ title: parts.filter(Boolean).join(' - ') });
  }

  // 表单值变化：标题手动编辑后锁定；其余关键字段变化时自动生成标题
  function onValuesChange(changed, all) {
    if ('title' in changed) {
      setTitleTouched(true);
      return;
    }
    if (!titleTouched && ('system' in changed || 'upgrade_type' in changed || 'upgrade_time' in changed)) {
      recomputeTitle(all);
    }
  }

  // 暴露 submit 给父组件（替代 window 全局变量）
  useImperativeHandle(ref, () => ({
    submit: handleSubmit
  }));

  // 同步 form 数据到 store.record
  useEffect(() => {
    if (!isNew && store.record.id) {
      form.setFieldsValue({
        ...store.record,
        upgrade_time: store.record.upgrade_time ? moment(store.record.upgrade_time) : null,
      });
    }
  }, [store.record, isNew]);

  function handleSubmit(redirectMode) {
    form.validateFields().then(values => {
      if (onSaveStart) onSaveStart();
      const formData = { ...values };

      if (formData.upgrade_time) {
        formData.upgrade_time = formData.upgrade_time.format('YYYY-MM-DD HH:mm:ss');
      }

      // 新建模式：状态由后端默认"处理中"，前端不传
      if (isNew) {
        delete formData.status;
      }

      const url = isNew
        ? '/api/upgrade/records/create/'
        : `/api/upgrade/records/${recordId}/update/`;
      const method = isNew ? 'post' : 'put';

      http[method](url, formData)
        .then((res) => {
          if (isNew && selectedPlan && res && res.id) {
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
          message.success(isNew ? '创建成功' : '保存成功');
          return res;
        })
        .then((res) => {
          if (onSaveSuccess) onSaveSuccess(res && res.id, redirectMode);
        })
        .catch(() => {
          if (onSaveError) onSaveError();
        });
    }).catch(() => {
      if (onSaveError) onSaveError();
    });
  }

  // 步骤操作
  function handleStepAction(step, action) {
    http.put(`/api/upgrade/record-steps/${step.id}/update/`, { action })
      .then(() => {
        const actionText = action === 'complete' ? '完成' : '重置';
        message.success(`步骤已标记为${actionText}`);
        store.fetchRecordSteps(recordId);
        store.fetchStatusLogs(recordId);
        store.fetchRecords();
      });
  }

  function handleDeleteStep(step) {
    http.delete(`/api/upgrade/record-steps/${step.id}/delete/`)
      .then(() => {
        message.success('步骤已删除');
        store.fetchRecordSteps(recordId);
        store.fetchRecords();
      });
  }

  function handleAddStep(values) {
    http.post(`/api/upgrade/records/${recordId}/steps/add/`, values)
      .then(() => {
        message.success('步骤添加成功');
        setAddStepVisible(false);
        addStepForm.resetFields();
        store.fetchRecordSteps(recordId);
      });
  }

  function handleClearSteps() {
    http.delete(`/api/upgrade/records/${recordId}/steps/clear/`)
      .then(() => {
        message.success('已清空所有步骤');
        store.fetchRecordSteps(recordId);
      });
  }

  // 流程节点操作（暂停/继续/失败/回退；完成靠逐个打勾步骤）
  function handleNodeAction(action, node) {
    const payload = {
      action,
      remark: '',
      target_action: action === 'rollback' ? node.label : '',
      phase: ['pause', 'resume', 'test_fail'].includes(action) ? node.label : '',
    };
    http.post(`/api/upgrade/records/${recordId}/status-logs/`, payload)
      .then((res) => {
        const actionText = { pause: '已暂停', resume: '已继续', test_fail: '已标记失败', rollback: '已回退' }[action];
        message.success(actionText);
        if (res && res.id) {
          store.statusLogs = [res, ...store.statusLogs];
          if (res.to_status && res.to_status !== res.from_status) {
            store.record.status = res.to_status;
          }
        } else {
          store.fetchStatusLogs(recordId);
        }
        // rollback 会重置步骤，需刷新步骤清单
        if (action === 'rollback') {
          store.fetchRecordSteps(recordId);
        }
        store.fetchRecords();
      });
  }

  function handleDeleteStatusLog(logId) {
    http.delete(`/api/upgrade/status-logs/${logId}/delete/`)
      .then(() => {
        message.success('日志已删除');
        store.fetchStatusLogs(recordId);
        store.fetchRecords();
        // 后端删除日志后重算了主表 status，同步刷新当前记录
        store.fetchRecord(recordId).catch(() => {});
      });
  }

  // 应用方案
  function handleApplyPlan(planId, isEditMode) {
    if (isEditMode) {
      if (!recordId) return;
      const plan = store.plans.find(p => p.id === planId);
      const existingSteps = store.recordSteps;
      const hasExisting = existingSteps.length > 0;

      function doApply(replace) {
        store.applyPlan(planId, recordId, replace)
          .then(res => {
            const parts = [`已应用方案${plan ? `「${plan.name}」` : ''}`];
            if (res.deleted_count > 0) {
              parts.push(`替换 ${res.deleted_count} 个旧步骤`);
            }
            parts.push(`新增 ${res.created_count} 个步骤`);
            message.success(parts.join('，'));
            store.fetchRecordSteps(recordId);
          })
          .catch(() => {
            message.error('应用方案失败');
          })
          .finally(() => {
            setPlanSelectValue(undefined);
          });
      }

      if (hasExisting) {
        const executedCount = existingSteps.filter(
          s => s.status === 'completed' || s.status === 'skipped'
        ).length;
        const title = '应用方案将替换现有步骤';
        const content = executedCount > 0
          ? `当前已有 ${existingSteps.length} 个步骤（其中 ${executedCount} 个已执行），应用方案将替换所有现有步骤，是否继续？`
          : `当前已有 ${existingSteps.length} 个步骤，应用方案将替换所有现有步骤，是否继续？`;
        Modal.confirm({
          title,
          content,
          okText: '替换',
          cancelText: '取消',
          okButtonProps: { danger: executedCount > 0 },
          onOk: () => doApply(true),
          onCancel: () => setPlanSelectValue(undefined),
        });
      } else {
        doApply(false);
      }
    } else {
      store.fetchPlanDetail(planId).then(plan => {
        if (!plan) { message.error('获取方案失败'); return; }
        setSelectedPlan(plan);
        const values = {};
        if (plan.system) values.system = plan.system;
        if (plan.upgrade_type) values.upgrade_type = plan.upgrade_type;
        form.setFieldsValue(values);
        // 方案预填后重新生成标题（若用户未手动编辑过标题）
        recomputeTitle(form.getFieldsValue());
        const stepCount = (plan.steps || []).length;
        message.info(`已应用方案「${plan.name}」基本信息${stepCount ? `，保存后将自动生成 ${stepCount} 个步骤` : ''}`);
      });
    }
  }

  // 打印基本信息（存档封面）
  function handlePrintBasicInfo() {
    const win = window.open('', '_blank', 'width=900,height=700');
    if (!win) { message.warning('请允许浏览器弹窗以打印基本信息'); return; }

    const escapeHtml = (s) => String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');

    const info = store.record;
    const fields = [
      ['标题', info.title],
      ['系统', info.system],
      ['升级类型', info.upgrade_type],
      ['负责人', info.owner],
      ['计划升级时间', info.upgrade_time],
      ['状态', info.status],
    ];
    const blocks = [
      ['升级内容', info.upgrade_content],
      ['影响范围', info.impact_scope],
      ['风险说明', info.risk_desc],
      ['回退方案摘要', info.rollback_plan],
    ];
    const rowsHtml = fields.map(([k, v]) =>
      `<tr><th>${k}</th><td>${escapeHtml(v || '-')}</td></tr>`
    ).join('');
    const blocksHtml = blocks.map(([k, v]) =>
      `<div style="margin-top:14px"><div style="font-weight:bold;border-bottom:1px solid #000;padding-bottom:4px">${k}</div><div style="padding:8px 4px;min-height:40px;white-space:pre-wrap;line-height:1.8">${escapeHtml(v || '（无）')}</div></div>`
    ).join('');

    win.document.write(`<!DOCTYPE html><html><head><meta charset="utf-8"><title>升级存档 - ${escapeHtml(info.title)}</title><style>@page { size: A4 portrait; margin: 15mm; } body { font-family: -apple-system, "Microsoft YaHei", "PingFang SC", sans-serif; font-size: 13px; color: #000; margin: 0; } h1 { font-size: 22px; text-align: center; margin: 0 0 6px; } .subtitle { text-align: center; color: #666; font-size: 12px; margin-bottom: 20px; } table { width: 100%; border-collapse: collapse; } th, td { border: 1px solid #000; padding: 8px 10px; text-align: left; } th { background: #f0f0f0; font-weight: bold; width: 130px; } .footer { margin-top: 28px; font-size: 11px; color: #666; text-align: right; border-top: 1px dashed #999; padding-top: 6px; } .no-print { text-align: center; margin-top: 20px; } .no-print button { padding: 6px 18px; margin: 0 6px; font-size: 13px; cursor: pointer; } @media print { .no-print { display: none; } }</style></head><body><h1>升级存档</h1><div class="subtitle">升级基本信息</div><table>${rowsHtml}</table>${blocksHtml}<div class="footer">打印时间：${new Date().toLocaleString()}</div><div class="no-print"><button onclick="window.print()">打印</button><button onclick="window.close()">关闭</button></div></body></html>`);
    win.document.close();
    win.focus();
    setTimeout(() => { try { win.print(); } catch (e) {} }, 300);
  }

  // 打印步骤清单
  function handlePrintSteps(phase) {
    const win = window.open('', '_blank', 'width=900,height=700');
    if (!win) { message.warning('请允许浏览器弹窗以打印步骤清单'); return; }

    const escapeHtml = (s) => String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');

    let printSteps;
    if (phase) {
      printSteps = store.recordSteps.filter(s => s.phase === phase);
    } else {
      printSteps = store.recordSteps;
    }

    const phases = store.filterOptions.phases || [];
    const { groups, ungrouped } = groupStepsByPhase(printSteps, phases);

    const buildSection = (title, steps) => {
      const rows = steps.map((s, i) => {
        const desc = s.description || s.remark || '';
        return `<tr><td style="text-align:center">${s.sequence || i + 1}</td><td><div class="step-title">${escapeHtml(s.title)}</div>${desc ? `<div class="step-desc">${escapeHtml(desc)}</div>` : ''}</td><td style="text-align:center">☐</td><td></td></tr>`;
      }).join('');
      return `<div class="phase-section"><div class="phase-header">【${escapeHtml(title)}】 <span class="phase-check">阶段完成：☐</span></div><table><thead><tr><th style="width:40px">序号</th><th>步骤说明</th><th style="width:70px">执行情况</th><th style="width:120px">备注</th></tr></thead><tbody>${rows || '<tr><td colspan="4" style="text-align:center">暂无步骤</td></tr>'}</tbody></table></div>`;
    };

    let sectionsHtml = '';
    if (phase) {
      const target = groups.find(g => g.name === phase);
      sectionsHtml = buildSection(phase, target ? target.steps : []);
    } else {
      sectionsHtml = groups.map(g => buildSection(g.name, g.steps)).join('');
      if (ungrouped.length > 0) {
        sectionsHtml += buildSection('未分组', ungrouped);
      }
    }

    const info = store.record;
    win.document.write(`<!DOCTYPE html><html><head><meta charset="utf-8"><title>升级步骤执行清单 - ${escapeHtml(info.title)}</title><style>@page { size: A4 portrait; margin: 15mm; } body { font-family: -apple-system, "Microsoft YaHei", "PingFang SC", sans-serif; font-size: 12px; color: #000; margin: 0; } h1 { font-size: 18px; text-align: center; margin: 0 0 8px; } .meta { margin: 8px 0 12px; border-bottom: 2px solid #000; padding-bottom: 8px; } .meta div { display: inline-block; margin-right: 28px; line-height: 1.9; } .meta b { font-weight: bold; } table { width: 100%; border-collapse: collapse; margin-top: 4px; } th, td { border: 1px solid #000; padding: 8px; text-align: left; vertical-align: top; } th { background: #f0f0f0; font-weight: bold; text-align: center; font-size: 12px; } td { line-height: 28px; } .step-title { font-weight: bold; } .step-desc { font-size: 11px; color: #444; margin-top: 4px; line-height: 1.5; } .phase-section { margin-bottom: 16px; page-break-inside: avoid; } .phase-header { font-weight: bold; font-size: 13px; padding: 6px 8px; background: #f0f0f0; border: 1px solid #000; border-bottom: none; display: flex; justify-content: space-between; } .phase-check { font-weight: normal; font-size: 11px; } .sign { margin-top: 24px; font-size: 12px; } .sign div { display: inline-block; margin-right: 60px; } .footer { margin-top: 16px; font-size: 11px; color: #666; text-align: right; border-top: 1px dashed #999; padding-top: 6px; } .no-print { text-align: center; margin-top: 20px; } .no-print button { padding: 6px 18px; margin: 0 6px; font-size: 13px; cursor: pointer; } @media print { .no-print { display: none; } }</style></head><body><h1>升级步骤执行清单</h1><div class="meta"><div><b>标题：</b>${escapeHtml(info.title)}</div><div><b>系统：</b>${escapeHtml(info.system)}</div><div><b>升级类型：</b>${escapeHtml(info.upgrade_type)}</div><div><b>升级时间：</b>${escapeHtml(info.upgrade_time)}</div><div><b>负责人：</b>${escapeHtml(info.owner)}</div><div><b>状态：</b>${escapeHtml(info.status)}</div></div>${sectionsHtml || '<div style="text-align:center;padding:20px;">暂无步骤</div>'}<div class="sign"><div>执行人签字：________________</div><div>使用部门确认：________________</div></div><div class="footer">打印时间：${new Date().toLocaleString()}</div><div class="no-print"><button onclick="window.print()">打印</button><button onclick="window.close()">关闭</button></div></body></html>`);
    win.document.close();
    win.focus();
    setTimeout(() => { try { win.print(); } catch (e) {} }, 300);
  }

  // 渲染头部信息栏
  function renderHeader(canEdit) {
    const info = store.record;
    return (
      <div style={{ background: '#fafafa', padding: '12px 16px', borderRadius: 4, marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '4px 24px' }}>
          <span><strong>标题：</strong>{info.title || '-'}</span>
          <span><strong>系统：</strong>{info.system}</span>
          <span><strong>类型：</strong>{info.upgrade_type}</span>
          <span><strong>时间：</strong>{info.upgrade_time}</span>
          <span><strong>负责人：</strong>{info.owner}</span>
          <span><strong>状态：</strong><Tag color={STATUS_TAG_COLOR[info.status] || 'default'}>{info.status}</Tag></span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
            <Button size="small" icon={<PrinterOutlined />} onClick={handlePrintBasicInfo}>打印基本信息</Button>
            <Dropdown overlay={(
              <Menu>
                <Menu.Item key="all" onClick={() => handlePrintSteps()} disabled={store.recordSteps.length === 0}>打印全部阶段</Menu.Item>
                <Menu.Divider />
                {(store.filterOptions.phases || []).map(p => (
                  <Menu.Item key={p} onClick={() => handlePrintSteps(p)}>只打印【{p}】</Menu.Item>
                ))}
              </Menu>
            )}>
              <Button size="small" icon={<PrinterOutlined />} disabled={store.recordSteps.length === 0}>
                打印步骤 <DownOutlined />
              </Button>
            </Dropdown>
          </span>
        </div>
        {canEdit && (
          <Collapse ghost style={{ marginTop: 4 }}>
            <Panel header="编辑基本信息" key="edit-basic">
              <Form form={form} layout="vertical">
                <Row gutter={16}>
                  <Col span={12}>
                    <Form.Item name="title" label="标题">
                      <Input placeholder="标题" />
                    </Form.Item>
                  </Col>
                  <Col span={6}>
                    <Form.Item name="system" label="系统">
                      <SystemSelect placeholder="系统" />
                    </Form.Item>
                  </Col>
                  <Col span={6}>
                    <Form.Item name="upgrade_type" label="类型">
                      <Select placeholder="类型">
                        <Option value="功能升级">功能升级</Option>
                        <Option value="Bug修复">Bug修复</Option>
                        <Option value="安全补丁">安全补丁</Option>
                        <Option value="性能优化">性能优化</Option>
                      </Select>
                    </Form.Item>
                  </Col>
                  <Col span={6}>
                    <Form.Item name="owner" label="负责人">
                      <Input placeholder="负责人" />
                    </Form.Item>
                  </Col>
                  <Col span={6}>
                    <Form.Item name="upgrade_time" label="计划升级时间">
                      <DatePicker showTime style={{ width: '100%' }} placeholder="计划升级时间" />
                    </Form.Item>
                  </Col>
                  <Col span={6}>
                    <Form.Item name="status" label="状态">
                      <Select placeholder="状态">
                        <Option value="处理中">处理中</Option>
                        <Option value="已完成">已完成</Option>
                        <Option value="已回退">已回退</Option>
                      </Select>
                    </Form.Item>
                  </Col>
                  <Col span={24}>
                    <Form.Item name="upgrade_content" label="升级内容">
                      <TextArea rows={2} placeholder="升级内容" />
                    </Form.Item>
                  </Col>
                  <Col span={12}>
                    <Form.Item name="impact_scope" label="影响范围">
                      <TextArea rows={2} placeholder="影响范围（选填）" />
                    </Form.Item>
                  </Col>
                  <Col span={12}>
                    <Form.Item name="risk_desc" label="风险说明">
                      <TextArea rows={2} placeholder="风险说明（选填）" />
                    </Form.Item>
                  </Col>
                  <Col span={24}>
                    <Form.Item name="rollback_plan" label="回退方案摘要">
                      <TextArea rows={2} placeholder="回退方案摘要（选填）" />
                    </Form.Item>
                  </Col>
                </Row>
              </Form>
            </Panel>
          </Collapse>
        )}
      </div>
    );
  }

  // 渲染单个步骤行
  function renderStepRow(step, canEdit) {
    return (
      <div key={step.id} style={{
        display: 'flex', alignItems: 'center', padding: '8px 12px',
        borderBottom: '1px solid #f0f0f0', gap: 8,
        backgroundColor: step.status === 'completed' ? '#f6ffed' :
          step.status === 'skipped' ? '#fff7e6' : 'transparent'
      }}>
        <span style={{ color: '#999', minWidth: 20, fontWeight: 'bold' }}>{step.sequence}.</span>
        <StepStatusTag status={step.status} />
        <span style={{
          flex: 1, textDecoration: 'none',
          color: step.status !== 'pending' ? '#999' : '#333', fontSize: 13
        }}>{step.title}</span>
        {step.is_required && <Tag color="blue" style={{ margin: 0 }}>必选</Tag>}
        {step.description && (
          <Tooltip title={step.description}>
            <span style={{ color: '#1890ff', cursor: 'help', fontSize: 12 }}>详情</span>
          </Tooltip>
        )}
        {step.completed_by && (
          <span style={{ color: '#bbb', fontSize: 11, whiteSpace: 'nowrap' }}>{step.completed_by} {step.completed_at}</span>
        )}
        {canEdit && (
          <Space size={0}>
            {step.status === 'pending' && (
                <Button size="small" type="link" icon={<CheckCircleOutlined />} onClick={() => handleStepAction(step, 'complete')}>完成</Button>
            )}
            {step.status !== 'pending' && hasPermission('upgrade.upgrade.step_reset') && (
              <Button size="small" type="link" onClick={() => handleStepAction(step, 'reset')}>重置</Button>
            )}
            {hasPermission('upgrade.upgrade.step_del') && (
              <Button size="small" type="link" danger onClick={() => handleDeleteStep(step)}>删除</Button>
            )}
          </Space>
        )}
      </div>
    );
  }

  // 渲染步骤清单面板
  function renderStepsPanel(canEdit) {
    const phases = store.filterOptions.phases || [];
    const { groups, ungrouped } = groupStepsByPhase(store.recordSteps, phases);

    const stepStats = store.recordStepStats || {};
    const total = stepStats.total || store.recordSteps.length;
    const completed = stepStats.completed || 0;
    const progress = total > 0 ? Math.round((completed / total) * 100) : 0;

    return (
      <Col span={15}>
        <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontWeight: 'bold' }}>
            步骤清单 <span style={{ color: '#999', fontSize: 12 }}>（{completed}/{total}）</span>
          </span>
          {canEdit && (
            <Space size={4}>
              {store.plans.length > 0 && (
                <Select
                  size="small" style={{ width: 200 }} placeholder="应用方案" allowClear
                  value={planSelectValue}
                  onChange={(v) => v && handleApplyPlan(v, true)}
                >
                  {store.plans.map(p => (
                    <Option key={p.id} value={p.id}>{p.name} ({p.step_count}步)</Option>
                  ))}
                </Select>
              )}
              <Button size="small" icon={<PlusOutlined />} onClick={() => setAddStepVisible(true)}>添加步骤</Button>
              {store.recordSteps.length > 0 && hasPermission('upgrade.upgrade.step_del') && (
                <Popconfirm title="确定清空所有步骤？" onConfirm={handleClearSteps}>
                  <Button size="small" danger>清空</Button>
                </Popconfirm>
              )}
            </Space>
          )}
        </div>

        {total > 0 && (
          <Progress percent={progress} size="small" style={{ marginBottom: 8 }}
            status={progress === 100 ? 'success' : 'active'}
            format={() => `${completed}/${total}`} />
        )}

        <div style={{ maxHeight: 400, overflowY: 'auto', border: '1px solid #f0f0f0', borderRadius: 4 }}>
          {groups.map(g => {
            const doneCount = g.steps.filter(s => s.status === 'completed').length;
            return (
              <div key={g.name}>
                <div style={{
                  background: '#fafafa', padding: '4px 12px', fontSize: 12,
                  fontWeight: 'bold', color: '#555', borderBottom: '1px solid #f0f0f0',
                  display: 'flex', justifyContent: 'space-between'
                }}>
                  <span>【{g.name}】</span>
                  <span style={{ color: '#999' }}>{doneCount}/{g.steps.length}</span>
                </div>
                {g.steps.map(step => renderStepRow(step, canEdit))}
              </div>
            );
          })}
          {ungrouped.length > 0 && (
            <div>
              <div style={{ background: '#fafafa', padding: '4px 12px', fontSize: 12, fontWeight: 'bold', color: '#555', borderBottom: '1px solid #f0f0f0' }}>【未分组】</div>
              {ungrouped.map(step => renderStepRow(step, canEdit))}
            </div>
          )}
          {store.recordSteps.length === 0 && (
            <div style={{ textAlign: 'center', color: '#999', padding: 32, fontSize: 13 }}>
              暂无步骤{canEdit ? '，可通过上方应用方案或手动添加' : ''}
            </div>
          )}
        </div>
      </Col>
    );
  }

  // 渲染流程节点（带交互：current→暂停/失败菜单，paused→继续，completed→回退，failed→提示）
  function renderFlowNodeWithAction(node, idx, canEdit) {
    const el = renderFlowNode(node, idx);
    if (!canEdit) return <span key={node.action}>{el}</span>;
    if (node.state === 'current') {
      return (
        <Dropdown key={node.action} overlay={(
          <Menu onClick={({ key }) => handleNodeAction(key, node)}>
            <Menu.Item key="pause">暂停该阶段</Menu.Item>
            <Menu.Item key="test_fail">标记失败</Menu.Item>
          </Menu>
        )}>
          <span style={{ cursor: 'pointer' }}>{el}</span>
        </Dropdown>
      );
    }
    if (node.state === 'paused') {
      return (
        <Popconfirm key={node.action} title="继续该阶段？" onConfirm={() => handleNodeAction('resume', node)}>
          <span style={{ cursor: 'pointer' }}>{el}</span>
        </Popconfirm>
      );
    }
    if (node.state === 'completed') {
      return (
        <Popconfirm key={node.action} title={`回退到【${node.label}】？该阶段及之后的步骤将重置为待执行`} onConfirm={() => handleNodeAction('rollback', node)}>
          <span style={{ cursor: 'pointer' }}>{el}</span>
        </Popconfirm>
      );
    }
    if (node.state === 'failed') {
      return <Tooltip key={node.action} title="该阶段失败，请回退到之前的阶段重做">{el}</Tooltip>;
    }
    return <span key={node.action}>{el}</span>;
  }

  // 渲染时间线面板
  function renderTimelinePanel(canEdit) {
    const flowNodes = computeStepFlowState(store.recordSteps, store.filterOptions.phases, store.statusLogs).nodes;
    return (
      <Col span={9}>
        <div style={{ marginBottom: 8, fontWeight: 'bold' }}>
          状态时间线 <span style={{ color: '#999', fontSize: 12 }}>（{store.statusLogs.length}）</span>
        </div>

        <div style={{ background: '#f6f8fa', border: '1px solid #e8e8e8', borderRadius: 4, padding: '8px 10px', marginBottom: 8 }}>
          <div style={{ fontSize: 11, color: '#999', marginBottom: 6 }}>升级流程</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {flowNodes.length > 0
              ? flowNodes.map((node, idx) => renderFlowNodeWithAction(node, idx + 1, canEdit))
              : <span style={{ color: '#bbb', fontSize: 11 }}>暂无阶段（请为步骤设置阶段）</span>}
          </div>
        </div>

        <div style={{ maxHeight: 360, overflowY: 'auto', border: '1px solid #f0f0f0', borderRadius: 4, padding: 12 }}>
          {store.statusLogs.length > 0 ? (
            <Timeline>
              {store.statusLogs.map(log => {
                const isPhaseDone = log.action === 'phase_done';
                const logColor = isPhaseDone
                  ? (log.outcome === 'failed' ? 'red' : log.outcome === 'revoked' ? 'default' : 'green')
                  : getActionColor(log.action);
                const tagText = isPhaseDone ? `✓ ${log.phase || '阶段'}` : log.action_text;
                const dimmed = isPhaseDone && log.outcome === 'revoked';
                return (
                <Timeline.Item key={log.id} color={logColor}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', opacity: dimmed ? 0.5 : 1 }}>
                    <div style={{ flex: 1 }}>
                      <div>
                        <Tag color={logColor} style={{ marginRight: 4 }}>{tagText}</Tag>
                        {isPhaseDone && log.outcome === 'failed' && (
                          <Tag color="red" style={{ marginLeft: 4, fontSize: 10, lineHeight: '16px' }}>已失败</Tag>
                        )}
                        {isPhaseDone && log.outcome === 'revoked' && (
                          <Tag color="default" style={{ marginLeft: 4, fontSize: 10, lineHeight: '16px' }}>已撤销</Tag>
                        )}
                        {log.action === 'rollback' && log.target_action_text && (
                          <span style={{ color: '#ff4d4f', fontSize: 11, marginLeft: 2 }}>回退到：{log.target_action_text}</span>
                        )}
                        {log.action === 'test_fail' && log.phase && (
                          <span style={{ color: '#ff4d4f', fontSize: 11, marginLeft: 2 }}>失败阶段：{log.phase}</span>
                        )}
                        {log.to_status && log.to_status !== log.from_status && (
                          <span style={{ color: '#999', fontSize: 11 }}>{log.from_status}→{log.to_status}</span>
                        )}
                      </div>
                      <div style={{ color: '#999', fontSize: 11, marginTop: 2 }}>{log.operator_name} · {log.created_at}</div>
                      {log.remark && <div style={{ color: '#555', marginTop: 4, fontSize: 12 }}>{log.remark}</div>}
                    </div>
                    {canEdit && (
                      <Popconfirm title="确定删除此日志？" onConfirm={() => handleDeleteStatusLog(log.id)}>
                        <Button type="link" size="small" danger icon={<DeleteOutlined />} style={{ padding: 0 }} />
                      </Popconfirm>
                    )}
                  </div>
                </Timeline.Item>
                );
              })}
            </Timeline>
          ) : (
            <Empty description="暂无状态记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          )}
        </div>
      </Col>
    );
  }

  // ===== 新建模式表单（只负责建单，不承载升级执行过程）=====
  if (isNew) {
    const initialValues = { ...store.record };
    if (initialValues.upgrade_time) {
      initialValues.upgrade_time = moment(initialValues.upgrade_time);
    }

    return (
      <Form form={form} initialValues={initialValues} onValuesChange={onValuesChange} layout="vertical">
        {/* 基本信息 */}
        <Card size="small" title="基本信息" style={{ marginBottom: 16 }}>
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
          </Row>
        </Card>

        {/* 升级说明 */}
        <Card size="small" title="升级说明" style={{ marginBottom: 16 }}>
          <Form.Item name="upgrade_content" label="升级内容" rules={[{ required: true, message: '请输入升级内容' }]}>
            <TextArea rows={3} placeholder="说明这次要升级什么" />
          </Form.Item>
          <Form.Item name="impact_scope" label="影响范围">
            <TextArea rows={2} placeholder="说明影响哪些系统、模块、用户或服务（选填）" />
          </Form.Item>
          <Form.Item name="risk_desc" label="风险说明">
            <TextArea rows={2} placeholder="说明停机、兼容性、数据、回退等风险（选填）" />
          </Form.Item>
          <Form.Item name="rollback_plan" label="回退方案摘要">
            <TextArea rows={2} placeholder="简要说明发生问题时如何回退（选填）" />
          </Form.Item>
        </Card>

        {/* 初始化配置 */}
        <Card size="small" title="初始化配置">
          <Form.Item label="升级方案/步骤模板"
            tooltip="选择后保存时自动初始化该升级单的步骤清单；不选则创建空步骤清单，后续在升级工作台维护">
            <Select allowClear placeholder="选择方案以初始化步骤清单（选填）"
              value={selectedPlan?.id}
              onChange={(v) => v ? handleApplyPlan(v, false) : setSelectedPlan(null)}
              onClear={() => setSelectedPlan(null)}>
              {store.plans.map(p => (
                <Option key={p.id} value={p.id}>
                  {p.name}{p.step_count ? ` (${p.step_count}步)` : ''}
                </Option>
              ))}
            </Select>
          </Form.Item>
        </Card>
      </Form>
    );
  }

  // ===== 查看/编辑模式工作台 =====
  const canEdit = hasPermission('upgrade.upgrade.edit');
  const info = store.record;

  return (
    <div>
      {renderHeader(canEdit)}
      <Row gutter={16}>
        {renderStepsPanel(canEdit)}
        {renderTimelinePanel(canEdit)}
      </Row>
      <Divider style={{ margin: '16px 0 12px' }} />
      <Collapse>
        <Panel header={<span><PaperClipOutlined /> 附件 ({store.attachmentCount})</span>} key="att">
          <AttachmentManager
            module="upgrade" objectType="record" recordId={info.id}
            listUrl={`/api/upgrade/records/${info.id}/attachments/`}
            uploadUrl={`/api/upgrade/records/${info.id}/attachments/`}
            deleteUrl="/api/upgrade/attachments/"
            downloadUrlPrefix="/api/upgrade/attachments/"
            previewUrlPrefix="/api/upgrade/attachments/"
            readOnly={!canEdit}
            uploadPerm="upgrade.upgrade.edit" deletePerm="upgrade.upgrade.edit"
            previewPerm="upgrade.upgrade.view"
            maxFileSize={500} onCountChange={store.setAttachmentCount}
          />
        </Panel>
      </Collapse>


      {/* 添加步骤弹窗 */}
      <Modal title="添加步骤" visible={addStepVisible}
        onCancel={() => { setAddStepVisible(false); addStepForm.resetFields(); }}
        onOk={() => addStepForm.validateFields().then(handleAddStep)} width={500}>
        <Form form={addStepForm} labelCol={{ span: 5 }} wrapperCol={{ span: 17 }}>
          <Form.Item name="phase" label="所属阶段">
            <AutoComplete
              options={(store.filterOptions.phases || []).map(p => ({ value: p }))}
              allowClear
              placeholder="输入或选择步骤所属阶段（选填）"
              filterOption={(input, option) =>
                (option.value || '').toLowerCase().includes((input || '').toLowerCase())
              }
            />
          </Form.Item>
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
    </div>
  );
});

export default observer(WorkbenchForm);
