/**
 * NavigationSync - URL同步管理
 * 
 * 职责：处理浏览器URL与导航状态的同步
 * 支持通过URL参数分享当前位置
 */
class NavigationSync {
  constructor(navigationStore) {
    this.store = navigationStore;
    this.syncEnabled = true;
  }

  // ============================================================
  // URL参数管理
  // ============================================================

  /**
   * 从URL解析导航状态
   * @returns {object|null} 解析后的状态 { folderId, isPublic, path }
   */
  parseFromUrl() {
    try {
      const params = new URLSearchParams(window.location.search);
      const folderId = params.get('folder');
      const isPublic = params.get('space') === 'public';
      
      if (!folderId) return null;

      return {
        folderId: parseInt(folderId, 10),
        isPublic,
        path: this.parsePathFromUrl(params.get('path'))
      };
    } catch (error) {
      console.warn('解析URL导航参数失败:', error);
      return null;
    }
  }

  /**
   * 将当前导航状态同步到URL
   * 不触发页面刷新
   */
  syncToUrl() {
    if (!this.syncEnabled) return;

    try {
      const params = new URLSearchParams();
      
      // 设置空间类型
      if (this.store.isPublic) {
        params.set('space', 'public');
      }

      // 设置当前文件夹
      if (this.store.currentFolderId) {
        params.set('folder', this.store.currentFolderId.toString());
      }

      // 设置路径（可选，用于更精确的状态恢复）
      const pathStr = this.serializePathToUrl();
      if (pathStr) {
        params.set('path', pathStr);
      }

      // 构建新URL
      const newUrl = params.toString()
        ? `${window.location.pathname}?${params.toString()}`
        : window.location.pathname;

      // 使用 replaceState 避免污染历史记录
      window.history.replaceState(
        { 
          folderId: this.store.currentFolderId,
          isPublic: this.store.isPublic 
        },
        '',
        newUrl
      );
    } catch (error) {
      console.warn('同步导航状态到URL失败:', error);
    }
  }

  /**
   * 从URL参数解析路径
   * @param {string} pathStr - 路径字符串，格式：id:name/id:name/...
   * @returns {Array} 路径数组
   */
  parsePathFromUrl(pathStr) {
    if (!pathStr) return [];
    
    try {
      return pathStr.split('/').map(segment => {
        const [id, name] = segment.split(':');
        return {
          id: parseInt(id, 10),
          name: decodeURIComponent(name || '')
        };
      });
    } catch (error) {
      console.warn('解析路径参数失败:', error);
      return [];
    }
  }

  /**
   * 将路径序列化为URL参数
   * @returns {string} 路径字符串
   */
  serializePathToUrl() {
    if (!this.store.path?.length) return '';
    
    return this.store.path
      .map(p => `${p.id}:${encodeURIComponent(p.name)}`)
      .join('/');
  }

  // ============================================================
  // 同步控制
  // ============================================================

  /**
   * 启用URL同步
   */
  enable() {
    this.syncEnabled = true;
    this.syncToUrl();
  }

  /**
   * 禁用URL同步
   */
  disable() {
    this.syncEnabled = false;
  }

  /**
   * 获取分享链接
   * @returns {string} 包含当前导航状态的完整URL
   */
  getShareUrl() {
    return window.location.href;
  }
}

export default NavigationSync;
