/**
 * UploadStateMachine - 上传任务状态机（解耦版）
 * 【任务4.1】使用事件总线替代隐式回调，与Store完全解耦
 *
 * 职责：
 * - 只管理状态流转逻辑
 * - 通过事件总线通知外部
 * - 不直接依赖任何Store
 *
 * 依赖：
 * - guards.js: 守卫条件函数
 * - actions.js: 动作创建器（通过事件总线通信）
 * - EventBus.js: 事件总线
 */

import {
  canStart,
  shouldResumeWaiting,
  shouldRecalculateMD5,
  shouldResumeUpload,
  isNormalUpload,
  isChunkedUpload
} from './guards';

// 【方向B 2026-06-27】移除解耦设施（EventBus/StoreEventAdapter/actions）
// 状态机通过 context.queueStore 直接更新 item，不再经过事件总线绕路
// 原因：useDecoupledStateMachine 从未启用，adapter 半死不活，
// 同一 item.status 被两条路径同时写（StateChangeHandler + StoreEventAdapter）

export class UploadStateMachine {
  // 静态常量定义
  static STATES = ['waiting', 'calculating', 'uploading', 'paused', 'merging', 'completed', 'error', 'cancelled'];
  static EVENTS = ['START', 'MD5_COMPLETE', 'UPLOAD_COMPLETE', 'MERGE_SUCCESS', 'PAUSE', 'RESUME', 'ERROR', 'CANCEL', 'RETRY_MERGE'];

  // 【任务3.3】监听器数量上限配置
  static MAX_LISTENERS = 10;

  constructor(uploadId, context = {}) {
    this.uploadId = uploadId;
    this.context = context;
    this.currentState = 'waiting';
    this.history = [];  // 状态历史记录
    this.listeners = new Set();
    this._listenerWarningEmitted = false;  // 【任务3.3】防止重复警告

    // 创建 actions（通过事件总线与外部通信）
    // 【方向B 2026-06-27】已移除，entry/exit 直接调 context.queueStore
    this.actions = null;

    // 状态定义
    this.states = {
      waiting: {
        entry: this.onWaitingEntry.bind(this),
        exit: this.onWaitingExit.bind(this),
        transitions: {
          START: { target: 'calculating', guard: this.canStart.bind(this) },
          PAUSE: { target: 'paused' },
          // 【方向B 2026-06-27】移除 action: this.actions.onCancel，onCancelledEntry 已处理副作用
          CANCEL: { target: 'cancelled' },
          // 【P1修复 2026-06-27】合并失败重试快捷路径：waiting → merging
          // 场景：状态机因终态被释放后由 ensureStateMachine 重建为 waiting，
          // 但分片已全部上传完成，只需重新触发合并，无需重走 calculating → uploading
          RETRY_MERGE: { target: 'merging' }
        }
      },
      calculating: {
        entry: this.onCalculatingEntry.bind(this),
        exit: this.onCalculatingExit.bind(this),
        transitions: {
          MD5_COMPLETE: { target: 'uploading' },
          PAUSE: { target: 'paused' },
          ERROR: { target: 'error' },
          CANCEL: { target: 'cancelled' }
        }
      },
      uploading: {
        entry: this.onUploadingEntry.bind(this),
        exit: this.onUploadingExit.bind(this),
        transitions: [
          {
            event: 'UPLOAD_COMPLETE',
            target: 'completed',
            guard: this.isNormalUpload.bind(this)
            // 【方向B】移除 action: this.actions.onNormalUploadComplete，onCompletedEntry 已处理
          },
          {
            event: 'UPLOAD_COMPLETE',
            target: 'merging',
            guard: this.isChunkedUpload.bind(this)
          },
          { event: 'PAUSE', target: 'paused' },
          { event: 'ERROR', target: 'error' },
          { event: 'CANCEL', target: 'cancelled' }
        ]
      },
      paused: {
        entry: this.onPausedEntry.bind(this),
        exit: this.onPausedExit.bind(this),
        transitions: [
          {
            event: 'RESUME',
            target: 'waiting',
            guard: this.shouldResumeWaiting.bind(this),
            action: this.onResumeToWaitingAction.bind(this)
          },
          {
            event: 'RESUME',
            target: 'calculating',
            guard: this.shouldRecalculateMD5.bind(this)
            // 【方向B】移除 action: this.actions.onResumeToCalculating（adapter 中是空实现）
          },
          {
            event: 'RESUME',
            target: 'uploading',
            guard: this.shouldResumeUpload.bind(this)
            // 【方向B】移除 action: this.actions.onResumeToUploading（adapter 中是空实现）
          },
          // 【修复 2026-06-06】暂停期间允许接收 ERROR 事件（如后端推送合并失败）
          { event: 'ERROR', target: 'error' },
          { event: 'CANCEL', target: 'cancelled' }
        ]
      },
      merging: {
        entry: this.onMergingEntry.bind(this),
        exit: this.onMergingExit.bind(this),
        transitions: {
          MERGE_SUCCESS: { target: 'completed' },
          ERROR: { target: 'error' },
          // 【修复 2026-06-06】合并中允许取消（之前已有，但已确认无 PAUSE）
          CANCEL: { target: 'cancelled' }
        }
      },
      completed: {
        entry: this.onCompletedEntry.bind(this),
        type: 'final'
      },
      error: {
        entry: this.onErrorEntry.bind(this),
        transitions: {
          RESUME: { target: 'waiting', action: this.onRetryAction.bind(this) },
          // 【修复 2026-06-06】失败状态下允许取消（之前缺失，导致非法转换被静默吞下）
          CANCEL: { target: 'cancelled' },
          // 【P1修复 2026-06-27】合并失败重试快捷路径：error → merging
          // 场景：分片已全部上传完成，合并失败后直接重试合并，无需重传
          RETRY_MERGE: { target: 'merging' }
        }
      },
      cancelled: {
        entry: this.onCancelledEntry.bind(this),
        type: 'final'
      }
    };
  }

