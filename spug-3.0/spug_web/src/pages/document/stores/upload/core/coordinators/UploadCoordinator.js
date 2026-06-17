/**
 * UploadCoordinator - 上传协调器
 * 负责任务调度、并发控制和上传流程管理
 */
import { action } from 'mobx';
import { MAX_CONCURRENT_UPLOADS, ACTIVE_STATES, UPLOAD_CONSTANTS, generateUploadId } from '../upload-core-constants';

export class UploadCoordinator {
  constructor(coreStore) {
    this.core = coreStore;
  }

  /**
   * 【Loop-200修复】懒创建状态机
   * 调度时为即将启动的 waiting 任务按需创建状态机，避免入队时批量创建占满上限。
   * - 已存在则直接返回
   * - 不存在则根据队列 item 补齐 context 后创建（与原入队创建 context 保持一致）
   * - 创建失败记录日志并返回 null，调用方保持 waiting 等待下次调度
   */
  ensureStateMachine(item) {
    let stateMachine = this.core.stateMachineManager?.get(item.id);
    if (stateMachine) {
      return stateMachine;
    }

    stateMachine = this.core.stateMachineManager?.create(item.id, {
      queueStore: this.core.queueStore,
      transferStore: this.core.transferStore,
      md5Store: this.core.md5Store,
      file: item.file,
      folderId: item.folderId,
      item,
    });

    if (!stateMachine) {
      console.error('[UploadCoordinator] 状态机懒创建失败', {
        uploadId: item.id,
        name: item.name,
        machineCount: this.core.stateMachineManager?.size?.(),
        activeUploads: this.core.activeUploads,
      });
      return null;
    }

    return stateMachine;
  }

  /**
   * 【新增】启动所有处于 waiting 状态且可以运行的任务
   * 受并发限制控制
   * 【Loop-200修复】不再要求 waiting 任务预先存在状态机，改为调度时通过 ensureStateMachine 懒创建
   * 【P1修复】统一并发控制逻辑，确保全局并发数不超过限制
   * 【P2修复】merging状态不占用并发槽位，因为只是轮询等待后端完成
   * 【P0修复】检查全局暂停状态，确保新添加的文件能够自动开始
   */
  @action
  startWaiting() {
    const tenantId = this.core.getCurrentTenantId();
    const maxConcurrent = this.core.maxConcurrentUploads || MAX_CONCURRENT_UPLOADS;
    const queue = this.core.queueStore.uploadQueue[tenantId] || [];
    const sm = this.core.stateMachineManager;

    // 【P0修复】如果全局暂停，不启动新任务（但新添加的文件会重置isPaused）
    if (this.core.isPaused) {
      return;
    }

    // 【Loop-1003修复】并发槽位统计改用状态机 currentState，不依赖 item.status
    // 原因：item.status 通过 EventBus → StoreEventAdapter 更新，虽然通常是同步的，
    //   但 MobX reaction 批量更新等边界场景可能导致 item.status 延迟更新。
    //   状态机 currentState 在 transition() 内同步更新（第196行），是唯一可靠的真相源。
    // merging 不占槽位（后端合并、前端只轮询，不占前端网络/CPU 资源）。
    const activeCount = sm
      ? sm.countByStates(['calculating', 'uploading'])
      : 0;

    // 计算还可以启动多少个任务
    const availableSlots = maxConcurrent - activeCount;

    if (availableSlots <= 0) {
      return;
    }

    // 找到所有 waiting 状态任务
    const waitingItems = queue.filter(item => item.status === 'waiting');

    // 【Loop-1003修复】一轮调度最多启动 availableSlots 个任务
    // 关键：不 remove 任何状态机！canTransition('START') 失败只 continue
    // 原因：状态机可能已在运行（calculating/uploading），只是 item.status 仍是 waiting（时序窗口），
    //   remove 会误删正在运行的状态机导致上传中断 + 状态机数量爆炸
    let startedCount = 0;
    for (const item of waitingItems) {
      if (startedCount >= availableSlots) {
        break;
      }

      // 预检：避免创建无法 START 的状态机
      if (!this.canPrepareStart(item)) {
        continue;
      }

      // 检查是否已有状态机（避免重复调度）
      const existing = sm?.get(item.id);
      if (existing) {
        const machineState = existing.getState();
        if (machineState !== 'waiting') {
          // 状态机已在运行（calculating/uploading/merging等），跳过不重复调度
          continue;
        }
        // 状态机在 waiting 状态，可以尝试 START
      }

      // 懒创建状态机
      const stateMachine = this.ensureStateMachine(item);
      if (!stateMachine) {
        // 创建失败（保护阈值满且强化清理无效）：break 等待终态释放后重试
        console.warn('[启动任务] 状态机创建失败，停止本轮调度，等待下次重试');
        break;
      }

      if (!stateMachine.canTransition('START')) {
        // 不能 START：已存在的状态机只 continue（可能正在运行，remove 会误删）
        // 新创建的 waiting 状态机没有运行中资源，安全 remove 避免泄漏
        if (!existing) {
          sm?.remove(item.id);
        }
        continue;
      }

      const success = stateMachine.transition('START');
      if (success) {
        startedCount++;
      } else if (!existing) {
        // 新创建但 START 失败：安全 remove，避免 waiting 状态机泄漏累积
        sm?.remove(item.id);
      }
      // 已存在的状态机 transition 失败不 remove（安全第一）
    }
  }

