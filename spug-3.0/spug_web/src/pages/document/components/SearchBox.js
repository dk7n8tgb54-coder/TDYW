/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useCallback, useRef, useEffect } from 'react';
import { Input } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import http from 'libs/http';

/**
 * 搜索框组件 - 全库搜索
 */
const SearchBox = ({ 
  isPublic, 
  onSearchStart, 
  onSearchResult, 
  onSearchError,
  onClearSearch 
}) => {
  const [keyword, setKeyword] = useState('');
  const debounceTimer = useRef(null);

  // 执行搜索（全库搜索）
  const doSearch = useCallback(async (searchKeyword) => {
    if (!searchKeyword || searchKeyword.trim() === '') {
      if (onClearSearch) onClearSearch();
      return;
    }

    if (onSearchStart) onSearchStart();

    try {
      const tenantId = isPublic ? null : localStorage.getItem('tenant_id');
      // 全库搜索：folder_id 为 null
      const res = await http.get('/api/document/folder/search/', {
        params: {
          folder_id: null, // 全库搜索
          keyword: searchKeyword.trim(),
          is_public: isPublic,
          tenant_id: tenantId
        },
        paramsSerializer: params => {
          return Object.keys(params)
            .filter(key => params[key] !== null && params[key] !== undefined)
            .map(key => `${encodeURIComponent(key)}=${encodeURIComponent(params[key])}`)
            .join('&');
        }
      });

      // 格式化结果
      const folders = (res.folders || []).map(f => ({
        ...f,
        isFolder: true,
        key: `folder_${f.id}`,
        rawId: f.id,
        path: f.path || ''
      }));

      const files = (res.files || []).map(f => ({
        ...f,
        isFolder: false,
        key: `file_${f.id}`,
        rawId: f.id,
        path: f.path || ''
      }));

      // 获取后端分页信息
      const pagination = res.pagination || {};
      const totalResults = (pagination.total_folders || 0) + (pagination.total_files || 0);

      if (onSearchResult) {
        onSearchResult({
          items: [...folders, ...files],
          folders,
          files,
          keyword: searchKeyword,
          scope: 'global',
          pagination: {
            total: totalResults,
            page: pagination.page || 1,
            pageSize: pagination.page_size || 50,
            hasMore: pagination.has_more || false
          }
        });
      }
    } catch (error) {
      console.error('[SearchBox] 搜索失败:', error);
      if (onSearchError) onSearchError(error.message || '搜索失败');
    }
  }, [isPublic, onSearchStart, onSearchResult, onSearchError, onClearSearch]);

  // 防抖搜索
  const debouncedSearch = useCallback((value) => {
    clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(() => {
      doSearch(value);
    }, 300);
  }, [doSearch]);

  // 清理定时器
  useEffect(() => {
    return () => clearTimeout(debounceTimer.current);
  }, []);

  // 处理输入变化
  const handleInputChange = (e) => {
    const value = e.target.value;
    setKeyword(value);
    debouncedSearch(value);
  };

  // 处理点击搜索按钮
  const handleSearchClick = () => {
    doSearch(keyword);
  };

  // 清空搜索
  const handleClear = () => {
    setKeyword('');
    if (onClearSearch) onClearSearch();
  };

  return (
    <Input
      placeholder="搜索整个资料库"
      value={keyword}
      onChange={handleInputChange}
      onPressEnter={handleSearchClick}
      allowClear
      style={{ width: 260 }}
      prefix={<SearchOutlined style={{ color: '#bfbfbf' }} />}
    />
  );
};

export default SearchBox;
