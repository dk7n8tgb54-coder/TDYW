/**
 * UploadPanelStore - 上传面板状态管理
 *
 * 职责：管理上传传输面板的显示/隐藏/展开状态
 * 抽屉模式（仿百度网盘）：
 *   - 收起态：底部小条（h=40px），不挡视野
 *   - 展开态：底部抽屉（h=60% 屏幕高度），显示完整列表
 *
 * 状态机：
 *   - collapsed: 抽屉完全隐藏
 *   - mini:      仅显示底部小条（默认）
 *   - expanded:  抽屉展开（显示完整列表）
 */
import { observable, action, computed } from 'mobx';

class UploadPanelStore {
  constructor(rootStore) {
    this.rootStore = rootStore;
  }

  // ============================================================
  // 状态
  // ============================================================

  /**
   * 抽屉是否展开（true=完整列表，false=仅小条）
   * @type {boolean}
   */
  @observable expanded = false;

  // ============================================================
  // Computed
  // ============================================================

  /**
   * 抽屉是否完全隐藏（无任务时）
   * 由上层根据 totalTaskCount > 0 决定是否挂载
   */
  @computed
  get isVisible() {
    return this.expanded;
  }

  // ============================================================
  // Actions
  // ============================================================

  /**
   * 展开抽屉（点击小条触发）
   */
  @action.bound
  expand() {
    this.expanded = true;
  }

  /**
   * 收起抽屉（拖到底部或点击关闭）
   */
  @action.bound
  collapse() {
    this.expanded = false;
  }

  /**
   * 切换展开/收起
   */
  @action.bound
  toggle() {
    this.expanded = !this.expanded;
  }

  /**
   * 显示/隐藏面板（兼容旧 API，等同于 expand/collapse）
   */
  @action.bound
  show() {
    this.expanded = true;
  }

  @action.bound
  hide() {
    this.expanded = false;
  }

}

export default UploadPanelStore;
