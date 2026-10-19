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
 * - RecordInfoBar：顶部信息栏（两行层级 + 只读详细说明 + 编辑基本信息面板）；
 * - WorkbenchStepsPanel：步骤清单面板（完成主操作 + 更多菜单 + 定位待执行 + 阶段吸顶）；
 * - WorkbenchTimelinePanel：流程节点 + 阶段操作菜单 + 状态时间线（新日志高亮/不抢滚动）；
 * - 动作函数在 workbenchActions.js，存档打印在 archivePrint.js。
 * 子组件直接读 store（模块级单例），必须逐个包 observer 保持响应式。
 */
import React, { useState, useRef, useEffect, forwardRef, useImperativeHandle } from 'react';
import { observer } from 'mobx-react';
import {
  Form, Input, Select, AutoComplete, DatePicker, Button, message, Progress, Tag, Popconfirm,
  Switch, Tooltip, Space, Timeline, Empty, Row, Col, Collapse, Divider, Dropdown,
  Menu, Modal, Card
} from 'antd';
import {
  PlusOutlined, CheckCircleOutlined, MoreOutlined, AimOutlined,
  PaperClipOutlined,
} from '@ant-design/icons';
import { AttachmentManager } from 'components';
import { hasPermission } from 'libs';
import moment from 'moment';
import store from './store';
import { useSyncRecordToForm, useBasicInfoEditor } from './hooks';
import {
  computeStepFlowState, StepStatusTag,
  groupStepsByPhase, buildPhaseActionGroups,
  LOG_TONE, getLogTone, buildLogTitle, STEP_STATUS_TEXT,
  UPGRADE_TYPE_OPTIONS,
} from './shared';
import SystemSelect from './components/SystemSelect';
import RecordInfoBar from './components/WorkbenchInfoBar';
import {PhaseActionMenu, PhaseFlowArea, TimelineActionModals} from './components/TimelineModals';
import { printUpgradeArchive, printUpgradeSteps } from './archivePrint';
import {
  submitUpgradeForm, postStepAction, deleteStep, addStep, clearSteps,
  applyPlanToRecord,
} from './workbenchActions';
import styles from './Workbench.module.less';

const { Option } = Select;
const { TextArea } = Input;
const { Panel } = Collapse;

const STEP_DONE = s => s.status === 'completed' || s.status === 'skipped';

/** 步骤"更多"菜单项：按状态与权限生成（跳过/重置/删除，权限码与原有口径一致） */
function buildStepMoreItems(step) {
  const items = [];
  if (step.status === 'pending') items.push({key: 'skip', label: '跳过'});
  if (step.status !== 'pending' && hasPermission('upgrade.upgrade.step_reset')) {
    items.push({key: 'reset', label: '重置'});
  }
  if (hasPermission('upgrade.upgrade.step_del')) {
    items.push({key: 'del', label: '删除', danger: true});
  }
  return items;
}

/** 步骤动作分发：更多菜单 → 原有动作函数（权限与确认规则不变） */
function dispatchStepMoreAction(recordId, step, key) {
  if (key === 'skip') return postStepAction(recordId, step, 'skip');
  if (key === 'reset') return postStepAction(recordId, step, 'reset');
  if (key === 'del') return deleteStep(recordId, step);
  return undefined;
}

/**
 * 单个步骤行：待执行"完成"为行内主要操作，跳过/重置/删除收进"更多"菜单；
 * 说明点击展开/收起（长内容可读）；已完成/已跳过降低强调但保持可读。
 * 失败待处理（phaseBlocked）阶段：完成/跳过禁用并提示先走"处理失败"。
 */
