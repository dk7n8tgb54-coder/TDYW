/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * RecycleBinBusinessStore - 回收站业务逻辑管理
 * 职责：处理业务逻辑（数据获取、恢复、删除等）
 */
import { observable, action } from 'mobx';
import * as service from '../service';

class RecycleBinBusinessStore {
  @observable items = [];
  @observable total = 0;
  @observable stats = {
    total_count: 0, total_size: 0,
    private_count: 0, private_size: 0,
    public_count: 0, public_size: 0,
    expiring_soon: 0, retention_days: 30
  };
  @observable folderContent = [];
  @observable folderContentTotal = 0;

  _requestId = 0;
  _abortController = null;

  /**
   * 获取回收站列表
   */
  @action
  fetchList = async (params) => {
    const requestId = ++this._requestId;
    this._abortController = new AbortController();

    try {
      const data = await service.getRecycleBinList({
        page: params.page,
        page_size: params.pageSize,
        keyword: params.keyword,
        space: params.space,
      }, this._abortController.signal);

      if (requestId !== this._requestId) return null;

      // 去重：防止后端返回重复id导致React key警告
      const uniqueItems = Array.from(new Map((data.items || []).map(item => [item.id, item])).values());
      this.items = uniqueItems;
      this.total = data.total || 0;
      return data;
    } catch (error) {
      if (error.name !== 'AbortError') throw error;
      return null;
    }
  };

  /**
   * 获取统计数据
   */
  @action
  fetchStats = async () => {
    const data = await service.getRecycleBinStats();
    this.stats = { ...this.stats, ...data };
    return data;
  };

  /**
   * 刷新列表和统计
   */
  refresh = async (params) => {
    await Promise.all([this.fetchList(params), this.fetchStats()]);
  };

  /**
   * 执行恢复操作
   */
  @action
  doRestore = async (selectedRows, idempotentKey) => {
    const fileIds = selectedRows.filter(r => r.type !== 'folder').map(r => r.id);
    const folderIds = selectedRows.filter(r => r.type === 'folder').map(r => r.id);

    const results = { fileResult: null, folderResult: null };

    if (fileIds.length > 0) {
      results.fileResult = await service.restoreFiles({
        file_ids: fileIds,
        idempotent_key: idempotentKey,
      });
    }

    if (folderIds.length > 0) {
      results.folderResult = await service.restoreFolders({
        folder_ids: folderIds,
        restore_mode: 'original',
        idempotent_key: idempotentKey,
      });
    }

    return results;
  };

  /**
   * 执行删除操作
   */
  @action
  doDelete = async (selectedRows) => {
    const fileIds = selectedRows.filter(r => r.type !== 'folder').map(r => r.id);
    const folderIds = selectedRows.filter(r => r.type === 'folder').map(r => r.id);

    const results = { fileResult: null, folderResult: null, asyncTasks: [] };

    if (fileIds.length > 0) {
      results.fileResult = await service.permanentDeleteFiles({
        file_ids: fileIds,
        async_mode: true,
      });
      if (results.fileResult?.async && results.fileResult?.task_id) {
        results.asyncTasks.push({
          taskId: results.fileResult.task_id,
          fileName: `文件 (${fileIds.length}个)`,
          type: 'file',
          count: fileIds.length,
        });
      }
    }

    if (folderIds.length > 0) {
      results.folderResult = await service.permanentDeleteFolders({
        folder_ids: folderIds,
        async_mode: true,
      });
      if (results.folderResult?.async && results.folderResult?.task_id) {
        results.asyncTasks.push({
          taskId: results.folderResult.task_id,
          fileName: `文件夹 (${folderIds.length}个)`,
          type: 'folder',
          count: folderIds.length,
        });
      }
    }

    return results;
  };

  /**
   * 轮询删除任务进度
   */
  pollDeleteProgress = async (tasks, onUpdate, onComplete) => {
    const maxAttempts = 120;
    const interval = 2000;
    const pendingTasks = new Set(tasks.map(t => t.taskId));

    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      if (pendingTasks.size === 0) break;
      await new Promise(resolve => setTimeout(resolve, interval));

      const checkPromises = Array.from(pendingTasks).map(async (taskId) => {
        try {
          const status = await service.getTaskStatus(taskId);
          onUpdate(taskId, {
            progress: status.progress || 0,
            status: status.state,
            message: this._getStatusMessage(status),
          });

          if (status.ready) {
            pendingTasks.delete(taskId);
            onUpdate(taskId, {
              progress: status.successful ? 100 : 0,
              status: status.successful ? 'SUCCESS' : 'FAILURE',
              message: status.successful ? '删除成功' : (status.error || '删除失败'),
            });
          }
          return { taskId, status };
        } catch (error) {
          console.error(`[RecycleBin] 查询任务状态失败: ${taskId}`, error);
          return { taskId, error };
        }
      });

      await Promise.all(checkPromises);
    }

    onComplete();
  };

  _getStatusMessage = (status) => {
    if (status.state === 'PENDING') return '等待中...';
    if (status.state === 'STARTED') return '开始执行...';
    if (status.state === 'PROGRESS') return `正在删除... ${status.progress || 0}%`;
    if (status.state === 'SUCCESS') return '删除成功';
    if (status.state === 'FAILURE') return status.error || '删除失败';
    return status.state;
  };

  /**
   * 获取文件夹内容
   */
  @action
  fetchFolderContent = async (folderId, space, page, pageSize) => {
    const data = await service.getFolderContent({
      folder_id: folderId,
      space: space,
      page: page,
      page_size: pageSize,
    });

    // 去重：防止后端返回重复id导致React key警告
    const uniqueItems = Array.from(new Map((data.items || []).map(item => [item.id, item])).values());
    this.folderContent = uniqueItems;
    this.folderContentTotal = data.total || 0;
    return data;
  };

  /**
   * 取消进行中的请求
   */
  cancelPendingRequests = () => {
    this._requestId++;
    if (this._abortController) {
      this._abortController.abort();
      this._abortController = null;
    }
  };

  /**
   * 重置状态
   */
  @action
  reset = () => {
    this.items = [];
    this.total = 0;
    this.folderContent = [];
    this.folderContentTotal = 0;
    this.cancelPendingRequests();
  };
}

export default new RecycleBinBusinessStore();
