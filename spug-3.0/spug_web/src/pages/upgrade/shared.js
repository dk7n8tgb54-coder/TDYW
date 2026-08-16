/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
// 升级模块共享常量与组件（WorkbenchForm / CreateUpgradeModal 复用，消除重复定义）
import React from 'react';
import { Tag, Tooltip } from 'antd';
import { CheckCircleOutlined, CloseCircleOutlined, UndoOutlined, PauseCircleOutlined } from '@ant-design/icons';

// 动作类型 → 时间线颜色（与后端 ACTION_COLOR_MAP 对齐）
export const ACTION_COLOR = {
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

export function getActionColor(action) {
  return ACTION_COLOR[action] || 'blue';
}

// 标准升级流程顺序（主线，异常分支如回退/暂停/失败不进主线）
// 用于时间线顶部对照参考。这里展示阶段名，完成/当前/未开始由图标和颜色表达。
export const STANDARD_FLOW = [
  { action: 'start', label: '升级启动' },
  { action: 'backup', label: '备份' },
  { action: 'gray_release', label: '灰度发布' },
  { action: 'test_pass', label: '升级测试' },
  { action: 'full_release', label: '全量发布' },
  { action: 'observe', label: '观察' },
  { action: 'complete', label: '升级完成' },
];

// 主线动作 → 序号快查
const FLOW_INDEX = STANDARD_FLOW.reduce((acc, node, idx) => {
  acc[node.action] = idx;
  return acc;
}, {});

// 可作为回退目标的主线节点（不含 complete）
export const ROLLBACK_TARGETS = STANDARD_FLOW.filter(n => n.action !== 'complete');

// 状态 → Tag 颜色
export const STATUS_TAG_COLOR = {
  '处理中': 'processing',
  '已完成': 'success',
  '已回退': 'error',
};

/**
 * 流程归约函数：根据状态日志序列计算标准流程参考进度。
 *
 * 语义：状态时间线动作代表"该节点已完成/达成"，参考条文本只显示阶段名；
 * 绿色对勾表示完成，蓝色右三角表示当前阶段/待完成。
 *
 * 算法：
 * - 按 event_seq / id / created_at 正序处理日志
 * - 主线 action 推进 currentIndex（需满足顺序或 is_override）
 * - rollback 根据 target_action 把 currentIndex 退回到 target_idx - 1
 *   （目标节点变为 current，表示需要重新执行/确认）
 * - test_fail 将"升级测试"标记为 failed，并停留在该阶段
 * - 被回退失效的后续节点标记为 rolled_back（曾完成但已回退）
 *
 * @param {Array} statusLogs - 状态日志列表（可为倒序，函数内部排序）
 * @returns {{currentIndex: number, nodes: Array}} 归约结果
 *   nodes[].state: 'completed' | 'current' | 'pending' | 'rolled_back' | 'override' | 'skipped' | 'failed'
 */
export function computeFlowState(statusLogs) {
  if (!statusLogs || statusLogs.length === 0) {
    return {
      currentIndex: -1,
      nodes: STANDARD_FLOW.map((node, idx) => ({
        ...node, index: idx, state: idx === 0 ? 'current' : 'pending',
      })),
    };
  }

  // 正序排序：event_seq → id → created_at
  const sorted = [...statusLogs].sort((a, b) => {
    const sa = a.event_seq ?? 0;
    const sb = b.event_seq ?? 0;
    if (sa !== sb) return sa - sb;
    const ia = a.id ?? 0;
    const ib = b.id ?? 0;
    if (ia !== ib) return ia - ib;
    return (a.created_at || '').localeCompare(b.created_at || '');
  });

  let currentIndex = -1;
  const everDoneSet = new Set();   // 曾经完成过的节点（用于标记 rolled_back）
  const overrideSet = new Set();   // 通过补录/跳步完成的节点
  const failedSet = new Set();     // 当前失败/阻塞的节点

  for (const log of sorted) {
    const { action, target_action, is_override } = log;

    if (action === 'rollback') {
      const target = target_action || '';
      if (target in FLOW_INDEX) {
        const targetIdx = FLOW_INDEX[target];
        // 仅当目标在当前进度范围内才生效（不能回退到未完成的节点）
        if (targetIdx <= currentIndex) {
          // 回退到 target：target 变为待重做（current），所以 currentIndex = targetIdx - 1
          currentIndex = targetIdx - 1;
        }
      }
    } else if (action === 'test_fail') {
      const testIdx = FLOW_INDEX.test_pass;
      if (testIdx !== undefined && (testIdx <= currentIndex + 1 || is_override)) {
        currentIndex = is_override
          ? Math.max(currentIndex, testIdx - 1)
          : Math.min(currentIndex, testIdx - 1);
        failedSet.add('test_pass');
      }
    } else if (action in FLOW_INDEX) {
      const idx = FLOW_INDEX[action];
      // 正常推进（idx <= currentIndex+1）或补录跳步（is_override）
      if (idx <= currentIndex + 1 || is_override) {
        currentIndex = Math.max(currentIndex, idx);
        everDoneSet.add(action);
        if (is_override) overrideSet.add(action);
        failedSet.delete(action);
      }
    }
    // 非主线动作（pause/resume）不影响进度
  }

  const nodes = STANDARD_FLOW.map((node, idx) => {
    if (failedSet.has(node.action) && idx === currentIndex + 1) {
      return { ...node, index: idx, state: 'failed' };
    } else if (everDoneSet.has(node.action) && idx <= currentIndex) {
      // 实际完成且当前有效
      return { ...node, index: idx, state: overrideSet.has(node.action) ? 'override' : 'completed' };
    } else if (idx <= currentIndex) {
      // 在 currentIndex 范围内但未实际完成（被 override 跳过）
      return { ...node, index: idx, state: 'skipped' };
    } else if (idx === currentIndex + 1) {
      // 当前阶段/下一步应执行
      return { ...node, index: idx, state: 'current' };
    } else if (everDoneSet.has(node.action)) {
      // 曾经完成但已回退
      return { ...node, index: idx, state: 'rolled_back' };
    }
    return { ...node, index: idx, state: 'pending' };
  });

  return { currentIndex, nodes };
}

/**
 * 渲染标准流程参考条节点标签
 * @param {Object} node - computeFlowState 返回的 node 项
 * @param {number} displayIdx - 显示序号（从 1 开始）
 */
export function renderFlowNode(node, displayIdx) {
  const styleMap = {
    completed: {
      bg: '#f6ffed', color: '#52c41a', border: '#b7eb8f', fontWeight: 'normal',
      icon: <CheckCircleOutlined />, prefix: '',
    },
    override: {
      bg: '#fff7e6', color: '#fa8c16', border: '#ffd591', fontWeight: 'normal',
      icon: <CheckCircleOutlined />, prefix: '补',
    },
    current: {
      bg: '#e6f7ff', color: '#1890ff', border: '#91d5ff', fontWeight: 'bold',
      icon: null, prefix: '▶',
    },
    rolled_back: {
      bg: '#fff1f0', color: '#ff4d4f', border: '#ffa39e', fontWeight: 'normal',
      icon: <UndoOutlined />, prefix: '',
    },
    skipped: {
      bg: '#fffbe6', color: '#d4b106', border: '#ffe58f', fontWeight: 'normal',
      icon: <CloseCircleOutlined />, prefix: '跳',
    },
    failed: {
      bg: '#fff1f0', color: '#cf1322', border: '#ffa39e', fontWeight: 'bold',
      icon: <CloseCircleOutlined />, prefix: '',
    },
    paused: {
      bg: '#fff7e6', color: '#fa8c16', border: '#ffd591', fontWeight: 'bold',
      icon: <PauseCircleOutlined />, prefix: '',
    },
    pending: {
      bg: '#fafafa', color: '#bbb', border: '#e8e8e8', fontWeight: 'normal',
      icon: null, prefix: '',
    },
  };
  const cfg = styleMap[node.state] || styleMap.pending;
  const label = (
    <span style={{
      fontSize: 11, padding: '2px 8px', borderRadius: 10,
      display: 'inline-flex', alignItems: 'center', gap: 4,
      background: cfg.bg, color: cfg.color,
      border: `1px solid ${cfg.border}`,
      fontWeight: cfg.fontWeight,
    }}>
      {cfg.icon}
      {cfg.prefix && <span style={{ fontWeight: 'bold' }}>{cfg.prefix}</span>}
      {displayIdx}.{node.label}
    </span>
  );

  // override / rolled_back / skipped 状态加 tooltip 说明
  if (node.state === 'override') {
    return <Tooltip key={node.action} title="此节点通过补录/跳步完成，非正常顺序推进">{label}</Tooltip>;
  }
  if (node.state === 'rolled_back') {
    return <Tooltip key={node.action} title="此节点曾完成但已被回退">{label}</Tooltip>;
  }
  if (node.state === 'skipped') {
    return <Tooltip key={node.action} title="此节点被跳过（因补录/跳步越过）">{label}</Tooltip>;
  }
  if (node.state === 'failed') {
    return <Tooltip key={node.action} title="此阶段测试失败，需重新处理或回退">{label}</Tooltip>;
  }
  return <span key={node.action}>{label}</span>;
}

// 步骤状态标签（纯展示组件，定义在模块顶层避免每次父渲染重建组件类型）
export function StepStatusTag({ status }) {
  const map = {
    pending: { color: 'default', icon: null, text: '待执行' },
    completed: { color: 'success', icon: <CheckCircleOutlined />, text: '已完成' },
    skipped: { color: 'warning', icon: <CloseCircleOutlined />, text: '已跳过' },
  };
  const cfg = map[status] || map.pending;
  return <Tag color={cfg.color} icon={cfg.icon}>{cfg.text}</Tag>;
}

/**
 * 按阶段文本分组步骤（保序去重）。
 * 预设阶段按给定顺序在前，自定义阶段按首次出现顺序追加，空 phase 归"未分组"。
 *
 * @param {Array} steps - 步骤数组，每项含 phase 字段（显示名）
 * @param {Array} presetPhases - 预设阶段名列表（字符串），控制前置分组顺序
 * @returns {{groups: Array<{name:string, steps:Array}>, ungrouped: Array}}
 *   groups: 有阶段名的分组（按预设顺序 + 自定义首次出现顺序），ungrouped: phase 为空的步骤
 */
export function groupStepsByPhase(steps, presetPhases = []) {
  // 组顺序按步骤首次出现顺序（即 sequence 顺序），尊重用户拖拽顺序，保证序号连续。
  // 不再用 presetPhases 强制排序（旧 UPGRADE_PHASES 固定顺序会与 sequence 冲突）。
  // presetPhases 参数保留兼容（前端 AutoComplete 候选用），此处不影响排序。
  const grouped = {};
  const orderedNames = [];
  const ungrouped = [];

  (steps || []).forEach(step => {
    const name = (step && step.phase || '').trim();
    if (!name) { ungrouped.push(step); return; }
    if (!grouped[name]) {
      grouped[name] = [];
      orderedNames.push(name);
    }
    grouped[name].push(step);
  });

  const groups = orderedNames.map(name => ({ name, steps: grouped[name] }));
  return { groups, ungrouped };
}

/**
 * 根据步骤清单的阶段分组推算"升级流程"参考条节点状态。
 *
 * 节点 = 步骤的阶段（去重保序，预设在前），状态由该阶段步骤完成度决定：
 *   - 该阶段所有步骤 completed → completed
 *   - 第一个未全部完成的阶段 → current（再结合 statusLogs 推断 paused/failed）
 *   - 其后阶段 → pending
 * 全部完成时 currentIndex = -1，所有节点 completed。
 *
 * paused/failed 推断：查 statusLogs 中该阶段最近一条 pause/resume/test_fail 事件：
 *   - 最近 pause → paused（流程挂起）
 *   - 最近 test_fail → failed（需回退重做）
 *   - 最近 resume 或无 → current
 *
 * @param {Array} steps - 步骤数组，每项含 phase / status 字段
 * @param {Array} presetPhases - 预设阶段名列表（控制前置顺序）
 * @param {Array} statusLogs - 状态日志（用于推断 paused/failed）
 * @returns {{currentIndex: number, nodes: Array}} nodes 项含 {action, label, state, index}
 */
export function computeStepFlowState(steps, presetPhases = [], statusLogs = []) {
  const { groups } = groupStepsByPhase(steps, presetPhases);
  // skipped 与 completed 同样视为已处理（与后端阶段完成判定一致）
  const isDone = s => s.status === 'completed' || s.status === 'skipped';
  const currentIndex = groups.findIndex(g => g.steps.some(s => !isDone(s)));

  // 按阶段查最近的 pause/resume/test_fail 事件（正序遍历，后覆盖前 = 最近生效）
  const phaseEvent = {};
  const sortedLogs = [...(statusLogs || [])].sort((a, b) => {
    const sa = a.event_seq ?? 0, sb = b.event_seq ?? 0;
    if (sa !== sb) return sa - sb;
    return (a.id ?? 0) - (b.id ?? 0);
  });
  for (const log of sortedLogs) {
    if (['pause', 'resume', 'test_fail'].includes(log.action) && log.phase) {
      phaseEvent[log.phase] = log.action;
    }
  }

  const nodes = groups.map((g, idx) => {
    const allDone = g.steps.every(isDone);
    let state;
    if (allDone) {
      state = 'completed';
    } else if (idx === currentIndex) {
      const evt = phaseEvent[g.name];
      if (evt === 'pause') state = 'paused';
      else if (evt === 'test_fail') state = 'failed';
      else state = 'current';
    } else {
      state = 'pending';
    }
    return { action: g.name, label: g.name, state, index: idx };
  });
  return { currentIndex, nodes };
}
