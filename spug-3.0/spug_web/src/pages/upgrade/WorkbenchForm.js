/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 升级工作台表单（新建 + 查看/编辑）。
 *
 * 组件拆分（代码质量门禁：单函数 ≤120 行）：
 * - CreateFormCards：新建模式的表单卡片（只负责建单）；
 * - WorkbenchHeaderBar：头部信息栏 + 编辑基本信息折叠面板 + 打印入口；
 * - WorkbenchStepsPanel：步骤清单面板 + 添加步骤弹窗 + 应用方案替换确认；
 * - WorkbenchTimelinePanel：流程节点 + 状态时间线；
 * - 动作函数在 workbenchActions.js，存档打印在 archivePrint.js。
 * 子组件直接读 store（模块级单例），必须逐个包 observer 保持响应式。
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
import { hasPermission } from 'libs';
import moment from 'moment';
import store from './store';
import {
  getActionColor, computeStepFlowState, renderFlowNode, STATUS_TAG_COLOR, StepStatusTag,
  groupStepsByPhase,
} from './shared';
import SystemSelect from './components/SystemSelect';
import { printUpgradeArchive, printUpgradeSteps } from './archivePrint';
import {
  submitUpgradeForm, postStepAction, deleteStep, addStep, clearSteps,
  applyPlanToRecord, postNodeAction, deleteStatusLog,
} from './workbenchActions';

const { Option } = Select;
const { TextArea } = Input;
const { Panel } = Collapse;

const UPGRADE_TYPE_OPTIONS = ['功能升级', 'Bug修复', '安全补丁', '性能优化'];
const STATUS_OPTIONS = ['处理中', '已完成', '已回退'];

/** 渲染单个步骤行（纯函数，动作经 workbenchActions 发出） */
function renderStepRow(recordId, step, canEdit) {
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
            <Button size="small" type="link" icon={<CheckCircleOutlined />}
              onClick={() => postStepAction(recordId, step, 'complete')}>完成</Button>
          )}
          {step.status === 'pending' && (
            <Button size="small" type="link" onClick={() => postStepAction(recordId, step, 'skip')}>跳过</Button>
          )}
          {step.status !== 'pending' && hasPermission('upgrade.upgrade.step_reset') && (
            <Button size="small" type="link" onClick={() => postStepAction(recordId, step, 'reset')}>重置</Button>
          )}
          {hasPermission('upgrade.upgrade.step_del') && (
            <Button size="small" type="link" danger onClick={() => deleteStep(recordId, step)}>删除</Button>
          )}
        </Space>
      )}
    </div>
  );
}

/** 新建模式表单卡片（只负责建单，不承载升级执行过程） */
const CreateFormCards = observer(function CreateFormCards({selectedPlan, setSelectedPlan, onApplyPlanPrefill}) {
  return (
    <>
      {/* 基本信息 */}
      <Card size="small" title="基本信息" style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          <Col span={24}>
            <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
              <Input placeholder="根据系统/类型/计划日期自动生成，可手动修改" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="system" label="升级系统" rules={[{ required: true, message: '请选择升级系统' }]}>
              <SystemSelect />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="upgrade_type" label="升级类型" rules={[{ required: true, message: '请选择升级类型' }]}>
              <Select placeholder="请选择升级类型">
                {UPGRADE_TYPE_OPTIONS.map(t => <Option key={t} value={t}>{t}</Option>)}
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
            onChange={(v) => v ? onApplyPlanPrefill(v) : setSelectedPlan(null)}
            onClear={() => setSelectedPlan(null)}>
            {store.plans.map(p => (
              <Option key={p.id} value={p.id}>
                {p.name}{p.step_count ? ` (${p.step_count}步)` : ''}
              </Option>
            ))}
          </Select>
        </Form.Item>
      </Card>
    </>
  );
});

