/**
 * 协作任务前端单元测试
 *
 * 1. utils.js 纯函数：分派状态聚合（与后端 compute_assignment_status 语义一致）、
 *    创建任务请求体构造（截止时间格式 / 材料去空格 / 按账号构造分发对象）
 * 2. CoopTaskBadgeStore 真实 store 行为：权限门控、拉取与计数更新、
 *    失败容错、5 分钟轮询
 */
import moment from 'moment';
import {
  TASK_STATUS_MAP,
  computeAssignmentStatus,
  buildTaskPayload,
} from '../utils';

const mockHttpGet = jest.fn();
const mockHasPermission = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: jest.fn(),
    put: jest.fn(),
    delete: jest.fn(),
  },
  hasPermission: mockHasPermission,
}));

// 模块导出的是单例 store 实例（与应用内共享同一份）
const coopTaskBadge = require('@/layout/CoopTaskBadgeStore').default;

// ============================================================
// utils.js 纯函数
// ============================================================

describe('computeAssignmentStatus（与后端 compute_assignment_status 一致）', () => {
  test('全待交付 -> pending', () => {
    expect(computeAssignmentStatus(2, 0, 0, 2)).toBe('pending');
  });

  test('无明细 -> pending', () => {
    expect(computeAssignmentStatus(0, 0, 0, 0)).toBe('pending');
  });

  test('有退回 -> rejected（优先于其他中间态）', () => {
    expect(computeAssignmentStatus(3, 1, 1, 1)).toBe('rejected');
  });

  test('全部验收 -> accepted', () => {
    expect(computeAssignmentStatus(2, 2, 0, 0)).toBe('accepted');
  });

  test('无待交付但未全验收 -> submitted（待验收）', () => {
    expect(computeAssignmentStatus(2, 1, 0, 0)).toBe('submitted');
  });

  test('部分交付 -> partial', () => {
    expect(computeAssignmentStatus(2, 0, 0, 1)).toBe('partial');
  });
});

describe('buildTaskPayload', () => {
  test('构造创建请求体：截止时间格式化、材料去空格、按账号构造分发对象', () => {
    const values = {
      title: ' 征集台账 ',
      description: '说明',
      deadline: moment('2026-09-30 18:00'),
      items: [{name: ' 工作总结 ', remark: ' Word '}, {name: '设备台账', remark: ''}],
    };
    const payload = buildTaskPayload(values, [7, 9]);
    expect(payload.title).toBe(' 征集台账 '); // title 由后端统一 strip
    expect(payload.deadline).toBe('2026-09-30 18:00:00');
    expect(payload.items[0]).toEqual({name: '工作总结', remark: 'Word'});
    expect(payload.items[1]).toEqual({name: '设备台账', remark: ''});
    expect(payload.targets[0]).toEqual({user_id: 7});
    expect(payload.targets[1]).toEqual({user_id: 9});
  });

  test('未选择交付对象时 targets 为空数组', () => {
    const payload = buildTaskPayload(
      {title: 'x', deadline: moment('2026-01-01 08:00'), items: [{name: 'a'}]},
      []);
    expect(payload.targets).toEqual([]);
  });
});

describe('TASK_STATUS_MAP 完整性', () => {
  test('后端三种任务状态均有映射', () => {
    expect(Object.keys(TASK_STATUS_MAP).sort()).toEqual(['completed', 'in_progress', 'voided']);
  });
});

// ============================================================
// CoopTaskBadgeStore 真实 store 行为
// ============================================================

describe('CoopTaskBadgeStore', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
  });

  afterEach(() => {
    coopTaskBadge.stop();
    jest.useRealTimers();
  });

  test('无 coop.task.view 权限时不拉取角标', () => {
    mockHasPermission.mockReturnValue(false);
    coopTaskBadge.start();
    expect(mockHttpGet).not.toHaveBeenCalled();
    jest.advanceTimersByTime(5 * 60 * 1000);
    expect(mockHttpGet).not.toHaveBeenCalled();
    coopTaskBadge.stop();
  });

  test('有权限时立即拉取并更新计数', async () => {
    mockHasPermission.mockReturnValue(true);
    mockHttpGet.mockResolvedValue({data: {count: 3, inbox_pending: 1, accept_pending: 2, urge_unread: 1}});
    coopTaskBadge.start();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/coop-task/badge/');
    await Promise.resolve();
    await Promise.resolve();
    expect(coopTaskBadge.loaded).toBe(true);
    expect(coopTaskBadge.count).toBe(3);
    expect(coopTaskBadge.inboxPending).toBe(1);
    expect(coopTaskBadge.acceptPending).toBe(2);
    expect(coopTaskBadge.urgeUnread).toBe(1);
    coopTaskBadge.stop();
  });

  test('拉取失败静默容错，保留旧值', async () => {
    mockHasPermission.mockReturnValue(true);
    mockHttpGet.mockResolvedValueOnce({data: {count: 5, inbox_pending: 0, accept_pending: 5, urge_unread: 0}});
    coopTaskBadge.fetch();
    await Promise.resolve();
    await Promise.resolve();
    expect(coopTaskBadge.count).toBe(5);
    mockHttpGet.mockRejectedValueOnce(new Error('network down'));
    coopTaskBadge.fetch();
    await Promise.resolve();
    await Promise.resolve();
    expect(coopTaskBadge.count).toBe(5);
    expect(coopTaskBadge.loaded).toBe(true);
  });

  test('start 后按 5 分钟轮询', async () => {
    mockHasPermission.mockReturnValue(true);
    mockHttpGet.mockResolvedValue({data: {count: 0, inbox_pending: 0, accept_pending: 0, urge_unread: 0}});
    coopTaskBadge.start();
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
    jest.advanceTimersByTime(5 * 60 * 1000);
    expect(mockHttpGet).toHaveBeenCalledTimes(2);
    jest.advanceTimersByTime(5 * 60 * 1000);
    expect(mockHttpGet).toHaveBeenCalledTimes(3);
    coopTaskBadge.stop();
    jest.advanceTimersByTime(10 * 60 * 1000);
    expect(mockHttpGet).toHaveBeenCalledTimes(3); // stop 后不再轮询
  });
});
