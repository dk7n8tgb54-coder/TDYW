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
  PrinterOutlined, DeleteOutlined, PaperClipOutlined, DownOutlined, FormOutlined,
} from '@ant-design/icons';
import { AttachmentManager } from 'components';
import { hasPermission } from 'libs';
import moment from 'moment';
import store from './store';
import { useSyncRecordToForm, useBasicInfoEditor } from './hooks';
import {
  getActionColor, computeStepFlowState, renderFlowNode, STATUS_TAG_COLOR, StepStatusTag,
  groupStepsByPhase, buildPhaseActionGroups, flowHeadline,
} from './shared';
import SystemSelect from './components/SystemSelect';
import { printUpgradeArchive, printUpgradeSteps } from './archivePrint';
import {
  submitUpgradeForm, postStepAction, deleteStep, addStep, clearSteps,
  applyPlanToRecord, postNodeAction, deleteStatusLog, confirmRollback,
} from './workbenchActions';
import styles from './Workbench.module.less';

const { Option } = Select;
const { TextArea } = Input;
const { Panel } = Collapse;

const UPGRADE_TYPE_OPTIONS = ['功能升级', 'Bug修复', '安全补丁', '性能优化'];
const STATUS_OPTIONS = ['处理中', '已完成', '已回退'];
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
 */
