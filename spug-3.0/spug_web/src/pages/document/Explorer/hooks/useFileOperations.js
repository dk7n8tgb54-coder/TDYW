/**
 * 文件操作 Hook
 * 严格遵循原始 Explorer.js 的实现
 */
import { useCallback, useState, useRef } from 'react';
import { Modal, message } from 'antd';
import http from 'libs/http';
import { appendSystemFolderParam, withSystemFolderParams } from 'libs/systemFolderContext';
import { CONSTANTS, getDeleteTimeout } from '../utils';

export const useFileOperations = ({
  isPublic,
  folderId,
  refresh,
  onFolderChange,
}) => {
  // 冲突弹窗状态
  const [conflictState, setConflictState] = useState({
    visible: false,
    conflicts: [],
    pendingOps: [],
    operationType: null,
    summary: { success: 0, fail: 0, skip: 0 },
  });

  // 跟踪异步复制任务，避免重复轮询
  const pollingCopyTransfersRef = useRef(new Set());

  // 轮询异步复制任务状态，完成时提示
  const pollAsyncCopyStatus = useCallback((transferIds) => {
    const ids = transferIds.filter(id => id && !pollingCopyTransfersRef.current.has(id));
    if (ids.length === 0) return;
    ids.forEach(id => pollingCopyTransfersRef.current.add(id));

    let pollCount = 0;
    const MAX_POLLS = 120; // 最多轮询 10 分钟（5s * 120）
    const POLL_INTERVAL = 5000;

    const poll = async () => {
      pollCount++;
      try {
        const resp = await http.get('/api/document/transfers/', {
          params: { transfer_type: 'COPY', is_public: isPublic }
        });
        const transfers = Array.isArray(resp) ? resp : (resp?.data || []);
        const completed = [];
        const failed = [];
        for (const id of ids) {
          const t = transfers.find(x => x.id === id);
          if (!t) continue;
          if (t.status === 'COMPLETED') {
            completed.push(t);
            pollingCopyTransfersRef.current.delete(id);
          } else if (t.status === 'FAILED') {
            failed.push(t);
            pollingCopyTransfersRef.current.delete(id);
          } else if (t.status === 'CANCELED') {
            pollingCopyTransfersRef.current.delete(id);
          }
        }
        // 提示完成的任务
        if (completed.length > 0) {
          if (completed.length === 1) {
            message.success(`"${completed[0].file_name}" 复制完成`);
          } else {
            message.success(`${completed.length} 项文件复制完成`);
          }
          if (refresh) refresh(true);
        }
        // 提示失败的任务
        for (const t of failed) {
          message.error(`"${t.file_name}" 复制失败: ${t.error_message || '未知错误'}`);
        }
        // 如果还有未完成的，继续轮询
        const remaining = ids.filter(id => pollingCopyTransfersRef.current.has(id));
        if (remaining.length > 0 && pollCount < MAX_POLLS) {
          setTimeout(poll, POLL_INTERVAL);
        } else {
          remaining.forEach(id => pollingCopyTransfersRef.current.delete(id));
        }
      } catch (e) {
        // 网络错误时继续轮询
        if (pollCount < MAX_POLLS) {
          setTimeout(poll, POLL_INTERVAL);
        } else {
          ids.forEach(id => pollingCopyTransfersRef.current.delete(id));
        }
      }
    };

    setTimeout(poll, POLL_INTERVAL);
  }, [refresh, isPublic]);

  // 统一批量结果提示
  const showBatchResult = useCallback((success, fail, skip = 0, pending = 0) => {
    if (pending > 0) {
      // 有后台复制中的大文件
      const parts = [];
      if (success > 0) parts.push(`成功 ${success}`);
      parts.push(`${pending} 项后台复制中`);
      if (skip > 0) parts.push(`跳过 ${skip}`);
      if (fail > 0) parts.push(`失败 ${fail}`);
      message.info(parts.join('，'));
    } else if (fail === 0 && skip === 0) {
      message.success(`成功 ${success} 项`);
    } else if (success === 0 && skip === 0) {
      message.error(`失败 ${fail} 项`);
    } else {
      const parts = [`成功 ${success}`];
      if (skip > 0) parts.push(`跳过 ${skip}`);
      if (fail > 0) parts.push(`失败 ${fail}`);
      message.warning(parts.join('，'));
    }
  }, []);
  // 删除文件/文件夹
  const handleDelete = useCallback(async (record) => {
    const isAdmin = sessionStorage.getItem('is_supper') === 'true';
    const currentUserId = parseInt(sessionStorage.getItem('id') || '0');
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
    const token = sessionStorage.getItem('token');
    const url = appendSystemFolderParam(`/api/document/download/?id=${file.id}&is_public=${isPublic}&x-token=${token}`);
    window.open(url);
  }, [isPublic]);

  // 批量下载
  const handleDownloadSelected = useCallback((selectedRowKeys, items) => {
    const token = sessionStorage.getItem('token');
    const selectedItems = selectedRowKeys.map(key =>
      items.find(i => i.key === key)
    ).filter(item => item && !item.isFolder);

    selectedItems.forEach(item => {
      const url = appendSystemFolderParam(`/api/document/download/?id=${item.id}&is_public=${isPublic}&x-token=${token}`);
      window.open(url);
    });
    message.success(`已开始下载 ${selectedItems.length} 个文件`);
  }, [isPublic]);

  // 轮询文件夹打包任务状态，完成后经 ready 接口取件
  const pollFolderPackTask = useCallback((taskId, token) => {
    const readyUrl = `/api/document/folder/download/ready/?task_id=${taskId}&x-token=${token}`;
    let pollCount = 0;
    let failureCount = 0;
    const MAX_POLLS = 600; // 打包最长等待 20 分钟（2s * 600）
    const POLL_INTERVAL = 2000;

    // 轮询回调已脱离用户手势上下文，用临时 anchor 触发下载，避免被弹窗拦截
    const triggerDownload = () => {
      const anchor = document.createElement('a');
      anchor.href = readyUrl;
      anchor.download = '';
      anchor.style.display = 'none';
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
    };

    const poll = async () => {
      pollCount += 1;
      try {
        const data = await http.get('/api/document/folder/download/status/', {
          params: { task_id: taskId },
          skipErrorNotification: true,
        });
        failureCount = 0;
        if (data && data.status === 'success') {
          triggerDownload();
          return;
        }
        if (data && data.status === 'failed') {
          message.error((data && data.error) || '文件夹打包失败');
          return;
        }
        if (pollCount >= MAX_POLLS) {
          message.error('文件夹打包超时，请稍后重试');
          return;
        }
        setTimeout(poll, POLL_INTERVAL);
      } catch (e) {
        // 状态查询失败（skipErrorNotification 已抑制拦截器弹窗）：
        // 瞬时网络抖动继续重试，连续失败达到阈值才提示一次
        failureCount += 1;
        if (failureCount >= 3) {
          message.error('查询打包进度失败，请稍后重试');
          return;
        }
        if (pollCount < MAX_POLLS) {
          setTimeout(poll, POLL_INTERVAL);
        }
      }
    };
    setTimeout(poll, POLL_INTERVAL);
  }, []);

  // 下载文件夹
  // 先以 probe=true 探测打包方式：小文件夹直接流式下载；大文件夹（≥100 个文件）
  // 在探测请求内提交异步打包任务，轮询状态后经 ready 接口触发下载，
  // 避免 window.open 直接收到大文件夹返回的任务 JSON 而无法下载。
  const handleFolderDownload = useCallback((folder) => {
    const token = sessionStorage.getItem('token');
    const url = appendSystemFolderParam(`/api/document/folder/download/?id=${folder.id}&is_public=${isPublic}&x-token=${token}`);
    http.get('/api/document/folder/download/', {
      params: withSystemFolderParams({
        id: folder.id,
        is_public: isPublic,
        probe: 'true',
      }),
    }).then((data) => {
      if (data && data.mode === 'async' && data.task_id) {
        message.info('文件夹较大，正在后台打包，完成后将自动开始下载');
        pollFolderPackTask(data.task_id, token);
      } else {
        window.open(url);
      }
    }).catch(() => {
      // 错误提示由 HTTP 拦截器统一负责，此处不再重复提示
    });
  }, [isPublic, pollFolderPackTask]);

  // 创建文件夹
  const handleCreateFolder = useCallback(async (name, parentId) => {
    if (!name) {
      return Promise.reject('请输入文件夹名称');
    }
    // 显式注入 system_folder（不依赖 HTTP 拦截器），确保党建目录上下文始终正确
    const body = withSystemFolderParams({
      name: name,
      parent_id: parentId || folderId,
      is_public: isPublic
    });
    const result = await http.post('/api/document/folder/', body);
    // 仅在真正创建时刷新列表和树；不在此处提示消息，由调用方统一负责
    if (result && result.created) {
      if (refresh) refresh(true);
      if (onFolderChange) onFolderChange();
    }
    return result;
  }, [isPublic, folderId, refresh, onFolderChange]);

  // 重命名
  // 注意：不在此处调用 message.success / message.error，通知由调用方 confirmRename 统一负责。
  // HTTP 拦截器已对后端 error 调用 message.error，此处再弹会导致重复提示。
  const handleRename = useCallback(async (record, newName) => {
    const url = record.isFolder ? '/api/document/folder/rename/' : '/api/document/file/rename/';
    await http.post(url, {
      id: record.id,
      name: newName,
      is_public: isPublic
    });
    // 成功后刷新列表（通知由 confirmRename 负责）
    if (refresh) refresh(true);
    if (record.isFolder && onFolderChange) {
      onFolderChange();
    }
  }, [isPublic, refresh, onFolderChange]);

  // 执行复制操作（带冲突检测）
  const handleCopyItems = useCallback(async (items, targetFolderId) => {
    let successCount = 0;
    let failCount = 0;
    let pendingCount = 0;
    const asyncTransferIds = [];
    const conflicts = [];
    const pendingOps = [];

    try {
      for (const item of items) {
        if (item.isFolder) {
          // 文件夹复制：直接执行
          try {
            const result = await http.post('/api/document/folder/copy/', {
              id: item.id, target_id: targetFolderId, is_public: isPublic
            }, { timeout: 300000 });
            // 文件夹复制可能返回 pending（包含大文件）
            if (result && result.status === 'pending') {
              pendingCount++;
              if (result.transfer_id) asyncTransferIds.push(result.transfer_id);
            } else {
              successCount++;
            }
          } catch (e) {
            failCount++;
          }
        } else {
          // 文件复制：先检查冲突
          try {
            const result = await http.post('/api/document/file/copy/', {
              id: item.id, folder_id: targetFolderId, is_public: isPublic
            }, { timeout: 300000 });
            if (result && result.status === 'conflict') {
              conflicts.push(result.conflicts[0]);
              pendingOps.push({ item, endpoint: '/api/document/file/copy/', targetFolderId, paramKey: 'folder_id' });
            } else if (result && result.status === 'pending') {
              // 大文件异步复制
              pendingCount++;
              if (result.transfer_id) asyncTransferIds.push(result.transfer_id);
            } else {
              successCount++;
            }
          } catch (e) {
            failCount++;
          }
        }
      }

      if (conflicts.length > 0) {
        setConflictState({
          visible: true, conflicts, pendingOps,
          operationType: 'copy',
          summary: { success: successCount, fail: failCount, skip: 0, pending: pendingCount },
          asyncTransferIds,
        });
      } else {
        showBatchResult(successCount, failCount, 0, pendingCount);
        if (refresh) refresh(true);
        // 传入目标目录：目标分支与当前分支（复制源）都要刷新
        if (items.some(i => i.isFolder) && onFolderChange) onFolderChange(targetFolderId);
        // 有后台复制任务时，启动轮询
        if (pendingCount > 0 && asyncTransferIds.length > 0) {
          pollAsyncCopyStatus(asyncTransferIds);
        }
      }
    } catch (e) {
      message.error(e.message || '复制失败');
      throw e;
    }
  }, [isPublic, refresh, onFolderChange, showBatchResult, pollAsyncCopyStatus]);

  // 执行移动操作（带冲突检测）
  const handleMoveItems = useCallback(async (items, targetFolderId) => {
    let successCount = 0;
    let failCount = 0;
    const conflicts = [];
    const pendingOps = [];

    try {
      for (const item of items) {
        if (item.isFolder) {
          // 文件夹移动：直接执行
          try {
            await http.post('/api/document/folder/move/', {
              id: item.id, target_id: targetFolderId, is_public: isPublic
            });
            successCount++;
          } catch (e) {
            failCount++;
          }
        } else {
          // 文件移动：先检查冲突
          try {
            const result = await http.post('/api/document/file/move/', {
              id: item.id, target_id: targetFolderId, is_public: isPublic
            });
            if (result && result.status === 'conflict') {
              conflicts.push(result.conflicts[0]);
              pendingOps.push({ item, endpoint: '/api/document/file/move/', targetFolderId, paramKey: 'target_id' });
            } else {
              successCount++;
            }
          } catch (e) {
            failCount++;
          }
        }
      }

      if (conflicts.length > 0) {
        setConflictState({
          visible: true, conflicts, pendingOps,
          operationType: 'move',
          summary: { success: successCount, fail: failCount, skip: 0 },
        });
      } else {
        showBatchResult(successCount, failCount);
        if (refresh) refresh(true);
        // 传入目标目录：目标分支与当前分支（移出方）都要刷新
        if (items.some(i => i.isFolder) && onFolderChange) onFolderChange(targetFolderId);
      }
    } catch (e) {
      message.error(e.message || '移动失败');
      throw e;
    }
  }, [isPublic, refresh, onFolderChange, showBatchResult]);

  // 解决冲突（用户确认后执行）
  const resolveConflicts = useCallback(async (actions) => {
    const { pendingOps, summary, asyncTransferIds: prevAsyncIds } = conflictState;
    setConflictState(prev => ({ ...prev, visible: false }));

    let successCount = summary.success;
    let failCount = summary.fail;
    let skipCount = 0;
    let pendingCount = summary.pending || 0;
    const asyncTransferIds = [...(prevAsyncIds || [])];

    for (let i = 0; i < pendingOps.length; i++) {
      const { item, endpoint, targetFolderId, paramKey } = pendingOps[i];
      const action = actions[i];

      if (action === 'skip') {
        skipCount++;
        continue;
      }

      try {
        const result = await http.post(endpoint, {
          id: item.id,
          [paramKey]: targetFolderId,
          is_public: isPublic,
          conflict_action: action,
        }, { timeout: 300000 });

        if (result && result.status === 'conflict') {
          // 仍然有冲突（并发变化）
          failCount++;
        } else if (result && result.status === 'skipped') {
          skipCount++;
        } else if (result && result.status === 'pending') {
          // 大文件异步复制
          pendingCount++;
          if (result.transfer_id) asyncTransferIds.push(result.transfer_id);
        } else {
          successCount++;
        }
      } catch (e) {
        failCount++;
      }
    }

    showBatchResult(successCount, failCount, skipCount, pendingCount);
    if (refresh) refresh(true);
    // 传入目标目录（冲突项统一操作同一目标），目标分支与当前分支都要刷新
    if (onFolderChange) onFolderChange(pendingOps.length > 0 ? pendingOps[0].targetFolderId : undefined);
    // 有后台复制任务时，启动轮询
    if (pendingCount > 0 && asyncTransferIds.length > 0) {
      pollAsyncCopyStatus(asyncTransferIds);
    }
  }, [conflictState, isPublic, refresh, onFolderChange, showBatchResult, pollAsyncCopyStatus]);

  // 关闭冲突弹窗
  const closeConflictModal = useCallback(() => {
    setConflictState(prev => ({ ...prev, visible: false }));
  }, []);

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
    conflictState,
    resolveConflicts,
    closeConflictModal,
  };
};
