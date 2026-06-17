/**
 * StateMachineManager - 状态机管理器（解耦版）
 * 【任务4.1】使用解耦版状态机，通过事件总线与Store通信
 *
 * 职责：
 * - 管理所有上传任务的状态机实例
 * - 批量操作支持
 * - 自动清理机制
 * - 全局监听器管理
 * - 监控指标统计
 */

import { UploadStateMachine } from './UploadStateMachine';

export class StateMachineManager {
  // 【任务3.3】全局监听器数量上限
  static MAX_GLOBAL_LISTENERS = 20;
  // 【Loop-1003修复】保护性阈值（不再是上传容量上限）
  // 正常运行时状态机数≈活跃并发+暂停+短期历史，远小于此值（如并发3时通常<10）
  // 仅在异常情况（状态机泄漏/超发）下触达：触达时先强化清理终态+orphan，仍超才拒绝创建
  // 关键：此阈值只能限制运行时资源，不能限制单次入队文件数（入队不创建状态机）
  static MAX_ACTIVE_MACHINES = 1000;

  constructor() {
    this.machines = new Map();
    this.globalListeners = new Set();
    // 监控指标
    this.metrics = {
      invalidTransitions: 0,  // 非法转换次数
      totalTransitions: 0,    // 总转换次数
      hookErrors: 0          // 钩子函数异常次数
    };
    // 【任务3.3】警告标志，防止重复输出
    this._warningsEmitted = {
      globalListenerLimit: false,
      machineLimit: false
    };
  }

  /**
   * 创建状态机
   * 自动注入metrics引用，用于监控埋点
   *
   * @param {string} uploadId - 上传任务ID
   * @param {object} context - 上下文数据（包含 getItem 方法）
   * @returns {UploadStateMachine|null} 状态机实例，如果超过上限则返回null
   */
  create(uploadId, context) {
    // 【Loop-1003修复】达到保护阈值时先强化清理（终态+orphan），仍超才拒绝
    if (this.machines.size >= StateMachineManager.MAX_ACTIVE_MACHINES) {
      if (!this._warningsEmitted.machineLimit) {
        console.warn(`[StateMachineManager] 状态机数量已达保护阈值(${StateMachineManager.MAX_ACTIVE_MACHINES})，触发强化清理`);
        this._warningsEmitted.machineLimit = true;
      }
      const cleaned = this._aggressiveCleanup();
      if (this.machines.size >= StateMachineManager.MAX_ACTIVE_MACHINES) {
        console.error(`[StateMachineManager] 强化清理后仍达保护阈值，拒绝创建新状态机`, {
          size: this.machines.size,
          uploadId,
          cleaned,
        });
        return null;
      }
    }

    const machine = new UploadStateMachine(uploadId, {
      ...context,
      metrics: this.metrics  // 注入metrics引用
    });

    // 添加全局监听器
    this.globalListeners.forEach(listener => {
      machine.addListener(listener);
    });

    this.machines.set(uploadId, machine);
    return machine;
  }

  /**
   * 【Loop-1003修复】强化清理：终态状态机 + orphan（队列中已不存在的非终态状态机）
   * 在达到保护阈值时调用，腾出空间给即将运行的任务
   * @returns {number} 清理的数量
   */
  _aggressiveCleanup() {
    const FINAL_STATES = ['completed', 'error', 'cancelled'];
    // waiting 状态机没有运行中资源（无网络请求/MD5计算），可安全回收
    // 下次 startWaiting 会通过 ensureStateMachine 重新创建
    const SAFE_TO_REMOVE = ['completed', 'error', 'cancelled', 'waiting'];
    const toRemove = [];
    this.machines.forEach((machine, uploadId) => {
      const state = machine.getState();
      // 1. 终态 + waiting 状态机安全清理
      if (SAFE_TO_REMOVE.includes(state)) {
        toRemove.push(uploadId);
        return;
      }
      // 2. orphan 清理：队列中已不存在的非终态状态机（如任务被删除但状态机未释放）
      const queueStore = machine.context?.queueStore;
      if (queueStore && typeof queueStore.findUploadItemInCurrentTenant === 'function') {
        const item = queueStore.findUploadItemInCurrentTenant(uploadId);
        if (!item) {
          toRemove.push(uploadId);
        }
      }
    });
    if (toRemove.length > 0) {
      console.log(`[StateMachineManager] 强化清理 ${toRemove.length} 个状态机（终态+waiting+orphan）`);
      toRemove.forEach(id => this.remove(id));
    }
    return toRemove.length;
  }