function StepRow({recordId, step, canEdit, descExpanded, onToggleDesc}) {
  const done = step.status !== 'pending';
  const moreItems = canEdit ? buildStepMoreItems(step) : [];
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
          <Button size="small" type="link" icon={<CheckCircleOutlined />}
            className={styles.completeBtn}
            onClick={() => postStepAction(recordId, step, 'complete')}>完成</Button>
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

/** 只读详细说明块：查看用户也能阅读升级内容/影响范围/风险说明/回退摘要 */
const DETAIL_BLOCKS = [
  ['upgrade_content', '升级内容'],
  ['impact_scope', '影响范围'],
  ['risk_desc', '风险说明'],
  ['rollback_plan', '回退方案摘要'],
];

function DetailBlocks() {
  return (
    <div className={styles.detailBlocks}>
      {DETAIL_BLOCKS.map(([field, label]) => (
        <div key={field} className={styles.detailBlock}>
          <div className={styles.detailBlockTitle}>{label}</div>
          <div className={styles.detailBlockBody}>{store.record[field] || '—'}</div>
        </div>
      ))}
    </div>
  );
}

/** 编辑基本信息面板：表单字段与原折叠面板一致，面板内提供保存修改/取消 */
function EditBasicInfoPanel({form, saving, onSaveEdit, onCancelEdit}) {
  return (
    <div className={styles.editPanel}>
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
      <div className={styles.editActions}>
        <Button type="primary" loading={saving} onClick={onSaveEdit}>保存修改</Button>
        <Button onClick={onCancelEdit}>取消</Button>
      </div>
    </div>
  );
}

/**
 * 顶部信息栏（紧凑两行）：
 * 第一行 = 升级标题 + 状态，右侧编辑/打印入口；
 * 第二行 = 系统/计划升级时间/负责人主字段，编号/升级类型为次要信息；
 * 详细说明默认收起，展开后只读展示四段说明。
 */
const RecordInfoBar = observer(function RecordInfoBar(
  {canEdit, form, editVisible, saving, onToggleEdit, onSaveEdit, onCancelEdit, onPrintBasicInfo, onPrintSteps}) {
  const [detailVisible, setDetailVisible] = useState(false);
  const info = store.record;
  return (
    <div className={styles.infoBar}>
      <div className={styles.infoRowMain}>
        <span className={styles.infoTitle}>{info.title || '（未命名）'}</span>
        <Tag color={STATUS_TAG_COLOR[info.status] || 'default'}>{info.status}</Tag>
        <span className={styles.infoActions}>
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
          {canEdit && (
            <Button size="small" icon={<FormOutlined />} aria-expanded={!!editVisible}
              onClick={onToggleEdit}>编辑基本信息</Button>
          )}
        </span>
      </div>
      <div className={styles.infoRowSub}>
        <span><span className={styles.infoLabel}>系统</span>{info.system_name || '-'}</span>
        <span><span className={styles.infoLabel}>计划升级时间</span>{info.upgrade_time || '-'}</span>
        <span><span className={styles.infoLabel}>负责人</span>{info.owner || '-'}</span>
        <span className={styles.infoMinor}><span className={styles.infoLabel}>编号</span>{info.upgrade_no || '-'}</span>
        <span className={styles.infoMinor}><span className={styles.infoLabel}>升级类型</span>{info.upgrade_type || '-'}</span>
        <Button type="link" size="small" className={styles.detailToggle}
          aria-expanded={detailVisible}
          onClick={() => setDetailVisible(v => !v)}>
          {detailVisible ? '收起详细说明' : '详细说明'}
        </Button>
      </div>
      {detailVisible && <DetailBlocks />}
      {canEdit && editVisible && (
        <EditBasicInfoPanel
          form={form} saving={saving}
          onSaveEdit={onSaveEdit} onCancelEdit={onCancelEdit}/>
      )}
    </div>
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
  // 阶段状态复用 computeStepFlowState（当前阶段标记底色，不另加业务判断）
  const phaseStateMap = computeStepFlowState(
    store.recordSteps, phases, store.statusLogs).nodes
    .reduce((map, n) => { map[n.label] = n.state; return map; }, {});
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

/** 键盘可操作的流程节点包装（Enter/空格触发点击，焦点样式见 nodeClickable:focus-visible） */
function ClickableNode({onClick, children}) {
  return (
    <span className={styles.nodeClickable} tabIndex={0} role="button" onClick={onClick}
      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') e.target.click(); }}>
      {children}
    </span>
  );
}

/** 流程节点快捷交互（保留原有入口；回退改走带影响预览的统一确认） */
function FlowNodeWithAction({node, idx, canEdit, recordId}) {
  const el = renderFlowNode(node, idx);
  if (!canEdit) return <span key={node.action}>{el}</span>;
  if (node.state === 'current') {
    return (
      <Dropdown key={node.action} trigger={['click']} overlay={(
        <Menu onClick={({key}) => postNodeAction(recordId, key, node)}>
          <Menu.Item key="pause">暂停该阶段</Menu.Item>
          <Menu.Item key="test_fail">标记失败</Menu.Item>
        </Menu>
      )}>
        <ClickableNode>{el}</ClickableNode>
      </Dropdown>
    );
  }
  if (node.state === 'paused') {
    return (
      <Popconfirm key={node.action} title="继续该阶段？" onConfirm={() => postNodeAction(recordId, 'resume', node)}>
        <ClickableNode>{el}</ClickableNode>
      </Popconfirm>
    );
  }
  if (node.state === 'completed') {
    return (
      <ClickableNode key={node.action} onClick={() => confirmRollback(recordId, node)}>
        {el}
      </ClickableNode>
    );
  }
  if (node.state === 'failed') {
    return <Tooltip key={node.action} title="该阶段失败，请回退到之前的阶段重做">{el}</Tooltip>;
  }
  return <span key={node.action}>{el}</span>;
}

/** 单条状态日志：结果为一级文案，操作人/时间次要，备注可读（撤销条目弱化） */
function LogTimelineItem({log, canEdit, recordId, highlightId}) {
  const isPhaseDone = log.action === 'phase_done';
  const dimmed = isPhaseDone && log.outcome === 'revoked';
  let logColor;
  let mainText;
  let tagColor;
  if (isPhaseDone) {
    const phase = log.phase || '阶段';
    if (log.outcome === 'failed') {
      logColor = 'red'; tagColor = 'red'; mainText = `${phase}阶段未通过`;
    } else if (log.outcome === 'revoked') {
      logColor = 'gray'; tagColor = 'default'; mainText = `${phase}阶段已撤销`;
    } else {
      logColor = 'green'; tagColor = 'success'; mainText = `${phase}阶段已完成`;
    }
  } else {
    logColor = getActionColor(log.action);
    tagColor = logColor;
    mainText = log.action_text;
  }
  return (
    <Timeline.Item key={log.id} color={logColor}>
      <div className={styles.logRow} style={dimmed ? {opacity: 0.55} : undefined}>
        <div className={highlightId === log.id
          ? `${styles.logItem} ${styles.logItemHighlight}` : styles.logItem}>
          <div className={styles.logMain}>
            <Tag color={tagColor} className={styles.logTag}>{mainText}</Tag>
            {log.action === 'rollback' && log.target_action_text && (
              <span className={styles.logWarnText}>回退到：{log.target_action_text}</span>
            )}
            {log.action === 'test_fail' && log.phase && (
              <span className={styles.logWarnText}>失败阶段：{log.phase}</span>
            )}
            {log.to_status && log.to_status !== log.from_status && (
              <span className={styles.logStatusText}>{log.from_status}→{log.to_status}</span>
            )}
          </div>
          <div className={styles.logMeta}>{log.operator_name} · {log.created_at}</div>
          {log.remark && <div className={styles.logRemark}>{log.remark}</div>}
        </div>
        {canEdit && (
          <Popconfirm title="确定删除此日志？" onConfirm={() => deleteStatusLog(recordId, log.id)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />} style={{ padding: 0 }} />
          </Popconfirm>
        )}
      </div>
    </Timeline.Item>
  );
}

/**
 * 状态时间线面板：流程节点（带快捷交互）+ 阶段操作菜单 + 状态日志时间线。
 * - 日志条目以事件结果为一级信息（如"备份阶段已完成"），操作人/时间为次要信息；
 * - 新日志到达时短暂高亮；用户已滚离顶部时不抢滚动，改用"有新记录"按钮定位。
 */
const WorkbenchTimelinePanel = observer(function WorkbenchTimelinePanel({recordId, canEdit}) {
  const flowNodes = computeStepFlowState(store.recordSteps, store.filterOptions.phases, store.statusLogs).nodes;
  const actionGroups = buildPhaseActionGroups(flowNodes);
  const listRef = useRef(null);
  const prevLogIdsRef = useRef(null);
  const [highlightId, setHighlightId] = useState(null);
  const [hasNewBelow, setHasNewBelow] = useState(false);
  const highlightTimerRef = useRef(null);

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

  /** "阶段操作"菜单点击 → 复用既有节点动作（回退走确认预览） */
  function handlePhaseMenuClick({key}) {
    const [action, ...rest] = key.split('::');
    if (!action) return;
    const node = flowNodes.find(n => n.label === rest.join('::'));
    if (!node) return;
    if (action === 'rollback') return confirmRollback(recordId, node);
    if (['pause', 'resume', 'test_fail'].includes(action)) {
      return postNodeAction(recordId, action, node);
    }
    return undefined;
  }

  return (
    <div className={styles.panel}>
      <div className={styles.panelHeader}>
        <span className={styles.panelTitle}>
          状态时间线 <span className={styles.panelSub}>（{store.statusLogs.length}）</span>
        </span>
        {canEdit && actionGroups.length > 0 && (
          <span className={styles.panelHeaderActions}>
            <Dropdown trigger={['click']} overlay={(
              <Menu onClick={handlePhaseMenuClick}>
                {actionGroups.map(g => (
                  <Menu.ItemGroup key={g.key} title={g.title}>
                    {g.items.map(item => (
                      <Menu.Item key={item.key} danger={item.danger} disabled={item.disabled}>
                        {item.label}
                      </Menu.Item>
                    ))}
                  </Menu.ItemGroup>
                ))}
              </Menu>
            )}>
              <Button size="small">阶段操作 <DownOutlined /></Button>
            </Dropdown>
          </span>
        )}
      </div>

      <div className={styles.flowArea}>
        <div className={styles.flowHeadline}>{flowHeadline(flowNodes)}</div>
        <div className={styles.flowNodes}>
          {flowNodes.length > 0
            ? flowNodes.map((node, idx) => (
              <FlowNodeWithAction key={node.action} node={node} idx={idx + 1}
                canEdit={canEdit} recordId={recordId}/>
            ))
            : <span className={styles.flowEmpty}>暂无阶段（请为步骤设置阶段）</span>}
        </div>
      </div>

      <div className={styles.timelineWrap}>
        {hasNewBelow && (
          <Button size="small" type="primary" className={styles.newLogBadge}
            onClick={scrollLogToTop}>有新记录</Button>
        )}
        <div className={styles.timelineScroll} ref={listRef} onScroll={handleListScroll}>
          {store.statusLogs.length > 0
            ? <Timeline>{store.statusLogs.map(log => (
              <LogTimelineItem key={log.id} log={log} canEdit={canEdit}
                recordId={recordId} highlightId={highlightId}/>
            ))}</Timeline>
            : <Empty description="暂无状态记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
        </div>
      </div>
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
