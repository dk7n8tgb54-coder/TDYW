/**
 * 缺陷复现测试（2026-10-04 审计）：workbenchActions 动作层。
 *
 * P1  postStepAction/deleteStep/addStep 成功后未刷新 store.record：
 *     后端步骤操作会联动主表 status（步骤打勾→已完成、加/删步骤→回退处理中），
 *     动作层只刷新步骤与列表，工作台头部状态标签继续显示旧值。
 *     期望：三个动作成功后都调用 store.fetchRecord(recordId)。
 *
 * 2026-10-15 追加（体验改造）：
 * G1  postStepAction/postNodeAction 在途守卫：同一目标相同动作请求返回前
 *     不重复提交（弱网双击防护）。
 *
 * 2026-10-18 追加（失败闭环改造）：
 * F1  markPhaseFailure/startFailureRedo/correctFailure/executeRedoFrom
 *     请求契约（URL/payload）与成功后刷新（步骤/时间线/失败单/主记录）。
 *     删除状态日志已下线（历史事件禁删改），deleteStatusLog 动作移除。
 */
import {act} from 'react-dom/test-utils';

jest.mock('libs', () => ({
  http: {
    get: jest.fn(() => Promise.resolve({})),
    post: jest.fn(() => Promise.resolve({})),
    put: jest.fn(() => Promise.resolve({})),
    delete: jest.fn(() => Promise.resolve({})),
  },
  hasPermission: jest.fn(() => true),
}));

jest.mock('antd', () => {
  const actual = jest.requireActual('antd');
  return {
    ...actual,
    message: {
      success: jest.fn(),
      error: jest.fn(),
      warning: jest.fn(),
      info: jest.fn(),
      confirm: jest.fn(),
    },
    // Modal 组件本体保留（applyPlanToRecord 的替换确认真实渲染）
  };
});

const {http} = require('libs');
const store = require('../store').default;
const {
  postStepAction, deleteStep, addStep, postNodeAction,
  markPhaseFailure, startFailureRedo, correctFailure, executeRedoFrom,
} = require('../workbenchActions');

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

function mockRefreshers() {
  const fetchRecord = jest.fn(() => Promise.resolve({id: 1}));
  store.fetchRecord = fetchRecord;
  store.fetchRecordSteps = jest.fn(() => Promise.resolve());
  store.fetchStatusLogs = jest.fn(() => Promise.resolve());
  store.fetchRecords = jest.fn(() => Promise.resolve());
  store.fetchFailures = jest.fn(() => Promise.resolve());
  return fetchRecord;
}

describe('缺陷复现：步骤动作后刷新主记录（P1）', () => {
  let fetchRecord;

  beforeEach(() => {
    jest.clearAllMocks();
    fetchRecord = mockRefreshers();
  });

  it('postStepAction 成功后刷新 store.record', async () => {
    http.put.mockResolvedValue({});
    postStepAction('1', {id: 11}, 'complete');
    await flush();
    await flush();
    expect(http.put).toHaveBeenCalledWith(
      '/api/upgrade/record-steps/11/update/', {action: 'complete'});
    expect(fetchRecord).toHaveBeenCalledWith('1');
  });

  it('deleteStep 成功后刷新 store.record', async () => {
    http.delete.mockResolvedValue({});
    deleteStep('1', {id: 11});
    await flush();
    await flush();
    expect(fetchRecord).toHaveBeenCalledWith('1');
  });

  it('addStep 成功后返回 promise 并刷新 store.record', async () => {
    http.post.mockResolvedValue({});
    const result = addStep('1', {title: '新步骤'});
    // 弹窗依赖该 promise 决定何时关闭（提交失败不关弹窗）
    expect(result && typeof result.then).toBe('function');
    await flush();
    await flush();
    expect(fetchRecord).toHaveBeenCalledWith('1');
  });
});

