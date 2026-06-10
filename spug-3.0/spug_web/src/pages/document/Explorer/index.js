/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 *
 * 【任务4.2】Explorer组件重构
 * - 拆分为更小的子组件
 * - 简化Hook和Store的嵌套依赖
 */
import React, { useEffect, useCallback, useState, useMemo, forwardRef, useImperativeHandle, useRef } from 'react';
import { observer } from 'mobx-react';
import { autorun } from 'mobx';
import { message } from 'antd';
import { http } from 'libs';

// Stores
import navigationStore from '../stores/navigation';
import uploadUIStore from '../stores/upload/ui';
import { uploadCoreStore } from '../stores';

// Components
import PreviewModal from '../PreviewModal';
import ContextMenu from '../components/ContextMenu';
import FolderTreeSelector from '../components/FolderTreeSelector';
import { FileTable, FileGrid, SearchResults, DetailPanel, PropertiesModal } from './components';

// Hooks（简化后的统一入口）
import {
  useExplorerState,
  useFileOperations,
  useColumns,
  useSearchGrouping,
  useContextMenu,
  useSorting,
  useTableHandlers,
} from './hooks';

// Utils
import { getCurrentUserId, checkIsAdmin, canEditItem, CONSTANTS } from './utils';

const Explorer = observer(forwardRef(({
  isPublic: propIsPublic,
  folderId: propFolderId,
  onFolderChange,
  searchState,
  viewMode = 'list',
}, ref) => {
  // ===== 基础状态 =====
  const isPublic = propIsPublic || false;
  const folderId = propFolderId || null;
  const isAdmin = checkIsAdmin();
  const currentUserId = getCurrentUserId();
  const isSearching = searchState?.isSearching || false;

  // ===== Explorer状态管理 =====
  const {
    items,
    loading,
    selectedRowKeys,
    sortOrder,
    clickTimeout,
    folderContents,
    currentPage,
    pageSize,
    total,
    fetchItems,
    handleTableChange: originalHandleTableChange,
    setSelectedRowKeys,
    setClickTimeout,
    setFolderContents,
    setPage,
    setSortOrder,
    fetchFolderContents,
    getSelectedItem,
    // 行内编辑
    creatingFolder,
    tempFolderName,
    setTempFolderName,
    startCreateFolder,
    cancelCreateFolder,
    renamingRecord,
    tempRenameValue,
    setTempRenameValue,
    startRename,
    cancelRename,
  } = useExplorerState(isPublic, folderId);

  // 【性能优化】使用 ref 存储 selectedRowKeys，避免闭包导致的重复渲染
  const selectedRowKeysRef = useRef(selectedRowKeys);
  useEffect(() => {
    selectedRowKeysRef.current = selectedRowKeys;
  }, [selectedRowKeys]);

  // ===== 文件操作 =====
  const {
    handleDelete,
    handleDeleteSelected,
    handleDownload,
    handleDownloadSelected,
    handleFolderDownload,
    handleCreateFolder,
    handleRename,
    handleCopyItems,
    handleMoveItems,
  } = useFileOperations({
    isPublic,
    folderId,
    refresh: fetchItems,
    onFolderChange,
  });

  // ===== 右键菜单管理 =====
  const {
    contextMenu,
    showContextMenu,
    closeContextMenu,
    createEmptyAreaMenu,
    createSingleSelectMenu,
    createMultiSelectMenu,
  } = useContextMenu();

  // ===== 表格列配置 =====
  const getColumns = useColumns({
    sortOrder,
    isSearching,
    isPublic,
    currentUserId,
    creatingFolder,
    tempFolderName,
    setTempFolderName,
    confirmCreateFolder: useCallback(async (folderName) => {
      if (!folderName?.trim()) {
        message.warning('请输入文件夹名称');
        return;
      }
      try {
        await handleCreateFolder(folderName.trim());
        cancelCreateFolder();
        message.success('文件夹创建成功');
      } catch (error) {
        message.error('创建失败：' + (error?.message || '未知错误'));
      }
    }, [handleCreateFolder, cancelCreateFolder]),
    cancelCreateFolder,
    renamingRecord,
    tempRenameValue,
    setTempRenameValue,
    confirmRename: useCallback(async (record, newName) => {
      if (!newName?.trim()) {
        message.warning(`请输入${record.isFolder ? '文件夹' : '文件'}名称`);
        return;
      }
      const currentName = record.display_name || record.name;
      if (newName.trim() === currentName) {
        cancelRename();
        return;
      }
      try {
        await handleRename(record, newName.trim());
        cancelRename();
        message.success('重命名成功');
      } catch (error) {
        message.error('重命名失败：' + (error?.message || '未知错误'));
      }
    }, [handleRename, cancelRename]),
    cancelRename,
  });

  // ===== 数据处理和排序 =====
  const filteredItems = isSearching ? (searchState?.results || []) : items;
  const sortedData = useSorting(filteredItems, sortOrder, creatingFolder);
  const groupedByType = useSearchGrouping(filteredItems, isSearching);

  // ===== 表格事件处理 =====
  const { handleTableChange } = useTableHandlers(setSortOrder);

  // ===== 搜索分页信息 =====
  const searchPagination = searchState?.pagination;
  const displayTotal = isSearching ? (searchPagination?.total || filteredItems.length) : total;
  const displayPageSize = isSearching ? (searchPagination?.pageSize || 50) : pageSize;
  const displayCurrentPage = isSearching ? (searchPagination?.page || 1) : currentPage;

  // ===== 文件夹选择器状态 =====
  const [folderSelector, setFolderSelector] = useState({
    visible: false,
    title: '',
    mode: null,
    record: null,
    allFolders: [],
  });
  const [pendingOperation, setPendingOperation] = useState({ mode: null, items: [] });

  // ===== 详情面板状态 =====
  const [detailPanelExpanded, setDetailPanelExpanded] = useState(false);

  // ===== 属性弹窗状态 =====
  const [propertiesModal, setPropertiesModal] = useState({ visible: false, record: null });

  // ===== 副作用：监听上传刷新（带防抖） =====
  useEffect(() => {
    let timeoutId = null;
    const disposer = autorun(() => {
      const trigger = uploadCoreStore.refreshTrigger;
      if (trigger > 0) {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => fetchItems(true), 500);
      }
    });
    return () => {
      disposer();
      clearTimeout(timeoutId);
    };
  }, [fetchItems]);

  // ===== 副作用：初始加载 =====
  useEffect(() => {
    fetchItems(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ===== 行操作处理 =====
  const handleDoubleClick = useCallback((record) => {
    if (record.isFolder) {
      navigationStore.enterFolder(record.id, record.name);
    } else {
      uploadUIStore.handlePreview(record);
    }
  }, []);

  const handleRowClick = useCallback((record) => {
    if (clickTimeout) clearTimeout(clickTimeout);

    const timeoutId = setTimeout(() => {
      const key = record.key;
      // 【性能优化】使用 ref 获取最新值，避免 selectedRowKeys 在依赖项中导致的重渲染
      const currentSelection = Array.isArray(selectedRowKeysRef.current) ? selectedRowKeysRef.current : [];
      const newSelectedKeys = currentSelection.includes(key)
        ? currentSelection.filter(k => k !== key)
        : [...currentSelection, key];

      setSelectedRowKeys(newSelectedKeys);
      setClickTimeout(null);

      // 加载文件夹内容到详情面板
      if (newSelectedKeys.length > 0 && record.isFolder) {
        fetchFolderContents(record.id).then(contents => setFolderContents(contents));
      } else if (newSelectedKeys.length === 0) {
        setFolderContents(null);
      }
    }, 250);

    setClickTimeout(timeoutId);
  }, [clickTimeout, setSelectedRowKeys, setClickTimeout, fetchFolderContents, setFolderContents]);

  const handleRowDoubleClick = useCallback((record) => {
    if (clickTimeout) {
      clearTimeout(clickTimeout);
      setClickTimeout(null);
    }
    handleDoubleClick(record);
  }, [clickTimeout, handleDoubleClick, setClickTimeout]);

  // ===== 右键菜单处理 =====
  const fetchAllFolders = useCallback(async () => {
    try {
      const res = await http.get('/api/document/folder/', {
        params: { id: null, all: true, is_public: isPublic }
      });
      if (Array.isArray(res)) return res;
      if (Array.isArray(res.data)) return res.data;
      if (Array.isArray(res.folders)) return res.folders;
      return [];
    } catch {
      message.error('获取文件夹列表失败');
      return [];
    }
  }, [isPublic]);

  const handleCopyToClipboard = useCallback(async (record) => {
    const allFolders = await fetchAllFolders();
    const itemsToOperate = selectedRowKeys.length > 1
      ? selectedRowKeys.map(key => items.find(i => i.key === key)).filter(Boolean)
      : [record];

    setFolderSelector({
      visible: true,
      title: '复制到',
      mode: 'copy',
      record,
      allFolders,
    });
    setPendingOperation({ mode: 'copy', items: itemsToOperate });
  }, [fetchAllFolders, selectedRowKeys, items]);

  const handleCutToClipboard = useCallback(async (record) => {
    const allFolders = await fetchAllFolders();
    const itemsToOperate = selectedRowKeys.length > 1
      ? selectedRowKeys.map(key => items.find(i => i.key === key)).filter(Boolean)
      : [record];

    setFolderSelector({
      visible: true,
      title: '移动到',
      mode: 'move',
      record,
      allFolders,
    });
    setPendingOperation({ mode: 'move', items: itemsToOperate });
  }, [fetchAllFolders, selectedRowKeys, items]);

  // ===== 行菜单项生成 =====
  const getRowMenuItems = useCallback((record) => {
    const canEdit = canEditItem(record, isPublic, isAdmin, currentUserId);
    const isMultiSelect = selectedRowKeys.length > 1;
    const selectedCount = selectedRowKeys.length;

    // 多选状态
    if (isMultiSelect) {
      return createMultiSelectMenu(selectedCount, {
        canEdit,
        onBatchDownload: () => handleDownloadSelected(selectedRowKeys, items),
        onBatchCopy: () => handleCopyToClipboard(record),
        onBatchCut: () => handleCutToClipboard(record),
        onBatchDelete: () => handleDeleteSelected(selectedRowKeys, items),
      });
    }

    // 单选状态
    return createSingleSelectMenu(record, {
      canEdit,
      onOpen: record.isFolder
        ? () => navigationStore.enterFolder(record.id, record.name)
        : () => uploadUIStore.handlePreview(record),
      onDownload: record.isFolder
        ? () => handleFolderDownload(record)
        : () => handleDownload(record),
      onCopy: () => handleCopyToClipboard(record),
      onCut: () => handleCutToClipboard(record),
      onRename: () => startRename(record),
      onDelete: () => handleDelete(record),
      onProperties: () => setPropertiesModal({ visible: true, record }),
    });
  }, [
    selectedRowKeys, items, isPublic, isAdmin, currentUserId,
    handleDownloadSelected, handleCopyToClipboard, handleCutToClipboard,
    handleDeleteSelected, handleFolderDownload, handleDownload,
    handleDelete, startRename, createMultiSelectMenu, createSingleSelectMenu,
  ]);

  // ===== 表格行事件 =====
  // 【性能优化】createRowHandlers 不再依赖 selectedRowKeys，使用 ref 获取最新值
  const createRowHandlers = useCallback((record) => ({
    onClick: () => handleRowClick(record),
    onDoubleClick: () => handleRowDoubleClick(record),
    onContextMenu: (e) => {
      // 使用 ref 获取最新选中状态
      const currentSelection = Array.isArray(selectedRowKeysRef.current) ? selectedRowKeysRef.current : [];
      const isAlreadySelected = currentSelection.includes(record.key);
      if (!isAlreadySelected) setSelectedRowKeys([record.key]);
      showContextMenu(e, getRowMenuItems(record));
    },
    style: { cursor: 'pointer' },
  }), [handleRowClick, handleRowDoubleClick, setSelectedRowKeys, showContextMenu, getRowMenuItems]);

  // ===== 空白区域右键菜单 =====
  const handleEmptyAreaContextMenu = useCallback((e) => {
    // 只有当右键点击在空白区域时才触发
    if (e.target.closest('.ant-table') && !e.target.closest('.ant-table-row')) {
      showContextMenu(e, createEmptyAreaMenu(() => startCreateFolder()));
    }
  }, [showContextMenu, createEmptyAreaMenu, startCreateFolder]);

  // ===== 暴露方法 =====
  useImperativeHandle(ref, () => ({
    toggleDetailPanel: (callback) => {
      setDetailPanelExpanded(prev => {
        const newState = !prev;
        if (callback) callback(newState);
        return newState;
      });
    },
    handleAddFolder: startCreateFolder,
    fetchItems,
  }), [startCreateFolder, fetchItems]);

  // ===== 渲染 =====
  const columns = useMemo(() => getColumns(), [getColumns]);
  const selectedItem = getSelectedItem();
  const safeSelectedRowKeys = useMemo(() =>
    Array.isArray(selectedRowKeys) ? selectedRowKeys : []
  , [selectedRowKeys]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', width: '100%', minWidth: 0 }}>
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', position: 'relative' }}>
        <div
          className="file-list-container"
          style={{ flex: 1, overflowY: 'auto', transition: 'flex 0.3s ease' }}
          onContextMenu={handleEmptyAreaContextMenu}
        >
          {isSearching && groupedByType ? (
            <SearchResults
              groups={groupedByType}
              columns={columns}
              loading={loading}
              selectedRowKeys={safeSelectedRowKeys}
              onSelectChange={setSelectedRowKeys}
              onRow={createRowHandlers}
            />
          ) : viewMode === 'grid' ? (
            <FileGrid
              dataSource={sortedData}
              loading={loading}
              selectedRowKeys={safeSelectedRowKeys}
              onSelectChange={setSelectedRowKeys}
              onRow={createRowHandlers}
              isPublic={isPublic}
              currentUserId={currentUserId}
              pagination={{
                current: displayCurrentPage,
                pageSize: displayPageSize,
                total: displayTotal,
                onChange: (page, newPageSize) => {
                  if (!isSearching) setPage(page, newPageSize);
                },
              }}
            />
          ) : (
            <FileTable
              columns={columns}
              dataSource={sortedData}
              loading={loading}
              selectedRowKeys={safeSelectedRowKeys}
              onSelectChange={setSelectedRowKeys}
              isSearching={isSearching}
              pagination={{
                current: displayCurrentPage,
                pageSize: displayPageSize,
                total: displayTotal,
                onChange: (page, newPageSize) => {
                  if (!isSearching) setPage(page, newPageSize);
                },
              }}
              onTableChange={handleTableChange}
              onRow={createRowHandlers}
              showPagination={!isSearching}
              isPublic={isPublic}
            />
          )}
        </div>

        <DetailPanel
          expanded={detailPanelExpanded}
          onToggle={(newState) => setDetailPanelExpanded(newState)}
          selectedItem={selectedItem}
          selectedCount={safeSelectedRowKeys.length}
          folderContents={folderContents}
        />
      </div>

      {/* Modals */}
      <PreviewModal />
      
      <ContextMenu
        visible={contextMenu.visible}
        position={contextMenu.position}
        items={contextMenu.items}
        onClose={closeContextMenu}
      />
      
      <FolderTreeSelector
        visible={folderSelector.visible}
        title={folderSelector.title}
        allFolders={folderSelector.allFolders}
        onConfirm={async (targetFolderId) => {
          const { mode, items } = pendingOperation;
          try {
            if (mode === 'copy') await handleCopyItems(items, targetFolderId);
            else if (mode === 'move') await handleMoveItems(items, targetFolderId);
          } catch (e) {
            // 错误已在handleCopyItems/handleMoveItems中处理
          }
          setFolderSelector(prev => ({ ...prev, visible: false }));
        }}
        onCancel={() => setFolderSelector(prev => ({ ...prev, visible: false }))}
      />

      <PropertiesModal
        visible={propertiesModal.visible}
        record={propertiesModal.record}
        isPublic={isPublic}
        onClose={() => setPropertiesModal({ visible: false, record: null })}
      />
    </div>
  );
}));

export default Explorer;