  /**
   * 获取状态机
   *
   * @param {string} uploadId - 上传任务ID
   * @returns {UploadStateMachine|undefined} 状态机实例
   */
  get(uploadId) {
    return this.machines.get(uploadId);
  }

  /**
   * 删除状态机
   *
   * @param {string} uploadId - 上传任务ID
   * @returns {boolean} 是否成功删除
   */
  remove(uploadId) {
    const machine = this.machines.get(uploadId);
    if (machine) {
      // 清理资源
      this.machines.delete(uploadId);
      return true;
    }
    return false;
  }

  /**
   * 添加全局监听器
   * 新添加的监听器会自动应用到所有现有状态机
   *
   * @param {Function} listener - 监听器函数
   */
  addGlobalListener(listener) {
    if (typeof listener !== 'function') {
      console.error('[StateMachineManager] 监听器必须是函数');
      return;
    }

    // 【任务3.3】检查全局监听器数量上限
    if (this.globalListeners.size >= StateMachineManager.MAX_GLOBAL_LISTENERS) {
      if (!this._warningsEmitted.globalListenerLimit) {
        console.warn(`[StateMachineManager] 全局监听器数量已达上限(${StateMachineManager.MAX_GLOBAL_LISTENERS})，拒绝添加新监听器`);
        this._warningsEmitted.globalListenerLimit = true;
      }
      return;
    }

    this.globalListeners.add(listener);

    // 为所有现有状态机添加监听器
    this.machines.forEach(machine => {
      machine.addListener(listener);
    });
  }

  /**
   * 移除全局监听器
   *
   * @param {Function} listener - 监听器函数
   */
  removeGlobalListener(listener) {
    this.globalListeners.delete(listener);
  }

  /**
   * 获取所有状态机状态
   * 用于调试和监控
   *
   * @returns {object} 所有状态机的状态信息
   */
  getAllStates() {
    const states = {};
    this.machines.forEach((machine, uploadId) => {
      states[uploadId] = {
        current: machine.getState(),
        history: machine.getHistory()
      };
    });
    return states;
  }

  /**
   * 批量状态转换
   * 【P2修复】跳过终态任务，避免统计偏差
   *
   * @param {string} event - 事件名称
   * @param {Function|null} filterFn - 过滤函数，返回true才执行转换
   * @returns {Array} 转换结果数组
   */
  batchTransition(event, filterFn = null) {
    const results = [];
    // 【P2修复】终态列表
    const FINAL_STATES = ['completed', 'error', 'cancelled'];

    this.machines.forEach((machine, uploadId) => {
      // 【P2修复】跳过终态任务，不计入统计
      if (FINAL_STATES.some(state => machine.isInState(state))) {
        return;
      }

      if (!filterFn || filterFn(machine, uploadId)) {
        const success = machine.transition(event);
        results.push({ uploadId, success, state: machine.getState() });
      }
    });
    return results;
  }

  /**
   * 批量暂停
   * 暂停所有可以暂停的任务
   * 【P1修复】过滤终态任务，避免无效转换
   *
   * @returns {Array} 转换结果数组
   */
  batchPause() {
    // 【关键修复】扩展不可暂停的状态列表，包括终态和合并中
    const NON_PAUSEABLE_STATES = ['completed', 'error', 'cancelled', 'merging'];
    const results = [];

    this.machines.forEach((machine, uploadId) => {
      const state = machine.getState();

      // 跳过不可暂停的状态
      if (NON_PAUSEABLE_STATES.includes(state)) {
        return;
      }

      // 【关键修复】同时检查前端item的状态，防止状态不一致
      const context = machine.context;
      if (context?.queueStore) {
        const item = context.queueStore.findUploadItemInCurrentTenant(uploadId);
        if (item) {
          // 如果前端状态已经是终态，跳过
          if (['completed', 'error', 'cancelled'].includes(item.status)) {
            return;
          }
          // 如果前端在合并中，也跳过
          if (item.status === 'merging') {
            return;
          }
        }
      }

      // 只有明确可以转换时才执行
      if (machine.canTransition('PAUSE')) {
        const success = machine.transition('PAUSE');
        results.push({ uploadId, success, state: machine.getState() });
      }
    });

    return results;
  }

