/**
 * StateMachineManager 单元测试
 * 测试状态机生命周期、批量操作、清理机制、监控指标等功能
 */

import { StateMachineManager } from '../StateMachineManager';
import { UploadStateMachine } from '../UploadStateMachine';

describe('StateMachineManager', () => {
  let manager;
  
  beforeEach(() => {
    manager = new StateMachineManager();
  });
  
  afterEach(() => {
    manager.clear();
    manager = null;
  });

  // ============ 生命周期测试 ============
  
  describe('生命周期', () => {
    it('创建和获取状态机', () => {
      const machine = manager.create('id1', {});
      
      expect(machine).toBeInstanceOf(UploadStateMachine);
      expect(manager.get('id1')).toBe(machine);
    });
    
    it('创建时自动注入 metrics', () => {
      const machine = manager.create('id1', {});
      
      expect(machine.context.metrics).toBe(manager.metrics);
    });
    
    it('删除状态机', () => {
      manager.create('id1', {});
      const result = manager.remove('id1');
      
      expect(result).toBe(true);
      expect(manager.get('id1')).toBeUndefined();
    });
    
    it('删除不存在的状态机返回 false', () => {
      const result = manager.remove('non-existent');
      
      expect(result).toBe(false);
    });
    
    it('获取状态机数量', () => {
      manager.create('id1', {});
      manager.create('id2', {});
      
      expect(manager.size()).toBe(2);
    });
  });

  // ============ 全局监听器测试 ============
  
  describe('全局监听器', () => {
    it('添加全局监听器', () => {
      const listener = jest.fn();
      manager.addGlobalListener(listener);
      
      expect(manager.globalListeners.has(listener)).toBe(true);
    });
    
    it('非函数监听器应被拒绝', () => {
      const consoleSpy = jest.spyOn(console, 'error').mockImplementation();
      
      manager.addGlobalListener('not a function');
      
      expect(consoleSpy).toHaveBeenCalled();
      consoleSpy.mockRestore();
    });
    
    it('新创建的状态机应自动添加全局监听器', async () => {
      const listener = jest.fn();
      manager.addGlobalListener(listener);
      
      const machine = manager.create('id1', {
        queueStore: {
          findUploadItemInCurrentTenant: () => ({ file: {} }),
          updateUploadItem: jest.fn()
        }
      });
      
      machine.transition('START');
      
      // 等待微任务执行
      await new Promise(resolve => setTimeout(resolve, 10));
      
      expect(listener).toHaveBeenCalled();
    });
    
    it('可以移除全局监听器', () => {
      const listener = jest.fn();
      manager.addGlobalListener(listener);
      manager.removeGlobalListener(listener);
      
      expect(manager.globalListeners.has(listener)).toBe(false);
    });
  });

  // ============ 批量操作测试 ============
  
  describe('批量操作', () => {
    beforeEach(() => {
      // 【P0修复 2026-06-27】mock item 包含 totalChunks: 5，
      // 使 isChunkedUpload 守卫返回 true，UPLOAD_COMPLETE → merging 而非 completed
      const mockQueueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {}, totalChunks: 5 }),
        updateUploadItem: jest.fn()
      };

      manager.create('id1', { queueStore: mockQueueStore });
      manager.create('id2', { queueStore: mockQueueStore });
    });

    it('批量转换', () => {
      const results = manager.batchTransition('START');

      expect(results).toHaveLength(2);
      expect(results.every(r => r.success)).toBe(true);
      expect(results[0].uploadId).toBe('id1');
      expect(results[1].uploadId).toBe('id2');
    });

    it('批量转换带过滤', () => {
      // 第一个状态机转换到 calculating
      manager.get('id1').transition('START');
      // id2 转到终态，不可 PAUSE
      manager.get('id2').transition('CANCEL');

      // 只过滤可以 PAUSE 的状态机（batchTransition 已跳过终态）
      const results = manager.batchTransition('PAUSE',
        (machine) => machine.canTransition('PAUSE')
      );

      expect(results).toHaveLength(1);
      expect(results[0].uploadId).toBe('id1');
    });

    it('批量暂停', () => {
      manager.get('id1').transition('START');
      manager.get('id2').transition('START');

      const results = manager.batchPause();

      expect(results).toHaveLength(2);
      expect(results.every(r => r.success)).toBe(true);
      expect(manager.get('id1').getState()).toBe('paused');
      expect(manager.get('id2').getState()).toBe('paused');
    });

    it('批量恢复', () => {
      manager.get('id1').transition('START');
      manager.get('id1').transition('PAUSE');
      // id2 转到终态，不可恢复
      manager.get('id2').transition('CANCEL');

      const results = manager.batchResume();

      expect(results.filter(r => r.success)).toHaveLength(1);
    });

    it('批量取消', () => {
      manager.get('id1').transition('START');
      manager.get('id1').transition('PAUSE');
      // id2 转到终态，batchCancel 已跳过终态
      manager.get('id2').transition('CANCEL');

      const results = manager.batchCancel();

      expect(results.filter(r => r.success)).toHaveLength(1);
      expect(manager.get('id1').getState()).toBe('cancelled');
    });

    it('批量暂停应跳过合并中任务', () => {
      manager.get('id1').transition('START');
      manager.get('id1').transition('MD5_COMPLETE');
      manager.get('id1').transition('UPLOAD_COMPLETE');
      expect(manager.get('id1').getState()).toBe('merging');

      const results = manager.batchPause();

      expect(results.find(r => r.uploadId === 'id1')).toBeUndefined();
      expect(manager.get('id1').getState()).toBe('merging');
    });

    it('单个取消和批量取消状态语义一致（均进入 cancelled）', () => {
      const mockQueueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };

      // 创建两个状态机：一个走单个 CANCEL，一个走 batchCancel
      manager.create('single', { queueStore: mockQueueStore });
      manager.create('batch', { queueStore: mockQueueStore });

      // 单个取消
      manager.get('single').transition('START');
      expect(manager.get('single').canTransition('CANCEL')).toBe(true);
      manager.get('single').transition('CANCEL');
      expect(manager.get('single').getState()).toBe('cancelled');

      // 批量取消
      manager.get('batch').transition('START');
      const batchResults = manager.batchCancel();
      expect(batchResults.find(r => r.uploadId === 'batch')).toBeDefined();
      expect(manager.get('batch').getState()).toBe('cancelled');

      // 两者最终状态一致
      expect(manager.get('single').getState()).toBe(manager.get('batch').getState());
    });

    it('RETRY_MERGE 事件从 error 状态进入 merging', () => {
      const mockQueueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };
      manager.create('retry-merge', { queueStore: mockQueueStore });

      // 走到 error 状态
      manager.get('retry-merge').transition('START');
      manager.get('retry-merge').transition('ERROR', { error: '合并失败' });
      expect(manager.get('retry-merge').getState()).toBe('error');

      // RETRY_MERGE 应能转换到 merging
      expect(manager.get('retry-merge').canTransition('RETRY_MERGE')).toBe(true);
      manager.get('retry-merge').transition('RETRY_MERGE');
      expect(manager.get('retry-merge').getState()).toBe('merging');
    });

    it('RETRY_MERGE 事件从 waiting 状态进入 merging', () => {
      const mockQueueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };
      manager.create('retry-merge-waiting', { queueStore: mockQueueStore });

      // waiting 状态下直接 RETRY_MERGE（模拟状态机重建后快捷重试合并）
      expect(manager.get('retry-merge-waiting').canTransition('RETRY_MERGE')).toBe(true);
      manager.get('retry-merge-waiting').transition('RETRY_MERGE');
      expect(manager.get('retry-merge-waiting').getState()).toBe('merging');
    });

    it('批量取消后状态为 cancelled', () => {
      const mockQueueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };
      manager.create('cancel-1', { queueStore: mockQueueStore });
      manager.create('cancel-2', { queueStore: mockQueueStore });

      manager.get('cancel-1').transition('START');
      manager.get('cancel-2').transition('START');

      const results = manager.batchCancel();

      expect(results.every(r => r.success)).toBe(true);
      expect(manager.get('cancel-1').getState()).toBe('cancelled');
      expect(manager.get('cancel-2').getState()).toBe('cancelled');
    });

    it('批量取消不会被错误恢复（completed/error/cancelled/merging 跳过）', () => {
      const mockQueueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {}, totalChunks: 5 }),
        updateUploadItem: jest.fn()
      };
      // completed（普通上传：START → MD5_COMPLETE → UPLOAD_COMPLETE → completed）
      // 注意：totalChunks=5 时 isChunkedUpload 返回 true，UPLOAD_COMPLETE → merging
      // 要走到 completed 需要 totalChunks=1（普通上传）
      const mockQueueStoreNormal = {
        findUploadItemInCurrentTenant: () => ({ file: {}, totalChunks: 1 }),
        updateUploadItem: jest.fn()
      };
      manager.create('done', { queueStore: mockQueueStoreNormal });
      manager.get('done').transition('START');
      manager.get('done').transition('MD5_COMPLETE');
      manager.get('done').transition('UPLOAD_COMPLETE');
      expect(manager.get('done').getState()).toBe('completed');

      // cancelled
      manager.create('canceled', { queueStore: mockQueueStore });
      manager.get('canceled').transition('CANCEL');

      // merging
      manager.create('merging-one', { queueStore: mockQueueStore });
      manager.get('merging-one').transition('START');
      manager.get('merging-one').transition('MD5_COMPLETE');
      manager.get('merging-one').transition('UPLOAD_COMPLETE');
      expect(manager.get('merging-one').getState()).toBe('merging');

      // batchResume 应跳过所有终态和 merging
      const results = manager.batchResume(3, () => 0);
      const resumedIds = results.filter(r => r.success).map(r => r.uploadId);
      expect(resumedIds).not.toContain('done');
      expect(resumedIds).not.toContain('canceled');
      expect(resumedIds).not.toContain('merging-one');
      expect(manager.get('done').getState()).toBe('completed');
      expect(manager.get('canceled').getState()).toBe('cancelled');
      expect(manager.get('merging-one').getState()).toBe('merging');
    });

    it('completed 终态不会被非终态回滚', () => {
      const mockQueueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {}, totalChunks: 1 }),
        updateUploadItem: jest.fn()
      };
      manager.create('done-rollback', { queueStore: mockQueueStore });
      manager.get('done-rollback').transition('START');
      manager.get('done-rollback').transition('MD5_COMPLETE');
      manager.get('done-rollback').transition('UPLOAD_COMPLETE');
      expect(manager.get('done-rollback').getState()).toBe('completed');

      // completed 是 final 类型，无任何 transitions，无法回滚
      expect(manager.get('done-rollback').canTransition('PAUSE')).toBe(false);
      expect(manager.get('done-rollback').canTransition('START')).toBe(false);
      expect(manager.get('done-rollback').canTransition('ERROR')).toBe(false);
    });

    it('merging 状态不可暂停（canTransition PAUSE 为 false）', () => {
      const mockQueueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {}, totalChunks: 5 }),
        updateUploadItem: jest.fn()
      };
      manager.create('merging-pause', { queueStore: mockQueueStore });
      manager.get('merging-pause').transition('START');
      manager.get('merging-pause').transition('MD5_COMPLETE');
      manager.get('merging-pause').transition('UPLOAD_COMPLETE');
      expect(manager.get('merging-pause').getState()).toBe('merging');

      // merging 状态定义中无 PAUSE 转换
      expect(manager.get('merging-pause').canTransition('PAUSE')).toBe(false);
    });

    it('cancelled 终态不可 RETRY_MERGE（避免已取消任务被错误重试合并）', () => {
      const mockQueueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };
      manager.create('cancelled-no-retry', { queueStore: mockQueueStore });
      manager.get('cancelled-no-retry').transition('CANCEL');
      expect(manager.get('cancelled-no-retry').getState()).toBe('cancelled');

      // cancelled 是 final，无 RETRY_MERGE 转换
      expect(manager.get('cancelled-no-retry').canTransition('RETRY_MERGE')).toBe(false);
    });
  });

  // ============ 清理机制测试 ============
  
  describe('清理机制', () => {
    it('清理超时的已完成任务', () => {
      const mockQueueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };
      const mockTransferStore = {
        updateTransferStatus: jest.fn()
      };
      
      // Mock Date.now() 返回固定时间
      const baseTime = Date.now();
      let currentTime = baseTime;
      jest.spyOn(Date, 'now').mockImplementation(() => currentTime);
      
      manager.create('id1', { queueStore: mockQueueStore, transferStore: mockTransferStore });
      
      // 完成状态机
      manager.get('id1').transition('START');
      manager.get('id1').transition('MD5_COMPLETE');
      manager.get('id1').transition('UPLOAD_COMPLETE');
      manager.get('id1').transition('MERGE_SUCCESS');
      
      // 前进时间6分钟
      currentTime = baseTime + 6 * 60 * 1000;
      
      const cleaned = manager.cleanup();
      
      expect(cleaned).toBe(1);
      expect(manager.get('id1')).toBeUndefined();
      
      Date.now.mockRestore();
    });
    
    it('不清理未超时的任务', () => {
      const mockQueueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };
      const mockTransferStore = {
        updateTransferStatus: jest.fn()
      };
      
      // Mock Date.now()
      const baseTime = Date.now();
      let currentTime = baseTime;
      jest.spyOn(Date, 'now').mockImplementation(() => currentTime);
      
      manager.create('id1', { queueStore: mockQueueStore, transferStore: mockTransferStore });
      
      // 完成状态机
      manager.get('id1').transition('START');
      manager.get('id1').transition('MD5_COMPLETE');
      manager.get('id1').transition('UPLOAD_COMPLETE');
      manager.get('id1').transition('MERGE_SUCCESS');
      
      // 只前进1分钟
      currentTime = baseTime + 1 * 60 * 1000;
      
      const cleaned = manager.cleanup();
      
      expect(cleaned).toBe(0);
      expect(manager.get('id1')).toBeDefined();
      
      Date.now.mockRestore();
    });
    
    it('超过实例上限时自动清理最老的任务', () => {
      const mockQueueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };
      const mockTransferStore = {
        updateTransferStatus: jest.fn()
      };
      
      // Mock Date.now()
      const baseTime = Date.now();
      let currentTime = baseTime;
      jest.spyOn(Date, 'now').mockImplementation(() => currentTime);
      
      // 创建150个已完成的状态机
      for (let i = 0; i < 150; i++) {
        const machine = manager.create(`id${i}`, { 
          queueStore: mockQueueStore, 
          transferStore: mockTransferStore 
        });
        machine.transition('START');
        machine.transition('MD5_COMPLETE');
        machine.transition('UPLOAD_COMPLETE');
        machine.transition('MERGE_SUCCESS');
        
        // 每个间隔1ms，确保时间不同
        currentTime += 1;
      }
      
      expect(manager.size()).toBe(150);
      
      // 清理，设置上限为100
      const cleaned = manager.cleanup(5 * 60 * 1000, 100);
      
      expect(cleaned).toBe(50);
      expect(manager.size()).toBe(100);
      
      Date.now.mockRestore();
    });
    
    it('清理error状态的任务', () => {
      const mockQueueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };
      
      // Mock Date.now()
      const baseTime = Date.now();
      let currentTime = baseTime;
      jest.spyOn(Date, 'now').mockImplementation(() => currentTime);
      
      manager.create('id1', { queueStore: mockQueueStore });
      manager.get('id1').transition('START');
      manager.get('id1').transition('ERROR', { error: 'test error' });
      
      // 前进6分钟
      currentTime = baseTime + 6 * 60 * 1000;
      
      const cleaned = manager.cleanup();
      
      expect(cleaned).toBe(1);
      
      Date.now.mockRestore();
    });
  });

  // ============ 统计信息测试 ============
  
  describe('统计信息', () => {
    it('获取状态机统计信息', () => {
      const mockQueueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };
      
      const m1 = manager.create('id1', { queueStore: mockQueueStore });
      const m2 = manager.create('id2', { queueStore: mockQueueStore });
      
      m1.transition('START');
      m2.transition('START');
      m2.transition('PAUSE');
      
      const stats = manager.getStats();
      
      expect(stats.total).toBe(2);
      expect(stats.byState['calculating']).toBe(1);
      expect(stats.byState['paused']).toBe(1);
    });
    
    it('统计 completed 和 error 数量', () => {
      const mockQueueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };
      const mockTransferStore = {
        updateTransferStatus: jest.fn()
      };
      
      const m1 = manager.create('id1', { queueStore: mockQueueStore, transferStore: mockTransferStore });
      const m2 = manager.create('id2', { queueStore: mockQueueStore });
      
      // id1 完成
      m1.transition('START');
      m1.transition('MD5_COMPLETE');
      m1.transition('UPLOAD_COMPLETE');
      m1.transition('MERGE_SUCCESS');
      
      // id2 错误
      m2.transition('START');
      m2.transition('ERROR', { error: new Error('test') });
      
      const stats = manager.getStats();
      
      expect(stats.completed).toBe(1);
      expect(stats.error).toBe(1);
    });
  });

  // ============ 监控指标测试 ============
  
  describe('监控指标', () => {
    it('获取监控指标', () => {
      const metrics = manager.getMetrics();
      
      expect(metrics).toHaveProperty('invalidTransitions');
      expect(metrics).toHaveProperty('totalTransitions');
      expect(metrics).toHaveProperty('hookErrors');
    });
    
    it('metrics 是只读副本', () => {
      const metrics = manager.getMetrics();
      metrics.invalidTransitions = 999;
      
      expect(manager.metrics.invalidTransitions).toBe(0);
    });
    
    it('重置监控指标', () => {
      manager.metrics.invalidTransitions = 10;
      manager.metrics.totalTransitions = 20;
      manager.metrics.hookErrors = 5;
      
      manager.resetMetrics();
      
      expect(manager.metrics.invalidTransitions).toBe(0);
      expect(manager.metrics.totalTransitions).toBe(0);
      expect(manager.metrics.hookErrors).toBe(0);
    });
    
    it('状态机应共享 metrics', () => {
      const machine = manager.create('id1', {});
      
      machine.transition('INVALID_EVENT');
      
      expect(manager.getMetrics().invalidTransitions).toBe(1);
    });
  });

  // ============ 状态查询测试 ============
  
  describe('状态查询', () => {
    beforeEach(() => {
      const mockQueueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };
      
      manager.create('id1', { queueStore: mockQueueStore });
      manager.create('id2', { queueStore: mockQueueStore });
      
      manager.get('id1').transition('START');
    });

    it('检查是否存在指定状态', () => {
      expect(manager.hasState('calculating')).toBe(true);
      expect(manager.hasState('completed')).toBe(false);
    });
    
    it('获取指定状态的所有ID', () => {
      const calculatingIds = manager.getIdsByState('calculating');
      const waitingIds = manager.getIdsByState('waiting');
      
      expect(calculatingIds).toContain('id1');
      expect(waitingIds).toContain('id2');
    });
    
    it('获取所有状态机状态', () => {
      const allStates = manager.getAllStates();
      
      expect(allStates['id1'].current).toBe('calculating');
      expect(allStates['id2'].current).toBe('waiting');
      expect(allStates['id1'].history).toBeDefined();
    });
  });

  // ============ 并发测试 ============
  
  describe('并发测试', () => {
    it('并发创建100个状态机', () => {
      const machines = [];
      for (let i = 0; i < 100; i++) {
        machines.push(manager.create(`id${i}`, {}));
      }
      
      expect(manager.machines.size).toBe(100);
      expect(manager.getStats().total).toBe(100);
    });
    
    it('并发状态转换', () => {
      const mockQueueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };
      
      // 创建多个状态机
      for (let i = 0; i < 10; i++) {
        manager.create(`id${i}`, { queueStore: mockQueueStore });
      }
      
      // 并发转换
      const promises = [];
      for (let i = 0; i < 10; i++) {
        promises.push(
          Promise.resolve(manager.get(`id${i}`).transition('START'))
        );
      }
      
      return Promise.all(promises).then(results => {
        expect(results.every(r => r === true)).toBe(true);
        expect(manager.getStats().byState['calculating']).toBe(10);
      });
    });
  });

  // ============ 边界情况测试 ============
  
  describe('边界情况', () => {
    it('清空所有状态机', () => {
      manager.create('id1', {});
      manager.create('id2', {});
      
      manager.clear();
      
      expect(manager.size()).toBe(0);
    });
    
    it('清理空管理器不应报错', () => {
      expect(() => manager.cleanup()).not.toThrow();
    });
    
    it('获取不存在的状态机返回 undefined', () => {
      expect(manager.get('non-existent')).toBeUndefined();
    });
  });
});
