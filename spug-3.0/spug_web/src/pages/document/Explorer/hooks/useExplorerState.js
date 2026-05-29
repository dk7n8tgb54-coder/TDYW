/**
 * Explorer 状态管理 Hook
 * 【修复】重构后版本 - 函数行数控制在200行以内
 * 通过组合多个子 Hook 实现
 */
import { useState, useCallback, useEffect, useRef } from 'react';
import { usePagination } from './usePagination';
import { useFolderEditing } from './useFolderEditing';
import { useDataFetching } from './useDataFetching';

export const useExplorerState = (isPublic, folderId, onError) => {
  // ===== 组合子 Hooks =====
  const {
    currentPage,
    pageSize,
    total,
    setPage,
    setPaginationData,
    resetPage,
  } = usePagination();

  const {
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
    resetEditingState,
  } = useFolderEditing();

  const {
    items,
    loading,
    folderContents,
    setFolderContents,
    fetchItems: fetchItemsBase,
    fetchFolderContents,
  } = useDataFetching(isPublic, folderId, onError);

  // ===== 本地状态 =====
  const [selectedRowKeys, setSelectedRowKeys] = useState([]);
  const [sortOrder, setSortOrder] = useState({ columnKey: null, order: null });
  const [clickTimeout, setClickTimeout] = useState(null);

  // ===== Refs =====
  const isInitialMount = useRef(true);
  const prevFolderId = useRef(folderId);
  const prevIsPublic = useRef(isPublic);

  // ===== 包装数据获取函数 =====
  const fetchItems = useCallback(async (resetSelected = false) => {
    const result = await fetchItemsBase(currentPage, pageSize, resetSelected);
    if (result.pagination) {
      setPaginationData(result.pagination);
    }
    if (resetSelected) {
      setSelectedRowKeys([]);
    }
  }, [fetchItemsBase, currentPage, pageSize, setPaginationData]);

  // ===== 表格排序处理 =====
  const handleTableChange = useCallback((_pagination, _filters, sorter) => {
    setSortOrder(sorter?.columnKey
      ? { columnKey: sorter.columnKey, order: sorter.order }
      : { columnKey: null, order: null }
    );
  }, []);

  // ===== 选中行管理 =====
  const handleSetSelectedRowKeys = useCallback((keys) => {
    setSelectedRowKeys(Array.isArray(keys) ? keys : []);
  }, []);

  // ===== 点击超时管理 =====
  const handleSetClickTimeout = useCallback((timeout) => {
    setClickTimeout(timeout);
  }, []);

  const clearClickTimeout = useCallback(() => {
    if (clickTimeout) {
      clearTimeout(clickTimeout);
      setClickTimeout(null);
    }
  }, [clickTimeout]);

  // ===== 获取当前选中项 =====
  const getSelectedItem = useCallback(() => {
    if (!Array.isArray(selectedRowKeys) || selectedRowKeys.length === 0) {
      return null;
    }
    return items.find(item => item.key === selectedRowKeys[0]) || null;
  }, [selectedRowKeys, items]);

  // ===== 监听 folderId 和 isPublic 变化 =====
  useEffect(() => {
    if (folderId !== prevFolderId.current || isPublic !== prevIsPublic.current) {
      resetPage();
      prevFolderId.current = folderId;
      prevIsPublic.current = isPublic;
      resetEditingState();
    }
  }, [isPublic, folderId, resetPage, resetEditingState]);

  // ===== 监听分页变化 =====
  useEffect(() => {
    if (isInitialMount.current) {
      isInitialMount.current = false;
      fetchItems(true);
    } else {
      const timer = setTimeout(() => fetchItems(true), 0);
      return () => clearTimeout(timer);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentPage, pageSize, isPublic, folderId]);

  return {
    // 数据状态
    items,
    loading,
    // 分页状态
    currentPage,
    pageSize,
    total,
    setPage,
    // 选中和排序
    selectedRowKeys,
    setSelectedRowKeys: handleSetSelectedRowKeys,
    sortOrder,
    setSortOrder,
    // 点击超时
    clickTimeout,
    setClickTimeout: handleSetClickTimeout,
    clearClickTimeout,
    // 文件夹内容
    folderContents,
    setFolderContents,
    // 数据操作
    fetchItems,
    fetchFolderContents,
    getSelectedItem,
    // 表格
    handleTableChange,
    // 新建文件夹
    creatingFolder,
    tempFolderName,
    setTempFolderName,
    startCreateFolder,
    cancelCreateFolder,
    // 重命名
    renamingRecord,
    tempRenameValue,
    setTempRenameValue,
    startRename,
    cancelRename,
  };
};

export default useExplorerState;
