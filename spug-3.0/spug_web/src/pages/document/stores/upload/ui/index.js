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
  }

  // ============================================================
  // 兼容原 API 的代理属性
  // ============================================================

  // ----- 面板相关 -----
  // 【重构 2026-06-06】抽屉模式：uploadPanelVisible 等同于 panel.expanded
  // 旧代码（Popover 显示/隐藏）现在用 panel.expanded 控制 Drawer 展开
  get uploadPanelVisible() {
    return this.panel.expanded;
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

// 导出类（供 RootStore 创建实例和单元测试使用）
export { UploadUIStore };

// ========== 向后兼容 ==========
// 旧组件使用: import uploadUIStore from './stores/upload/ui'
// 新组件应使用: import rootStore from './stores'; rootStore.uploadUIStore
// 
// 使用 Proxy 实现延迟绑定：default export 指向 RootStore 中的实例，
// 避免循环依赖，同时保证旧代码拿到的是 RootStore 管理的同一实例。
let _rootStoreUploadUIStore = null;

export function _bindUploadUIStore(instance) {
  _rootStoreUploadUIStore = instance;
}

// default export 是一个 Proxy，所有属性访问委托给 RootStore 中的实例
const uploadUIStoreProxy = typeof Proxy !== 'undefined' 
  ? new Proxy({}, {
      get(_target, prop) {
        const store = _rootStoreUploadUIStore;
        if (!store) {
          return undefined;
        }
        const value = store[prop];
        if (typeof value === 'function') {
          return value.bind(store);
        }
        return value;
      }
    })
  : new UploadUIStore(); // 不支持 Proxy 的环境降级为独立实例

export default uploadUIStoreProxy;