  /**
   * 批量恢复
   * 恢复所有可以恢复的任务，但受并发限制
   * 【P1修复】waiting状态使用START事件，其他使用RESUME事件
   * 【P2修复】计算并发槽位时包含 calculating 状态
   * 【P3优化】优先恢复 paused 状态的任务
   * 【P0修复】改进并发控制逻辑，确保waiting任务最终能够启动
   *
   * @param {number} maxConcurrent - 最大并发数，默认3
   * @param {Function} getActiveCount - 获取当前活跃上传数的函数
   * @returns {Array} 转换结果数组
   */
  batchResume(maxConcurrent = 3, getActiveCount = null) {
    const results = [];
    let resumedCount = 0;

    // 【P2修复】计算占用并发槽位的数量
    let activeCount = 0;
    this.machines.forEach(m => {
      if (m.isInState('uploading') || m.isInState('merging') || m.isInState('calculating')) {
        activeCount++;
      }
    });

    // 如果提供了 getActiveCount 函数，使用它获取活跃数
    if (typeof getActiveCount === 'function') {
      activeCount = getActiveCount();
    }

    const availableSlots = Math.max(0, maxConcurrent - activeCount);
    
    // 【P0修复】记录是否有waiting任务被跳过（用于后续自动启动）
    let hasWaitingTasksSkipped = false;

    // 【P3优化】收集所有可恢复的任务，按优先级排序
    const machinesToResume = [];
    this.machines.forEach((machine, uploadId) => {
      const currentState = machine.getState();
      // waiting状态使用START，其他状态使用RESUME
      const eventName = currentState === 'waiting' ? 'START' : 'RESUME';

      // 检查是否可以转换
      if (machine.canTransition(eventName)) {
        // 对于START事件，额外检查canStart守卫
        if (eventName === 'START' && machine.canStart && !machine.canStart()) {
          return;
        }
        machinesToResume.push({ machine, uploadId, state: currentState, eventName });
      }
    });

    // 【P3优化】按优先级排序：waiting > paused > 其他（新添加的文件优先）
    // 【P0修复】调整优先级，确保新添加的waiting任务能够被处理
    machinesToResume.sort((a, b) => {
      const priority = { 'waiting': 0, 'paused': 1, 'error': 2 };
      const priorityA = priority[a.state] ?? 3;
      const priorityB = priority[b.state] ?? 3;
      return priorityA - priorityB;
    });

    // 按排序后的顺序恢复任务
    for (const { machine, uploadId, eventName } of machinesToResume) {
      if (resumedCount >= availableSlots) {
        // 【P0修复】记录是否有waiting任务因为槽位不足被跳过
        if (machine.getState() === 'waiting') {
          hasWaitingTasksSkipped = true;
        }
        continue; // 【P0修复】使用continue而不是break，让后续任务也能被记录
      }

      const success = machine.transition(eventName);
      if (success) {
        resumedCount++;
      }
      results.push({ uploadId, success, state: machine.getState(), event: eventName });
    }
    
    // 【P0修复】如果有waiting任务被跳过，记录日志便于排查
    if (hasWaitingTasksSkipped) {
      console.log(`[batchResume] 有waiting任务因并发槽位不足被跳过，将在当前任务完成后自动启动。可用槽位: ${availableSlots}`);
    }

    return results;
  }

  /**
   * 批量取消
   * 取消所有可以取消的任务
   * 【P1修复】排除 merging 状态，避免合并中断导致文件损坏
   *
   * @returns {Array} 转换结果数组
   */
  batchCancel() {
    const NON_CANCELLABLE_STATES = ['completed', 'error', 'cancelled', 'merging'];
    return this.batchTransition('CANCEL', (machine) => {
      // 跳过不可取消的状态
      if (NON_CANCELLABLE_STATES.some(state => machine.isInState(state))) {
        return false;
      }
      return machine.canTransition('CANCEL');
    });
  }