  // ============ 核心方法 ============

  /**
   * 状态转换
   * @param {string} event - 事件名称
   * @param {object} payload - 事件数据
   * @returns {boolean} 转换是否成功
   */
  transition(event, payload = {}) {
    // 输入验证
    if (typeof event !== 'string' || !event.trim()) {
      return false;
    }

    if (typeof payload !== 'object' || payload === null) {
      return false;
    }

    // 【7.3 异步操作加版本号】payload 版本兜底检查
    // 异步回调返回时应在 payload 中携带 operationVersion；
    // 若版本已过期（用户在此期间执行了 PAUSE/CANCEL/RESUME/RETRY/START），
    // 则拒绝该转换，防止旧回调覆盖新状态。
    if (payload.operationVersion !== undefined && payload.operationVersion !== null) {
      const currentVersion = this.context.queueStore?.getOperationVersion?.(this.uploadId) || 0;
      if (payload.operationVersion !== currentVersion) {
        console.debug(
          `[UploadStateMachine] ${this.uploadId}: 拒绝过期回调 event=${event} ` +
          `payloadVersion=${payload.operationVersion} currentVersion=${currentVersion}`
        );
        if (this.context.metrics) {
          this.context.metrics.staleCallbackRejected =
            (this.context.metrics.staleCallbackRejected || 0) + 1;
        }
        return false;
      }
    }

    const currentStateDef = this.states[this.currentState];

    // 查找匹配的转换规则
    const transition = this.findTransition(currentStateDef, event);

    if (!transition) {
      console.warn(`[UploadStateMachine] ${this.uploadId}: 转换失败-无匹配规则 currentState=${this.currentState} event=${event}`);
      // 监控埋点：非法转换次数
      if (this.context.metrics) {
        this.context.metrics.invalidTransitions++;
      }
      return false;
    }

    // 检查守卫条件
    if (transition.guard && !transition.guard(payload)) {
      console.warn(`[UploadStateMachine] ${this.uploadId}: 转换失败-守卫不满足 ${this.currentState} --${event}--> ${transition.target}`);
      return false;
    }

    const fromState = this.currentState;
    const toState = transition.target;

    // 【7.3】对新生命周期事件递增操作版本号（在执行转换前递增）
    // - START/RESUME：开始新一轮异步操作（MD5/上传/合并），旧回调应失效
    // - PAUSE：让正在返回的上传/MD5/轮询结果失效
    // - CANCEL：让所有旧回调失效
    // 递增后，entry 钩子启动的异步操作将捕获新版本；
    // 旧版本回调在 payload 兜底检查或调用方 isCurrentOperation 检查中被丢弃。
    const VERSION_BUMP_EVENTS = ['START', 'RESUME', 'PAUSE', 'CANCEL'];
    if (VERSION_BUMP_EVENTS.includes(event)) {
      const queueStore = this.context.queueStore;
      if (queueStore && queueStore.bumpOperationVersion) {
        queueStore.bumpOperationVersion(this.uploadId);
      }
    }

    // 钩子函数异常防护
    try {
      // 执行退出动作
      if (currentStateDef.exit) {
        currentStateDef.exit(payload);
      }

      // 更新状态
      this.currentState = toState;
      // 更新上下文
      this.updateContext(payload);

      // 记录历史
      this.history.push({
        from: fromState,
        to: toState,
        event,
        timestamp: Date.now(),
        payload
      });

      // 执行进入动作
      const toStateDef = this.states[toState];
      if (toStateDef.entry) {
        toStateDef.entry(payload);
      }

      // 执行转换动作
      if (transition.action) {
        transition.action(payload);
      }

      // 通知监听器
      this.notifyListeners(fromState, toState, event, payload);

      // 【新增 2026-06-06】一致性检查：状态机 currentState 与 Store item.status 应保持一致
      this.assertStatusConsistency(toState, event);

      // 总转换次数埋点
      if (this.context.metrics) {
        this.context.metrics.totalTransitions++;
      }

      return true;
    } catch (error) {
      // 钩子函数异常处理
      console.error(`[UploadStateMachine] ${this.uploadId}: 状态转换异常 ${fromState} -> ${toState}`, error);

      // 钩子异常次数埋点
      if (this.context.metrics) {
        this.context.metrics.hookErrors++;
      }

      // 【方向B】actions 已移除，直接通过 transition 进 error（避免递归，直接写状态）
      this.updateItem({
        status: 'error',
        error: `状态转换异常: ${error.message}`,
        canAbort: false
      });

      // 通知错误监听器
      this.notifyListeners(fromState, 'error', 'ERROR', { error, originalEvent: event });

      return false;
    }
  }

