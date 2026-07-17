/**
 * Explorer 状态管理 Hook
 * 【修复 2026-07-17】消除切换目录时的重复刷新
 *
 * 核心改动：
 * 1. 合并原本分离的「folderId/isPublic 监听」与「分页监听」两个 useEffect 为单一数据获取入口，
 *    一次目录切换只发送一次有效列表请求。
 * 2. skipNextPageEffectRef：folderId 变化时若当前页非 1，resetPage() 会再次触发本 effect，
 *    用 ref 标记跳过那次分页 effect，避免重复请求。
 * 3. fetchItems 包装透传 loadType，兼容旧布尔调用（useFileOperations 仍用 refresh(true)）。
 * 4. 初始加载由本 Hook 负责，Explorer/index.js 不再重复首次 fetchItems。
 */
import { useState, useCallback, useEffect, useRef } from 'react';
import { usePagination } from './usePagination';
import { useFolderEditing } from './useFolderEditing';
import { useDataFetching } from './useDataFetching';

/**
 * 点击超时管理 Hook（提取自 useExplorerState 以控制函数行数）。
 * 内部维护 timeout id 与 ref，卸载时清理。
 */
function useClickTimeout(isMountedRef) {
  const [clickTimeout, setClickTimeoutState] = useState(null);
  const clickTimeoutRef = useRef(null);

  const setClickTimeout = useCallback((timeout) => {
    clickTimeoutRef.current = timeout;
    if (isMountedRef.current) {
      setClickTimeoutState(timeout);
    }
  }, [isMountedRef]);

  const clearClickTimeout = useCallback(() => {
    if (clickTimeoutRef.current) {
      clearTimeout(clickTimeoutRef.current);
      clickTimeoutRef.current = null;
      if (isMountedRef.current) {
        setClickTimeoutState(null);
      }
    }
  }, [isMountedRef]);

  useEffect(() => {
    return () => {
      if (clickTimeoutRef.current) {
        clearTimeout(clickTimeoutRef.current);
        clickTimeoutRef.current = null;
      }
    };
  }, []);

  return { clickTimeout, setClickTimeout, clearClickTimeout };
}

/**
 * 解析 fetchItems 包装入参，兼容三种调用方式：
 *   fetchItems()                 → 手动刷新
 *   fetchItems(true)             → 操作后刷新 + 重置选中
 *   fetchItems({ loadType, ... })
 */
function resolveFetchItemsOptions(options, currentPage, pageSize) {
  let opts;
  if (typeof options === 'boolean') {
    opts = { loadType: 'refresh', resetSelected: options, useCache: false };
  } else if (!options) {
    opts = { loadType: 'refresh', resetSelected: false, useCache: false };
  } else {
    opts = {
      loadType: options.loadType || 'refresh',
      resetSelected: !!options.resetSelected,
      useCache: !!options.useCache,
      page: options.page,
      pageSize: options.pageSize,
    };
  }
  if (opts.page === undefined) opts.page = currentPage;
  if (opts.pageSize === undefined) opts.pageSize = pageSize;
  return opts;
}

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
    loadType,
    interactionDisabled,
    folderContents,
    setFolderContents,
    fetchItems: fetchItemsBase,
    fetchFolderContents,
  } = useDataFetching(isPublic, folderId, onError);

  // ===== 本地状态 =====
  const [selectedRowKeys, setSelectedRowKeys] = useState([]);
  const [sortOrder, setSortOrder] = useState({ columnKey: null, order: null });

  // ===== Refs =====
  const isInitialMount = useRef(true);
  const prevFolderId = useRef(folderId);
  const prevIsPublic = useRef(isPublic);
  // folderId 变化触发 resetPage() 后，currentPage 变化会再次进入数据获取 effect；
  // 用此 ref 标记跳过那次分页 effect，避免目录切换产生两次请求。
  const skipNextPageEffectRef = useRef(false);
  const isMountedRef = useRef(true);

  // ===== 点击超时管理（提取为独立 hook）=====
  const { clickTimeout, setClickTimeout, clearClickTimeout } = useClickTimeout(isMountedRef);

  useEffect(() => {
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  // ===== 包装数据获取函数 =====
  const fetchItems = useCallback(async (options) => {
    const opts = resolveFetchItemsOptions(options, currentPage, pageSize);
    const result = await fetchItemsBase(null, null, null, opts);
    if (!isMountedRef.current || result?.cancelled) {
      return result;
    }
    if (result.pagination) {
      setPaginationData(result.pagination);
    }
    if (opts.resetSelected) {
      setSelectedRowKeys([]);
    }
    return result;
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
    if (isMountedRef.current) {
      setSelectedRowKeys(Array.isArray(keys) ? keys : []);
    }
  }, []);

  // ===== 获取当前选中项 =====
  const getSelectedItem = useCallback(() => {
    if (!Array.isArray(selectedRowKeys) || selectedRowKeys.length === 0) {
      return null;
    }
    return items.find(item => item.key === selectedRowKeys[0]) || null;
  }, [selectedRowKeys, items]);

  // ===== 唯一数据获取入口 =====
  // 监听 [currentPage, pageSize, isPublic, folderId]：
  //   - 首次 mount → initial
  //   - folderId/isPublic 变化 → navigate（立即清空选中、重置编辑态、必要时 resetPage）
  //   - 分页变化 → pagination
  // skipNextPageEffectRef 防止 resetPage 触发的二次 effect 重复请求
  useEffect(() => {
    const folderChanged = folderId !== prevFolderId.current;
    const isPublicChanged = isPublic !== prevIsPublic.current;

    if (isInitialMount.current) {
      isInitialMount.current = false;
      prevFolderId.current = folderId;
      prevIsPublic.current = isPublic;
      fetchItems({ loadType: 'initial', resetSelected: true, useCache: true });
      return;
    }

    if (folderChanged || isPublicChanged) {
      prevFolderId.current = folderId;
      prevIsPublic.current = isPublic;
      // 立即清空选中与编辑态（操作安全：目录切换时选中状态立即清理）
      setSelectedRowKeys([]);
      resetEditingState();
      // 当前页非 1 时 resetPage 会触发本 effect 再次执行，标记跳过
      if (currentPage !== 1) {
        skipNextPageEffectRef.current = true;
        resetPage();
      }
      fetchItems({ loadType: 'navigate', resetSelected: true, useCache: true, page: 1, pageSize });
      return;
    }

    // resetPage 触发的二次 effect：跳过，避免目录切换重复请求
    if (skipNextPageEffectRef.current) {
      skipNextPageEffectRef.current = false;
      return;
    }

    // 真正的分页变化
    const timer = setTimeout(() => {
      fetchItems({ loadType: 'pagination', resetSelected: true });
    }, 0);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentPage, pageSize, isPublic, folderId]);

  return {
    // 数据状态
    items,
    loading,
    loadType,
    interactionDisabled,
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
    setClickTimeout,
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
