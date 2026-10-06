/**
 * 缺陷复现测试（2026-10-04 审计）：workbenchActions 动作层。
 *
 * P1  postStepAction/deleteStep/addStep 成功后未刷新 store.record：
 *     后端步骤操作会联动主表 status（步骤打勾→已完成、加/删步骤→回退处理中），
 *     动作层只刷新步骤与列表，工作台头部状态标签继续显示旧值。
 *     期望：三个动作成功后都调用 store.fetchRecord(recordId)。
 *     （deleteStatusLog 已有此刷新，此处对齐同一契约。）
 */
import React from 'react';

jest.mock('libs', () => ({
  http: {
    get: jest.fn(() => Promise.resolve({})),
    post: jest.fn(() => Promise.resolve({})),
    put: jest.fn(() => Promise.resolve({})),
    delete: jest.fn(() => Promise.resolve({})),
  },
  hasPermission: jest.fn(() => true),
}));

jest.mock('antd', () => ({
  ...jest.requireActual('antd'),
  message: {
    success: jest.fn(),
    error: jest.fn(),
    warning: jest.fn(),
    info: jest.fn(),
    confirm: jest.fn(),
  },
}));

const {http} = require('libs');
const store = require('../store').default;
const {postStepAction, deleteStep, addStep} = require('../workbenchActions');

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

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
