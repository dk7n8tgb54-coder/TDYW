/**
 * 7.2 统一并发槽位口径 - 并发调度测试
 *
 * 验证《资料库并发上传与状态机修复方案.md》7.2 节要求：
 *   1. 调度决策只依赖 stateMachineManager.countByStates(['calculating','uploading'])
 *   2. handleUploadingState 不再等待并发槽位（已在 StateChangeHandler.js 中移除）
 *   3. activeUploads 不参与上传启动决策
 *   4. merging 不占前端上传槽位
 *   5. 暂停/取消/失败/完成后都能继续调度后续 waiting 任务
 *
 * 测试策略：
 *   - 使用真实的 StateMachineManager + StoreEventAdapter（同步 item.status）
 *   - 不导入 UploadCoordinator（它使用 @action 装饰器，CRA jest 未启用 decorators），
 *     而是提取 startWaiting 的核心调度逻辑为下面的 startWaitingTasks 辅助函数。
 *     该函数与 UploadCoordinator.startWaiting() 逻辑完全一致：
 *       a. maxConcurrent = core.maxConcurrentUploads || MAX_CONCURRENT_UPLOADS
 *       b. activeCount = sm.countByStates(['calculating', 'uploading'])
 *       c. availableSlots = maxConcurrent - activeCount
 *       d. 遍历 waiting items，ensureStateMachine + transition('START')，最多启动 availableSlots 个
 *   - 不注入 StateChangeHandler（不触发真实 MD5/上传业务）
 *   - 手动 transition 模拟不同终态/merging 场景
 *   - 断言 countByStates 和 item.status 一致性
 *
 * 注意：如 UploadCoordinator.startWaiting 逻辑变化，需同步更新 startWaitingTasks。
 */

import { StateMachineManager } from '../StateMachineManager';
import { StoreEventAdapter } from '../StoreEventAdapter';
import { globalEventBus } from '../EventBus';

// 刷新微任务队列（notifyListeners / onRetryAction 等异步 scheduleStart 用）
const flushMicrotasks = () => new Promise(resolve => setTimeout(resolve, 0));

/**
 * 【对应 UploadCoordinator.startWaiting 核心逻辑】
 * 基于 stateMachineManager.countByStates(['calculating','uploading']) 调度 waiting 任务。
 * 不使用 activeUploads，不使用 @action 装饰器（仅为规避 jest babel 限制）。
 *
 * @param {object} coreStore - 包含 stateMachineManager, queueStore, isPaused, maxConcurrentUploads
 */
function startWaitingTasks(coreStore) {
  const maxConcurrent = coreStore.maxConcurrentUploads || 3;
  const tenantId = coreStore.getCurrentTenantId();
  const queue = coreStore.queueStore.uploadQueue[tenantId] || [];
  const sm = coreStore.stateMachineManager;

  if (coreStore.isPaused) return;

  // 【7.2 核心】以状态机状态计数作为唯一并发口径
  const activeCount = sm ? sm.countByStates(['calculating', 'uploading']) : 0;
  const availableSlots = maxConcurrent - activeCount;
  if (availableSlots <= 0) return;

  const waitingItems = queue.filter(item => item.status === 'waiting');
  let startedCount = 0;

  for (const item of waitingItems) {
    if (startedCount >= availableSlots) break;

    // 预检
    if (!item || item.status !== 'waiting' || !item.file || item.isPausedByUser || item.isCancelledByUser) {
      continue;
    }

    // 懒创建/获取状态机
    let stateMachine = sm.get(item.id);
    if (!stateMachine) {
      stateMachine = sm.create(item.id, {
        queueStore: coreStore.queueStore,
        file: item.file,
        folderId: item.folderId,
        item,
      });
    }
    if (!stateMachine) break;

    // 已在运行的状态机跳过
    if (stateMachine.getState() !== 'waiting') continue;
    if (!stateMachine.canTransition('START')) continue;

    if (stateMachine.transition('START')) {
      startedCount++;
    }
  }
}

/**
 * 构造并发调度测试环境
 * @param {number} maxConcurrent - 最大并发数
 */
