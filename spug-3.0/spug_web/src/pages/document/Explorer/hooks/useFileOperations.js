/**
 * 文件操作 Hook
 * 严格遵循原始 Explorer.js 的实现
 */
import { useCallback } from 'react';
import { Modal, message } from 'antd';
import http from 'libs/http';
import { CONSTANTS, getDeleteTimeout } from '../utils';

export const useFileOperations = ({
  isPublic,
  folderId,
  refresh,
  onFolderChange,
}) => {
  // 删除文件/文件夹
  const handleDelete = useCallback(async (record) => {
    const isAdmin = localStorage.getItem('is_supper') === 'true';
    const currentUserId = parseInt(localStorage.getItem('id') || '0');
    const displayName = record.display_name || record.name;

    // 权限检查
    if (isPublic && !isAdmin && record.created_by_id !== currentUserId) {
      message.warning(`您没有权限删除此${record.isFolder ? '文件夹' : '文件'}`);
      return;
    }

    let content;
    if (record.isFolder) {
      content = isPublic
        ? `确定要删除公共文件夹 "${displayName}" 及其所有内容吗？删除后所有用户均无法访问此文件夹，此操作不可恢复。`
        : `确定要删除文件夹 "${displayName}" 及其所有内容吗？此操作不可恢复。`;
    } else {
      content = isPublic
        ? `确定要删除公共文件 "${displayName}" 吗？删除后所有用户均无法访问此文件，此操作不可恢复。`
        : `确定要删除文件 "${displayName}" 吗？`;
    }

    Modal.confirm({
      title: '删除确认',
      content,
      onOk: async () => {
        try {
          const url = record.isFolder ? '/api/document/folder/' : '/api/document/file/';
          await http.delete(url, {
            params: { id: record.id, is_public: isPublic },
            timeout: getDeleteTimeout()
          });
          message.success('删除成功');
          if (refresh) refresh(true);
          if (record.isFolder && onFolderChange) {
            onFolderChange();
          }
        } catch (e) {
          message.error(e.message || '删除失败');
        }
      }
    });
  }, [isPublic, refresh, onFolderChange]);

  // 批量删除
  const handleDeleteSelected = useCallback(async (selectedRowKeys, items) => {
    if (!selectedRowKeys || selectedRowKeys.length === 0) {
      message.warning('请先选择要删除的项');
      return;
    }

    Modal.confirm({
      title: '批量删除',
      content: `确定要删除选中的 ${selectedRowKeys.length} 项吗？`,
      onOk: async () => {
        try {
          let succeeded = 0;
          let failed = 0;
          const batchSize = CONSTANTS.BATCH_DELETE_SIZE;

          const selectedItems = selectedRowKeys.map(key =>
            items.find(i => i.key === key)
          ).filter(Boolean);

          // 分批处理
          for (let i = 0; i < selectedItems.length; i += batchSize) {
            const batch = selectedItems.slice(i, i + batchSize);
            const batchPromises = batch.map(async (item) => {
              try {
                const url = item.isFolder ? '/api/document/folder/' : '/api/document/file/';
                await http.delete(url, {
                  params: { id: item.id, is_public: isPublic },
                  timeout: getDeleteTimeout()
                });
                return { status: 'success' };
              } catch (err) {
                console.error('删除失败:', err);
                return { status: 'failed', error: err };
              }
            });

            const results = await Promise.all(batchPromises);
            succeeded += results.filter(r => r.status === 'success').length;
            failed += results.filter(r => r.status === 'failed').length;

            // 批次之间添加短暂延迟
            if (i + batchSize < selectedItems.length) {
              await new Promise(resolve => setTimeout(resolve, 100));
            }
          }

          if (succeeded > 0) {
            message.success(`成功删除 ${succeeded} 项${failed > 0 ? `，${failed} 项失败` : ''}`);
            if (refresh) refresh(true);
            const hasDeletedFolders = selectedItems.some(item => item.isFolder);
            if (hasDeletedFolders && onFolderChange) {
              onFolderChange();
            }
          } else {
            message.error('删除失败');
          }
        } catch (e) {
          message.error(e.message || '删除失败');
        }
      }
    });
  }, [isPublic, refresh, onFolderChange]);

  // 下载文件
  const handleDownload = useCallback((file) => {
    const token = localStorage.getItem('token');
    const url = `/api/document/download/?id=${file.id}&is_public=${isPublic}&x-token=${token}`;
    window.open(url);
  }, [isPublic]);

  // 批量下载
  const handleDownloadSelected = useCallback((selectedRowKeys, items) => {
    const token = localStorage.getItem('token');
    const selectedItems = selectedRowKeys.map(key =>
      items.find(i => i.key === key)
    ).filter(item => item && !item.isFolder);

    selectedItems.forEach(item => {
      const url = `/api/document/download/?id=${item.id}&is_public=${isPublic}&x-token=${token}`;
      window.open(url);
    });
    message.success(`已开始下载 ${selectedItems.length} 个文件`);
  }, [isPublic]);

  // 下载文件夹
  const handleFolderDownload = useCallback((folder) => {
    const token = localStorage.getItem('token');
    const url = `/api/document/folder/download/?id=${folder.id}&is_public=${isPublic}&x-token=${token}`;
    window.open(url);
  }, [isPublic]);

  // 创建文件夹
  const handleCreateFolder = useCallback(async (name, parentId) => {
    if (!name) {
      message.error('请输入文件夹名称');
      return Promise.reject('请输入文件夹名称');
    }
    try {
      await http.post('/api/document/folder/', {
        name: name,
        parent_id: parentId || folderId,
        is_public: isPublic
      });
      message.success('创建成功');
      if (refresh) refresh(true);
      if (onFolderChange) onFolderChange();
    } catch (e) {
      message.error(e.message || '创建失败');
      return Promise.reject(e.message || '创建失败');
    }
  }, [isPublic, folderId, refresh, onFolderChange]);

  // 重命名
  const handleRename = useCallback(async (record, newName) => {
    try {
      const url = record.isFolder ? '/api/document/folder/rename/' : '/api/document/file/rename/';
      await http.post(url, {
        id: record.id,
        name: newName,
        is_public: isPublic
      });
      message.success('重命名成功');
      if (refresh) refresh(true);
      if (record.isFolder && onFolderChange) {
        onFolderChange();
      }
    } catch (e) {
      message.error(e.message || '重命名失败');
      return Promise.reject(e.message || '重命名失败');
    }
  }, [isPublic, refresh, onFolderChange]);

  // 执行复制操作
  const handleCopyItems = useCallback(async (items, targetFolderId) => {
    let successCount = 0;
    let failCount = 0;
    const failedItems = [];

    try {
      const BATCH_SIZE = 3;
      for (let i = 0; i < items.length; i += BATCH_SIZE) {
        const batch = items.slice(i, i + BATCH_SIZE);
        const results = await Promise.allSettled(
          batch.map(async (item) => {
            if (item.isFolder) {
              await http.post('/api/document/folder/copy/', {
                id: item.id,
                target_id: targetFolderId,
                is_public: isPublic
              }, { timeout: 300000 });
            } else {
              await http.post('/api/document/file/copy/', {
                id: item.id,
                folder_id: targetFolderId,
                is_public: isPublic
              }, { timeout: 300000 });
            }
          })
        );

        for (let j = 0; j < results.length; j++) {
          const result = results[j];
          if (result.status === 'fulfilled') {
            successCount++;
          } else {
            failCount++;
            failedItems.push(items[i + j].name);
            console.error('[文档] 复制失败:', items[i + j].name, result.reason);
          }
        }
      }

      if (failCount === 0) {
        message.success(`已复制 ${items.length} 项`);
      } else if (successCount === 0) {
        message.error(`复制失败，所有 ${failCount} 项均复制失败`);
      } else {
        message.warning(`复制完成：成功 ${successCount} 项，失败 ${failCount} 项`);
      }

      if (refresh) refresh(true);
      const hasCopiedFolders = items.some(item => item.isFolder);
      if (hasCopiedFolders && onFolderChange) {
        onFolderChange();
      }
    } catch (e) {
      const errorMsg = e.message || '复制失败';
      if (errorMsg.includes('timeout') || errorMsg.includes('30000')) {
        message.error('文件较大，复制超时，请重试');
      } else {
        message.error(errorMsg);
      }
      throw e;
    }
  }, [isPublic, refresh, onFolderChange]);

  // 执行移动操作
  const handleMoveItems = useCallback(async (items, targetFolderId) => {
    try {
      const movePromises = items.map(async (item) => {
        if (item.isFolder) {
          await http.post('/api/document/folder/move/', {
            id: item.id,
            target_id: targetFolderId,
            is_public: isPublic
          });
        } else {
          await http.post('/api/document/file/move/', {
            id: item.id,
            target_id: targetFolderId,
            is_public: isPublic
          });
        }
      });

      await Promise.all(movePromises);

      message.success(`已移动 ${items.length} 项`);
      if (refresh) refresh(true);
      const hasMovedFolders = items.some(item => item.isFolder);
      if (hasMovedFolders && onFolderChange) {
        onFolderChange();
      }
    } catch (e) {
      message.error(e.message || '移动失败');
      throw e;
    }
  }, [isPublic, refresh, onFolderChange]);

  return {
    handleDelete,
    handleDeleteSelected,
    handleDownload,
    handleDownloadSelected,
    handleFolderDownload,
    handleCreateFolder,
    handleRename,
    handleCopyItems,
    handleMoveItems,
  };
};
