/**
 * UploadStateMachine 单元测试
 * 测试状态转换、守卫条件、监听器、历史记录等功能
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
      // 模拟 canStart 返回 true
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
    
    it('uploading → merging (UPLOAD_COMPLETE)', () => {
      machine.context.queueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };
      
      machine.transition('START');
      machine.transition('MD5_COMPLETE');
      expect(machine.transition('UPLOAD_COMPLETE')).toBe(true);
      expect(machine.getState()).toBe('merging');
    });
    
    it('merging → completed (MERGE_SUCCESS)', () => {
      machine.context.queueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };
      machine.context.transferStore = {
        updateTransferStatus: jest.fn()
      };
      
      machine.transition('START');
      machine.transition('MD5_COMPLETE');
      machine.transition('UPLOAD_COMPLETE');
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
    it('waiting → ? (PAUSE) [无效转换]', () => {
      expect(machine.transition('PAUSE')).toBe(false);
      expect(machine.getState()).toBe('waiting');
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
      machine.transition('UPLOAD_COMPLETE');
      machine.transition('MERGE_SUCCESS');
      
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

    it('RESUME 无 fileHash 时应到 calculating', () => {
      // 设置无 fileHash
      machine.context.queueStore.findUploadItemInCurrentTenant.mockReturnValue({});
      
      machine.transition('RESUME');
      expect(machine.getState()).toBe('calculating');
    });
    
    it('RESUME 有 fileHash 时应到 uploading', () => {
      // 设置有 fileHash
      machine.context.queueStore.findUploadItemInCurrentTenant.mockReturnValue({ 
        fileHash: 'abc123' 
      });
      
      machine.transition('RESUME');
      expect(machine.getState()).toBe('uploading');
    });
    
    it('forceRecalculateMD5=true 时应重新计算', () => {
      // 设置有 fileHash 但强制重新计算
      machine.context.queueStore.findUploadItemInCurrentTenant.mockReturnValue({ 
        fileHash: 'abc123',
        forceRecalculateMD5: true
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
      
      // 等待微任务执行
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
      
      // 等待微任务执行
      await new Promise(resolve => setTimeout(resolve, 10));
      
      expect(listener1).toHaveBeenCalled();
      expect(listener2).toHaveBeenCalled();
    });
    
    it('返回的取消函数可以移除监听器', async () => {
      const listener = jest.fn();
      const unsubscribe = machine.addListener(listener);
      
      unsubscribe();
      machine.transition('START');
      
      // 等待微任务执行
      await new Promise(resolve => setTimeout(resolve, 10));
      
      expect(listener).not.toHaveBeenCalled();
    });
    
    it('监听器异常不应影响状态转换', () => {
      machine.addListener(() => {
        throw new Error('监听器错误');
      });
      
      // 应该正常转换，不被监听器异常影响
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
      expect(machine.canTransition('PAUSE')).toBe(false);
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
    it('应更新白名单内的字段', () => {
      machine.updateContext({ fileHash: 'abc123', percent: 50 });
      
      expect(machine.context.fileHash).toBe('abc123');
      expect(machine.context.percent).toBe(50);
    });
    
    it('不应更新白名单外的字段', () => {
      machine.updateContext({ fileHash: 'abc123', maliciousField: 'bad' });
      
      expect(machine.context.fileHash).toBe('abc123');
      expect(machine.context.maliciousField).toBeUndefined();
    });
    
    it('应验证 fileHash 类型', () => {
      const consoleSpy = jest.spyOn(console, 'error').mockImplementation();
      
      machine.updateContext({ fileHash: 123 });
      
      expect(machine.context.fileHash).toBeUndefined();
      expect(consoleSpy).toHaveBeenCalled();
      
      consoleSpy.mockRestore();
    });
    
    it('应验证 percent 范围和类型', () => {
      const consoleSpy = jest.spyOn(console, 'error').mockImplementation();
      
      machine.updateContext({ percent: -10 });
      expect(machine.context.percent).toBeUndefined();
      
      machine.updateContext({ percent: 150 });
      expect(machine.context.percent).toBeUndefined();
      
      machine.updateContext({ percent: '50' });
      expect(machine.context.percent).toBeUndefined();
      
      expect(consoleSpy).toHaveBeenCalledTimes(3);
      consoleSpy.mockRestore();
    });
    
    it('应验证 error 类型', () => {
      const consoleSpy = jest.spyOn(console, 'error').mockImplementation();
      
      machine.updateContext({ error: new Error('test') });
      expect(machine.context.error).toBeUndefined();
      
      consoleSpy.mockRestore();
    });
    
    it('应验证 chunkIndex 类型', () => {
      const consoleSpy = jest.spyOn(console, 'error').mockImplementation();
      
      machine.updateContext({ chunkIndex: -1 });
      expect(machine.context.chunkIndex).toBeUndefined();
      
      machine.updateContext({ chunkIndex: 1.5 });
      expect(machine.context.chunkIndex).toBeUndefined();
      
      consoleSpy.mockRestore();
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
      
      // 失败因为守卫条件不满足
      machine.context.queueStore = {
        findUploadItemInCurrentTenant: () => null
      };
      machine.transition('START');
      
      expect(metrics.totalTransitions).toBe(0);
    });
  });
});
