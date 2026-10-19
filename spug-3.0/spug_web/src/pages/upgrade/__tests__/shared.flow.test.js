/**
 * 系统升级共享流程逻辑测试
 *
 * 覆盖 upgrade/shared.js 的核心纯函数：
 * - ACTION_COLOR / getActionColor / STANDARD_FLOW / ROLLBACK_TARGETS 常量契约
 * - computeFlowState：状态日志归约（空日志/顺序推进/倒序输入/回退/测试失败/补录跳步/
 *   回退到未完成节点不生效）
 * - groupStepsByPhase：按阶段保序分组、空阶段归未分组
 * - computeStepFlowState：按步骤完成度推算阶段状态（skipped 视为完成、pause/test_fail 推断）
 */
import {
  ACTION_COLOR,
  getActionColor,
  STANDARD_FLOW,
  ROLLBACK_TARGETS,
  computeFlowState,
  groupStepsByPhase,
  computeStepFlowState,
} from '../shared';

const FLOW_ACTIONS = ['start', 'backup', 'gray_release', 'test_pass', 'full_release', 'observe', 'complete'];

function log(action, seq, extra = {}) {
  return {id: seq, action, event_seq: seq, created_at: `2026-01-01 00:${String(seq).padStart(2, '0')}`, ...extra};
}

describe('升级动作与流程常量', () => {
  it('getActionColor 已知动作返回映射色，未知动作兜底蓝色', () => {
    expect(getActionColor('rollback')).toBe('red');
    expect(getActionColor('complete')).toBe('green');
    expect(getActionColor('unknown_action')).toBe('blue');
    expect(Object.keys(ACTION_COLOR)).toEqual(expect.arrayContaining([
      'start', 'backup', 'gray_release', 'full_release', 'test', 'test_pass', 'test_fail',
      'rollback', 'pause', 'resume', 'observe', 'complete',
    ]));
  });

  it('标准主线七步有序，回退目标不含"升级完成"', () => {
    expect(STANDARD_FLOW.map(n => n.action)).toEqual(FLOW_ACTIONS);
    expect(ROLLBACK_TARGETS.map(n => n.action)).toEqual(FLOW_ACTIONS.slice(0, 6));
  });
});

describe('computeFlowState 状态日志归约', () => {
  it('空日志：首节点 current，其余 pending', () => {
    const {currentIndex, nodes} = computeFlowState([]);
    expect(currentIndex).toBe(-1);
    expect(nodes.map(n => n.state)).toEqual(['current', 'pending', 'pending', 'pending', 'pending', 'pending', 'pending']);
  });

  it('顺序推进到全量发布：前五步 completed，观察为 current', () => {
    const logs = [log('start', 1), log('backup', 2), log('gray_release', 3), log('test_pass', 4), log('full_release', 5)];
    const {currentIndex, nodes} = computeFlowState(logs);
    expect(currentIndex).toBe(4);
    expect(nodes.map(n => n.state)).toEqual(
      ['completed', 'completed', 'completed', 'completed', 'completed', 'current', 'pending']
    );
  });

  it('日志倒序输入时按 event_seq 正序归约', () => {
    const logs = [log('backup', 2), log('start', 1)];
    const {currentIndex} = computeFlowState(logs);
    expect(currentIndex).toBe(1);
  });

  it('回退到备份：备份变为待重做（current），其后已完成节点标记 rolled_back', () => {
    const logs = [
      log('start', 1), log('backup', 2), log('gray_release', 3),
      log('test_pass', 4), log('full_release', 5),
      log('rollback', 6, {target_action: 'backup'}),
    ];
    const {currentIndex, nodes} = computeFlowState(logs);
    expect(currentIndex).toBe(0);
    expect(nodes.map(n => n.state)).toEqual(
      ['completed', 'current', 'rolled_back', 'rolled_back', 'rolled_back', 'pending', 'pending']
    );
  });

  it('回退到未完成的节点不生效', () => {
    const logs = [log('start', 1), log('backup', 2), log('rollback', 3, {target_action: 'full_release'})];
    const {currentIndex} = computeFlowState(logs);
    // full_release(idx4) 尚未完成，回退目标越界被忽略
    expect(currentIndex).toBe(1);
  });

  it('测试失败：升级测试节点标记 failed 并停留该阶段', () => {
    const logs = [log('start', 1), log('backup', 2), log('gray_release', 3), log('test_fail', 4)];
    const {currentIndex, nodes} = computeFlowState(logs);
    expect(currentIndex).toBe(2);
    expect(nodes.map(n => n.state)).toEqual(
      ['completed', 'completed', 'completed', 'failed', 'pending', 'pending', 'pending']
    );
  });

  it('补录跳步：越过的节点标记 skipped，补录节点标记 override', () => {
    const logs = [log('full_release', 1, {is_override: true})];
    const {currentIndex, nodes} = computeFlowState(logs);
    expect(currentIndex).toBe(4);
    expect(nodes.map(n => n.state)).toEqual(
      ['skipped', 'skipped', 'skipped', 'skipped', 'override', 'current', 'pending']
    );
  });
});

