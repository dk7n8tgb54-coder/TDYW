/**
 * UploadModalStore - 上传弹窗状态管理
 * 
 * 【迁移说明】
 * - 文件上传弹窗和文件夹上传弹窗已移除（使用新上传系统）
 * - 仅保留预览弹窗功能
 * 
 * 职责：管理文件预览弹窗的状态
 */
import { observable, action } from 'mobx';

class UploadModalStore {
  constructor(rootStore) {
    this.rootStore = rootStore;
  }

  // ============================================================
  // 【已移除】文件/文件夹上传弹窗状态
  // ============================================================
  // 【迁移】旧上传弹窗已移除，以下状态不再使用：
  // - uploadVisible: 文件上传弹窗可见性
  // - uploadFolderVisible: 文件夹上传弹窗可见性
  // 
  // 新上传系统使用 UploadPanel.js 显示上传进度
  // 入口：index.js 中的上传按钮调用 uploadCoreStore.handleFileSelect/handleFolderSelect

  // ============================================================
  // 预览弹窗状态
  // ============================================================
  
  /**
   * 预览弹窗是否可见
   * @type {boolean}
   */
  @observable previewVisible = false;

  /**
   * 当前预览的文件
   * @type {object|null}
   */
  @observable previewFile = null;

  // ============================================================
  // 【已移除】文件/文件夹上传弹窗 Actions
  // ============================================================
  // 【迁移】以下方法不再使用：
  // - openUpload/closeUpload: 文件上传弹窗控制
  // - openUploadFolder/closeUploadFolder: 文件夹上传弹窗控制
  //
  // 新上传系统通过文件选择器触发，无需弹窗控制

  // ============================================================
  // 预览弹窗 Actions
  // ============================================================

  /**
   * 打开预览弹窗
   * @param {object} file - 预览的文件对象
   */
  @action.bound
  openPreview(file) {
    this.previewFile = file;
    this.previewVisible = true;
  }

  /**
   * 关闭预览弹窗
   */
  @action.bound
  closePreview() {
    this.previewVisible = false;
    this.previewFile = null;
  }

  /**
   * 切换预览弹窗
   * @param {object} file - 预览的文件对象
   */
  @action.bound
  togglePreview(file) {
    if (this.previewVisible) {
      this.closePreview();
    } else {
      this.openPreview(file);
    }
  }
}

export default UploadModalStore;
