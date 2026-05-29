/**
 * 边界情况测试
 * 测试快速连续操作、异常处理、内存管理等边界情况
 */

import { UploadStateMachine } from '../UploadStateMachine';
import { StateMachineManager } from '../StateMachineManager';

describe('边界情况测试', () => {
  
  // ============ 快速连续操作测试 ============
  
  describe('快速连续操作', () => {
    let machine;
    
    beforeEach(() => {
      machine = new UploadStateMachine('test-id', {
        queueStore: {
          findUploadItemInCurrentTenant: () => ({ file: {} }),
          updateUploadItem: jest.fn()
        }
      });
    });

    it('快速连续暂停恢复', () => {
      machine.transition('START');
      
      // 快速连续操作
      machine.transition('PAUSE');
      machine.transition('RESUME');
      machine.transition('PAUSE');
      machine.transition('RESUME');
      
      // 最终状态应该是 calculating 或 uploading
      expect(['calculating', 'uploading', 'paused']).toContain(machine.getState());
    });
    
    it('快速连续相同事件', () => {
      machine.transition('START');
      machine.transition('START'); // 重复START
      machine.transition('START'); // 重复START
      
      // 应该只有一次成功
      expect(machine.getState()).toBe('calculating');
      expect(machine.getHistory().length).toBe(1);
    });
    
    it('快速切换不同状态', () => {
      machine.transition('START');
      machine.transition('PAUSE');
      machine.transition('RESUME');
      machine.transition('PAUSE');
      machine.transition('RESUME');
      machine.transition('PAUSE');
      
      // 历史记录应该有相应数量
      expect(machine.getHistory().length).toBeGreaterThanOrEqual(3);
    });
  });

  // ============ 异常处理测试 ============
  
  describe('异常处理', () => {
    it('守卫条件异常不应影响状态机', () => {
      const machine = new UploadStateMachine('test-id', {});
      
      machine.canStart = () => {
        throw new Error('Guard error');
      };
      
      // 转换应该失败，但不抛出异常
      expect(() => machine.transition('START')).not.toThrow();
      expect(machine.getState()).toBe('waiting');
    });
    
    it('无效转换不应抛出异常', () => {
      const machine = new UploadStateMachine('test-id', {});
      
      // 无效转换应该返回 false 但不抛出异常
      expect(() => machine.transition('INVALID_EVENT')).not.toThrow();
      expect(machine.transition('INVALID_EVENT')).toBe(false);
    });
  });

  // ============ 内存管理测试 ============
  
  describe('内存管理', () => {
    it('清理后应释放引用', () => {
      const manager = new StateMachineManager();
      const largeData = new Array(1000).fill('x');
      
      manager.create('id1', { largeData });
      
      // 获取状态机
      const machine = manager.get('id1');
      expect(machine).toBeDefined();
      expect(machine.context.largeData).toBe(largeData);
      
      // 清理
      manager.remove('id1');
      
      // 应该无法再获取
      expect(manager.get('id1')).toBeUndefined();
    });
    
    it('历史记录增长应有限制', () => {
      const machine = new UploadStateMachine('test-id', {
        queueStore: {
          findUploadItemInCurrentTenant: () => ({ file: {} }),
          updateUploadItem: jest.fn()
        }
      });
      
      machine.transition('START');
      machine.transition('PAUSE');
      machine.transition('RESUME');
      machine.transition('PAUSE');
      machine.transition('RESUME');
      
      const history = machine.getHistory();
      expect(history.length).toBe(5);
      
      // 验证历史记录格式
      history.forEach(record => {
        expect(record).toHaveProperty('from');
        expect(record).toHaveProperty('to');
        expect(record).toHaveProperty('event');
        expect(record).toHaveProperty('timestamp');
        expect(record).toHaveProperty('payload');
      });
    });
  });

  // ============ 输入边界测试 ============
  
  describe('输入边界', () => {
    let machine;
    
    beforeEach(() => {
      machine = new UploadStateMachine('test-id', {});
    });

    it('空字符串事件', () => {
      expect(machine.transition('')).toBe(false);
    });
    
    it('超长事件名', () => {
      const longEvent = 'A'.repeat(10000);
      expect(machine.transition(longEvent)).toBe(false);
    });
    
    it('特殊字符事件名', () => {
      expect(machine.transition('START\n')).toBe(false);
      expect(machine.transition('START\t')).toBe(false);
      expect(machine.transition(' START')).toBe(false);
    });
    
    it('payload 包含循环引用', () => {
      machine.context.queueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };
      
      const payload = { a: 1 };
      payload.self = payload; // 循环引用
      
      // 应该能正常处理
      expect(() => machine.transition('START', payload)).not.toThrow();
    });
  });

  // ============ 并发边界测试 ============
  
  describe('并发边界', () => {
    it('多状态机同时操作', () => {
      const manager = new StateMachineManager();
      const mockQueueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };
      
      // 创建多个状态机
      const count = 50;
      for (let i = 0; i < count; i++) {
        manager.create(`id${i}`, { queueStore: mockQueueStore });
      }
      
      // 同时启动所有状态机
      const results = manager.batchTransition('START');
      
      expect(results.length).toBe(count);
      expect(results.every(r => r.success)).toBe(true);
      
      // 验证所有状态
      const stats = manager.getStats();
      expect(stats.byState['calculating']).toBe(count);
    });
    
    it('混合操作并发', () => {
      const manager = new StateMachineManager();
      const mockQueueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };
      
      // 创建状态机并设置不同状态
      for (let i = 0; i < 20; i++) {
        const machine = manager.create(`id${i}`, { queueStore: mockQueueStore });
        if (i % 2 === 0) {
          machine.transition('START');
        }
      }
      
      // 批量暂停
      const pauseResults = manager.batchPause();
      
      // 只有 calculating 状态的才会被暂停
      expect(pauseResults.filter(r => r.success).length).toBe(10);
    });
  });

  // ============ 状态一致性测试 ============
  
  describe('状态一致性', () => {
    it('非法转换不应改变状态', () => {
      const machine = new UploadStateMachine('test-id', {});
      
      const initialState = machine.getState();
      machine.transition('INVALID_EVENT');
      
      expect(machine.getState()).toBe(initialState);
    });
    
    it('转换失败后应保持原状态可继续操作', () => {
      const machine = new UploadStateMachine('test-id', {
        queueStore: {
          findUploadItemInCurrentTenant: () => ({ file: {} }),
          updateUploadItem: jest.fn()
        }
      });
      
      // 尝试非法转换
      machine.transition('PAUSE'); // 在 waiting 状态无效
      expect(machine.getState()).toBe('waiting');
      
      // 应该仍然可以进行有效转换
      expect(machine.transition('START')).toBe(true);
      expect(machine.getState()).toBe('calculating');
    });
    
    it('历史记录不应被修改', () => {
      const machine = new UploadStateMachine('test-id', {
        queueStore: {
          findUploadItemInCurrentTenant: () => ({ file: {} }),
          updateUploadItem: jest.fn()
        }
      });
      
      machine.transition('START');
      
      const history1 = machine.getHistory();
      const history2 = machine.getHistory();
      
      // 修改返回的数组不应影响内部状态
      history1.push({ fake: true });
      
      const history3 = machine.getHistory();
      expect(history3.length).toBe(history2.length);
    });
  });

  // ============ 性能边界测试 ============
  
  describe('性能边界', () => {
    it('大量状态机创建', () => {
      const manager = new StateMachineManager();
      const startTime = Date.now();
      
      // 创建500个状态机
      for (let i = 0; i < 500; i++) {
        manager.create(`id${i}`, {});
      }
      
      const duration = Date.now() - startTime;
      
      expect(manager.size()).toBe(500);
      expect(duration).toBeLessThan(1000); // 应在1秒内完成
    });
    
    it('大量状态转换', () => {
      const manager = new StateMachineManager();
      const mockQueueStore = {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      };
      
      // 创建100个状态机
      for (let i = 0; i < 100; i++) {
        manager.create(`id${i}`, { queueStore: mockQueueStore });
      }
      
      const startTime = Date.now();
      
      // 批量转换
      manager.batchTransition('START');
      manager.batchPause();
      manager.batchResume();
      
      const duration = Date.now() - startTime;
      
      expect(duration).toBeLessThan(1000); // 应在1秒内完成
    });
  });
});