describe('groupStepsByPhase 步骤分组', () => {
  it('按阶段保序分组（首次出现顺序），空阶段归未分组', () => {
    const steps = [
      {id: 1, phase: '准备', status: 'completed'},
      {id: 2, phase: '', status: 'pending'},
      {id: 3, phase: '发布', status: 'pending'},
      {id: 4, phase: '准备', status: 'pending'},
      {id: 5, phase: null, status: 'completed'},
    ];
    const {groups, ungrouped} = groupStepsByPhase(steps, ['发布', '准备']);
    // 分组顺序按步骤首次出现顺序，不受 presetPhases 影响（保留参数仅为兼容）
    expect(groups.map(g => g.name)).toEqual(['准备', '发布']);
    expect(groups[0].steps.map(s => s.id)).toEqual([1, 4]);
    expect(groups[1].steps.map(s => s.id)).toEqual([3]);
    expect(ungrouped.map(s => s.id)).toEqual([2, 5]);
  });

  it('空步骤列表返回空分组', () => {
    expect(groupStepsByPhase([], [])).toEqual({groups: [], ungrouped: []});
  });
});

describe('computeStepFlowState 阶段状态推算', () => {
  const STEPS = [
    {id: 1, phase: '准备', status: 'completed'},
    {id: 2, phase: '准备', status: 'completed'},
    {id: 3, phase: '发布', status: 'pending'},
    {id: 4, phase: '验证', status: 'pending'},
  ];

  it('已完成阶段 completed，第一个未完阶段 current，其后 pending', () => {
    const {currentIndex, nodes} = computeStepFlowState(STEPS);
    expect(currentIndex).toBe(1);
    expect(nodes.map(n => n.state)).toEqual(['completed', 'current', 'pending']);
  });

  it('skipped 与 completed 同样视为已处理', () => {
    const steps = [
      {id: 1, phase: '准备', status: 'skipped'},
      {id: 2, phase: '发布', status: 'pending'},
    ];
    const {currentIndex, nodes} = computeStepFlowState(steps);
    expect(currentIndex).toBe(1);
    expect(nodes[0].state).toBe('completed');
    expect(nodes[1].state).toBe('current');
  });

  it('全部完成时所有节点 completed', () => {
    const steps = STEPS.map(s => ({...s, status: 'completed'}));
    const {currentIndex, nodes} = computeStepFlowState(steps);
    expect(currentIndex).toBe(-1);
    expect(nodes.every(n => n.state === 'completed')).toBe(true);
  });

  it('旧 test_fail 事件（无失败单）不再推断为失败状态（不凭旧事件推断未结失败）', () => {
    const logs = [log('test_fail', 1, {phase: '发布'})];
    const {nodes} = computeStepFlowState(STEPS, [], logs);
    expect(nodes[1].state).toBe('current');
  });

  it('暂停事件不再产生 paused（暂停/继续已下线，历史事件仅展示）', () => {
    const logs = [log('pause', 1, {phase: '发布'})];
    const {nodes} = computeStepFlowState(STEPS, [], logs);
    expect(nodes[1].state).toBe('current');
  });

  it('失败单优先：pending → failed，redoing → redoing', () => {
    const failures = [
      {id: 1, phase: '发布', status: 'pending'},
    ];
    const withFailure = computeStepFlowState(STEPS, [], [], failures);
    expect(withFailure.nodes[1].state).toBe('failed');

    const redoing = computeStepFlowState(STEPS, [], [], [
      {id: 1, phase: '发布', status: 'redoing'},
    ]);
    expect(redoing.nodes[1].state).toBe('redoing');

    // 已结案失败单不影响状态
    const resolved = computeStepFlowState(STEPS, [], [], [
      {id: 1, phase: '发布', status: 'resolved'},
    ]);
    expect(resolved.nodes[1].state).toBe('current');
  });
});
