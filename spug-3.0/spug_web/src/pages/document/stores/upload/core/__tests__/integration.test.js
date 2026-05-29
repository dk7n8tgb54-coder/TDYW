/**
 * 状态机与 Store 协作集成测试
 * 验证状态机状态流转与实际业务逻辑的集成
 */

import { StateMachineManager } from '../StateMachineManager';
import { UploadStateMachine } from '../UploadStateMachine';

describe('状态机与 Store 协作集成测试', () => {
  let manager;
  let mockQueueStore;
  let mockTransferStore;
  let mockMd5Store;

  beforeEach(() => {
    // 创建 mock stores
    mockQueueStore = {
      findUploadItemInCurrentTenant: jest.fn(() => ({
        file: { name: 'test.txt', size: 1024 },
        fileHash: null,
        status: 'waiting',
      })),
      updateUploadItem: jest.fn(),
      pauseUpload: jest.fn(),
      resumeUpload: jest.fn(),
    };

    mockTransferStore = {
      updateTransferStatus: jest.fn(),
    };

    mockMd5Store = {
      calculateFileMD5: jest.fn().mockResolvedValue('mock-hash-123'),
    };

    // 创建状态机管理器
    manager = new StateMachineManager();
  });

  afterEach(() => {
    manager.clear();
  });

  // ============ 完整上传流程测试 ============

  describe('完整上传流程', () => {
    it('应该完成 waiting -> calculating -> uploading -> merging -> completed 全流程', () => {
      const uploadId = 'test-flow-1';

      // 创建状态机
      const machine = manager.create(uploadId, {
        queueStore: mockQueueStore,
        transferStore: mockTransferStore,
      });

      // 1. waiting -> calculating
      expect(machine.transition('START')).toBe(true);
      expect(machine.getState()).toBe('calculating');

      // 2. calculating -> uploading
      expect(machine.transition('MD5_COMPLETE', { fileHash: 'abc123' })).toBe(true);
      expect(machine.getState()).toBe('uploading');

      // 3. uploading -> merging
      expect(machine.transition('UPLOAD_COMPLETE')).toBe(true);
      expect(machine.getState()).toBe('merging');

      // 4. merging -> completed
      expect(machine.transition('MERGE_SUCCESS')).toBe(true);
      expect(machine.getState()).toBe('completed');

      // 验证历史记录
      const history = machine.getHistory();
      expect(history).toHaveLength(4);
      expect(history[0]).toMatchObject({ from: 'waiting', to: 'calculating' });
      expect(history[3]).toMatchObject({ from: 'merging', to: 'completed' });
    });

    it('应该处理 waiting -> calculating -> paused -> calculating -> uploading 流程', () => {
      const uploadId = 'test-flow-2';

      const machine = manager.create(uploadId, {
        queueStore: mockQueueStore,
      });

      // 1. 开始计算
      machine.transition('START');
      expect(machine.getState()).toBe('calculating');

      // 2. 暂停计算
      machine.transition('PAUSE');
      expect(machine.getState()).toBe('paused');

      // 3. 恢复计算（无 fileHash，回到 calculating）
      machine.transition('RESUME');
      expect(machine.getState()).toBe('calculating');

      // 4. 完成计算
      machine.transition('MD5_COMPLETE', { fileHash: 'abc123' });
      expect(machine.getState()).toBe('uploading');
    });

    it('应该处理 waiting -> calculating -> uploading -> paused -> uploading 流程', () => {
      const uploadId = 'test-flow-3';

      // 设置 fileHash 使恢复时进入 uploading
      mockQueueStore.findUploadItemInCurrentTenant = jest.fn(() => ({
        file: { name: 'test.txt' },
        fileHash: 'abc123',
      }));

      const machine = manager.create(uploadId, {
        queueStore: mockQueueStore,
      });

      // 1. 开始
      machine.transition('START');
      machine.transition('MD5_COMPLETE');
      expect(machine.getState()).toBe('uploading');

      // 2. 暂停上传
      machine.transition('PAUSE');
      expect(machine.getState()).toBe('paused');

      // 3. 恢复上传（有 fileHash，回到 uploading）
      machine.transition('RESUME');
      expect(machine.getState()).toBe('uploading');
    });
  });

  // ============ 暂停/恢复场景测试 ============

  describe('暂停/恢复场景', () => {
    it('应该在 calculating 状态正确暂停和恢复', () => {
      const uploadId = 'test-pause-1';
      const machine = manager.create(uploadId, {
        queueStore: mockQueueStore,
      });

      // 启动
      machine.transition('START');
      expect(machine.getState()).toBe('calculating');

      // 暂停
      machine.transition('PAUSE');
      expect(machine.getState()).toBe('paused');

      // 验证 updateUploadItem 被调用（暂停时更新状态）
      expect(mockQueueStore.updateUploadItem).toHaveBeenCalledWith(
        uploadId,
        expect.objectContaining({ status: 'paused' })
      );

      // 恢复
      machine.transition('RESUME');
      expect(machine.getState()).toBe('calculating');
    });

    it('应该在 uploading 状态正确暂停和恢复', () => {
      const uploadId = 'test-pause-2';

      // 有 fileHash
      mockQueueStore.findUploadItemInCurrentTenant = jest.fn(() => ({
        file: { name: 'test.txt' },
        fileHash: 'abc123',
      }));

      const machine = manager.create(uploadId, {
        queueStore: mockQueueStore,
      });

      // 进入 uploading
      machine.transition('START');
      machine.transition('MD5_COMPLETE');
      expect(machine.getState()).toBe('uploading');

      // 暂停
      machine.transition('PAUSE');
      expect(machine.getState()).toBe('paused');

      // 恢复
      machine.transition('RESUME');
      expect(machine.getState()).toBe('uploading');
    });

    it('批量暂停应该暂停所有可暂停的任务', () => {
      const ids = ['batch-1', 'batch-2', 'batch-3'];

      // 创建并启动多个状态机
      ids.forEach((id) => {
        const machine = manager.create(id, { queueStore: mockQueueStore });
        machine.transition('START');
      });

      // 批量暂停
      const results = manager.batchPause();

      expect(results).toHaveLength(3);
      expect(results.every((r) => r.success)).toBe(true);

      // 验证都暂停了
      ids.forEach((id) => {
        expect(manager.get(id).getState()).toBe('paused');
      });
    });

    it('批量恢复应该根据 fileHash 决定目标状态', () => {
      // 创建3个状态机，2个有 fileHash，1个没有
      const machine1 = manager.create('resume-1', {
        queueStore: {
          findUploadItemInCurrentTenant: () => ({ file: {}, fileHash: 'hash1' }),
          updateUploadItem: jest.fn(),
        },
      });
      const machine2 = manager.create('resume-2', {
        queueStore: {
          findUploadItemInCurrentTenant: () => ({ file: {}, fileHash: 'hash2' }),
          updateUploadItem: jest.fn(),
        },
      });
      const machine3 = manager.create('resume-3', {
        queueStore: {
          findUploadItemInCurrentTenant: () => ({ file: {} }), // 无 fileHash
          updateUploadItem: jest.fn(),
        },
      });

      // 都暂停
      machine1.transition('START');
      machine1.transition('PAUSE');
      machine2.transition('START');
      machine2.transition('PAUSE');
      machine3.transition('START');
      machine3.transition('PAUSE');

      // 批量恢复
      const results = manager.batchResume();

      // 验证结果
      expect(manager.get('resume-1').getState()).toBe('uploading');
      expect(manager.get('resume-2').getState()).toBe('uploading');
      expect(manager.get('resume-3').getState()).toBe('calculating');
    });
  });

  // ============ 错误处理测试 ============

  describe('错误处理', () => {
    it('calculating 状态遇到错误应该转到 error', () => {
      const uploadId = 'test-error-1';
      const machine = manager.create(uploadId, {
        queueStore: mockQueueStore,
      });

      machine.transition('START');
      expect(machine.getState()).toBe('calculating');

      // 触发错误
      const error = new Error('MD5 计算失败');
      machine.transition('ERROR', { error });
      expect(machine.getState()).toBe('error');

      // 验证历史记录包含错误信息
      const history = machine.getHistory();
      expect(history[1].payload.error).toBe(error);
    });

    it('uploading 状态遇到错误应该转到 error', () => {
      const uploadId = 'test-error-2';
      const machine = manager.create(uploadId, {
        queueStore: mockQueueStore,
      });

      machine.transition('START');
      machine.transition('MD5_COMPLETE');
      expect(machine.getState()).toBe('uploading');

      // 触发错误
      machine.transition('ERROR', { error: new Error('上传失败') });
      expect(machine.getState()).toBe('error');
    });

    it('error 状态可以重试回到 waiting', () => {
      const uploadId = 'test-retry-1';
      const machine = manager.create(uploadId, {
        queueStore: mockQueueStore,
      });

      // 进入错误状态
      machine.transition('START');
      machine.transition('ERROR', { error: new Error('失败') });
      expect(machine.getState()).toBe('error');

      // 重试
      machine.transition('RESUME');
      expect(machine.getState()).toBe('waiting');
    });

    it('merging 状态遇到错误应该转到 error', () => {
      const uploadId = 'test-error-3';
      const machine = manager.create(uploadId, {
        queueStore: mockQueueStore,
      });

      machine.transition('START');
      machine.transition('MD5_COMPLETE');
      machine.transition('UPLOAD_COMPLETE');
      expect(machine.getState()).toBe('merging');

      // 合并失败
      machine.transition('ERROR', { error: new Error('合并失败') });
      expect(machine.getState()).toBe('error');
    });
  });

  // ============ 取消操作测试 ============

  describe('取消操作', () => {
    it('应该在 paused 状态取消任务', () => {
      const uploadId = 'test-cancel-1';
      const mockUpdateItem = jest.fn();

      const machine = manager.create(uploadId, {
        queueStore: {
          ...mockQueueStore,
          updateUploadItem: mockUpdateItem,
        },
      });

      machine.transition('START');
      machine.transition('PAUSE');
      expect(machine.getState()).toBe('paused');

      // 取消
      machine.transition('CANCEL');
      expect(machine.getState()).toBe('error');
    });

    it('批量取消应该取消所有 paused 状态的任务', () => {
      const ids = ['cancel-1', 'cancel-2', 'cancel-3'];

      ids.forEach((id) => {
        const machine = manager.create(id, { queueStore: mockQueueStore });
        machine.transition('START');
        machine.transition('PAUSE');
      });

      // 批量取消
      const results = manager.batchCancel();

      expect(results.filter((r) => r.success).length).toBe(3);
      ids.forEach((id) => {
        expect(manager.get(id).getState()).toBe('error');
      });
    });
  });

  // ============ 全局监听器测试 ============

  describe('全局监听器', () => {
    it('全局监听器应该收到所有状态变更通知', async () => {
      const listener = jest.fn();
      manager.addGlobalListener(listener);

      const machine = manager.create('listener-test', {
        queueStore: mockQueueStore,
      });

      machine.transition('START');

      // 等待微任务执行
      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(listener).toHaveBeenCalledWith(
        'waiting',
        'calculating',
        'START',
        expect.any(Object),
        'listener-test'
      );
    });

    it('移除全局监听器后不应再收到通知', async () => {
      const listener = jest.fn();
      manager.addGlobalListener(listener);
      manager.removeGlobalListener(listener);

      const machine = manager.create('listener-test-2', {
        queueStore: mockQueueStore,
      });

      machine.transition('START');

      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(listener).not.toHaveBeenCalled();
    });
  });

  // ============ 统计和监控测试 ============

  describe('统计和监控', () => {
    it('应该正确统计各状态的数量', () => {
      // 创建不同状态的状态机
      const m1 = manager.create('stats-1', { queueStore: mockQueueStore });
      m1.transition('START'); // calculating

      const m2 = manager.create('stats-2', { queueStore: mockQueueStore });
      m2.transition('START');
      m2.transition('PAUSE'); // paused

      const m3 = manager.create('stats-3', { queueStore: mockQueueStore });
      m3.transition('START');
      m3.transition('MD5_COMPLETE'); // uploading

      const stats = manager.getStats();

      expect(stats.total).toBe(3);
      expect(stats.byState.calculating).toBe(1);
      expect(stats.byState.paused).toBe(1);
      expect(stats.byState.uploading).toBe(1);
    });

    it('应该记录监控指标', () => {
      const machine = manager.create('metrics-test', {
        queueStore: mockQueueStore,
      });

      // 触发无效转换
      machine.transition('INVALID_EVENT');
      machine.transition('PAUSE'); // 在 waiting 状态无效

      const metrics = manager.getMetrics();

      expect(metrics.invalidTransitions).toBe(2);
    });
  });

  // ============ 清理机制测试 ============

  describe('清理机制', () => {
    it('应该清理已完成的超时任务', () => {
      // Mock Date.now()
      const baseTime = Date.now();
      let currentTime = baseTime;
      jest.spyOn(Date, 'now').mockImplementation(() => currentTime);

      const machine = manager.create('cleanup-test', {
        queueStore: mockQueueStore,
        transferStore: mockTransferStore,
      });

      // 完成任务
      machine.transition('START');
      machine.transition('MD5_COMPLETE');
      machine.transition('UPLOAD_COMPLETE');
      machine.transition('MERGE_SUCCESS');

      expect(machine.getState()).toBe('completed');

      // 前进6分钟
      currentTime = baseTime + 6 * 60 * 1000;

      // 清理
      const cleaned = manager.cleanup();

      expect(cleaned).toBe(1);
      expect(manager.get('cleanup-test')).toBeUndefined();

      Date.now.mockRestore();
    });

    it('应该清理 error 状态的超时任务', () => {
      const baseTime = Date.now();
      let currentTime = baseTime;
      jest.spyOn(Date, 'now').mockImplementation(() => currentTime);

      const machine = manager.create('cleanup-error', {
        queueStore: mockQueueStore,
      });

      machine.transition('START');
      machine.transition('ERROR', { error: new Error('失败') });

      // 前进6分钟
      currentTime = baseTime + 6 * 60 * 1000;

      const cleaned = manager.cleanup();

      expect(cleaned).toBe(1);

      Date.now.mockRestore();
    });
  });

  // ============ 边界情况测试 ============

  describe('边界情况', () => {
    it('重复创建相同ID的状态机应该返回已存在的实例', () => {
      const uploadId = 'duplicate-test';

      const machine1 = manager.create(uploadId, { queueStore: mockQueueStore });
      const machine2 = manager.create(uploadId, { queueStore: mockQueueStore });

      // 验证是同一个实例（通过比较uploadId）
      expect(machine1.uploadId).toBe(machine2.uploadId);
      expect(manager.size()).toBe(1);
    });

    it('获取不存在的状态机应该返回 undefined', () => {
      expect(manager.get('non-existent')).toBeUndefined();
    });

    it('删除不存在的状态机应该返回 false', () => {
      expect(manager.remove('non-existent')).toBe(false);
    });

    it('空管理器的统计应该返回0', () => {
      const stats = manager.getStats();

      expect(stats.total).toBe(0);
      expect(Object.keys(stats.byState)).toHaveLength(0);
    });

    it('应该处理大量状态机', () => {
      const count = 100;

      for (let i = 0; i < count; i++) {
        manager.create(`bulk-${i}`, { queueStore: mockQueueStore });
      }

      expect(manager.size()).toBe(count);

      // 批量启动
      const results = manager.batchTransition('START');
      expect(results.filter((r) => r.success).length).toBe(count);

      const stats = manager.getStats();
      expect(stats.byState.calculating).toBe(count);
    });
  });
});
