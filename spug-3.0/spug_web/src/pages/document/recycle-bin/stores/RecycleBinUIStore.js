/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * RecycleBinUIStore - 回收站UI状态管理
 * 职责：管理UI相关状态（弹窗显示、选中项、加载状态等）
 */
import { observable, action, computed } from 'mobx';
import { message } from 'antd';

class RecycleBinUIStore {
  @observable loading = false;
  @observable statsLoading = false;
  @observable operationLoading = false;
  @observable keyword = '';
  @observable space = 'all';
  @observable page = 1;
  @observable pageSize = 20;
  @observable selectedRowKeys = [];
  @observable selectedRows = [];
  @observable restoreVisible = false;
  @observable deleteVisible = false;
  @observable restoreMode = 'original';
  @observable targetFolderId = null;
  @observable deleteProgressVisible = false;
  @observable deleteTasks = new Map();
  @observable currentFolder = null;
  @observable folderContentPage = 1;
  @observable folderContentPageSize = 50;

  @computed get hasSelected() {
    return this.selectedRowKeys.length > 0;
  }

  @computed get selectedCount() {
    return this.selectedRowKeys.length;
  }

  @computed get selectedTotalSize() {
    return this.selectedRows.reduce((sum, row) => {
      const size = row.type === 'folder' ? (row.total_size || 0) : (row.file_size || 0);
      return sum + size;
    }, 0);
  }

  @action setLoading = (loading) => { this.loading = loading; };
  @action setStatsLoading = (loading) => { this.statsLoading = loading; };
  @action setOperationLoading = (loading) => { this.operationLoading = loading; };
  @action setKeyword = (keyword) => { this.keyword = keyword; this.page = 1; };
  @action setSpace = (space) => { this.space = space; this.page = 1; this.clearSelection(); };
  @action setPage = (page) => { this.page = page; };
  @action setPageSize = (pageSize) => { this.pageSize = pageSize; this.page = 1; };
  @action setSelectedRows = (keys, rows) => { this.selectedRowKeys = keys; this.selectedRows = rows; };
  @action clearSelection = () => { this.selectedRowKeys = []; this.selectedRows = []; };

  @action showRestoreModal = () => {
    if (!this.hasSelected) { message.warning('请选择要恢复的项目'); return false; }
    this.restoreMode = 'original';
    this.targetFolderId = null;
    this.restoreVisible = true;
    return true;
  };

  @action hideRestoreModal = () => { this.restoreVisible = false; };
  @action setRestoreMode = (mode) => { this.restoreMode = mode; };
  @action setTargetFolderId = (folderId) => { this.targetFolderId = folderId; };

  @action showDeleteModal = () => {
    if (!this.hasSelected) { message.warning('请选择要删除的项目'); return false; }
    this.deleteVisible = true;
    return true;
  };

  @action hideDeleteModal = () => { this.deleteVisible = false; };

  @action showDeleteProgress = (tasks) => {
    this.deleteProgressVisible = true;
    tasks.forEach(task => {
      this.deleteTasks.set(task.taskId, { fileName: task.fileName, progress: 0, status: 'PENDING', message: '等待中...' });
    });
  };

  @action updateDeleteTask = (taskId, update) => {
    const task = this.deleteTasks.get(taskId);
    if (task) this.deleteTasks.set(taskId, { ...task, ...update });
  };

  @action hideDeleteProgress = () => { this.deleteProgressVisible = false; this.deleteTasks.clear(); };

  @action enterFolder = (folder) => {
    this.currentFolder = { id: folder.id, name: folder.name, space: folder.space, parent_chain: [] };
    this.folderContentPage = 1;
    this.clearSelection();
  };

  @action exitFolder = () => { this.currentFolder = null; this.folderContentPage = 1; this.clearSelection(); };
  @action setFolderContentPage = (page) => { this.folderContentPage = page; };

  @action enterSubFolder = (folder) => {
    if (this.currentFolder) {
      const current = { id: this.currentFolder.id, name: this.currentFolder.name };
      this.currentFolder.parent_chain = [...(this.currentFolder.parent_chain || []), current];
    }
    this.enterFolder(folder);
  };

  @action reset = () => {
    this.loading = false;
    this.keyword = '';
    this.space = 'all';
    this.page = 1;
    this.clearSelection();
    this.restoreVisible = false;
    this.deleteVisible = false;
    this.deleteProgressVisible = false;
    this.deleteTasks.clear();
    this.currentFolder = null;
    this.folderContentPage = 1;
  };
}

export default new RecycleBinUIStore();