function StepRow({recordId, step, canEdit, phaseBlocked, descExpanded, onToggleDesc}) {
  const done = step.status !== 'pending';
  const blockedTip = '该阶段有未处理完的失败，请先在"处理失败"中选择重做范围';
  // 失败待处理阶段：跳过收起（后端同样拒绝）；重置/删除仍可用（重置为重做范围的一部分）
  const moreItems = canEdit ? buildStepMoreItems(step)
    .filter(item => !(phaseBlocked && item.key === 'skip')) : [];
  return (
    <div className={done ? styles.stepRowDone : styles.stepRowTodo} data-step-id={step.id}>
      <div className={styles.stepMain}>
        <span className={styles.stepSeq}>{step.sequence}.</span>
        <StepStatusTag status={step.status} />
        <span className={done ? styles.stepTitleDone : styles.stepTitleTodo}>{step.title}</span>
        {step.is_required && <Tag color="blue" className={styles.miniTag}>必选</Tag>}
        {step.description && (
          <Button type="link" size="small" className={styles.descToggle}
            aria-expanded={!!descExpanded}
            onClick={() => onToggleDesc(step.id)}>
            {descExpanded ? '收起说明' : '说明'}
          </Button>
        )}
        <span className={styles.stepMeta}>
          {step.completed_by ? `${step.completed_by} ${step.completed_at}` : ''}
        </span>
        {canEdit && step.status === 'pending' && (
          <Tooltip title={phaseBlocked ? blockedTip : ''}>
            <Button size="small" type="link" icon={<CheckCircleOutlined />}
              className={styles.completeBtn} disabled={phaseBlocked}
              onClick={() => postStepAction(recordId, step, 'complete')}>完成</Button>
          </Tooltip>
        )}
        {moreItems.length > 0 && (
          <Dropdown trigger={['click']} overlay={(
            <Menu onClick={({key}) => dispatchStepMoreAction(recordId, step, key)}>
              {moreItems.map(item => (
                <Menu.Item key={item.key} danger={item.danger}>{item.label}</Menu.Item>
              ))}
            </Menu>
          )}>
            <Button size="small" type="text" className={styles.moreBtn}
              aria-label={`步骤${step.sequence}更多操作`} icon={<MoreOutlined />} />
          </Dropdown>
        )}
      </div>
      {descExpanded && step.description && (
        <div className={styles.stepDesc}>{step.description}</div>
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

/** 添加步骤弹窗：提交成功才由 onOk 链关闭，失败保留现场 */
function AddStepModal({visible, form, phases, onCancel, onOk}) {
  return (
    <Modal title="添加步骤" visible={visible}
      onCancel={onCancel}
      onOk={() => form.validateFields().then(onOk).catch(() => {})}
      width={500}>
      <Form form={form} labelCol={{ span: 5 }} wrapperCol={{ span: 17 }}>
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
  );
}

/** 步骤面板工具条：应用方案/添加步骤/清空（add 权限门控）+ 添加步骤弹窗 */
const StepsToolbar = observer(function StepsToolbar({recordId}) {
  const [addStepVisible, setAddStepVisible] = useState(false);
  const [addStepForm] = Form.useForm();
  // 编辑模式下方案下拉框受控值（操作后重置）
  const [planSelectValue, setPlanSelectValue] = useState(undefined);
  // 应用方案/添加步骤走后端 add 权限（与 RecordStepAddView/PlanApplyView 一致）
  const canAdd = hasPermission('upgrade.upgrade.add');
  const phases = store.filterOptions.phases || [];

  // 提交成功才关闭弹窗并清空输入；失败保留现场（错误提示由 http 拦截器弹出）。
  // 返回 promise 交给 onOk 链的 .catch 统一吸收，避免 unhandled rejection。
  function handleAddStep(values) {
    return addStep(recordId, values)
      .then(() => {
        setAddStepVisible(false);
        addStepForm.resetFields();
      });
  }

  function handleApplyPlan(planId) {
    applyPlanToRecord(recordId, planId, () => setPlanSelectValue(undefined));
  }

  return (
    <>
      <Space size={4} className={styles.panelHeaderActions}>
        {canAdd && store.plans.length > 0 && (
          <Select
            size="small" style={{width: 200}} placeholder="应用方案" allowClear
            value={planSelectValue}
            onChange={(v) => v && handleApplyPlan(v)}
          >
            {store.plans.map(p => (
              <Option key={p.id} value={p.id}>{p.name} ({p.step_count}步)</Option>
            ))}
          </Select>
        )}
        {canAdd && (
          <Button size="small" icon={<PlusOutlined />} onClick={() => setAddStepVisible(true)}>添加步骤</Button>
        )}
        {store.recordSteps.length > 0 && hasPermission('upgrade.upgrade.step_del') && (
          <Popconfirm title="确定清空所有步骤？" onConfirm={() => clearSteps(recordId)}>
            <Button size="small" danger>清空</Button>
          </Popconfirm>
        )}
      </Space>
      <AddStepModal
        visible={addStepVisible} form={addStepForm} phases={phases}
        onCancel={() => { setAddStepVisible(false); addStepForm.resetFields(); }}
        onOk={handleAddStep}/>
    </>
  );
});

/** 步骤清单面板：应用方案/添加步骤/逐项操作 + 定位待执行 + 阶段分组吸顶 */
const WorkbenchStepsPanel = observer(function WorkbenchStepsPanel({recordId, canEdit}) {
  // 说明展开状态（按步骤 id）
  const [descExpandedIds, setDescExpandedIds] = useState(() => new Set());
  const listRef = useRef(null);

  const canAdd = hasPermission('upgrade.upgrade.add');
  const phases = store.filterOptions.phases || [];
  const {groups, ungrouped} = groupStepsByPhase(store.recordSteps, phases);
  // 阶段状态复用 computeStepFlowState（结合失败单推断 failed/redoing）
  const phaseStateMap = computeStepFlowState(
    store.recordSteps, phases, store.statusLogs, store.failures).nodes
    .reduce((map, n) => { map[n.label] = n.state; return map; }, {});
  // 失败待处理（pending）阶段：步骤的普通完成/跳过被后端拒绝，前端同步禁用并提示
  const blockedPhases = new Set((store.failures || [])
    .filter(f => f.status === 'pending').map(f => f.phase));
  const hasPending = store.recordSteps.some(s => s.status === 'pending');

  const stepStats = store.recordStepStats || {};
  const total = stepStats.total || store.recordSteps.length;
  // completed/skipped 均视为已处理（与后端完成度判定一致）
  const doneCount = (stepStats.completed || 0) + (stepStats.skipped || 0);
  const progress = total > 0 ? Math.round((doneCount / total) * 100) : 0;

  function toggleDesc(stepId) {
    setDescExpandedIds(prev => {
      const next = new Set(prev);
      if (next.has(stepId)) next.delete(stepId); else next.add(stepId);
      return next;
    });
  }

  // 仅在左侧清单内滚动到第一个待执行步骤，不改变任何状态
  function locatePending() {
    const target = store.recordSteps.find(s => s.status === 'pending');
    const el = listRef.current && target
      ? listRef.current.querySelector(`[data-step-id="${target.id}"]`) : null;
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({block: 'nearest', behavior: 'smooth'});
    }
  }

  function renderGroupHeader(name, steps, isCurrent) {
    const groupDone = steps.filter(STEP_DONE).length;
    return (
      <div className={isCurrent
        ? `${styles.stepGroupHeader} ${styles.stepGroupHeaderCurrent}`
        : styles.stepGroupHeader}>
        <span>【{name}】</span>
        <span className={styles.stepGroupCount}>
          {isCurrent && <span className={styles.currentPhaseTag}>当前阶段</span>}
          {groupDone}/{steps.length}
        </span>
      </div>
    );
  }

  function renderStepOf(step) {
    return (
      <StepRow key={step.id} recordId={recordId} step={step} canEdit={canEdit}
        phaseBlocked={(step.phase || '') && blockedPhases.has(step.phase || '')}
        descExpanded={descExpandedIds.has(step.id)} onToggleDesc={toggleDesc}/>
    );
  }

  return (
    <div className={styles.panel}>
      <div className={styles.panelHeader}>
        <span className={styles.panelTitle}>
          步骤清单 <span className={styles.panelSub}>（{doneCount}/{total}）</span>
        </span>
        {hasPending && (
          <Button type="link" size="small" icon={<AimOutlined />}
            className={styles.locateBtn} onClick={locatePending}>定位待执行</Button>
        )}
        {canEdit && <StepsToolbar recordId={recordId}/>}
      </div>

      {total > 0 && (
        <Progress percent={progress} size="small" className={styles.stepProgress}
          status={progress === 100 ? 'success' : 'active'}
          format={() => `${doneCount}/${total}`} />
      )}

      <div className={styles.stepList} ref={listRef}>
        {groups.map(g => {
          const isCurrent = phaseStateMap[g.name] === 'current';
          return (
            <div key={g.name} className={isCurrent ? styles.stepGroupCurrent : undefined}>
              {renderGroupHeader(g.name, g.steps, isCurrent)}
              {g.steps.map(renderStepOf)}
            </div>
          );
        })}
        {ungrouped.length > 0 && (
          <div>
            {renderGroupHeader('未分组', ungrouped, false)}
            {ungrouped.map(renderStepOf)}
          </div>
        )}
        {store.recordSteps.length === 0 && (
          <div className={styles.stepEmpty}>
            暂无步骤{canAdd ? '，可通过上方应用方案或手动添加' : ''}
          </div>
        )}
      </div>
    </div>
  );
});

/** 事件明细（detail.steps 快照）：默认只显示数量摘要，可展开查看受影响步骤 */
function LogEventDetail({detail}) {
  const [expanded, setExpanded] = useState(false);
  if (!detail || !Array.isArray(detail.steps) || detail.steps.length === 0) return null;
  const summary = [];
  if (typeof detail.selected_count === 'number') summary.push(`选择 ${detail.selected_count} 个步骤`);
  if (typeof detail.reset_count === 'number') summary.push(`实际重置 ${detail.reset_count} 个`);
  if (detail.later_action === 'keep') summary.push('后续结果已确认保留');
  if (detail.later_action === 'redo') summary.push('后续阶段一并重新执行');
  if (Array.isArray(detail.failures_resolved) && detail.failures_resolved.length > 0) {
    summary.push(`解除失败阻塞 ${detail.failures_resolved.length} 项`);
  }
  return (
    <div className={styles.logDetail}>
      {summary.length > 0 && (
        <div className={styles.logDetailSummary}>{summary.join(' · ')}</div>
      )}
      {detail.later_reason && (
        <div className={styles.logDetailNote}>保留理由：{detail.later_reason}</div>
      )}
      {detail.note && (
        <div className={styles.logDetailNote}>说明：{detail.note}</div>
      )}
      <Button type="link" size="small" className={styles.logDetailToggle}
        onClick={() => setExpanded(v => !v)}>
        {expanded ? '收起明细' : `展开明细（${detail.steps.length}）`}
      </Button>
      {expanded && (
        <div className={styles.logDetailSteps}>
          {detail.steps.map(s => (
            <div key={s.id} className={styles.logDetailStep}>
              {s.phase ? `【${s.phase}】` : ''}{s.title}：
              {STEP_STATUS_TEXT[s.from_status] || s.from_status}
              →{STEP_STATUS_TEXT[s.to_status] || s.to_status}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** 单条状态日志：第一行事件标题，第二行操作人/时间，状态变化、明细与备注为辅助内容（撤销/失效整体弱化） */
function LogTimelineItem({log, highlightId}) {
  const tone = LOG_TONE[getLogTone(log)];
  const dimmed = tone === LOG_TONE.muted;
  return (
    <Timeline.Item color={tone.dot}>
      <div className={styles.logRow} style={dimmed ? {opacity: 0.55} : undefined}>
        <div className={highlightId === log.id
          ? `${styles.logItem} ${styles.logItemHighlight}` : styles.logItem}>
          <div className={`${styles.logTitle}${tone.title ? ` ${styles[tone.title]}` : ''}`}>
            {buildLogTitle(log)}
          </div>
          <div className={styles.logMeta}>{log.operator_name} · {log.created_at}</div>
          {log.to_status && log.to_status !== log.from_status && (
            <div className={styles.logStatusText}>{log.from_status}→{log.to_status}</div>
          )}
          <LogEventDetail detail={log.detail} />
          {log.remark && <div className={styles.logRemark}>{log.remark}</div>}
        </div>
      </div>
    </Timeline.Item>
  );
}

/**
 * 状态时间线面板：流程节点（带快捷交互）+ 阶段操作菜单 + 状态日志时间线。
 * - 日志条目两行主结构：第一行事件标题（如"备份阶段完成""回退至「备份」"），
 *   第二行操作人/时间；状态变化与备注为下方辅助内容；
 * - 新日志到达时短暂高亮；用户已滚离顶部时不抢滚动，改用"有新记录"按钮定位。
 */
const WorkbenchTimelinePanel = observer(function WorkbenchTimelinePanel({recordId, canEdit}) {
  const flowNodes = computeStepFlowState(
    store.recordSteps, store.filterOptions.phases, store.statusLogs, store.failures).nodes;
  const actionGroups = buildPhaseActionGroups(flowNodes, store.failures);
  const listRef = useRef(null);
  const prevLogIdsRef = useRef(null);
  const [highlightId, setHighlightId] = useState(null);
  const [hasNewBelow, setHasNewBelow] = useState(false);
  const highlightTimerRef = useRef(null);
  // 失败处理/重新执行弹窗（phase 为空表示关闭）
  const [createFailurePhase, setCreateFailurePhase] = useState(null);
  const [handleFailure, setHandleFailure] = useState(null);   // 失败单对象
  const [redoPhase, setRedoPhase] = useState(null);

  // 新日志检测：仅当顶部出现旧列表中不存在的日志（真实新增，删除/重取不触发）
  // 时短暂高亮；用户滚离顶部则不打断阅读，显示"有新记录"按钮
  useEffect(() => {
    const prev = prevLogIdsRef.current;
    prevLogIdsRef.current = new Set(store.statusLogs.map(l => l.id));
    const top = store.statusLogs[0];
    if (!prev || !top || prev.has(top.id)) return;
    setHighlightId(top.id);
    if (highlightTimerRef.current) clearTimeout(highlightTimerRef.current);
    highlightTimerRef.current = setTimeout(() => setHighlightId(null), 2200);
    const el = listRef.current;
    if (el) {
      if (el.scrollTop > 8) setHasNewBelow(true);
      else el.scrollTop = 0;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store.statusLogs]);

  useEffect(() => () => {
    if (highlightTimerRef.current) clearTimeout(highlightTimerRef.current);
  }, []);

  function handleListScroll() {
    const el = listRef.current;
    if (el && el.scrollTop <= 8) setHasNewBelow(false);
  }

  function scrollLogToTop() {
    const el = listRef.current;
    if (el && typeof el.scrollTo === 'function') el.scrollTo({top: 0, behavior: 'smooth'});
    else if (el) el.scrollTop = 0;
    setHasNewBelow(false);
  }

  /** 打开"处理失败"弹窗：优先找该阶段未结失败单；无失败单则退化为标记失败 */
  function openFailureFor(phase) {
    const failure = (store.failures || []).find(f =>
      f.phase === phase && (f.status === 'pending' || f.status === 'redoing'));
    if (failure) setHandleFailure(failure);
    else setCreateFailurePhase(phase);
  }

  /** "阶段操作"菜单点击：标记失败弹原因；处理失败/重新执行弹对应窗口 */
  function handlePhaseMenuClick({key}) {
    const [action, ...rest] = key.split('::');
    if (!action) return;
    const phase = rest.join('::');
    if (!phase) return;
    if (action === 'test_fail') return setCreateFailurePhase(phase);
    if (action === 'handle_failure') return openFailureFor(phase);
    if (action === 'redo') return setRedoPhase(phase);
    return undefined;
  }

  /** 该阶段的未结失败单（处理失败弹窗渲染用） */
  function failureSteps(failure) {
    return store.recordSteps.filter(s => (s.phase || '') === failure.phase);
  }

  return (
    <div className={styles.panel}>
      <div className={styles.panelHeader}>
        <span className={styles.panelTitle}>
          状态时间线 <span className={styles.panelSub}>（{store.statusLogs.length}）</span>
        </span>
        {canEdit && actionGroups.length > 0 && (
          <span className={styles.panelHeaderActions}>
            <PhaseActionMenu groups={actionGroups} onClick={handlePhaseMenuClick}/>
          </span>
        )}
      </div>

      <PhaseFlowArea flowNodes={flowNodes} canEdit={canEdit}
        onMarkFailure={setCreateFailurePhase} onOpenFailure={openFailureFor}/>

      <div className={styles.timelineWrap}>
        {hasNewBelow && (
          <Button size="small" type="primary" className={styles.newLogBadge}
            onClick={scrollLogToTop}>有新记录</Button>
        )}
        <div className={styles.timelineScroll} ref={listRef} onScroll={handleListScroll}>
          {store.statusLogs.length > 0
            ? <Timeline>{store.statusLogs.map(log => (
              <LogTimelineItem key={log.id} log={log} highlightId={highlightId}/>
            ))}</Timeline>
            : <Empty description="暂无状态记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
        </div>
      </div>

      {canEdit && (
        <TimelineActionModals
          recordId={recordId}
          createFailurePhase={createFailurePhase}
          handleFailure={handleFailure}
          redoPhase={redoPhase}
          failureSteps={failureSteps}
          onCloseCreate={() => setCreateFailurePhase(null)}
          onCloseHandle={() => setHandleFailure(null)}
          onCloseRedo={() => setRedoPhase(null)}/>
      )}
    </div>
  );
});

/** 查看/编辑模式的左右工作台面板与附件区 */
const WorkbenchPanels = observer(function WorkbenchPanels({recordId, canEdit}) {
  return (
    <>
      <Row gutter={16} className={styles.panelsRow}>
        <Col span={15} className={styles.panelCol}>
          <WorkbenchStepsPanel recordId={recordId} canEdit={canEdit}/>
        </Col>
        <Col span={9} className={styles.panelCol}>
          <WorkbenchTimelinePanel recordId={recordId} canEdit={canEdit}/>
        </Col>
      </Row>
      <Divider style={{ margin: '16px 0 12px' }} />
      <Collapse>
        <Panel header={<span><PaperClipOutlined /> 附件 ({store.attachmentCount})</span>} key="att">
          <AttachmentManager
            module="upgrade" objectType="record" recordId={store.record.id}
            listUrl={`/api/upgrade/records/${store.record.id}/attachments/`}
            uploadUrl={`/api/upgrade/records/${store.record.id}/attachments/`}
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
    </>
  );
});

const WorkbenchForm = forwardRef(function WorkbenchForm({ isNew, recordId, onSaveStart, onSaveEnd, onSaveSuccess, onSaveError }, ref) {
  const [form] = Form.useForm();
  const [selectedPlan, setSelectedPlan] = useState(null);
  // 编辑基本信息面板状态与保存/取消动作（查看/编辑模式，逻辑在 hooks.useBasicInfoEditor）
  const {editVisible, saving, toggleEdit, cancelEdit, saveEdit} = useBasicInfoEditor(form, recordId);

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
  useSyncRecordToForm(form, isNew);

  // 应用方案（新建模式）：预填基本信息，保存时自动应用步骤
  function handleApplyPlanPrefill(planId) {
    store.fetchPlanDetail(planId).then(plan => {
      // 获取失败时提示已由 http 拦截器弹出，plan 为 null 直接返回
      if (!plan) return;
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
      <RecordInfoBar
        canEdit={canEdit} form={form}
        editVisible={editVisible} saving={saving}
        onToggleEdit={toggleEdit}
        onSaveEdit={saveEdit} onCancelEdit={cancelEdit}
        onPrintBasicInfo={() => printUpgradeArchive(info)}
        onPrintSteps={(phase) => printUpgradeSteps({
          info, recordSteps: store.recordSteps,
          phases: store.filterOptions.phases || [], phase,
        })}/>
      <WorkbenchPanels recordId={recordId} canEdit={canEdit}/>
    </div>
  );
});

export default observer(WorkbenchForm);
