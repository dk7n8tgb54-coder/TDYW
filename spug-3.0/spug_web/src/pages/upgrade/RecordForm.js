/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, Select, DatePicker, Button, message, Progress, Tag, Popconfirm, Switch, Tooltip, Space, Timeline, Empty, Row, Col, Collapse, Divider, Dropdown, Menu } from 'antd';
import { PlusOutlined, CheckCircleOutlined, CloseCircleOutlined, CopyOutlined, DeploymentUnitOutlined, PrinterOutlined, HistoryOutlined, DeleteOutlined, PaperClipOutlined, DownOutlined } from '@ant-design/icons';
import { http, hasPermission } from 'libs';
import { AttachmentManager } from 'components';
import moment from 'moment';
import store from './store';

const { Option } = Select;
const { TextArea } = Input;
const { Panel } = Collapse;

// 动作类型 → 时间线颜色（与后端 ACTION_COLOR_MAP 对齐）
const ACTION_COLOR = {
  start: 'blue',
  backup: 'gray',
  gray_release: 'cyan',
  full_release: 'geekblue',
  test: 'orange',
  test_pass: 'green',
  test_fail: 'red',
  rollback: 'red',
  pause: 'gray',
  resume: 'blue',
  observe: 'purple',
  complete: 'green',
};
function _getActionColor(action) {
  return ACTION_COLOR[action] || 'blue';
}

// 标准升级流程顺序（主线，异常分支如回退/暂停/失败不进主线）
// 用于时间线顶部对照参考，用户可据此看"实际做到哪步"
const STANDARD_FLOW = [
  { action: 'start', label: '开始升级' },
  { action: 'backup', label: '备份' },
  { action: 'gray_release', label: '灰度发布' },
  { action: 'test', label: '升级测试' },
  { action: 'test_pass', label: '测试通过' },
  { action: 'full_release', label: '全量发布' },
  { action: 'observe', label: '上线观察期' },
  { action: 'complete', label: '完成' },
];

// 状态 → Tag 颜色
const STATUS_TAG_COLOR = {
  '处理中': 'processing',
  '已完成': 'success',
  '已回退': 'error',
};

