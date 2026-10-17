/**
 * 缺陷复现测试（2026-10-04 审计）：workbenchActions 动作层。
 *
 * P1  postStepAction/deleteStep/addStep 成功后未刷新 store.record：
 *     后端步骤操作会联动主表 status（步骤打勾→已完成、加/删步骤→回退处理中），
 *     动作层只刷新步骤与列表，工作台头部状态标签继续显示旧值。
 *     期望：三个动作成功后都调用 store.fetchRecord(recordId)。
 *     （deleteStatusLog 已有此刷新，此处对齐同一契约。）
 *
 * 2026-10-15 追加（体验改造）：
 * G1  postStepAction/postNodeAction 在途守卫：同一目标相同动作请求返回前
 *     不重复提交（弱网双击防护）。
 * G2  confirmRollback：以 Modal.confirm 弹出回退影响预览（目标阶段/重置阶段/
 *     步骤数，基于真实步骤数据，口径同后端 _reset_steps_for_rollback），
 *     确认后才发起 rollback 请求。
 */
import React from 'react';
import {act} from 'react-dom/test-utils';
import ReactDOMServer from 'react-dom/server';

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
    // Modal 组件本体保留，静态 confirm 由测试 spyOn 拦截
  };
});

const {http} = require('libs');
const antd = require('antd');
const store = require('../store').default;
const {postStepAction, deleteStep, addStep, postNodeAction, confirmRollback} =
  require('../workbenchActions');

const flush = () => new Promise(resolve => setTimeout(resolve, 0));
let confirmSpy = null;

describe('缺陷复现：步骤动作后刷新主记录（P1）', () => {
  let fetchRecord;

  beforeEach(() => {
    jest.clearAllMocks();
    fetchRecord = jest.fn(() => Promise.resolve({id: 1}));
    store.fetchRecord = fetchRecord;
    store.fetchRecordSteps = jest.fn(() => Promise.resolve());
    store.fetchStatusLogs = jest.fn(() => Promise.resolve());
    store.fetchRecords = jest.fn(() => Promise.resolve());
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

  it('deleteStatusLog 已有的刷新行为保持不变（对照）', async () => {
    const {deleteStatusLog} = require('../workbenchActions');
    http.delete.mockResolvedValue({});
    deleteStatusLog('1', 99);
    await flush();
    await flush();
    expect(fetchRecord).toHaveBeenCalledWith('1');
  });
});

describe('G1：动作在途守卫（重复提交防护）', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    store.fetchRecord = jest.fn(() => Promise.resolve({id: 1}));
    store.fetchRecordSteps = jest.fn(() => Promise.resolve());
    store.fetchStatusLogs = jest.fn(() => Promise.resolve());
    store.fetchRecords = jest.fn(() => Promise.resolve());
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
    postNodeAction('1', 'pause', node);
    postNodeAction('1', 'pause', node);
    expect(http.post).toHaveBeenCalledTimes(1);
    await act(async () => {
      resolvePost({id: 9});
      await flush();
      await flush();
    });
    postNodeAction('1', 'pause', node);
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

describe('G2：confirmRollback 回退影响预览', () => {
  const NODE = {label: '备份'};

  beforeEach(() => {
    jest.clearAllMocks();
    confirmSpy = jest.spyOn(antd.Modal, 'confirm').mockImplementation(() => {});
    // 真实步骤数据：备份(2步,已完成) + 灰度发布(3步) + 无阶段步骤(1步，不受回退影响)
    store.recordSteps = [
      {id: 1, sequence: 1, phase: '备份', title: '备份数据库', status: 'completed'},
      {id: 2, sequence: 2, phase: '备份', title: '校验备份', status: 'completed'},
      {id: 3, sequence: 3, phase: '灰度发布', title: '执行脚本', status: 'pending'},
      {id: 4, sequence: 4, phase: '灰度发布', title: '更新终端', status: 'pending'},
      {id: 5, sequence: 5, phase: '灰度发布', title: '观察终端', status: 'pending'},
      {id: 6, sequence: 6, phase: '', title: '临时步骤', status: 'pending'},
    ];
    store.fetchRecordSteps = jest.fn(() => Promise.resolve());
    store.fetchRecords = jest.fn(() => Promise.resolve());
    store.fetchStatusLogs = jest.fn(() => Promise.resolve());
  });

  it('弹出确认：目标阶段/重置阶段/步骤数基于真实步骤数据', async () => {
    confirmRollback('1', NODE);
    expect(antd.Modal.confirm).toHaveBeenCalledTimes(1);
    const options = antd.Modal.confirm.mock.calls[0][0];
    expect(options.title).toBe('回退到【备份】');
    expect(options.okText).toBe('确认回退');
    expect(options.okButtonProps.danger).toBe(true);
    const html = ReactDOMServer.renderToStaticMarkup(options.content);
    expect(html).toContain('备份');
    expect(html).toContain('灰度发布');
    // 备份(2) + 灰度发布(3) = 5；无阶段步骤不计入
    expect(html).toContain('5 个步骤');
  });

  it('确认后发起 rollback 请求；阶段名在 payload.target_action', async () => {
    http.post.mockResolvedValue({id: 77});
    confirmRollback('1', NODE);
    const options = antd.Modal.confirm.mock.calls[0][0];
    await act(async () => {
      await options.onOk();
      await flush();
      await flush();
    });
    expect(http.post).toHaveBeenCalledWith(
      '/api/upgrade/records/1/status-logs/',
      expect.objectContaining({action: 'rollback', target_action: '备份'}));
    // 回退后刷新步骤清单
    expect(store.fetchRecordSteps).toHaveBeenCalledWith('1');
  });

  it('未知目标阶段退回通用文案（不崩溃）', () => {
    store.recordSteps = [];
    confirmRollback('1', NODE);
    const options = antd.Modal.confirm.mock.calls[0][0];
    expect(typeof options.content).toBe('string');
    expect(options.content).toContain('重置为待执行');
  });
});

afterEach(() => {
  if (confirmSpy) {
    confirmSpy.mockRestore();
    confirmSpy = null;
  }
});