describe('G1：动作在途守卫（重复提交防护）', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockRefreshers();
  });

  it('postStepAction 请求未返回前重复点击只提交一次', async () => {
    let resolvePut;
    http.put.mockImplementation(() => new Promise(r => { resolvePut = r; }));
    const step = {id: 11};
    postStepAction('1', step, 'complete');
    postStepAction('1', step, 'complete');
    postStepAction('1', step, 'complete');
    expect(http.put).toHaveBeenCalledTimes(1);
    await act(async () => {
      resolvePut({});
      await flush();
      await flush();
    });
    // 完成后守卫释放，可再次提交
    postStepAction('1', step, 'complete');
    expect(http.put).toHaveBeenCalledTimes(2);
  });

  it('postNodeAction 请求未返回前重复点击只提交一次', async () => {
    let resolvePost;
    http.post.mockImplementation(() => new Promise(r => { resolvePost = r; }));
    const node = {label: '备份'};
    postNodeAction('1', 'test_fail', node);
    postNodeAction('1', 'test_fail', node);
    expect(http.post).toHaveBeenCalledTimes(1);
    await act(async () => {
      resolvePost({id: 9});
      await flush();
      await flush();
    });
    postNodeAction('1', 'test_fail', node);
    expect(http.post).toHaveBeenCalledTimes(2);
  });

  it('请求失败也释放守卫（catch 后可重试）', async () => {
    http.put.mockRejectedValue('请求失败: 500');
    const step = {id: 12};
    postStepAction('1', step, 'skip');
    await flush();
    await flush();
    postStepAction('1', step, 'skip');
    expect(http.put).toHaveBeenCalledTimes(2);
  });
});

describe('F1：失败闭环动作契约', () => {
  let fetchRecord;

  beforeEach(() => {
    jest.clearAllMocks();
    fetchRecord = mockRefreshers();
  });

  it('markPhaseFailure：POST test_fail（阶段+原因），成功后刷新失败单并乐观插入日志', async () => {
    http.post.mockResolvedValue({id: 77});
    store.statusLogs = [];
    await markPhaseFailure('1', '灰度发布', '指标异常');
    expect(http.post).toHaveBeenCalledWith(
      '/api/upgrade/records/1/status-logs/',
      {action: 'test_fail', phase: '灰度发布', remark: '指标异常'});
    expect(store.fetchFailures).toHaveBeenCalledWith('1');
    // 后端返回完整日志时乐观插入时间线顶部，不发重复请求
    expect(store.statusLogs[0].id).toBe(77);
  });

  it('startFailureRedo：POST start-redo（选择/实际数量由后端返回），刷新步骤与主记录', async () => {
    http.post.mockResolvedValue({failure_id: 5, selected_count: 3, reset_count: 2});
    const res = await startFailureRedo('1', 5, {stepIds: [1, 2, 3], note: ''});
    expect(http.post).toHaveBeenCalledWith(
      '/api/upgrade/records/1/failures/5/start-redo/',
      {step_ids: [1, 2, 3], all_steps: false, note: ''});
    expect(res.selected_count).toBe(3);
    expect(store.fetchRecordSteps).toHaveBeenCalledWith('1');
    expect(store.fetchFailures).toHaveBeenCalledWith('1');
    expect(fetchRecord).toHaveBeenCalledWith('1');
  });

  it('startFailureRedo 支持整阶段重做（all_steps=true）', async () => {
    http.post.mockResolvedValue({failure_id: 5, selected_count: 3, reset_count: 3});
    await startFailureRedo('1', 5, {allSteps: true});
    expect(http.post).toHaveBeenCalledWith(
      '/api/upgrade/records/1/failures/5/start-redo/',
      {step_ids: [], all_steps: true, note: ''});
  });

  it('correctFailure：POST correct（原因必填语义由后端校验），刷新失败单', async () => {
    http.post.mockResolvedValue({});
    await correctFailure('1', 5, '误报：指标恢复');
    expect(http.post).toHaveBeenCalledWith(
      '/api/upgrade/records/1/failures/5/correct/', {reason: '误报：指标恢复'});
    expect(store.fetchFailures).toHaveBeenCalledWith('1');
    expect(store.fetchStatusLogs).toHaveBeenCalledWith('1');
  });

  it('executeRedoFrom：POST redo-execute（目标阶段+后续结果决定），全面刷新', async () => {
    http.post.mockResolvedValue({id: 88});
    await executeRedoFrom('1', {
      targetPhase: '备份', laterAction: 'keep', laterReason: '后续已验证有效', note: '',
    });
    expect(http.post).toHaveBeenCalledWith(
      '/api/upgrade/records/1/redo-execute/',
      {target_phase: '备份', later_action: 'keep',
       later_reason: '后续已验证有效', note: ''});
    expect(store.fetchRecordSteps).toHaveBeenCalledWith('1');
    expect(store.fetchFailures).toHaveBeenCalledWith('1');
    expect(fetchRecord).toHaveBeenCalledWith('1');
  });
});