export default observer(function () {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  // 新建模式下选中的方案（保存后自动应用其步骤）
  const [selectedPlan, setSelectedPlan] = useState(null);
  const [upgradeNo, setUpgradeNo] = useState('');

  // 步骤清单相关状态
  const [recordSteps, setRecordSteps] = useState([]);
  const [stepStats, setStepStats] = useState({ total: 0, completed: 0, skipped: 0, pending: 0, progress: 0 });
  const [addStepVisible, setAddStepVisible] = useState(false);
  const [addStepForm] = Form.useForm();

  // 附件计数
  const [attachmentCount, setAttachmentCount] = useState(0);

  // 状态时间线相关状态
  const [statusLogs, setStatusLogs] = useState([]);
  const [statusLogVisible, setStatusLogVisible] = useState(false);
  const [statusLogForm] = Form.useForm();
  const [actionOptions, setActionOptions] = useState([]);

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

  // 状态时间线：拉取日志 + 动作选项
  function fetchStatusLogs() {
    if (store.record.id) {
      http.get(`/api/upgrade/records/${store.record.id}/status-logs/`)
        .then(data => setStatusLogs(data || []))
        .catch(() => setStatusLogs([]));
    }
  }

  function fetchActionOptions() {
    http.get(`/api/upgrade/records/${store.record.id || 0}/status-logs/?action=options`)
      .then(data => setActionOptions(data || []))
      .catch(() => setActionOptions([]));
  }

  function handleAddStatusLog(values) {
    http.post(`/api/upgrade/records/${store.record.id}/status-logs/`, values)
      .then(() => {
        message.success('状态已记录');
        setStatusLogVisible(false);
        statusLogForm.resetFields();
        fetchStatusLogs();
        store.fetchRecords();  // 刷新列表（主表 status 可能联动变化）
      });
  }

  function handleDeleteStatusLog(logId) {
    http.delete(`/api/upgrade/status-logs/${logId}/delete/`)
      .then(() => {
        message.success('日志已删除');
        fetchStatusLogs();
      });
  }

  useEffect(() => {
    if (store.record.id) {
      fetchRecordSteps();
      fetchStatusLogs();
      fetchActionOptions();
    } else {
      // 新建模式：获取自动生成的升级单号 + 加载方案列表
      store.fetchNextUpgradeNo().then(no => {
        if (no) setUpgradeNo(no);
      });
      store.fetchPlans();
    }
  }, [store.record.id]);

  // 统一的方案应用入口
  function handleApplyPlan(planId, isEditMode) {
    if (isEditMode) {
      if (!store.record.id) return;
      const plan = store.plans.find(p => p.id === planId);
      store.applyPlan(planId, store.record.id)
        .then(res => {
          message.success(`已应用方案${plan ? `「${plan.name}」` : ''}，添加 ${res.created_count} 个步骤`);
          fetchRecordSteps();
        })
        .catch(() => {
          message.error('应用方案失败');
        });
    } else {
      store.fetchPlanDetail(planId).then(plan => {
        if (!plan) {
          message.error('获取方案失败');
          return;
        }
        setSelectedPlan(plan);
        const values = {};
        if (plan.system) values.system = plan.system;
        if (plan.upgrade_type) values.upgrade_type = plan.upgrade_type;
        if (plan.version) values.version = plan.version;
        if (plan.owner) values.owner = plan.owner;
        if (plan.status) values.status = plan.status;
        form.setFieldsValue(values);
        const stepCount = (plan.steps || []).length;
        message.info(`已应用方案「${plan.name}」基本信息${stepCount ? `，保存后将自动生成 ${stepCount} 个步骤` : ''}`);
      });
    }
  }

  // 更新步骤状态
  function handleStepAction(step, action) {
    http.put(`/api/upgrade/record-steps/${step.id}/update/`, { action })
      .then(() => {
        const actionText = action === 'complete' ? '完成' : action === 'skip' ? '跳过' : '重置';
        message.success(`步骤已标记为${actionText}`);
        fetchRecordSteps();
        store.fetchRecords();
      });
  }

  // 删除步骤
  function handleDeleteStep(step) {
    http.delete(`/api/upgrade/record-steps/${step.id}/delete/`)
      .then(() => {
        message.success('步骤已删除');
        fetchRecordSteps();
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

  // 打印步骤清单（A4 竖向，执行作业单格式）
  // phase 为空：打印全量（按阶段分段）；phase 指定值：只打印该阶段
  function handlePrintSteps(phase) {
    const win = window.open('', '_blank', 'width=900,height=700');
    if (!win) {
      message.warning('请允许浏览器弹窗以打印步骤清单');
      return;
    }

    const escapeHtml = (s) => String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');

    // 阶段定义 + 步骤分组
    const phases = store.filterOptions.phases || [];
    const phaseLabel = {};
    phases.forEach(p => { phaseLabel[p.value] = p.label; });

    // 按 phase 过滤 + 分组
    let printSteps;
    if (phase) {
      printSteps = recordSteps.filter(s => s.phase === phase);
    } else {
      printSteps = recordSteps;
    }

    // 按阶段分组（有 phase 的按定义顺序，无 phase 的归"未分组"）
    const phaseOrder = phases.map(p => p.value);
    const grouped = {};
    const ungrouped = [];
    printSteps.forEach(s => {
      if (s.phase && phaseOrder.includes(s.phase)) {
        if (!grouped[s.phase]) grouped[s.phase] = [];
        grouped[s.phase].push(s);
      } else {
        ungrouped.push(s);
      }
    });

    // 生成每个阶段的表格段
    const buildSection = (title, steps) => {
      const rows = steps.map((s, i) => {
        const desc = s.description || s.remark || '';
        return `
        <tr>
          <td style="text-align:center">${s.sequence || i + 1}</td>
          <td>
            <div class="step-title">${escapeHtml(s.title)}</div>
            ${desc ? `<div class="step-desc">${escapeHtml(desc)}</div>` : ''}
          </td>
          <td style="text-align:center">${s.is_required ? '是' : ''}</td>
          <td style="text-align:center">${'\u25A1'}</td>
          <td></td>
          <td></td>
          <td></td>
        </tr>`;
      }).join('');
      return `
      <div class="phase-section">
        <div class="phase-header">【${escapeHtml(title)}】 <span class="phase-check">阶段完成：${'\u25A1'}</span></div>
        <table>
          <thead><tr>
            <th style="width:40px">序号</th>
            <th>步骤说明</th>
            <th style="width:50px">必选</th>
            <th style="width:70px">执行情况</th>
            <th style="width:90px">执行人</th>
            <th style="width:130px">执行时间</th>
            <th style="width:120px">备注</th>
          </tr></thead>
          <tbody>${rows || '<tr><td colspan="7" style="text-align:center">暂无步骤</td></tr>'}</tbody>
        </table>
      </div>`;
    };

    let sectionsHtml = '';
    if (phase) {
      // 单阶段打印
      sectionsHtml = buildSection(phaseLabel[phase] || phase, grouped[phase] || []);
    } else {
      // 全量打印：按阶段分段
      phaseOrder.forEach(ph => {
        if (grouped[ph] && grouped[ph].length > 0) {
          sectionsHtml += buildSection(phaseLabel[ph], grouped[ph]);
        }
      });
      if (ungrouped.length > 0) {
        sectionsHtml += buildSection('未分组', ungrouped);
      }
    }

    win.document.write(`<!DOCTYPE html><html><head><meta charset="utf-8">
<title>升级步骤执行清单 - ${escapeHtml(info.upgrade_no)}</title>
<style>
  @page { size: A4 portrait; margin: 15mm; }
  body { font-family: -apple-system, "Microsoft YaHei", "PingFang SC", sans-serif; font-size: 12px; color: #000; margin: 0; }
  h1 { font-size: 18px; text-align: center; margin: 0 0 8px; }
  .meta { margin: 8px 0 12px; border-bottom: 2px solid #000; padding-bottom: 8px; }
  .meta div { display: inline-block; margin-right: 28px; line-height: 1.9; }
  .meta b { font-weight: bold; }
  table { width: 100%; border-collapse: collapse; margin-top: 4px; }
  th, td { border: 1px solid #000; padding: 8px; text-align: left; vertical-align: top; }
  th { background: #f0f0f0; font-weight: bold; text-align: center; font-size: 12px; }
  td { line-height: 28px; }
  .step-title { font-weight: bold; }
  .step-desc { font-size: 11px; color: #444; margin-top: 4px; line-height: 1.5; }
  .phase-section { margin-bottom: 16px; page-break-inside: avoid; }
  .phase-header { font-weight: bold; font-size: 13px; padding: 6px 8px; background: #f0f0f0; border: 1px solid #000; border-bottom: none; display: flex; justify-content: space-between; }
  .phase-check { font-weight: normal; font-size: 11px; }
  .sign { margin-top: 24px; font-size: 12px; }
  .sign div { display: inline-block; margin-right: 60px; }
  .footer { margin-top: 16px; font-size: 11px; color: #666; text-align: right; border-top: 1px dashed #999; padding-top: 6px; }
  .no-print { text-align: center; margin-top: 20px; }
  .no-print button { padding: 6px 18px; margin: 0 6px; font-size: 13px; cursor: pointer; }
  @media print { .no-print { display: none; } }
</style></head><body>
  <h1>升级步骤执行清单</h1>
  <div class="meta">
    <div><b>升级单号：</b>${escapeHtml(info.upgrade_no)}</div>
    <div><b>系统：</b>${escapeHtml(info.system)}</div>
    <div><b>版本：</b>${escapeHtml(info.version)}</div>
    <div><b>升级类型：</b>${escapeHtml(info.upgrade_type)}</div>
    <div><b>升级时间：</b>${escapeHtml(info.upgrade_time)}</div>
    <div><b>负责人：</b>${escapeHtml(info.owner)}</div>
    <div><b>状态：</b>${escapeHtml(info.status)}</div>
  </div>
  ${sectionsHtml || '<div style="text-align:center;padding:20px;">暂无步骤</div>'}
  <div class="sign">
    <div>执行人签字：________________</div>
    <div>审核人签字：________________</div>
  </div>
  <div class="footer">打印时间：${new Date().toLocaleString()}</div>
  <div class="no-print">
    <button onclick="window.print()">打印</button>
    <button onclick="window.close()">关闭</button>
  </div>
</body></html>`);
    win.document.close();
    win.focus();
    setTimeout(() => { try { win.print(); } catch (e) {} }, 300);
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

    const isCreate = !store.record.id;
    const url = isCreate
      ? '/api/upgrade/records/create/'
      : `/api/upgrade/records/${store.record.id}/update/`;
    const httpMethod = isCreate ? 'post' : 'put';

    http[httpMethod](url, formData)
      .then((res) => {
        if (isCreate && selectedPlan && res && res.id) {
          return store.applyPlan(selectedPlan.id, res.id)
            .then((applyRes) => {
              message.success(`操作成功，已应用方案「${selectedPlan.name}」${applyRes.created_count} 个步骤`);
            })
            .catch(() => {
              message.warning('操作成功，方案步骤应用失败，可稍后在详情中手动应用');
            });
        }
        message.success('操作成功');
      })
      .then(() => {
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

  // ============ 单页工作台子渲染（查看/编辑合并，按权限自动决定可操作性）============
  // 顶部信息条：基本信息展示 + 可编辑表单（有权限）+ 快捷操作
  function renderHeader(canEdit) {
    return (
      <div style={{ background: '#fafafa', padding: '12px 16px', borderRadius: 4, marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '4px 24px' }}>
          <span><strong>单号：</strong>{info.upgrade_no}</span>
          <span><strong>系统：</strong>{info.system}</span>
          <span><strong>版本：</strong>{info.version}</span>
          <span><strong>类型：</strong>{info.upgrade_type}</span>
          <span><strong>时间：</strong>{info.upgrade_time}</span>
          <span><strong>负责人：</strong>{info.owner}</span>
          <span><strong>状态：</strong><Tag color={STATUS_TAG_COLOR[info.status] || 'default'}>{info.status}</Tag></span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
            <Dropdown overlay={(
              <Menu>
                <Menu.Item key="all" onClick={() => handlePrintSteps()} disabled={recordSteps.length === 0}>打印全部阶段</Menu.Item>
                <Menu.Divider />
                {(store.filterOptions.phases || []).map(p => (
                  <Menu.Item key={p.value} onClick={() => handlePrintSteps(p.value)}>
                    只打印【{p.label}】
                  </Menu.Item>
                ))}
              </Menu>
            )}>
              <Button size="small" icon={<PrinterOutlined />} disabled={recordSteps.length === 0}>
                打印步骤 <DownOutlined />
              </Button>
            </Dropdown>
            {canEdit && (
              <Button size="small" type="primary" icon={<HistoryOutlined />} onClick={() => setStatusLogVisible(true)}>记录状态</Button>
            )}
          </span>
        </div>
        {canEdit && (
          <Collapse ghost style={{ marginTop: 4 }}>
            <Panel header="编辑基本信息" key="edit-basic">
              <Form form={form} layout="inline" initialValues={{
                ...info,
                upgrade_time: info.upgrade_time ? moment(info.upgrade_time) : null,
              }}>
                <Form.Item name="system" label="系统" rules={[{required: true}]}>
                  <Select showSearch allowClear style={{ width: 140 }} placeholder="系统">
                    {store.filterOptions.systems.map(item => (
                      <Option value={item} key={item}>{item}</Option>
                    ))}
                  </Select>
                </Form.Item>
                <Form.Item name="upgrade_type" label="类型" rules={[{required: true}]}>
                  <Select style={{ width: 110 }} placeholder="类型">
                    <Option value="功能升级">功能升级</Option>
                    <Option value="Bug修复">Bug修复</Option>
                    <Option value="安全补丁">安全补丁</Option>
                    <Option value="性能优化">性能优化</Option>
                  </Select>
                </Form.Item>
                <Form.Item name="version" label="版本" rules={[{required: true}]}>
                  <Input style={{ width: 120 }} placeholder="版本"/>
                </Form.Item>
                <Form.Item name="upgrade_time" label="时间" rules={[{required: true}]}>
                  <DatePicker showTime style={{ width: 180 }} placeholder="时间"/>
                </Form.Item>
                <Form.Item name="status" label="状态" rules={[{required: true}]}>
                  <Select style={{ width: 100 }} placeholder="状态">
                    <Option value="处理中">处理中</Option>
                    <Option value="已完成">已完成</Option>
                    <Option value="已回退">已回退</Option>
                  </Select>
                </Form.Item>
                <Form.Item name="owner" label="负责人" rules={[{required: true}]}>
                  <Input style={{ width: 100 }} placeholder="负责人"/>
                </Form.Item>
              </Form>
            </Panel>
          </Collapse>
        )}
      </div>
    );
  }

  // 单个步骤行渲染
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
          flex: 1,
          textDecoration: step.status === 'completed' ? 'line-through' : 'none',
          color: step.status !== 'pending' ? '#999' : '#333',
          fontSize: 13
        }}>
          {step.title}
        </span>
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
              <>
                <Button size="small" type="link" icon={<CheckCircleOutlined />} onClick={() => handleStepAction(step, 'complete')}>完成</Button>
                <Button size="small" type="link" onClick={() => handleStepAction(step, 'skip')}>跳过</Button>
              </>
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

  // 左栏：步骤清单（按阶段分组）
  function renderStepsPanel(canEdit) {
    // 按阶段分组步骤：有 phase 的按 PHASE_ORDER 分组，无 phase 的归入"未分组"
    const phases = store.filterOptions.phases || [];
    const phaseOrder = phases.map(p => p.value);
    const phaseLabel = {};
    phases.forEach(p => { phaseLabel[p.value] = p.label; });

    const grouped = {};
    const ungrouped = [];
    recordSteps.forEach(step => {
      if (step.phase && phaseOrder.includes(step.phase)) {
        if (!grouped[step.phase]) grouped[step.phase] = [];
        grouped[step.phase].push(step);
      } else {
        ungrouped.push(step);
      }
    });

    return (
      <Col span={15}>
        <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontWeight: 'bold' }}>
            步骤清单 {stepStats.total > 0 && <span style={{ color: '#999', fontSize: 12 }}>（{stepStats.completed}/{stepStats.total}）</span>}
          </span>
          {canEdit && (
            <Space size={4}>
              {store.plans.length > 0 && (
                <Select
                  size="small"
                  style={{ width: 200 }}
                  placeholder="应用方案"
                  allowClear
                  onChange={(v) => v && handleApplyPlan(v, true)}
                >
                  {store.plans.map(p => (
                    <Option key={p.id} value={p.id}>
                      {p.is_default ? '⭐ ' : ''}{p.name} ({p.step_count}步)
                    </Option>
                  ))}
                </Select>
              )}
              <Button size="small" icon={<PlusOutlined />} onClick={() => setAddStepVisible(true)}>添加步骤</Button>
              {recordSteps.length > 0 && hasPermission('upgrade.upgrade.step_del') && (
                <Popconfirm title="确定清空所有步骤？" onConfirm={handleClearSteps}>
                  <Button size="small" danger>清空</Button>
                </Popconfirm>
              )}
            </Space>
          )}
        </div>

        {stepStats.total > 0 && (
          <Progress percent={stepStats.progress} size="small" style={{ marginBottom: 8 }}
            status={stepStats.progress === 100 ? 'success' : 'active'}
            format={() => `${stepStats.completed}/${stepStats.total}`} />
        )}

        <div style={{ maxHeight: 400, overflowY: 'auto', border: '1px solid #f0f0f0', borderRadius: 4 }}>
          {phaseOrder.map(phase => {
            const steps = grouped[phase];
            if (!steps || steps.length === 0) return null;
            const doneCount = steps.filter(s => s.status === 'completed').length;
            return (
              <div key={phase}>
                <div style={{
                  background: '#fafafa', padding: '4px 12px', fontSize: 12,
                  fontWeight: 'bold', color: '#555', borderBottom: '1px solid #f0f0f0',
                  display: 'flex', justifyContent: 'space-between'
                }}>
                  <span>【{phaseLabel[phase]}】</span>
                  <span style={{ color: '#999' }}>{doneCount}/{steps.length}</span>
                </div>
                {steps.map(step => renderStepRow(step, canEdit))}
              </div>
            );
          })}
          {ungrouped.length > 0 && (
            <div>
              <div style={{
                background: '#fafafa', padding: '4px 12px', fontSize: 12,
                fontWeight: 'bold', color: '#555', borderBottom: '1px solid #f0f0f0'
              }}>
                【未分组】
              </div>
              {ungrouped.map(step => renderStepRow(step, canEdit))}
            </div>
          )}
          {recordSteps.length === 0 && (
            <div style={{ textAlign: 'center', color: '#999', padding: 32, fontSize: 13 }}>
              暂无步骤{canEdit ? '，可通过上方应用方案或手动添加' : ''}
            </div>
          )}
        </div>
      </Col>
    );
  }

  // 右栏：状态时间线 + 标准流程参考条
  function renderTimelinePanel(canEdit) {
    return (
      <Col span={9}>
        <div style={{ marginBottom: 8, fontWeight: 'bold' }}>
          状态时间线 <span style={{ color: '#999', fontSize: 12 }}>（{statusLogs.length}）</span>
        </div>

        {/* 标准升级流程参考条 */}
        <div style={{ background: '#f6f8fa', border: '1px solid #e8e8e8', borderRadius: 4, padding: '8px 10px', marginBottom: 8 }}>
          <div style={{ fontSize: 11, color: '#999', marginBottom: 6 }}>标准升级流程参考</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {STANDARD_FLOW.map((node, idx) => {
              const done = statusLogs.some(l => l.action === node.action);
              const firstUndoneIdx = STANDARD_FLOW.findIndex(n => !statusLogs.some(l => l.action === n.action));
              const isCurrent = idx === firstUndoneIdx;
              return (
                <span key={node.action} style={{
                  fontSize: 11,
                  padding: '2px 8px',
                  borderRadius: 10,
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4,
                  background: done ? '#f6ffed' : isCurrent ? '#e6f7ff' : '#fafafa',
                  color: done ? '#52c41a' : isCurrent ? '#1890ff' : '#bbb',
                  border: `1px solid ${done ? '#b7eb8f' : isCurrent ? '#91d5ff' : '#e8e8e8'}`,
                  fontWeight: isCurrent ? 'bold' : 'normal',
                }}>
                  {done ? '✓' : isCurrent ? '▶' : (idx + 1)}.
                  {node.label}
                </span>
              );
            })}
          </div>
        </div>

        <div style={{ maxHeight: 360, overflowY: 'auto', border: '1px solid #f0f0f0', borderRadius: 4, padding: 12 }}>
          {statusLogs.length > 0 ? (
            <Timeline>
              {statusLogs.map(log => (
                <Timeline.Item key={log.id} color={_getActionColor(log.action)}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div style={{ flex: 1 }}>
                      <div>
                        <Tag color={_getActionColor(log.action)} style={{ marginRight: 4 }}>{log.action_text}</Tag>
                        {log.to_status && log.to_status !== log.from_status && (
                          <span style={{ color: '#999', fontSize: 11 }}>{log.from_status}→{log.to_status}</span>
                        )}
                      </div>
                      <div style={{ color: '#999', fontSize: 11, marginTop: 2 }}>
                        {log.operator_name} · {log.created_at}
                      </div>
                      {log.remark && (
                        <div style={{ color: '#555', marginTop: 4, fontSize: 12 }}>{log.remark}</div>
                      )}
                    </div>
                    {canEdit && (
                      <Popconfirm title="确定删除此日志？" onConfirm={() => handleDeleteStatusLog(log.id)}>
                        <Button type="link" size="small" danger icon={<DeleteOutlined />} style={{ padding: 0 }} />
                      </Popconfirm>
                    )}
                  </div>
                </Timeline.Item>
              ))}
            </Timeline>
          ) : (
            <Empty description="暂无状态记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          )}
        </div>
      </Col>
    );
  }

  function renderWorkbench() {
    const canEdit = hasPermission('upgrade.upgrade.edit');
    return (
      <div>
        {renderHeader(canEdit)}
        <Row gutter={16}>
          {renderStepsPanel(canEdit)}
          {renderTimelinePanel(canEdit)}
        </Row>
        {/* 底部：附件（折叠） */}
        <Divider style={{ margin: '16px 0 12px' }} />
        <Collapse defaultActiveKey={attachmentCount > 0 ? ['att'] : []}>
          <Panel
            header={<span><PaperClipOutlined /> 附件 ({attachmentCount})</span>}
            key="att"
          >
            <AttachmentManager
              module="upgrade"
              recordId={info.id}
              listUrl={`/api/upgrade/records/${info.id}/attachments/`}
              uploadUrl={`/api/upgrade/records/${info.id}/attachments/`}
              deleteUrl="/api/upgrade/attachments/"
              downloadUrlPrefix="/api/upgrade/attachments/"
              readOnly={!canEdit}
              uploadPerm="upgrade.upgrade.edit"
              deletePerm="upgrade.upgrade.edit"
              maxFileSize={500}
              onCountChange={setAttachmentCount}
            />
          </Panel>
        </Collapse>
      </div>
    );
  }

  // ============ 已存在记录：单页工作台（查看/编辑合并，按权限自动决定可操作性）============
  if (store.record.id) {
    const canEdit = hasPermission('upgrade.upgrade.edit');
    return (
      <Modal
        visible
        width={1100}
        title="升级表单工作台"
        footer={canEdit ? undefined : [
          <Button key="close" onClick={() => store.formVisible = false}>关闭</Button>
        ]}
        onCancel={() => store.formVisible = false}
        {...(canEdit ? { confirmLoading: loading, onOk: handleSubmit, okText: '保存' } : {})}
      >
        {renderWorkbench()}
        {/* 记录状态弹窗 */}
        <Modal
          title="记录状态"
          visible={statusLogVisible}
          onCancel={() => { setStatusLogVisible(false); statusLogForm.resetFields(); }}
          onOk={() => statusLogForm.validateFields().then(handleAddStatusLog)}
          width={500}
        >
          <Form form={statusLogForm} labelCol={{ span: 5 }} wrapperCol={{ span: 17 }}>
            <Form.Item name="action" label="动作类型" rules={[{ required: true, message: '请选择动作类型' }]}>
              <Select placeholder="请选择动作类型">
                {actionOptions.map(opt => (
                  <Option key={opt.value} value={opt.value}>
                    <Tag color={opt.color} style={{ marginRight: 4 }}>{opt.label}</Tag>
                  </Option>
                ))}
              </Select>
            </Form.Item>
            <Form.Item name="remark" label="备注">
              <TextArea rows={3} placeholder="说明本次状态变更的情况（选填）" />
            </Form.Item>
          </Form>
        </Modal>
        {/* 手动添加步骤弹窗 */}
        <Modal
          title="添加步骤"
          visible={addStepVisible}
          onCancel={() => { setAddStepVisible(false); addStepForm.resetFields(); }}
          onOk={() => addStepForm.validateFields().then(handleAddStep)}
          width={500}
        >
          <Form form={addStepForm} labelCol={{ span: 5 }} wrapperCol={{ span: 17 }}>
            <Form.Item name="phase" label="所属阶段">
              <Select allowClear placeholder="选择步骤所属阶段（选填）">
                {store.filterOptions.phases.map(p => (
                  <Option key={p.value} value={p.value}>{p.label}</Option>
                ))}
              </Select>
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
      </Modal>
    );
  }

  // ============ 新建模式：保持简单表单 ============
  const initialValues = {...info};
  if (initialValues.upgrade_time) {
    initialValues.upgrade_time = moment(initialValues.upgrade_time);
  }
  if (upgradeNo) {
    initialValues.upgrade_no = upgradeNo;
  }

  return (
    <Modal
      visible
      width={700}
      maskClosable={false}
      title="新建升级表单"
      onCancel={() => store.formVisible = false}
      confirmLoading={loading}
      onOk={handleSubmit}>
      <Form form={form} initialValues={initialValues} labelCol={{span: 5}} wrapperCol={{span: 14}}>
        <Form.Item name="upgrade_no" label="升级单号">
          <Input
            placeholder="自动生成"
            disabled
            addonAfter={upgradeNo ? (
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

        {store.plans.length > 0 && (
          <Form.Item label="使用方案">
            <Select
              allowClear
              placeholder="选择方案快速填充并预设步骤（可选）"
              value={selectedPlan?.id}
              onChange={(v) => v ? handleApplyPlan(v, false) : setSelectedPlan(null)}
              onClear={() => setSelectedPlan(null)}
              style={{ width: '100%' }}
            >
              {store.plans.map(p => (
                <Option key={p.id} value={p.id}>
                  {p.is_default ? `⭐ ${p.name}` : p.name}
                  {p.step_count ? ` (${p.step_count}步)` : ''}
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
            <Option value="已回退">已回退</Option>
          </Select>
        </Form.Item>
        <Form.Item required name="owner" label="负责人" rules={[{required: true, message: '请输入负责人'}]}>
          <Input placeholder="请输入负责人"/>
        </Form.Item>
      </Form>
    </Modal>
  );
})
