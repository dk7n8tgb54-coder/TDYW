/**
 * UploadUIStore - UI状态管理组合器
 * 
 * 职责：组合 Panel 和 Modal 两个子模块，提供统一的 UI 状态管理接口
 * 保持与原 UploadUIStore 的 API 兼容
 */
import { observable, action } from 'mobx';
import UploadPanelStore from './panel';
import UploadModalStore from './modal';

class UploadUIStore {
  constructor(rootStore = null) {
    this.rootStore = rootStore;
    
    // 初始化子模块
    this.panel = new UploadPanelStore(rootStore);
    this.modal = new UploadModalStore(rootStore);
    
    // 如果没有传入 rootStore，尝试从 window 获取（开发调试用）
    if (!this.rootStore && typeof window !== 'undefined' && window.__ROOT_STORE__) {
      this.rootStore = window.__ROOT_STORE__;
    }
  }

  // ============================================================
  // 兼容原 API 的代理属性
  // ============================================================

  // ----- 面板相关 -----
  get uploadPanelVisible() {
    return this.panel.visible;
  }

  // ----- 弹窗相关 -----
  get uploadVisible() {
    return this.modal.uploadVisible;
  }

  get uploadFolderVisible() {
    return this.modal.uploadFolderVisible;
  }

  get previewVisible() {
    return this.modal.previewVisible;
  }

  get previewFile() {
    return this.modal.previewFile;
  }

  // ============================================================
  // 兼容原 API 的代理方法
  // ============================================================

  // ----- 面板方法 -----
  /**
   * 显示上传面板
   */
  @action.bound
  showUploadPanel() {
    return this.panel.show();
  }

  /**
   * 隐藏上传面板
   */
  @action.bound
  hideUploadPanel() {
    return this.panel.hide();
  }

  // ----- 文件上传弹窗方法 -----
  /**
   * 打开文件上传弹窗
   */
  @action.bound
  handleUpload() {
    return this.modal.openUpload();
  }

  /**
   * 关闭文件上传弹窗
   */
  @action.bound
  closeUpload() {
    return this.modal.closeUpload();
  }

  // ----- 文件夹上传弹窗方法 -----
  /**
   * 打开文件夹上传弹窗
   */
  @action.bound
  handleUploadFolder() {
    return this.modal.openUploadFolder();
  }

  /**
   * 关闭文件夹上传弹窗
   */
  @action.bound
  closeUploadFolder() {
    return this.modal.closeUploadFolder();
  }

  // ----- 预览弹窗方法 -----
  /**
   * 打开预览弹窗
   * @param {object} file - 预览的文件对象
   */
  @action.bound
  handlePreview(file) {
    return this.modal.openPreview(file);
  }

  /**
   * 关闭预览弹窗
   */
  @action.bound
  closePreview() {
    return this.modal.closePreview();
  }
}

// 创建单例实例（保持向后兼容）
const uploadUIStore = new UploadUIStore();
export default uploadUIStore;