  /**
   * 【Loop-1003修复】启动前预检：避免创建无法 START 的状态机
   * 在 ensureStateMachine 之前调用，过滤掉已暂停/已取消/缺文件的任务
   */
  canPrepareStart(item) {
    return (
      item &&
      item.status === 'waiting' &&
      !!item.file &&
      !item.isPausedByUser &&
      !item.isCancelledByUser
    );
  }

  /**
   * 【P0修复】处理等待中的上传任务
   * 当当前上传完成时，检查是否有waiting状态的任务可以开始
   * 【修复】统一使用 startWaiting 方法，避免并发控制逻辑分散
   */
  processPending() {
    // 【修复】统一调用 startWaiting，避免多处并发控制逻辑不一致
    this.startWaiting();
  }

  /**
   * 【核心】处理上传队列 - 协调任务调度和执行
   */
  @action
  async processQueue() {
    const files = this.core.pendingFiles || [];
    const folderPath = this.core.pendingFolderPath;
    const filesPerBatch = 30; // 每批处理的文件数
    const tenantId = this.core.getCurrentTenantId();

    if (files.length === 0) return;

    // 清空待处理文件
    this.core.pendingFiles = [];
    this.core.pendingFolderPath = null;

    // 分批处理文件
    for (let i = 0; i < files.length; i += filesPerBatch) {
      const batch = files.slice(i, i + filesPerBatch);
      
      // 检查是否已暂停或取消
      if (this.core.isPaused || this.core.isCancelled) {
        break;
      }

      // 处理批次中的每个文件
      for (const fileInfo of batch) {
        // 检查是否已暂停或取消
        if (this.core.isPaused || this.core.isCancelled) {
          break;
        }

        // 处理单个文件
        await this.processSingleFile(fileInfo, folderPath, tenantId);
      }

      // 让出主线程，避免卡顿
      await new Promise(resolve => setTimeout(resolve, 0));
    }

    // 【修复】使用统一的任务启动方法，受并发限制控制
    this.startWaiting();
  }

  /**
   * 处理单个文件上传
   */
  async processSingleFile(fileInfo, folderPath, tenantId) {
    const { file, targetFolderId, isPublic } = fileInfo;
    
    // 生成唯一key
    const uniqueKey = this.core.queueStore.generateUniqueKey(file, targetFolderId, isPublic);
    
    // 检查是否已在队列中
    if (this.core.queueStore.isFileInQueue(file, targetFolderId, isPublic)) {
      console.log('[跳过重复文件]', file.name);
      return;
    }
    
    // 生成上传ID
    const uploadId = generateUploadId();
    
    // 添加到唯一key集合
    this.core.queueStore.addUniqueKey(file, targetFolderId, isPublic);
    
    // 添加上传项
    this.core.queueStore.addToQueue({
      id: uploadId,
      name: file.name,
      file: file,
      fileSize: file.size,
      folderId: targetFolderId,
      folderPath: folderPath,
      isPublic: isPublic,
      status: 'waiting',
      percent: 0,
      error: null,
      uniqueKey: uniqueKey,
      canAbort: false,
      abortController: null,
      isPausedByUser: false,
      isCancelledByUser: false,
    }, tenantId);
    
    // 【Loop-200修复】入队阶段不再创建状态机，改由 startWaiting 调度时懒创建
    // 全局监听器（index.js _initStateMachine）已统一接入 StateChangeHandler，无需单独 addListener
  }
}

export default UploadCoordinator;
