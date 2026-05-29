/**
 * UploadPanelStore - 上传面板状态管理
 * 
 * 职责：管理上传传输面板的显示/隐藏状态
 * 对应原 UploadUIStore 中的 uploadPanelVisible 相关逻辑
 */
import { observable, action } from 'mobx';

class UploadPanelStore {
  constructor(rootStore) {
    this.rootStore = rootStore;
  }

  // ============================================================
  // 状态
  // ============================================================
  
  /**
   * 传输面板是否可见
   * @type {boolean}
   */
  @observable visible = false;

  // ============================================================
  // Actions
  // ============================================================

  /**
   * 显示上传面板
   */
  @action.bound
  show() {
    this.visible = true;
  }

  /**
   * 隐藏上传面板
   */
  @action.bound
  hide() {
    this.visible = false;
  }

  /**
   * 切换面板显示状态
   */
  @action.bound
  toggle() {
    this.visible = !this.visible;
  }
}

export default UploadPanelStore;