/** 头部信息栏 + 编辑基本信息折叠面板 + 打印入口（编辑表单不接标题自动生成，保持原有行为） */
const WorkbenchHeaderBar = observer(function WorkbenchHeaderBar({canEdit, form, onPrintBasicInfo, onPrintSteps}) {
  const info = store.record;
  return (
    <div style={{ background: '#fafafa', padding: '12px 16px', borderRadius: 4, marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '4px 24px' }}>
        <span><strong>编号：</strong>{info.upgrade_no || '-'}</span>
        <span><strong>标题：</strong>{info.title || '-'}</span>
        <span><strong>系统：</strong>{info.system_name || '-'}</span>
        <span><strong>类型：</strong>{info.upgrade_type}</span>
        <span><strong>时间：</strong>{info.upgrade_time}</span>
        <span><strong>负责人：</strong>{info.owner}</span>
        <span><strong>状态：</strong><Tag color={STATUS_TAG_COLOR[info.status] || 'default'}>{info.status}</Tag></span>
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <Button size="small" icon={<PrinterOutlined />} onClick={onPrintBasicInfo}>打印基本信息</Button>
          <Dropdown overlay={(
            <Menu>
              <Menu.Item key="all" onClick={() => onPrintSteps()} disabled={store.recordSteps.length === 0}>打印全部阶段</Menu.Item>
              <Menu.Divider />
              {(store.filterOptions.phases || []).map(p => (
                <Menu.Item key={p} onClick={() => onPrintSteps(p)}>只打印【{p}】</Menu.Item>
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
                      {UPGRADE_TYPE_OPTIONS.map(t => <Option key={t} value={t}>{t}</Option>)}
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
                      {STATUS_OPTIONS.map(s => <Option key={s} value={s}>{s}</Option>)}
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
});

/** 步骤清单面板：应用方案/添加步骤/逐项操作 + 添加步骤弹窗 */
const WorkbenchStepsPanel = observer(function WorkbenchStepsPanel({recordId, canEdit}) {
  const [addStepVisible, setAddStepVisible] = useState(false);
  const [addStepForm] = Form.useForm();
  // 编辑模式下方案下拉框受控值（操作后重置）
  const [planSelectValue, setPlanSelectValue] = useState(undefined);

  const phases = store.filterOptions.phases || [];
  const { groups, ungrouped } = groupStepsByPhase(store.recordSteps, phases);

  const stepStats = store.recordStepStats || {};
  const total = stepStats.total || store.recordSteps.length;
  // completed/skipped 均视为已处理（与后端完成度判定一致）
  const doneCount = (stepStats.completed || 0) + (stepStats.skipped || 0);
  const progress = total > 0 ? Math.round((doneCount / total) * 100) : 0;

  function handleAddStep(values) {
    addStep(recordId, values);
    setAddStepVisible(false);
    addStepForm.resetFields();
  }

  function handleApplyPlan(planId) {
    applyPlanToRecord(recordId, planId, () => setPlanSelectValue(undefined));
  }

  return (
    <Col span={15}>
      <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontWeight: 'bold' }}>
          步骤清单 <span style={{ color: '#999', fontSize: 12 }}>（{doneCount}/{total}）</span>
        </span>
        {canEdit && (
          <Space size={4}>
            {store.plans.length > 0 && (
              <Select
                size="small" style={{ width: 200 }} placeholder="应用方案" allowClear
                value={planSelectValue}
                onChange={(v) => v && handleApplyPlan(v)}
              >
                {store.plans.map(p => (
                  <Option key={p.id} value={p.id}>{p.name} ({p.step_count}步)</Option>
                ))}
              </Select>
            )}
            <Button size="small" icon={<PlusOutlined />} onClick={() => setAddStepVisible(true)}>添加步骤</Button>
            {store.recordSteps.length > 0 && hasPermission('upgrade.upgrade.step_del') && (
              <Popconfirm title="确定清空所有步骤？" onConfirm={() => clearSteps(recordId)}>
                <Button size="small" danger>清空</Button>
              </Popconfirm>
            )}
          </Space>
        )}
      </div>

      {total > 0 && (
        <Progress percent={progress} size="small" style={{ marginBottom: 8 }}
          status={progress === 100 ? 'success' : 'active'}
          format={() => `${doneCount}/${total}`} />
      )}

      <div style={{ maxHeight: 400, overflowY: 'auto', border: '1px solid #f0f0f0', borderRadius: 4 }}>
        {groups.map(g => {
          const groupDone = g.steps.filter(s => s.status === 'completed' || s.status === 'skipped').length;
          return (
            <div key={g.name}>
              <div style={{
                background: '#fafafa', padding: '4px 12px', fontSize: 12,
                fontWeight: 'bold', color: '#555', borderBottom: '1px solid #f0f0f0',
                display: 'flex', justifyContent: 'space-between'
              }}>
                <span>【{g.name}】</span>
                <span style={{ color: '#999' }}>{groupDone}/{g.steps.length}</span>
              </div>
              {g.steps.map(step => renderStepRow(recordId, step, canEdit))}
            </div>
          );
        })}
        {ungrouped.length > 0 && (
          <div>
            <div style={{ background: '#fafafa', padding: '4px 12px', fontSize: 12, fontWeight: 'bold', color: '#999', borderBottom: '1px solid #f0f0f0' }}>【未分组】</div>
            {ungrouped.map(step => renderStepRow(recordId, step, canEdit))}
          </div>
        )}
        {store.recordSteps.length === 0 && (
          <div style={{ textAlign: 'center', color: '#999', padding: 32, fontSize: 13 }}>
            暂无步骤{canEdit ? '，可通过上方应用方案或手动添加' : ''}
          </div>
        )}
      </div>

      <Modal title="添加步骤" visible={addStepVisible}
        onCancel={() => { setAddStepVisible(false); addStepForm.resetFields(); }}
        onOk={() => addStepForm.validateFields().then(handleAddStep)} width={500}>
        <Form form={addStepForm} labelCol={{ span: 5 }} wrapperCol={{ span: 17 }}>
          <Form.Item name="phase" label="所属阶段">
            <AutoComplete
              options={phases.map(p => ({ value: p }))}
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
    </Col>
  );
});

/** 状态时间线面板：流程节点（带交互）+ 状态日志时间线 */
const WorkbenchTimelinePanel = observer(function WorkbenchTimelinePanel({recordId, canEdit}) {
  const flowNodes = computeStepFlowState(store.recordSteps, store.filterOptions.phases, store.statusLogs).nodes;

  // 流程节点操作（暂停/继续/失败/回退；完成靠逐个打勾步骤）
  function renderFlowNodeWithAction(node, idx) {
    const el = renderFlowNode(node, idx);
    if (!canEdit) return <span key={node.action}>{el}</span>;
    if (node.state === 'current') {
      return (
        <Dropdown key={node.action} overlay={(
          <Menu onClick={({ key }) => postNodeAction(recordId, key, node)}>
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
        <Popconfirm key={node.action} title="继续该阶段？" onConfirm={() => postNodeAction(recordId, 'resume', node)}>
          <span style={{ cursor: 'pointer' }}>{el}</span>
        </Popconfirm>
      );
    }
    if (node.state === 'completed') {
      return (
        <Popconfirm key={node.action} title={`回退到【${node.label}】？该阶段及之后的步骤将重置为待执行`} onConfirm={() => postNodeAction(recordId, 'rollback', node)}>
          <span style={{ cursor: 'pointer' }}>{el}</span>
        </Popconfirm>
      );
    }
    if (node.state === 'failed') {
      return <Tooltip key={node.action} title="该阶段失败，请回退到之前的阶段重做">{el}</Tooltip>;
    }
    return <span key={node.action}>{el}</span>;
  }

  return (
    <Col span={9}>
      <div style={{ marginBottom: 8, fontWeight: 'bold' }}>
        状态时间线 <span style={{ color: '#999', fontSize: 12 }}>（{store.statusLogs.length}）</span>
      </div>

      <div style={{ background: '#f6f8fa', border: '1px solid #e8e8e8', borderRadius: 4, padding: '8px 10px', marginBottom: 8 }}>
        <div style={{ fontSize: 11, color: '#999', marginBottom: 6 }}>升级流程</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {flowNodes.length > 0
            ? flowNodes.map((node, idx) => renderFlowNodeWithAction(node, idx + 1))
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
                    <Popconfirm title="确定删除此日志？" onConfirm={() => deleteStatusLog(recordId, log.id)}>
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
});

const WorkbenchForm = forwardRef(function WorkbenchForm({ isNew, recordId, onSaveStart, onSaveEnd, onSaveSuccess, onSaveError }, ref) {
  const [form] = Form.useForm();
  const [selectedPlan, setSelectedPlan] = useState(null);

  // 标题是否已被用户手动编辑（一旦手动修改，不再自动覆盖）
  const [titleTouched, setTitleTouched] = useState(false);

  // 根据升级系统/类型/计划日期自动生成标题（system 为系统档案 ID，标题取系统名称）
  function recomputeTitle(allValues) {
    if (titleTouched) return;
    const parts = [];
    const sys = (store.systems || []).find(s => s.id === allValues.system);
    if (sys) parts.push(sys.name);
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
    submit: (redirectMode) => submitUpgradeForm({
      form, isNew, recordId, redirectMode, selectedPlan,
      onSaveStart, onSaveEnd, onSaveSuccess, onSaveError,
    })
  }));

  // 同步 form 数据到 store.record（system 表单值为系统档案 ID）
  useEffect(() => {
    if (!isNew && store.record.id) {
      form.setFieldsValue({
        ...store.record,
        system: store.record.system_id,
        upgrade_time: store.record.upgrade_time ? moment(store.record.upgrade_time) : null,
      });
    }
    // form 为 useForm 稳定实例；store.record 是 observable，
    // 依赖 store.record 是刻意的 mobx 刷新模式（与仓库其他页面一致）
  }, [store.record, isNew]);

  // 应用方案（新建模式）：预填基本信息，保存时自动应用步骤
  function handleApplyPlanPrefill(planId) {
    store.fetchPlanDetail(planId).then(plan => {
      if (!plan) { message.error('获取方案失败'); return; }
      setSelectedPlan(plan);
      const values = {};
      if (plan.system_id) values.system = plan.system_id;
      if (plan.upgrade_type) values.upgrade_type = plan.upgrade_type;
      form.setFieldsValue(values);
      // 方案预填后重新生成标题（若用户未手动编辑过标题）
      recomputeTitle(form.getFieldsValue());
      const stepCount = (plan.steps || []).length;
      message.info(`已应用方案「${plan.name}」基本信息${stepCount ? `，保存后将自动生成 ${stepCount} 个步骤` : ''}`);
    });
  }

  // ===== 新建模式表单 =====
  if (isNew) {
    const initialValues = { ...store.record };
    if (initialValues.upgrade_time) {
      initialValues.upgrade_time = moment(initialValues.upgrade_time);
    }
    return (
      <Form form={form} initialValues={initialValues} onValuesChange={onValuesChange} layout="vertical">
        <CreateFormCards
          selectedPlan={selectedPlan} setSelectedPlan={setSelectedPlan}
          onApplyPlanPrefill={handleApplyPlanPrefill}/>
      </Form>
    );
  }

  // ===== 查看/编辑模式工作台 =====
  const canEdit = hasPermission('upgrade.upgrade.edit');
  const info = store.record;

  return (
    <div>
      <WorkbenchHeaderBar
        canEdit={canEdit} form={form}
        onPrintBasicInfo={() => printUpgradeArchive(info)}
        onPrintSteps={(phase) => printUpgradeSteps({
          info, recordSteps: store.recordSteps,
          phases: store.filterOptions.phases || [], phase,
        })}/>
      <Row gutter={16}>
        <WorkbenchStepsPanel recordId={recordId} canEdit={canEdit}/>
        <WorkbenchTimelinePanel recordId={recordId} canEdit={canEdit}/>
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
    </div>
  );
});

export default observer(WorkbenchForm);
