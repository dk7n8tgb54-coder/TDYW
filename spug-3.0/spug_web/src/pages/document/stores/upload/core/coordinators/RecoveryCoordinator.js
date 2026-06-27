/**
 * RecoveryCoordinator - 恢复协调器
 * 负责调度恢复等待中的暂停任务
 */
import { MAX_CONCURRENT_UPLOADS, SLOT_OCCUPYING_STATUSES } from '../upload-core-constants';

export class RecoveryCoordinator {
  constructor(coreStore) {
    this.core = coreStore;
  }

  /**
   * 【关键修复】调度恢复等待中的暂停任务
   * 在全部开始时，只恢复够填满并发槽位的任务，其余任务在上传完成时自动恢复
   */
  schedule() {
    // 监听上传完成事件，自动恢复下一个暂停的任务
    const checkAndResumeNext = () => {
      if (this.core.isPaused || this.core.isCancelled) return;
      
      // 获取所有暂停状态的任务（只包含有File对象的）
      const pausedMachines = [];
      
      if (this.core.stateMachineManager?.machines) {
        this.core.stateMachineManager.machines.forEach((machine, id) => {
          const item = this.core.queueStore.findUploadItemInCurrentTenant(id);
          if (item?.file) {
            if (machine.getState() === 'paused') {
              pausedMachines.push({ id, machine, item });
            }
          }
        });
      }
      
      // 【7.2 统一并发槽位口径】以状态机状态计数作为唯一并发口径
      // 【P0修复 2026-06-27】使用 SLOT_OCCUPYING_STATUSES 常量
      const activeCount = this.core.stateMachineManager
        ? this.core.stateMachineManager.countByStates(SLOT_OCCUPYING_STATUSES)
        : 0;

      // 如果当前活跃任务数小于最大并发数，且有暂停的任务，恢复一个
      if (pausedMachines.length > 0 && activeCount < MAX_CONCURRENT_UPLOADS) {
        // 按添加顺序恢复（先入先出）
        const nextToResume = pausedMachines[0];
        console.log('[自动恢复] 恢复暂停任务:', nextToResume.id, nextToResume.item.name);
        nextToResume.machine.transition('RESUME');
      }
    };
    
    // 立即检查一次
    checkAndResumeNext();
    
    // 延迟再次检查（给状态转换留出时间）
    setTimeout(checkAndResumeNext, 100);
  }
}

export default RecoveryCoordinator;
