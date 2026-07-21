/**
 * UploadStateMachine 单元测试
 * 测试状态转换、守卫条件、监听器、历史记录等功能
 *
 * 更新 2026-07-19：同步业务代码变更
 * - uploading + UPLOAD_COMPLETE：小文件(无totalChunks)→completed，大文件(totalChunks>1)→merging
 * - waiting 允许 PAUSE→paused
 * - RESUME 守卫优先级：shouldResumeWaiting(无file或wasWaiting+无fileHash) > shouldRecalculateMD5 > shouldResumeUpload
 * - updateContext 简化为直接合并（无白名单过滤/类型验证）
 */

import { UploadStateMachine } from '../UploadStateMachine';

describe('UploadStateMachine', () => {
  let machine;

  beforeEach(() => {
    machine = new UploadStateMachine('test-id', {});
  });

  afterEach(() => {
    machine = null;
  });

  // ============ 基础状态转换测试 ============

  describe('基础状态转换', () => {
    it('初始状态应为 waiting', () => {
      expect(machine.getState()).toBe('waiting');
    });

    it('waiting → calculating (START)', () => {
      machine.context.queueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {}, isCancelledByUser: false }),
        updateUploadItem: jest.fn()
      };

      expect(machine.transition('START')).toBe(true);
      expect(machine.getState()).toBe('calculating');
    });

    it('calculating → uploading (MD5_COMPLETE)', () => {
      machine.context.queueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };

      machine.transition('START');
      expect(machine.transition('MD5_COMPLETE')).toBe(true);
      expect(machine.getState()).toBe('uploading');
    });

    it('calculating → paused (PAUSE)', () => {
      machine.context.queueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };

      machine.transition('START');
      expect(machine.transition('PAUSE')).toBe(true);
      expect(machine.getState()).toBe('paused');
    });

    it('uploading → completed (UPLOAD_COMPLETE, 小文件直接完成)', () => {
      // 默认 mock item 无 totalChunks → isNormalUpload=true → completed
      machine.context.queueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };

      machine.transition('START');
      machine.transition('MD5_COMPLETE');
      expect(machine.transition('UPLOAD_COMPLETE')).toBe(true);
      expect(machine.getState()).toBe('completed');
    });

    it('uploading → merging → completed (分片上传)', () => {
      // 分片上传：totalChunks>1 → isChunkedUpload → merging → MERGE_SUCCESS → completed
      machine.context.queueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {}, totalChunks: 2 }),
        updateUploadItem: jest.fn()
      };
      machine.context.transferStore = {
        updateTransferStatus: jest.fn()
      };

      machine.transition('START');
      machine.transition('MD5_COMPLETE');
      expect(machine.transition('UPLOAD_COMPLETE')).toBe(true);
      expect(machine.getState()).toBe('merging');

      expect(machine.transition('MERGE_SUCCESS')).toBe(true);
      expect(machine.getState()).toBe('completed');
    });

    it('uploading → error (ERROR)', () => {
      machine.context.queueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };

      machine.transition('START');
      machine.transition('MD5_COMPLETE');
      expect(machine.transition('ERROR', { error: new Error('上传失败') })).toBe(true);
      expect(machine.getState()).toBe('error');
    });

    it('error → waiting (RESUME重试)', () => {
      machine.context.queueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };

      machine.transition('START');
      machine.transition('ERROR', { error: new Error('上传失败') });
      expect(machine.transition('RESUME')).toBe(true);
      expect(machine.getState()).toBe('waiting');
    });
  });

  // ============ 无效状态转换测试 ============

  describe('无效状态转换', () => {
    it('waiting → paused (PAUSE) [有效转换]', () => {
      // 业务代码允许 waiting → PAUSE → paused
      expect(machine.transition('PAUSE')).toBe(true);
      expect(machine.getState()).toBe('paused');
    });

    it('waiting → ? (START) [守卫条件不满足]', () => {
      // canStart 返回 false
      machine.context.queueStore = {
        findUploadItemInCurrentTenant: () => null
      };

      expect(machine.transition('START')).toBe(false);
      expect(machine.getState()).toBe('waiting');
    });

    it('calculating → ? (START) [重复START]', () => {
      machine.context.queueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };

      machine.transition('START');
      expect(machine.transition('START')).toBe(false);
      expect(machine.getState()).toBe('calculating');
    });

    it('completed → ? [终态无转换]', () => {
      machine.context.queueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };
      machine.context.transferStore = {
        updateTransferStatus: jest.fn()
      };

      machine.transition('START');
      machine.transition('MD5_COMPLETE');
      machine.transition('UPLOAD_COMPLETE');  // 小文件直接 completed

      expect(machine.getState()).toBe('completed');
      expect(machine.transition('PAUSE')).toBe(false);
      expect(machine.transition('ERROR')).toBe(false);
    });
  });

  // ============ 守卫条件测试 ============

  describe('守卫条件', () => {
    beforeEach(() => {
      machine.context.queueStore = {
        findUploadItemInCurrentTenant: jest.fn(() => ({ file: {} })),
        updateUploadItem: jest.fn()
      };
      // 先进入 calculating 状态
      machine.transition('START');
      // 再进入 paused 状态
      machine.transition('PAUSE');
      // 验证初始状态
      expect(machine.getState()).toBe('paused');
    });

    it('RESUME 无 fileHash 时回到 waiting', () => {
      // item 有 file 但无 fileHash → shouldResumeWaiting: wasWaiting+无fileHash+非merging → true → waiting
      machine.context.queueStore.findUploadItemInCurrentTenant.mockReturnValue({ file: {} });

      machine.transition('RESUME');
      expect(machine.getState()).toBe('waiting');
    });

    it('RESUME 有 fileHash 时应到 uploading', () => {
      // item 有 file + fileHash → shouldResumeWaiting: hasFileHash=true → false
      // → shouldRecalculateMD5: 无 fileSize → false → shouldResumeUpload: 有 fileHash → true → uploading
      machine.context.queueStore.findUploadItemInCurrentTenant.mockReturnValue({
        file: {},
        fileHash: 'abc123'
      });

      machine.transition('RESUME');
      expect(machine.getState()).toBe('uploading');
    });

    it('forceRecalculateMD5=true 时应重新计算', () => {
      // item 有 file + fileHash + forceRecalculateMD5 + fileSize>=32MB
      // → shouldResumeWaiting: hasFileHash=true → false
      // → shouldRecalculateMD5: fileSize>=32MB + forceRecalculateMD5 → true → calculating
      machine.context.queueStore.findUploadItemInCurrentTenant.mockReturnValue({
        file: {},
        fileHash: 'abc123',
        forceRecalculateMD5: true,
        fileSize: 100 * 1024 * 1024  // 100MB > 32MB
      });

      machine.transition('RESUME');
      expect(machine.getState()).toBe('calculating');
    });
  });

  // ============ 监听器测试 ============

  describe('监听器', () => {
    beforeEach(() => {
      machine.context.queueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };
    });

    it('状态变更时通知监听器', async () => {
      const listener = jest.fn();

      machine.addListener(listener);
      machine.transition('START');

      await new Promise(resolve => setTimeout(resolve, 10));

      expect(listener).toHaveBeenCalledWith(
        'waiting', 'calculating', 'START', expect.any(Object), 'test-id'
      );
    });

    it('可以添加多个监听器', async () => {
      const listener1 = jest.fn();
      const listener2 = jest.fn();

      machine.addListener(listener1);
      machine.addListener(listener2);

      machine.transition('START');

      await new Promise(resolve => setTimeout(resolve, 10));

      expect(listener1).toHaveBeenCalled();
      expect(listener2).toHaveBeenCalled();
    });

    it('返回的取消函数可以移除监听器', async () => {
      const listener = jest.fn();
      const unsubscribe = machine.addListener(listener);

      unsubscribe();
      machine.transition('START');

      await new Promise(resolve => setTimeout(resolve, 10));

      expect(listener).not.toHaveBeenCalled();
    });

    it('监听器异常不应影响状态转换', () => {
      machine.addListener(() => {
        throw new Error('监听器错误');
      });

      expect(machine.transition('START')).toBe(true);
      expect(machine.getState()).toBe('calculating');
    });
  });

  // ============ 历史记录测试 ============

  describe('历史记录', () => {
    beforeEach(() => {
      machine.context.queueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };
    });

    it('记录状态历史', () => {
      machine.transition('START');
      machine.transition('MD5_COMPLETE');
      machine.transition('UPLOAD_COMPLETE');

      const history = machine.getHistory();
      expect(history).toHaveLength(3);
      expect(history[0].from).toBe('waiting');
      expect(history[0].to).toBe('calculating');
      expect(history[0].event).toBe('START');
      expect(history[0].timestamp).toBeGreaterThan(0);
    });

    it('历史记录应包含payload', () => {
      const payload = { fileHash: 'abc123' };
      machine.transition('START');
      machine.transition('MD5_COMPLETE', payload);

      const history = machine.getHistory();
      expect(history[1].payload).toEqual(payload);
    });

    it('getHistory 返回的是副本', () => {
      machine.transition('START');

      const history1 = machine.getHistory();
      const history2 = machine.getHistory();

      expect(history1).not.toBe(history2);
      expect(history1).toEqual(history2);
    });
  });

  // ============ canTransition 测试 ============

  describe('canTransition', () => {
    it('应正确判断可转换性', () => {
      machine.context.queueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} })
      };

      expect(machine.canTransition('START')).toBe(true);
      expect(machine.canTransition('PAUSE')).toBe(true);  // waiting 允许 PAUSE
      expect(machine.canTransition('ERROR')).toBe(false);
    });
  });

  // ============ isInState 测试 ============

  describe('isInState', () => {
    it('应正确判断当前状态', () => {
      expect(machine.isInState('waiting')).toBe(true);
      expect(machine.isInState('calculating')).toBe(false);
    });
  });

  // ============ 输入验证测试 ============

  describe('输入验证', () => {
    it('event 必须为字符串', () => {
      expect(machine.transition(null)).toBe(false);
      expect(machine.transition(123)).toBe(false);
      expect(machine.transition({})).toBe(false);
      expect(machine.transition('')).toBe(false);
      expect(machine.getState()).toBe('waiting');
    });

    it('payload 必须为对象', () => {
      machine.context.queueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} })
      };

      expect(machine.transition('START', null)).toBe(false);
      expect(machine.transition('START', 'string')).toBe(false);
      expect(machine.transition('START', 123)).toBe(false);
    });
  });

  // ============ updateContext 测试 ============

  describe('updateContext', () => {
    it('应更新字段', () => {
      machine.updateContext({ fileHash: 'abc123', percent: 50 });

      expect(machine.context.fileHash).toBe('abc123');
      expect(machine.context.percent).toBe(50);
    });

    it('直接合并所有字段（无白名单过滤）', () => {
      // 业务代码简化：updateContext 直接 { ...context, ...updates }，不做字段过滤
      machine.updateContext({ fileHash: 'abc123', maliciousField: 'bad' });

      expect(machine.context.fileHash).toBe('abc123');
      expect(machine.context.maliciousField).toBe('bad');
    });
  });

  // ============ 监控指标测试 ============

  describe('监控指标', () => {
    it('应记录非法转换次数', () => {
      const metrics = { invalidTransitions: 0, totalTransitions: 0, hookErrors: 0 };
      machine.context.metrics = metrics;

      machine.transition('INVALID_EVENT');

      expect(metrics.invalidTransitions).toBe(1);
    });

    it('应记录总转换次数', () => {
      const metrics = { invalidTransitions: 0, totalTransitions: 0, hookErrors: 0 };
      machine.context.metrics = metrics;
      machine.context.queueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };

      machine.transition('START');
      expect(metrics.totalTransitions).toBe(1);

      machine.transition('MD5_COMPLETE');
      expect(metrics.totalTransitions).toBe(2);
    });

    it('失败转换不应计入总次数', () => {
      const metrics = { invalidTransitions: 0, totalTransitions: 0, hookErrors: 0 };
      machine.context.metrics = metrics;

      machine.context.queueStore = {
        findUploadItemInCurrentTenant: () => null
      };
      machine.transition('START');

      expect(metrics.totalTransitions).toBe(0);
    });
  });
});
