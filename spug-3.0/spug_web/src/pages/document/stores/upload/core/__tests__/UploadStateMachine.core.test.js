/**
 * UploadStateMachine 核心功能测试（纯状态机，无外部依赖）
 * 只测试状态转换、守卫条件、事件机制等核心功能
 */

import { UploadStateMachine } from '../UploadStateMachine';

describe('UploadStateMachine - 核心功能', () => {
  let machine;

  beforeEach(() => {
    // 创建状态机，注入mock queueStore使守卫条件通过
    machine = new UploadStateMachine('test-id', {
      queueStore: {
        findUploadItemInCurrentTenant: () => ({ file: {} }),
        updateUploadItem: jest.fn()
      }
    });
  });

  afterEach(() => {
    machine = null;
  });

  // ============ 基础状态定义测试 ============

  describe('状态定义', () => {
    it('应有7个预定义状态', () => {
      const expectedStates = ['waiting', 'calculating', 'uploading', 'paused', 'merging', 'completed', 'error'];
      expect(UploadStateMachine.STATES).toEqual(expectedStates);
    });

    it('应有预定义事件', () => {
      const expectedEvents = ['START', 'MD5_COMPLETE', 'UPLOAD_COMPLETE', 'MERGE_SUCCESS', 'PAUSE', 'RESUME', 'ERROR', 'CANCEL'];
      expect(UploadStateMachine.EVENTS).toEqual(expectedEvents);
    });

    it('初始状态为 waiting', () => {
      expect(machine.getState()).toBe('waiting');
    });

    it('能获取正确的itemId', () => {
      expect(machine.getItemId()).toBe('test-id');
    });
  });

  // ============ 状态转换测试 ============

  describe('状态转换', () => {
    it('waiting -> calculating (START)', () => {
      expect(machine.transition('START')).toBe(true);
      expect(machine.getState()).toBe('calculating');
    });
    
    it('calculating -> uploading (MD5_COMPLETE)', () => {
      machine.transition('START');
      
      expect(machine.transition('MD5_COMPLETE')).toBe(true);
      expect(machine.getState()).toBe('uploading');
    });
    
    it('calculating -> paused (PAUSE)', () => {
      machine.transition('START');
      
      expect(machine.transition('PAUSE')).toBe(true);
      expect(machine.getState()).toBe('paused');
    });
    
    it('uploading -> paused (PAUSE)', () => {
      machine.transition('START');
      machine.transition('MD5_COMPLETE');
      
      expect(machine.transition('PAUSE')).toBe(true);
      expect(machine.getState()).toBe('paused');
    });
    
    it('uploading -> merging (UPLOAD_COMPLETE)', () => {
      machine.transition('START');
      machine.transition('MD5_COMPLETE');
      
      expect(machine.transition('UPLOAD_COMPLETE')).toBe(true);
      expect(machine.getState()).toBe('merging');
    });
    
    it('merging -> completed (MERGE_SUCCESS)', () => {
      machine.transition('START');
      machine.transition('MD5_COMPLETE');
      machine.transition('UPLOAD_COMPLETE');
      
      expect(machine.transition('MERGE_SUCCESS')).toBe(true);
      expect(machine.getState()).toBe('completed');
    });
    
    it('任何状态 -> error (ERROR)', () => {
      machine.transition('START');
      
      expect(machine.transition('ERROR', { error: 'test' })).toBe(true);
      expect(machine.getState()).toBe('error');
    });
    
    it('error -> waiting (RESUME重试)', () => {
      machine.transition('START');
      machine.transition('ERROR', { error: 'test' });
      
      expect(machine.transition('RESUME')).toBe(true);
      expect(machine.getState()).toBe('waiting');
    });
  });

  // ============ 无效状态转换测试 ============

  describe('无效转换', () => {
    it('waiting不能直接PAUSE', () => {
      expect(machine.transition('PAUSE')).toBe(false);
      expect(machine.getState()).toBe('waiting');
    });
    
    it('waiting不能ERROR', () => {
      expect(machine.transition('ERROR')).toBe(false);
      expect(machine.getState()).toBe('waiting');
    });
    
    it('completed状态不能进行任何转换', () => {
      machine.transition('START');
      machine.transition('MD5_COMPLETE');
      machine.transition('UPLOAD_COMPLETE');
      machine.transition('MERGE_SUCCESS');
      
      expect(machine.getState()).toBe('completed');
      expect(machine.transition('PAUSE')).toBe(false);
      expect(machine.transition('ERROR')).toBe(false);
      expect(machine.transition('RESUME')).toBe(false);
    });
    
    it('重复START无效', () => {
      machine.transition('START');
      
      expect(machine.transition('START')).toBe(false);
      expect(machine.getState()).toBe('calculating');
    });
  });

  // ============ 守卫条件测试 ============

  describe('守卫条件', () => {
    it('START守卫返回false时转换失败', () => {
      // 创建新状态机，让canStart返回false
      const machineWithFailedGuard = new UploadStateMachine('test-id-2', {
        queueStore: {
          findUploadItemInCurrentTenant: () => null, // 返回null使守卫失败
          updateUploadItem: jest.fn()
        }
      });
      
      expect(machineWithFailedGuard.transition('START')).toBe(false);
      expect(machineWithFailedGuard.getState()).toBe('waiting');
    });
    
    it('RESUME根据context决定目标状态 - 无fileHash到calculating', () => {
      machine.transition('START');
      machine.transition('PAUSE');
      
      machine.context.fileHash = null;
      expect(machine.transition('RESUME')).toBe(true);
      expect(machine.getState()).toBe('calculating');
    });
    
    it('RESUME根据context决定目标状态 - 有fileHash到uploading', () => {
      // 先修改mock返回值，让它返回有fileHash的item
      machine.context.queueStore.findUploadItemInCurrentTenant = () => ({ 
        file: {},
        fileHash: 'abc123' 
      });
      
      machine.transition('START');
      machine.transition('PAUSE');
      
      expect(machine.transition('RESUME')).toBe(true);
      expect(machine.getState()).toBe('uploading');
    });
    
    it('RESUME强制重新计算 - forceRecalculateMD5为true到calculating', () => {
      machine.transition('START');
      machine.transition('PAUSE');
      
      machine.context.fileHash = 'abc123';
      machine.context.forceRecalculateMD5 = true;
      expect(machine.transition('RESUME')).toBe(true);
      expect(machine.getState()).toBe('calculating');
    });
  });

  // ============ 监听器测试 ============

  describe('监听器', () => {
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

    it('可以移除监听器', async () => {
      const listener = jest.fn();
      const unsubscribe = machine.addListener(listener);

      unsubscribe();
      machine.transition('START');

      await new Promise(resolve => setTimeout(resolve, 10));

      expect(listener).not.toHaveBeenCalled();
    });

    it('监听器异常不影响状态转换', () => {
      machine.addListener(() => {
        throw new Error('监听器错误');
      });

      expect(machine.transition('START')).toBe(true);
      expect(machine.getState()).toBe('calculating');
    });
  });

  // ============ 历史记录测试 ============

  describe('历史记录', () => {
    it('记录状态转换历史', () => {
      machine.transition('START');
      machine.transition('MD5_COMPLETE');

      const history = machine.getHistory();
      expect(history).toHaveLength(2);
      expect(history[0]).toMatchObject({ from: 'waiting', to: 'calculating', event: 'START' });
      expect(history[1]).toMatchObject({ from: 'calculating', to: 'uploading', event: 'MD5_COMPLETE' });
    });

    it('历史记录包含payload', () => {
      machine.transition('START');
      machine.transition('ERROR', { error: new Error('test') });

      const history = machine.getHistory();
      expect(history[1].payload).toEqual({ error: expect.any(Error) });
    });

    it('getHistory返回副本', () => {
      machine.transition('START');

      const history1 = machine.getHistory();
      const history2 = machine.getHistory();

      expect(history1).not.toBe(history2);
      expect(history1).toEqual(history2);
    });
  });

  // ============ 工具方法测试 ============

  describe('工具方法', () => {
    it('canTransition正确判断可转换性', () => {
      expect(machine.canTransition('START')).toBe(true);
      expect(machine.canTransition('PAUSE')).toBe(false);
      
      machine.transition('START');
      expect(machine.canTransition('PAUSE')).toBe(true);
    });

    it('isInState正确判断当前状态', () => {
      expect(machine.isInState('waiting')).toBe(true);
      expect(machine.isInState('calculating')).toBe(false);
    });

    it('isInState支持数组', () => {
      expect(machine.isInState(['waiting', 'calculating'])).toBe(true);
      expect(machine.isInState(['calculating', 'uploading'])).toBe(false);
    });
  });

  // ============ 输入验证测试 ============

  describe('输入验证', () => {
    it('event必须是字符串', () => {
      expect(machine.transition(null)).toBe(false);
      expect(machine.transition(123)).toBe(false);
      expect(machine.transition({})).toBe(false);
      expect(machine.transition('')).toBe(false);
    });

    it('无效事件返回false', () => {
      expect(machine.transition('INVALID_EVENT')).toBe(false);
      expect(machine.transition('start')).toBe(false); // 大小写敏感
    });
  });

  // ============ Context更新测试 ============

  describe('Context更新', () => {
    it('updateContext更新白名单字段', () => {
      machine.updateContext({ fileHash: 'abc123', percent: 50 });

      expect(machine.context.fileHash).toBe('abc123');
      expect(machine.context.percent).toBe(50);
    });

    it('updateContext不更新非白名单字段', () => {
      machine.updateContext({ fileHash: 'abc123', invalidField: 'bad' });

      expect(machine.context.fileHash).toBe('abc123');
      expect(machine.context.invalidField).toBeUndefined();
    });
  });
});
