/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * RecycleBinStore - 回收站统一状态管理
 * 组合 UIStore 和 BusinessStore，提供统一的业务接口
 */
import { action } from 'mobx';
import uiStore from './RecycleBinUIStore';
import businessStore from './RecycleBinBusinessStore';
import { message } from 'antd';

class RecycleBinStore {
  // ========== 委托 UIStore 的状态 ==========
  get loading() { return uiStore.loading; }
  get statsLoading() { return uiStore.statsLoading; }
  get operationLoading() { return uiStore.operationLoading; }
  get keyword() { return uiStore.keyword; }
  get space() { return uiStore.space; }
  get page() { return uiStore.page; }
  get pageSize() { return uiStore.pageSize; }
  get selectedRowKeys() { return uiStore.selectedRowKeys; }
  get selectedRows() { return uiStore.selectedRows; }
  get restoreVisible() { return uiStore.restoreVisible; }
  get deleteVisible() { return uiStore.deleteVisible; }
  get restoreMode() { return uiStore.restoreMode; }
  get targetFolderId() { return uiStore.targetFolderId; }
  get deleteProgressVisible() { return uiStore.deleteProgressVisible; }
  get deleteTasks() { return uiStore.deleteTasks; }
  get currentFolder() { return uiStore.currentFolder; }
  get folderContentPage() { return uiStore.folderContentPage; }

  // ========== 委托 BusinessStore 的状态 ==========
  get items() { return businessStore.items; }
  get total() { return businessStore.total; }
  get stats() { return businessStore.stats; }
  get folderContent() { return businessStore.folderContent; }
  get folderContentTotal() { return businessStore.folderContentTotal; }

  // ========== 计算属性 ==========
  get hasSelected() { return uiStore.hasSelected; }
  get selectedCount() { return uiStore.selectedCount; }
  get selectedTotalSize() { return uiStore.selectedTotalSize; }

  // ========== UI Actions ==========
  setLoading = (loading) => uiStore.setLoading(loading);
  setStatsLoading = (loading) => uiStore.setStatsLoading(loading);
  setOperationLoading = (loading) => uiStore.setOperationLoading(loading);
  setKeyword = (keyword) => uiStore.setKeyword(keyword);
  setSpace = (space) => uiStore.setSpace(space);
  setPage = (page) => uiStore.setPage(page);
  setPageSize = (pageSize) => uiStore.setPageSize(pageSize);
  setSelectedRows = (keys, rows) => uiStore.setSelectedRows(keys, rows);
  clearSelection = () => uiStore.clearSelection();
  showRestoreModal = () => uiStore.showRestoreModal();
  hideRestoreModal = () => uiStore.hideRestoreModal();
  setRestoreMode = (mode) => uiStore.setRestoreMode(mode);
  setTargetFolderId = (folderId) => uiStore.setTargetFolderId(folderId);
  showDeleteModal = () => uiStore.showDeleteModal();
  hideDeleteModal = () => uiStore.hideDeleteModal();
  hideDeleteProgress = () => uiStore.hideDeleteProgress();
  enterFolder = (folder) => uiStore.enterFolder(folder);
  exitFolder = () => uiStore.exitFolder();
  setFolderContentPage = (page) => uiStore.setFolderContentPage(page);

  // ========== 业务 Actions ==========

  /**
   * 获取回收站列表
   */
  @action
  fetchList = async () => {
    this.setLoading(true);
    try {
      await businessStore.fetchList({
        page: this.page,
        pageSize: this.pageSize,
        keyword: this.keyword,
        space: this.space,
      });
    } finally {
      this.setLoading(false);
    }
  };

  /**
   * 获取统计数据
   */
  @action
  fetchStats = async () => {
    this.setStatsLoading(true);
    try {
      await businessStore.fetchStats();
    } finally {
      this.setStatsLoading(false);
    }
  };

  /**
   * 刷新列表和统计
   */
  @action
  refresh = async () => {
    this.setLoading(true);
    this.setStatsLoading(true);
    try {
      await businessStore.refresh({
        page: this.page,
        pageSize: this.pageSize,
        keyword: this.keyword,
        space: this.space,
      });
    } finally {
      this.setLoading(false);
      this.setStatsLoading(false);
    }
  };