  /**
   * 查找转换规则
   */
  findTransition(stateDef, event) {
    const transitions = stateDef.transitions;
    if (!transitions) return null;

    let candidates = [];

    if (Array.isArray(transitions)) {
      candidates = transitions.filter(t => t.event === event);
    } else {
      candidates = Object.entries(transitions)
        .filter(([key]) => key === event)
        .map(([_, value]) => value);
    }

    if (candidates.length === 0) return null;
    if (candidates.length === 1) return candidates[0];

    return candidates.find(t => !t.guard || t.guard()) || candidates[0];
  }

  /**
   * 检查是否可以转换
   */
  canTransition(event) {
    const currentStateDef = this.states[this.currentState];
    const transition = this.findTransition(currentStateDef, event);
    return !!transition;
  }

  /**
   * 获取当前状态
   */
  getState() {
    return this.currentState;
  }

  /**
   * 获取上传项ID
   */
  getItemId() {
    return this.uploadId;
  }

  /**
   * 检查是否处于某状态
   */
  isInState(state) {
    if (Array.isArray(state)) {
      return state.includes(this.currentState);
    }
    return this.currentState === state;
  }

  /**
   * 添加状态变更监听器
   */
  addListener(listener) {
    // 【任务3.3】检查监听器数量上限
    if (this.listeners.size >= UploadStateMachine.MAX_LISTENERS) {
      if (!this._listenerWarningEmitted) {
        console.warn(`[UploadStateMachine] ${this.uploadId}: 监听器数量已达上限(${UploadStateMachine.MAX_LISTENERS})`);
        this._listenerWarningEmitted = true;
      }
      return () => {};
    }

    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /**
   * 通知监听器
   */
  notifyListeners(fromState, toState, event, payload) {
    this.listeners.forEach((listener, index) => {
      const scheduleTask = typeof queueMicrotask !== 'undefined'
        ? queueMicrotask
        : (fn) => Promise.resolve().then(fn);

      scheduleTask(() => {
        try {
          listener(fromState, toState, event, payload, this.uploadId);
        } catch (error) {
          console.error(`[UploadStateMachine] ${this.uploadId}: 监听器 #${index} 错误`, error);
        }
      });
    });
  }

  /**
   * 获取状态历史
   */
  getHistory() {
    return [...this.history];
  }

  // ============ 状态钩子 ============

  onWaitingEntry() {
    this.updateItem({
      status: 'waiting',
      error: null,
      canAbort: false
    });
  }

  onWaitingExit() {
    // 清理等待状态
  }

  onCalculatingEntry() {
    // 【P0修复】检查上传项是否存在
    const item = this.context.queueStore?.findUploadItemInCurrentTenant(this.uploadId);
    if (!item) {
      console.warn(`[UploadStateMachine] ${this.uploadId}: item not found in onCalculatingEntry`);
      // 延迟执行错误转换，避免同步调用导致的问题
      const scheduleError = typeof queueMicrotask !== 'undefined'
        ? queueMicrotask
        : (fn) => Promise.resolve().then(fn);
      scheduleError(() => {
        // 【额外检查】确保状态机实例仍然存在（未被清理）
        if (this.currentState === 'calculating' && this.context.queueStore?.findUploadItemInCurrentTenant(this.uploadId)) {
          this.transition('ERROR', { error: '上传项不存在' });
        }
      });
      return;
    }

    // 【P0修复】检查File对象是否存在
    if (!item.file) {
      console.warn(`[UploadStateMachine] ${this.uploadId}: file object not found`);
      this.updateItem({
        status: 'error',
        error: '请重新选择文件',
        canAbort: false
      });
      // 延迟执行错误转换
      const scheduleError = typeof queueMicrotask !== 'undefined'
        ? queueMicrotask
        : (fn) => Promise.resolve().then(fn);
      scheduleError(() => {
        // 【额外检查】确保状态机实例仍然存在
        if (this.currentState === 'calculating' && this.context.queueStore?.findUploadItemInCurrentTenant(this.uploadId)) {
          this.transition('ERROR', { error: '请重新选择文件' });
        }
      });
      return;
    }

    this.updateItem({
      status: 'calculating',
      percent: 0,
      canAbort: true
    });

    // 【方向B】移除 this.actions.startMD5Calculation()（死代码：md5Store 无此方法，
    // 实际 MD5 计算由 StateChangeHandler → UploadLifecycle.onCalculating 触发）
  }

  onCalculatingExit() {
    // 【方向B】移除 this.actions.cancelMD5Calculation()（死代码：md5Store 无此方法）
  }

  onUploadingEntry() {
    // 【7.1 状态机唯一入口】生命周期字段全部由状态机 entry 管理
    // isPausedByUser / isCancelledByUser 原先在 StateChangeHandler.handleUploadingState
    // 中重置，现收敛到状态机内部，避免业务模块直接写生命周期字段。
    this.updateItem({
      status: 'uploading',
      canAbort: true,
      isPausedByUser: false,
      isCancelledByUser: false
    });
  }

  onUploadingExit() {
    // 【方向B】清理上传资源（中止请求 + 清空 abortController/abortToken）
    // 原 this.actions.abortUpload + cleanupUploadResources 已合并到 this.cleanupUploadResources
    this.cleanupUploadResources();
  }

  onPausedEntry() {
    this.updateItem({
      status: 'paused',
      error: '已暂停',
      canAbort: false
    });

    // 【P0修复 2026-06-27】后端同步由 StateChangeHandler → StatusSynchronizer 统一处理
    // 不再在 entry 钩子中直接调 updateTransferStatus，避免双重同步链路
  }

  onPausedExit() {
    this.updateItem({
      error: null
    });
  }

  onMergingEntry() {
    // 【P0修复】检查上传项是否存在
    const item = this.context.queueStore?.findUploadItemInCurrentTenant(this.uploadId);
    if (!item) {
      console.warn(`[UploadStateMachine] ${this.uploadId}: item not found in onMergingEntry`);
      // 延迟执行错误转换
      const scheduleError = typeof queueMicrotask !== 'undefined'
        ? queueMicrotask
        : (fn) => Promise.resolve().then(fn);
      scheduleError(() => {
        // 【额外检查】确保状态机实例仍然存在
        if (this.currentState === 'merging' && this.context.queueStore?.findUploadItemInCurrentTenant(this.uploadId)) {
          this.transition('ERROR', { error: '上传项不存在' });
        }
      });
      return;
    }

    this.updateItem({
      status: 'merging',
      canAbort: false
    });
  }

  onMergingExit() {
    // 清理合并资源
  }

  onCompletedEntry() {
    this.updateItem({
      status: 'completed',
      percent: 100,
      canAbort: false,
      completedAt: Date.now()
    });

    // 清理资源
    this.cleanupAllResources();

    // 【P0修复 2026-06-27】后端同步由 StateChangeHandler → StatusSynchronizer 统一处理
  }

  onErrorEntry() {
    this.updateItem({
      status: 'error',
      canAbort: false
    });

    // error状态保留file对象用于重试
    const scheduleCleanup = typeof queueMicrotask !== 'undefined'
      ? queueMicrotask
      : (fn) => Promise.resolve().then(fn);
    scheduleCleanup(() => {
      this.cleanupUploadResources();
    });
  }

  onCancelledEntry() {
    try {
      this.updateItem({
        status: 'cancelled',
        error: '已取消',
        canAbort: false,
        percent: 0
      });

      // 清理资源
      this.cleanupAllResources();

      // 【P0修复 2026-06-27】后端同步由 StateChangeHandler → StatusSynchronizer 统一处理
      // 不再在 entry 钩子中直接调 updateTransferStatus('CANCELED')
    } catch (error) {
      console.error(`[UploadStateMachine] ${this.uploadId}: onCancelledEntry 异常`, error);
      throw error;
    }
  }

  // ============ 守卫条件包装器 ============

  /**
   * 【P0修复】检查是否可以启动上传
   * 增强健壮性，确保即使context不完整也能正常工作
   */
  canStart() {
    // 【修复】优先从context获取item（如果创建时已传入）
    let item = this.context.item;
    
    // 如果context中没有item，从queueStore查找
    if (!item && this.context.queueStore) {
      item = this.context.queueStore.findUploadItemInCurrentTenant(this.uploadId);
    }
    
    // 【修复】如果没有找到item，说明队列中不存在此任务，不能启动
    if (!item) {
      console.warn(`[canStart] ${this.uploadId}: item not found in queue`);
      return false;
    }
    
    // 【修复】检查是否被取消（优先使用item的属性，其次是context）
    const isCancelledByUser = item.isCancelledByUser || this.context.isCancelledByUser;
    
    return canStart({ item, isCancelledByUser });
  }

  shouldResumeWaiting() {
    const item = this.context.queueStore?.findUploadItemInCurrentTenant(this.uploadId);
    return shouldResumeWaiting({ item, history: this.history });
  }

  shouldRecalculateMD5() {
    const item = this.context.queueStore?.findUploadItemInCurrentTenant(this.uploadId);
    return shouldRecalculateMD5({ item });
  }

  shouldResumeUpload() {
    const item = this.context.queueStore?.findUploadItemInCurrentTenant(this.uploadId);
    return shouldResumeUpload({ item });
  }

  isNormalUpload() {
    const item = this.context.queueStore?.findUploadItemInCurrentTenant(this.uploadId);
    return isNormalUpload({ item });
  }

  isChunkedUpload() {
    const item = this.context.queueStore?.findUploadItemInCurrentTenant(this.uploadId);
    return isChunkedUpload({ item });
  }

  // ============ 动作包装器 ============

  onResumeToWaitingAction() {
    // 【方向B】原 this.actions.onResumeToWaiting(needsReSelect) 通过 EventBus 通知 adapter
    // adapter handleResumeToWaiting 调 updateItem({status:'waiting', canAbort:false, error: needsReSelect?'请重新选择文件后继续':null})
    // 但 RESUME→waiting 转换后 onWaitingEntry 已写 status:'waiting'/error:null/canAbort:false
    // 这里仅补充 needsReSelect 的 error 提示（onWaitingEntry 会覆盖 error:null，需在 entry 后执行）
    const item = this.context.queueStore?.findUploadItemInCurrentTenant(this.uploadId);
    const needsReSelect = !item?.file;
    if (needsReSelect) {
      // 延迟执行，避免被 onWaitingEntry 的 error:null 覆盖
      const scheduleError = typeof queueMicrotask !== 'undefined'
        ? queueMicrotask
        : (fn) => Promise.resolve().then(fn);
      scheduleError(() => {
        this.updateItem({ error: '请重新选择文件后继续' });
      });
    }
  }

  onRetryAction() {
    // 【方向B】原 this.actions.onRetry() 通过 EventBus 通知 adapter
    // adapter handleRetry 调 updateItem({error:null, percent:0})
    // 但 RESUME→waiting 转换后 onWaitingEntry 已写 error:null/canAbort:false
    // 这里仅重置 percent（onWaitingEntry 不写 percent）
    this.updateItem({ percent: 0 });

    // 重试后自动开始上传
    const scheduleStart = typeof queueMicrotask !== 'undefined'
      ? queueMicrotask
      : (fn) => Promise.resolve().then(fn);
    scheduleStart(() => {
      if (this.currentState === 'waiting' && this.canTransition('START')) {
        this.transition('START');
      }
    });
  }

  // ============ 辅助方法 ============

  /**
   * 【方向B 2026-06-27】更新队列项（替代原 this.actions.updateItem）
   * 直接通过 context.queueStore 更新，不经过 EventBus 绕路
   */
  updateItem(updates) {
    if (this.context.queueStore?.updateUploadItem) {
      this.context.queueStore.updateUploadItem(this.uploadId, updates);
    }
  }

  /**
   * 【方向B 2026-06-27】清理上传资源（替代原 this.actions.cleanupUploadResources）
   * 中止请求 + 清空 abortController/abortToken
   */
  cleanupUploadResources() {
    const item = this.context.queueStore?.findUploadItemInCurrentTenant?.(this.uploadId);
    if (item) {
      if (item.abortController) {
        try { item.abortController.abort('状态转换'); } catch (e) { /* 忽略 */ }
      }
      if (item.canAbort && item.abortToken) {
        try { item.abortToken.cancel('状态转换'); } catch (e) { /* 忽略 */ }
      }
    }
    this.updateItem({ abortController: null, abortToken: null });
  }

  /**
   * 【方向B 2026-06-27】清理所有资源（替代原 this.actions.cleanupAllResources）
   * 在 cleanupUploadResources 基础上额外清空 file 对象
   */
  cleanupAllResources() {
    this.cleanupUploadResources();
    this.updateItem({ file: null });
  }

  updateContext(updates) {
    this.context = { ...this.context, ...updates };
  }

  /**
   * 【新增 2026-06-06，7.1 强化 2026-06-23】状态一致性检查
   *
   * 检查状态机 currentState 与 Store item.status 是否一致。
   * 业务模块（chunkUpload.js / fileUpload.js 等）应通过 transition(event) 触发状态迁移，
   * 不再直接写 item.status / canAbort / isPausedByUser / isCancelledByUser。
   *
   * 策略：
   * - 开发环境：打印详细报警（含调用栈），便于定位绕写点。
   * - 生产环境：记录到 metrics，并自动以状态机状态修复 Store 状态。
   * - 自动修复只是兜底，不应掩盖业务模块绕写问题；修复后绕写点应明显减少。
   *
   * @param {string} expectedState - 状态机转换后的目标状态
   * @param {string} event - 触发转换的事件
   */
  assertStatusConsistency(expectedState, event) {
    try {
      const item = this.context.queueStore?.findUploadItemInCurrentTenant?.(this.uploadId);
      if (!item) return;

      if (item.status !== expectedState) {
        const msg = `[UploadStateMachine] 状态不一致! uploadId=${this.uploadId}, stateMachine=${expectedState}, item.status=${item.status}, event=${event}`;

        // 开发环境：报警 + 调用栈，便于定位绕写点
        if (process.env.NODE_ENV === 'development') {
          console.warn(msg, '\n调用栈:', new Error().stack);
        } else {
          // 生产环境：静默记录到 metrics
          if (this.context.metrics) {
            this.context.metrics.statusInconsistencies = (this.context.metrics.statusInconsistencies || 0) + 1;
          }
        }

        // 自动修复：让 item.status 跟随状态机（以状态机为准）
        if (this.context.queueStore?.updateUploadItem) {
          this.context.queueStore.updateUploadItem(this.uploadId, { status: expectedState });
        }
      }
    } catch (e) {
      // 一致性检查异常不应阻塞状态转换
      console.error('[UploadStateMachine] assertStatusConsistency 异常:', e);
    }
  }
}

export default UploadStateMachine;
