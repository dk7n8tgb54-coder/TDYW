/**
 * NetworkLifecycle - 网络生命周期管理
 * 负责网络状态变化的监听和处理
 */
import { message } from 'antd';

export class NetworkLifecycle {
  constructor(coreStore) {
    this.core = coreStore;
    this._handleOffline = null;
    this._handleOnline = null;
  }

  /**
   * 初始化网络监听
   */
  init() {
    this._handleOffline = () => {
      if (this.core.debounceController) {
        this.core.debounceController.pauseAll();
      }
      message.warning('网络已断开，上传任务已暂停');
    };

    this._handleOnline = () => {
      message.info('网络已恢复，正在恢复上传任务');
      if (this.core.debounceController) {
        this.core.debounceController.resumeAll();
      }
    };

    window.addEventListener('offline', this._handleOffline);
    window.addEventListener('online', this._handleOnline);
  }

  /**
   * 手动触发离线处理
   */
  handleOffline() {
    if (this._handleOffline) {
      this._handleOffline();
    }
  }

  /**
   * 手动触发在线处理
   */
  handleOnline() {
    if (this._handleOnline) {
      this._handleOnline();
    }
  }

  /**
   * 清理网络监听
   */
  cleanup() {
    if (this._handleOffline) {
      window.removeEventListener('offline', this._handleOffline);
      this._handleOffline = null;
    }
    if (this._handleOnline) {
      window.removeEventListener('online', this._handleOnline);
      this._handleOnline = null;
    }
  }
}

export default NetworkLifecycle;