  /**
   * 执行恢复
   */
  @action
  doRestore = async () => {
    if (!this.hasSelected) {
      message.warning('请选择要恢复的项目');
      return;
    }

    this.setOperationLoading(true);
    try {
      const idempotentKey = Date.now().toString();
      const results = await businessStore.doRestore(
        this.selectedRows,
        this.restoreMode,
        this.targetFolderId,
        idempotentKey
      );

      const fileSuccess = results.fileResult?.success_count || 0;
      const fileFailed = results.fileResult?.failed_count || 0;
      const folderSuccess = results.folderResult?.success_count || 0;
      const folderFailed = results.folderResult?.failed_count || 0;
      const totalSuccess = fileSuccess + folderSuccess;
      const totalFailed = fileFailed + folderFailed;

      if (totalFailed > 0) {
        message.warning(`恢复完成：成功${totalSuccess}个，失败${totalFailed}个`);
      } else {
        message.success(`成功恢复${totalSuccess}个项目`);
      }

      this.hideRestoreModal();
      this.clearSelection();
      await this.refresh();

      return results;
    } catch (error) {
      message.error('恢复失败');
      throw error;
    } finally {
      this.setOperationLoading(false);
    }
  };

  /**
   * 执行删除
   */
  @action
  doPermanentDelete = async () => {
    if (!this.hasSelected) {
      message.warning('请选择要删除的项目');
      return;
    }

    this.setOperationLoading(true);
    try {
      const results = await businessStore.doDelete(this.selectedRows);

      if (results.asyncTasks.length > 0) {
        this.hideDeleteModal(); // 【修复】异步删除时关闭确认对话框
        uiStore.showDeleteProgress(results.asyncTasks);
        businessStore.pollDeleteProgress(
          results.asyncTasks,
          (taskId, update) => uiStore.updateDeleteTask(taskId, update),
          () => {
            setTimeout(() => {
              uiStore.hideDeleteProgress();
              this.clearSelection();
              this.refresh();
            }, 1500);
          }
        );
      } else {
        const totalSuccess = (results.fileResult?.success_count || 0) + (results.folderResult?.success_count || 0);
        const totalFreed = (results.fileResult?.freed_space || 0) + (results.folderResult?.freed_space || 0);
        message.success(`成功删除${totalSuccess}个项目，释放${this._formatFileSize(totalFreed)}`);
        this.hideDeleteModal();
        this.clearSelection();
        await this.refresh();
      }

      return results;
    } catch (error) {
      message.error('删除失败');
      throw error;
    } finally {
      this.setOperationLoading(false);
    }
  };

  /**
   * 获取文件夹内容
   */
  @action
  fetchFolderContent = async () => {
    if (!this.currentFolder) return;
    this.setLoading(true);
    try {
      await businessStore.fetchFolderContent(
        this.currentFolder.id,
        this.currentFolder.space,
        this.folderContentPage,
        uiStore.folderContentPageSize
      );
    } finally {
      this.setLoading(false);
    }
  };

  /**
   * 进入子文件夹
   */
  @action
  enterSubFolder = (folder) => {
    uiStore.enterSubFolder(folder);
    this.fetchFolderContent();
  };

  /**
   * 返回上级文件夹
   */
  @action
  goToParentFolder = () => {
    if (!this.currentFolder?.parent_chain?.length) {
      this.exitFolder();
      return;
    }
    const parentChain = [...this.currentFolder.parent_chain];
    const parent = parentChain.pop();
    uiStore.currentFolder = {
      id: parent.id,
      name: parent.name,
      space: this.currentFolder.space,
      parent_chain: parentChain,
    };
    uiStore.folderContentPage = 1;
    this.clearSelection();
    this.fetchFolderContent();
  };

  /**
   * 重置所有状态
   */
  @action
  reset = () => {
    uiStore.reset();
    businessStore.reset();
  };

  // 【2.3重构】使用公共工具函数
  _formatFileSize = (size) => {
    const { formatFileSize } = require('@/utils/format');
    return formatFileSize(size);
  };
}

export default new RecycleBinStore();
