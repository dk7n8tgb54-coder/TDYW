/**
 * EventBus - 事件总线
 * 【任务4.1】用于状态机与Store解耦，替代隐式回调
 * 
 * 设计模式：发布订阅模式（Pub/Sub）
 * 职责：解耦状态机与业务逻辑，状态机只负责状态流转，业务逻辑通过事件监听处理
 */

export class EventBus {
  constructor() {
    this.events = new Map();
    this.onceEvents = new Map();
  }

  /**
   * 订阅事件
   * @param {string} event - 事件名称
   * @param {Function} callback - 回调函数
   * @returns {Function} 取消订阅函数
   */
  on(event, callback) {
    if (typeof callback !== 'function') {
      console.error(`[EventBus] 回调必须是函数: ${event}`);
      return () => {};
    }

    if (!this.events.has(event)) {
      this.events.set(event, new Set());
    }
    this.events.get(event).add(callback);

    // 返回取消订阅函数
    return () => this.off(event, callback);
  }

  /**
   * 一次性订阅（只触发一次）
   * @param {string} event - 事件名称
   * @param {Function} callback - 回调函数
   * @returns {Function} 取消订阅函数
   */
  once(event, callback) {
    if (typeof callback !== 'function') {
      console.error(`[EventBus] 回调必须是函数: ${event}`);
      return () => {};
    }

    if (!this.onceEvents.has(event)) {
      this.onceEvents.set(event, new Set());
    }
    this.onceEvents.get(event).add(callback);

    return () => this.off(event, callback);
  }

  /**
   * 取消订阅
   * @param {string} event - 事件名称
   * @param {Function} callback - 回调函数
   */
  off(event, callback) {
    // 从常规事件中移除
    if (this.events.has(event)) {
      this.events.get(event).delete(callback);
      if (this.events.get(event).size === 0) {
        this.events.delete(event);
      }
    }

    // 从一次性事件中移除
    if (this.onceEvents.has(event)) {
      this.onceEvents.get(event).delete(callback);
      if (this.onceEvents.get(event).size === 0) {
        this.onceEvents.delete(event);
      }
    }
  }

  /**
   * 触发事件
   * @param {string} event - 事件名称
   * @param {*} data - 事件数据
   */
  emit(event, data) {
    // 触发常规事件
    if (this.events.has(event)) {
      this.events.get(event).forEach(callback => {
        try {
          callback(data);
        } catch (error) {
          console.error(`[EventBus] 事件处理错误: ${event}`, error);
        }
      });
    }

    // 触发一次性事件
    if (this.onceEvents.has(event)) {
      this.onceEvents.get(event).forEach(callback => {
        try {
          callback(data);
        } catch (error) {
          console.error(`[EventBus] 一次性事件处理错误: ${event}`, error);
        }
      });
      // 清理一次性事件
      this.onceEvents.delete(event);
    }
  }

  /**
   * 异步触发事件（使用微任务）
   * @param {string} event - 事件名称
   * @param {*} data - 事件数据
   */
  emitAsync(event, data) {
    const scheduleTask = typeof queueMicrotask !== 'undefined'
      ? queueMicrotask
      : (fn) => Promise.resolve().then(fn);

    scheduleTask(() => this.emit(event, data));
  }

  /**
   * 检查是否有监听器
   * @param {string} event - 事件名称
   * @returns {boolean}
   */
  hasListeners(event) {
    const hasRegular = this.events.has(event) && this.events.get(event).size > 0;
    const hasOnce = this.onceEvents.has(event) && this.onceEvents.get(event).size > 0;
    return hasRegular || hasOnce;
  }

  /**
   * 获取监听器数量
   * @param {string} event - 事件名称（不传则返回所有）
   * @returns {number}
   */
  listenerCount(event) {
    if (event) {
      const regularCount = this.events.has(event) ? this.events.get(event).size : 0;
      const onceCount = this.onceEvents.has(event) ? this.onceEvents.get(event).size : 0;
      return regularCount + onceCount;
    }

    let total = 0;
    this.events.forEach(listeners => total += listeners.size);
    this.onceEvents.forEach(listeners => total += listeners.size);
    return total;
  }

  /**
   * 清除所有事件
   */
  clear() {
    this.events.clear();
    this.onceEvents.clear();
  }

  /**
   * 清除指定事件的所有监听器
   * @param {string} event - 事件名称
   */
  clearEvent(event) {
    this.events.delete(event);
    this.onceEvents.delete(event);
  }
}

// 创建全局事件总线实例
export const globalEventBus = new EventBus();

export default EventBus;