  /**
   * 清理已完成的状态机
   * 双策略清理：时间策略 + 数量策略
   *
   * @param {number} maxAge - 最大保留时间（毫秒），默认5分钟
   * @param {number} maxInstances - 最大实例数量限制，默认100
   * @returns {number} 清理的数量
   */
  cleanup(maxAge = 5 * 60 * 1000, maxInstances = 100) {
    const now = Date.now();
    const toRemove = [];

    // 1. 清理超时的已完成任务
    const FINAL_STATES = ['completed', 'error', 'cancelled'];
    this.machines.forEach((machine, uploadId) => {
      const history = machine.getHistory();
      const lastTransition = history[history.length - 1];

      if (lastTransition &&
          FINAL_STATES.some(state => machine.isInState(state)) &&
          (now - lastTransition.timestamp > maxAge)) {
        toRemove.push(uploadId);
      }
    });

    // 2. 如果实例数量超过上限，清理最老的已完成任务
    if (this.machines.size - toRemove.length > maxInstances) {
      const completedMachines = [];

      this.machines.forEach((machine, uploadId) => {
        if (!toRemove.includes(uploadId) &&
            FINAL_STATES.some(state => machine.isInState(state))) {
          const history = machine.getHistory();
          const lastTransition = history[history.length - 1];
          completedMachines.push({
            uploadId,
            lastTimestamp: lastTransition?.timestamp || 0
          });
        }
      });

      // 按时间排序，清理最老的
      completedMachines.sort((a, b) => a.lastTimestamp - b.lastTimestamp);
      const excessCount = this.machines.size - toRemove.length - maxInstances;

      for (let i = 0; i < excessCount && i < completedMachines.length; i++) {
        toRemove.push(completedMachines[i].uploadId);
      }
    }

    // 执行清理
    toRemove.forEach(uploadId => this.remove(uploadId));

    return toRemove.length;
  }

  /**
   * 获取状态机统计信息
   *
   * @returns {object} 统计信息
   */
  getStats() {
    const stats = {
      total: this.machines.size,
      byState: {},
      completed: 0,
      error: 0
    };

    this.machines.forEach(machine => {
      const state = machine.getState();
      stats.byState[state] = (stats.byState[state] || 0) + 1;

      if (state === 'completed') stats.completed++;
      if (state === 'error') stats.error++;
    });

    return stats;
  }

  /**
   * 获取监控指标
   *
   * @returns {object} 监控指标
   */
  getMetrics() {
    return { ...this.metrics };
  }

  /**
   * 重置监控指标
   */
  resetMetrics() {
    this.metrics = {
      invalidTransitions: 0,
      totalTransitions: 0,
      hookErrors: 0
    };
  }

  /**
   * 检查是否存在指定状态的状态机
   *
   * @param {string} state - 状态名称
   * @returns {boolean} 是否存在
   */
  hasState(state) {
    for (const machine of this.machines.values()) {
      if (machine.isInState(state)) {
        return true;
      }
    }
    return false;
  }

  /**
   * 获取指定状态的所有状态机ID
   *
   * @param {string} state - 状态名称
   * @returns {string[]} 状态机ID数组
   */
  getIdsByState(state) {
    const ids = [];
    this.machines.forEach((machine, uploadId) => {
      if (machine.isInState(state)) {
        ids.push(uploadId);
      }
    });
    return ids;
  }

  /**
   * 获取状态机数量
   *
   * @returns {number} 状态机数量
   */
  size() {
    return this.machines.size;
  }

  /**
   * 【Loop-1003修复】统计指定状态集合内的状态机数量
   * 用于并发槽位计算，直接读 currentState（同步准确），不依赖 item.status 的 EventBus 更新
   *
   * @param {string[]} states - 状态名称数组
   * @returns {number} 匹配的状态机数量
   */
  countByStates(states) {
    let count = 0;
    this.machines.forEach(machine => {
      if (states.includes(machine.getState())) {
        count++;
      }
    });
    return count;
  }

  /**
   * 清空所有状态机
   * 谨慎使用！
   */
  clear() {
    this.machines.clear();
  }
}

export default StateMachineManager;
