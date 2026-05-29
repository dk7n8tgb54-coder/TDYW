/**
 * DisplayCoordinator - 显示协调器
 * 【简化】移除 pendingDisplayQueue 相关逻辑
 * 仅保留启动等待任务的功能
 */
import { action } from 'mobx';

export class DisplayCoordinator {
  constructor(coreStore) {
    this.core = coreStore;
  }

  /**
   * 【简化】仅触发 startWaiting，不再处理显示队列
   */
  @action
  replenish() {
    console.log('[DisplayCoordinator] 触发任务调度');
    
    if (this.core.uploadCoordinator) {
      this.core.uploadCoordinator.startWaiting();
    }
  }
}

export default DisplayCoordinator;
