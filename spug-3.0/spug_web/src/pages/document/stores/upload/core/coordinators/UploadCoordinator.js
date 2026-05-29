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
   * 【新增】启动所有处于 waiting 状态且可以运行的任务
   * 受并发限制控制
   * 【P1修复】统一并发控制逻辑，确保全局并发数不超过限制
   * 【P2修复】merging状态不占用并发槽位，因为只是轮询等待后端完成
   * 【P0修复】检查全局暂停状态，确保新添加的文件能够自动开始
   */
  @action
  startWaiting() {
    const tenantId = this.core.getCurrentTenantId();
    const maxConcurrent = this.core.maxConcurrentUploads || MAX_CONCURRENT_UPLOADS;
    const queue = this.core.queueStore.uploadQueue[tenantId] || [];
    
    // 【P0修复】如果全局暂停，不启动新任务（但新添加的文件会重置isPaused）
    if (this.core.isPaused) {
      console.log('[启动任务] 全局暂停中，不启动新任务');
      return;
    }
    
    // 【P1修复】计算全局活跃任务数（不按租户隔离，确保总并发不超过限制）
    // 【P2修复】只计算占用网络资源的任务：calculating(MD5计算)和uploading(实际上传)
    // merging状态只是轮询等待后端合并完成，不占用网络资源，不占用并发槽位
    // 【P0修复】使用 queueStore.activeUploads 而不是重新计算，确保与 increment/decrement 一致
    const activeCount = this.core.activeUploads || 0;
    
    // 计算还可以启动多少个任务
    const availableSlots = maxConcurrent - activeCount;
    
    console.log('[启动任务] 活跃任务:', activeCount, '最大并发:', maxConcurrent, '可用槽位:', availableSlots);
    
    if (availableSlots <= 0) {
      console.log('[启动任务] 无可用槽位，跳过');
      return;
    }
    
    // 【修复】找到所有 waiting 状态且有状态机的任务
    const waitingItems = queue.filter(item => {
      if (item.status !== 'waiting') return false;
      const sm = this.core.stateMachineManager?.get(item.id);
      // 必须有状态机且可以 START
      return sm && sm.canTransition('START');
    });
    
    console.log('[启动任务] 可启动的waiting任务数:', waitingItems.length);
    
    // 启动最多 availableSlots 个 waiting 任务
    let startedCount = 0;
    for (const item of waitingItems) {
      if (startedCount >= availableSlots) {
        break;
      }
      
      const stateMachine = this.core.stateMachineManager?.get(item.id);
      if (stateMachine) {
        console.log('[启动任务] 启动任务:', item.id, item.name);
        stateMachine.transition('START');
        startedCount++;
      }
    }
    
    console.log('[启动任务] 实际启动:', startedCount);
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
    console.log('[processUploadQueue] 开始启动任务, displayItems:', this.core.queueStore.currentUploadQueue.length);
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
    
    // 创建状态机
    const stateMachine = this.core.stateMachineManager.create(uploadId, {
      fileName: file.name,
      fileSize: file.size,
      folderId: targetFolderId,
    });
    
    // 添加状态变更监听器
    stateMachine.addListener((fromState, toState, event, payload) => {
      if (this.core.stateChangeHandler) {
        this.core.stateChangeHandler.handle(fromState, toState, event, payload, uploadId);
      }
    });
  }
}

export default UploadCoordinator;