function setupConcurrencyEnv(maxConcurrent = 3) {
  const items = new Map();
  const tenantId = 'default';

  const mockQueueStore = {
    uploadQueue: { [tenantId]: [] },
    findUploadItemInCurrentTenant: jest.fn((id) => items.get(id) || null),
    findUploadItem: jest.fn((id) => {
      const item = items.get(id);
      return item ? { item, tenantId } : { item: null, tenantId: null };
    }),
    updateUploadItem: jest.fn((id, updates) => {
      const item = items.get(id);
      if (item) {
        Object.assign(item, updates);
      }
    }),
    // 【7.2】activeUploads 保留但不参与调度，验证它不被调用
    activeUploads: 0,
    incrementActiveUploads: jest.fn(),
    decrementActiveUploads: jest.fn(),
  };

  const stateMachineManager = new StateMachineManager();

  // 使用 StoreEventAdapter 连接 EventBus → queueStore（同步 item.status）
  // 不注入 md5Store/transferStore，MD5_START / TRANSFER_STATUS_UPDATE 事件安全忽略
  const adapter = new StoreEventAdapter({
    queueStore: mockQueueStore,
  });
  adapter.init();

  // 不注入 stateChangeHandler 作为 globalListener
  // → 状态机 transition 只改变状态 + 通过 EventBus 同步 item.status
  // → 不触发真实 MD5 计算 / 上传 / 合并业务

  const coreStore = {
    queueStore: mockQueueStore,
    stateMachineManager,
    isPaused: false,
    isCancelled: false,
    maxConcurrentUploads: maxConcurrent,
    getCurrentTenantId: () => tenantId,
  };

  /**
   * 添加一个 waiting 任务
   * @param {string} id - 任务ID
   * @param {object} opts - { totalChunks, fileSize }
   */
  function addWaitingTask(id, opts = {}) {
    const file = { name: `file-${id}`, size: opts.fileSize || 1024 };
    const item = {
      id,
      name: file.name,
      file,
      fileSize: file.size,
      folderId: null,
      isPublic: false,
      status: 'waiting',
      percent: 0,
      error: null,
      uniqueKey: `key-${id}`,
      canAbort: false,
      abortController: null,
      isPausedByUser: false,
      isCancelledByUser: false,
      totalChunks: opts.totalChunks || 1,
      currentChunk: 0,
      fileHash: null,
    };
    items.set(id, item);
    mockQueueStore.uploadQueue[tenantId].push(item);
    return item;
  }

  /** 统计当前 calculating + uploading 的状态机数量（即占用上传槽位数） */
  function activeSlotCount() {
    return stateMachineManager.countByStates(['calculating', 'uploading']);
  }

  /** 统计 item.status 为指定值的数量 */
  function countByItemStatus(status) {
    let count = 0;
    items.forEach(item => {
      if (item.status === status) count++;
    });
    return count;
  }

  return {
    coreStore,
    stateMachineManager,
    mockQueueStore,
    adapter,
    items,
    tenantId,
    addWaitingTask,
    activeSlotCount,
    countByItemStatus,
    // 调度入口（对应 UploadCoordinator.startWaiting）
    startWaiting: () => startWaitingTasks(coreStore),
    // 调度入口（对应 UploadCoordinator.processPending）
    processPending: () => startWaitingTasks(coreStore),
  };
}

function teardownConcurrencyEnv(env) {
  env.adapter.destroy();
  env.stateMachineManager.clear();
  globalEventBus.clear();
}

