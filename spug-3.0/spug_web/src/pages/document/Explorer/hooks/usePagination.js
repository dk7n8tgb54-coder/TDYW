/**
 * 分页状态管理 Hook
 * 【修复】从 useExplorerState 拆分出来的独立 Hook
 */
import { useState, useCallback } from 'react';

export const usePagination = () => {
  const [pagination, setPagination] = useState({
    currentPage: 1,
    pageSize: 20,
    total: 0,
    backendPagination: null,
  });

  const setPage = useCallback((page, newPageSize) => {
    setPagination(prev => ({
      ...prev,
      currentPage: page,
      pageSize: newPageSize || prev.pageSize,
    }));
  }, []);

  const setPaginationData = useCallback((backendPagination) => {
    const totalItems = (backendPagination?.total_folders || 0) + (backendPagination?.total_files || 0);
    setPagination(prev => ({
      ...prev,
      total: totalItems,
      backendPagination,
    }));
  }, []);

  const resetPage = useCallback(() => {
    setPagination(prev => ({ ...prev, currentPage: 1 }));
  }, []);

  return {
    ...pagination,
    setPage,
    setPaginationData,
    resetPage,
  };
};

export default usePagination;
