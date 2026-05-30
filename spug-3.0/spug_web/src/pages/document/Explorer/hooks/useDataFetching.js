/**
 * 数据获取 Hook
 * 【修复】从 useExplorerState 拆分出来的独立 Hook
 * 职责：处理文件列表和文件夹内容的数据获取
 */
import { useState, useCallback } from 'react';
import http from 'libs/http';
import { generateKey } from '../utils';

export const useDataFetching = (isPublic, folderId, onError) => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [folderContents, setFolderContents] = useState(null);

  // 获取文件列表
  const fetchItems = useCallback(async (currentPage, pageSize, resetSelected = false) => {
    setLoading(true);
    try {
      const tenantId = isPublic ? null : sessionStorage.getItem('tenant_id');
      const res = await http.get('/api/document/folder/', {
        params: {
          id: folderId,
          is_public: isPublic,
          tenant_id: tenantId,
          page: currentPage || 1,
          page_size: pageSize || 20,
        }
      });

      // 合并文件夹和文件
      const folders = (res.folders || []).map(f => ({
        ...f,
        isFolder: true,
        key: generateKey(f?.id, 'folder'),
        rawId: f?.id
      }));

      const files = (res.files || []).map(f => ({
        ...f,
        isFolder: false,
        key: generateKey(f?.id, 'file'),
        rawId: f?.id
      }));

      // 去重处理
      const seen = new Map();
      const mergedItems = [...folders, ...files].filter(item => {
        if (seen.has(item.key)) {
          console.warn('[Explorer] 检测到重复ID:', item.key, item.name);
          return false;
        }
        seen.set(item.key, true);
        return true;
      });

      setItems(mergedItems);
      setLoading(false);
      
      return {
        items: mergedItems,
        pagination: res.pagination || {},
      };
    } catch (error) {
      console.error('[Explorer] fetchItems error:', error);
      setItems([]);
      setLoading(false);
      if (onError) onError(error);
      return { items: [], pagination: {} };
    }
  }, [isPublic, folderId, onError]);

  // 获取文件夹内容
  const fetchFolderContents = useCallback(async (targetFolderId) => {
    try {
      const res = await http.get('/api/document/folder/', {
        params: { id: targetFolderId, is_public: isPublic }
      });
      const contents = {
        folders: res.folders || [],
        files: res.files || []
      };
      setFolderContents(contents);
      return contents;
    } catch (e) {
      const empty = { folders: [], files: [] };
      setFolderContents(empty);
      return empty;
    }
  }, [isPublic]);

  return {
    items,
    loading,
    folderContents,
    setFolderContents,
    fetchItems,
    fetchFolderContents,
  };
};

export default useDataFetching;