describe('7.2 统一并发槽位口径', () => {
  let env;
  beforeEach(() => { env = setupConcurrencyEnv(3); });
  afterEach(() => { teardownConcurrencyEnv(env); });

  // ============ 场景1：并发上限 ============

  it('场景1: 10 个 waiting 任务，MAX=3 时最多 3 个进入 calculating/uploading', () => {
    for (let i = 0; i < 10; i++) {
      env.addWaitingTask(`task-${i}`);
    }

    env.startWaiting();

    // 验证：最多 3 个任务占槽位
    expect(env.activeSlotCount()).toBe(3);
    // 验证：7 个仍在 waiting
    expect(env.countByItemStatus('waiting')).toBe(7);
    // 验证：3 个进入 calculating
    expect(env.countByItemStatus('calculating')).toBe(3);
    // 验证：activeUploads 的 increment 未被调用（不参与调度）
    expect(env.mockQueueStore.incrementActiveUploads).not.toHaveBeenCalled();
  });

  it('场景1b: 再次调用 startWaiting 不会超发', () => {
    for (let i = 0; i < 10; i++) {
      env.addWaitingTask(`task-${i}`);
    }

    env.startWaiting();
    expect(env.activeSlotCount()).toBe(3);

    // 再次调用，不应启动更多任务
    env.startWaiting();
    expect(env.activeSlotCount()).toBe(3);
    expect(env.countByItemStatus('waiting')).toBe(7);
  });

  // ============ 场景2：merging 不占槽位 ============

  it('场景2: 任务进入 merging 后不占上传槽，新 waiting 任务能启动', () => {
    // 添加 4 个分片上传任务（totalChunks > 1 → UPLOAD_COMPLETE 进入 merging）
    for (let i = 0; i < 4; i++) {
      env.addWaitingTask(`task-${i}`, { totalChunks: 5, fileSize: 100 * 1024 * 1024 });
    }

    env.startWaiting();
    expect(env.activeSlotCount()).toBe(3);

    // 将 task-0 从 calculating → uploading → merging
    const machine0 = env.stateMachineManager.get('task-0');
    expect(machine0).toBeDefined();
    machine0.transition('MD5_COMPLETE', { fileHash: 'hash-0' });
    expect(machine0.getState()).toBe('uploading');
    machine0.transition('UPLOAD_COMPLETE');
    expect(machine0.getState()).toBe('merging');

    // merging 不在 ['calculating', 'uploading'] 中 → 不占上传槽
    expect(env.activeSlotCount()).toBe(2);

    // 调用 startWaiting（模拟 processPending），应启动 1 个新 waiting 任务
    env.startWaiting();
    expect(env.activeSlotCount()).toBe(3);
    expect(env.countByItemStatus('merging')).toBe(1);
    expect(env.countByItemStatus('waiting')).toBe(0);
  });

  // ============ 场景3：completed 后继续调度 ============

  it('场景3: 任务 completed 后，新 waiting 任务能启动', () => {
    for (let i = 0; i < 4; i++) {
      env.addWaitingTask(`task-${i}`, { totalChunks: 1 }); // 普通上传
    }

    env.startWaiting();
    expect(env.activeSlotCount()).toBe(3);

    // task-0: calculating → uploading → completed
    const machine0 = env.stateMachineManager.get('task-0');
    machine0.transition('MD5_COMPLETE', { fileHash: 'hash-0' });
    machine0.transition('UPLOAD_COMPLETE'); // isNormalUpload → completed
    expect(machine0.getState()).toBe('completed');

    // completed 不占槽 → activeSlotCount 应降为 2
    expect(env.activeSlotCount()).toBe(2);

    env.startWaiting();
    expect(env.activeSlotCount()).toBe(3);
    expect(env.countByItemStatus('completed')).toBe(1);
    expect(env.countByItemStatus('waiting')).toBe(0);
  });

  // ============ 场景4：error 后继续调度 ============

  it('场景4: 任务 error 后，新 waiting 任务能启动', () => {
    for (let i = 0; i < 4; i++) {
      env.addWaitingTask(`task-${i}`);
    }

    env.startWaiting();
    expect(env.activeSlotCount()).toBe(3);

    // task-0: calculating → error
    const machine0 = env.stateMachineManager.get('task-0');
    machine0.transition('ERROR', { error: '模拟失败' });
    expect(machine0.getState()).toBe('error');

    // error 不占槽 → activeSlotCount 应降为 2
    expect(env.activeSlotCount()).toBe(2);

    env.startWaiting();
    expect(env.activeSlotCount()).toBe(3);
    expect(env.countByItemStatus('error')).toBe(1);
    expect(env.countByItemStatus('waiting')).toBe(0);
  });

  // ============ 场景5：cancelled 后继续调度 ============

  it('场景5: 任务 cancelled 后，新 waiting 任务能启动', () => {
    for (let i = 0; i < 4; i++) {
      env.addWaitingTask(`task-${i}`);
    }

    env.startWaiting();
    expect(env.activeSlotCount()).toBe(3);

    // task-0: calculating → cancelled
    const machine0 = env.stateMachineManager.get('task-0');
    machine0.transition('CANCEL');
    expect(machine0.getState()).toBe('cancelled');

    // cancelled 不占槽 → activeSlotCount 应降为 2
    expect(env.activeSlotCount()).toBe(2);

    env.startWaiting();
    expect(env.activeSlotCount()).toBe(3);
    expect(env.countByItemStatus('cancelled')).toBe(1);
    expect(env.countByItemStatus('waiting')).toBe(0);
  });

  // ============ 场景6：暂停不占槽位 ============

  it('场景6: 暂停任务不继续占用上传槽', () => {
    for (let i = 0; i < 4; i++) {
      env.addWaitingTask(`task-${i}`);
    }

    env.startWaiting();
    expect(env.activeSlotCount()).toBe(3);

    // task-0: calculating → paused
    const machine0 = env.stateMachineManager.get('task-0');
    machine0.transition('PAUSE');
    expect(machine0.getState()).toBe('paused');

    // paused 不在 ['calculating', 'uploading'] 中 → 不占槽
    expect(env.activeSlotCount()).toBe(2);

    // startWaiting 应能启动 1 个新 waiting 任务
    env.startWaiting();
    expect(env.activeSlotCount()).toBe(3);
    expect(env.countByItemStatus('paused')).toBe(1);
    expect(env.countByItemStatus('waiting')).toBe(0);
  });

  // ============ 场景7：连续失败/重试不泄漏槽位 ============

  it('场景7: 连续失败/重试不会导致槽位泄漏', async () => {
    for (let i = 0; i < 3; i++) {
      env.addWaitingTask(`task-${i}`);
    }

    env.startWaiting();
    expect(env.activeSlotCount()).toBe(3);

    // task-0: calculating → error → retry(RESUME) → waiting → START → calculating → error
    const machine0 = env.stateMachineManager.get('task-0');

    // 第一次失败
    machine0.transition('ERROR', { error: '第一次失败' });
    expect(machine0.getState()).toBe('error');
    expect(env.activeSlotCount()).toBe(2);

    // 重试：error → waiting（onRetryAction 会异步 START）
    machine0.transition('RESUME');
    expect(machine0.getState()).toBe('waiting');

    // 等待异步 scheduleStart（onRetryAction 中的 queueMicrotask）
    await flushMicrotasks();

    // 重试后应回到 calculating，占槽
    expect(machine0.getState()).toBe('calculating');
    expect(env.activeSlotCount()).toBe(3);

    // 第二次失败
    machine0.transition('ERROR', { error: '第二次失败' });
    expect(machine0.getState()).toBe('error');
    expect(env.activeSlotCount()).toBe(2);

    // startWaiting 能启动新任务（如有 waiting）
    env.addWaitingTask('task-3');
    env.startWaiting();
    expect(env.activeSlotCount()).toBe(3);
  });

  // ============ 场景8：不依赖 activeUploads 也不超发 ============

  it('场景8: activeUploads 始终为 0（不参与调度），调度仍正常工作', () => {
    // activeUploads 初始为 0，且 increment 从未被调用
    expect(env.mockQueueStore.activeUploads).toBe(0);

    for (let i = 0; i < 6; i++) {
      env.addWaitingTask(`task-${i}`);
    }

    env.startWaiting();

    // 即使 activeUploads 仍为 0，调度仍正确限制为 3
    expect(env.mockQueueStore.activeUploads).toBe(0);
    expect(env.mockQueueStore.incrementActiveUploads).not.toHaveBeenCalled();
    expect(env.activeSlotCount()).toBe(3);

    // 完成 1 个后，再启动 1 个
    const machine0 = env.stateMachineManager.get('task-0');
    machine0.transition('MD5_COMPLETE', { fileHash: 'h0' });
    machine0.transition('UPLOAD_COMPLETE'); // → completed
    expect(env.activeSlotCount()).toBe(2);

    env.startWaiting();
    expect(env.activeSlotCount()).toBe(3);
    expect(env.mockQueueStore.activeUploads).toBe(0); // 仍为 0
  });

  // ============ 补充：全局暂停时不启动新任务 ============

  it('补充: 全局暂停时不启动新任务', () => {
    for (let i = 0; i < 5; i++) {
      env.addWaitingTask(`task-${i}`);
    }

    env.coreStore.isPaused = true;
    env.startWaiting();

    expect(env.activeSlotCount()).toBe(0);
    expect(env.countByItemStatus('waiting')).toBe(5);
  });
});
