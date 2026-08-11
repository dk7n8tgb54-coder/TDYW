/**
 * 数据获取 Hook
 * 【修复 2026-07-17】消除切换目录时的整表变灰、闪烁与重复刷新
 *
 * 核心改动：
 * 1. 区分 loadType：initial / navigate / pagination / refresh / silent
 *    - initial/navigate/pagination：150ms 延迟后才显示 loading，避免快请求闪烁
 *    - refresh：不显示整表 loading（仅刷新按钮 loading），失效全部缓存
 *    - silent：上传完成静默刷新，不显示 loading，失败不清空列表
 * 2. 内存缓存：key 含 isPublic + systemFolderCode + tenantId + folderId + page + pageSize
 *    navigate/initial 命中缓存时优先展示，再后台静默更新
 * 3. interactionDisabled：目录切换未命中缓存时，旧行交互禁用直至新数据返回
 * 4. latest-request-wins：requestId 机制保证旧请求不覆盖新目录
 */
import { useState, useCallback, useEffect, useRef } from 'react';
import { message } from 'antd';
import http from 'libs/http';
import { generateKey } from '../utils';
import navigationStore from '../../stores/navigation';

// ============================================================
// 内存缓存（模块级单例，跨 Explorer 实例 / 跨目录切换共享）
// ============================================================
const folderListCache = new Map();
const CACHE_MAX = 50;

function buildCacheKey({ isPublic, systemFolderCode, tenantId, folderId, page, pageSize }) {
  return [
    'pub',
    systemFolderCode || 'none',
    tenantId || 'none',
    folderId || 'root',
    'p' + (page || 1),
    's' + (pageSize || 20),
  ].join(':');
}

/** 失效全部目录缓存（删除/移动/重命名/新建/手动刷新后调用） */
export function invalidateAllFolderCache() {
  folderListCache.clear();
}

/** 失效与指定作用域相关的所有缓存（按前缀匹配） */
export function invalidateScopeCache({ isPublic, systemFolderCode, tenantId }) {
  const prefix = [
    'pub',
    systemFolderCode || 'none',
    tenantId || 'none',
  ].join(':');
  for (const key of Array.from(folderListCache.keys())) {
    if (key.startsWith(prefix)) folderListCache.delete(key);
  }
}

// loading 延迟显示阈值：请求在 150ms 内完成则不显示加载动画
const LOADING_DELAY = 150;

/**
 * 规范化 fetchItems 入参，兼容三种调用方式：
 *   - fetchItems()                 → { loadType: 'refresh' }
 *   - fetchItems(true)             → { loadType: 'refresh', resetSelected: true }（向后兼容 useFileOperations）
 *   - fetchItems({ loadType, ... })
 */
function normalizeOptions(options, currentPage, pageSize) {
  if (typeof options === 'boolean') {
    return {
      loadType: 'refresh',
      resetSelected: options,
      useCache: false,
      page: currentPage,
      pageSize,
    };
  }
  if (!options) {
    return {
      loadType: 'refresh',
      resetSelected: false,
      useCache: false,
      page: currentPage,
      pageSize,
    };
  }
  return {
    loadType: options.loadType || 'refresh',
    resetSelected: !!options.resetSelected,
    useCache: !!options.useCache,
    page: options.page || currentPage,
    pageSize: options.pageSize || pageSize,
  };
}

/**
 * 合并 folders + files 列表，标记 isFolder/key/rawId 并按 key 去重。
 */
function mergeFolderItems(res) {
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
  const seen = new Map();
  return [...folders, ...files].filter(item => {
    if (seen.has(item.key)) {
      console.warn('[Explorer] 检测到重复ID:', item.key, item.name);
      return false;
    }
    seen.set(item.key, true);
    return true;
  });
}

/**
 * 发送文件夹列表请求（普通模式自动带 tenant_id，公共模式不带）。
 */
async function requestFolderList({ isPublic, folderId, page, pageSize }) {
  const tenantId = null;
  return http.get('/api/document/folder/', {
    params: {
      id: folderId,
      is_public: isPublic,
      tenant_id: tenantId,
      page,
      page_size: pageSize,
    },
    // 空间切换可能产生过期请求，由 useDataFetching 的版本号机制保证 latest-wins；
    // 错误提示交给业务层决定，避免 HTTP 层重复弹窗
    skipErrorNotification: true,
  });
}

/**
 * 解析 fetchItems 入参，兼容旧签名 fetchItems(page, pageSize, resetSelected)
 * 与新签名 fetchItems(options)。
 */
function resolveFetchItemOptions(currentPageArg, pageSizeArg, resetSelectedArg, optionsArg) {
  if (optionsArg && typeof optionsArg === 'object') {
    return normalizeOptions(optionsArg, currentPageArg || 1, pageSizeArg || 20);
  }
  return {
    loadType: 'navigate',
    resetSelected: !!resetSelectedArg,
    useCache: true,
    page: currentPageArg || 1,
    pageSize: pageSizeArg || 20,
  };
}

export const useDataFetching = (isPublic, folderId, onError) => {
  const [items, setItems] = useState([]);
  // loading：仅当 initial/navigate/pagination 请求超过 150ms 仍未完成时为 true
  const [loading, setLoading] = useState(false);
  // 最近一次加载类型（供 UI 决定是否显示骨架/进度条）
  const [loadType, setLoadType] = useState('initial');
  // 目录切换未命中缓存时禁用旧行交互，直至新数据返回
  const [interactionDisabled, setInteractionDisabled] = useState(false);
  const [folderContents, setFolderContents] = useState(null);

  const isMountedRef = useRef(true);
  const fetchItemsRequestRef = useRef(0);
  const fetchFolderContentsRequestRef = useRef(0);
  const loadingTimerRef = useRef(null);

  useEffect(() => {
    return () => {
      isMountedRef.current = false;
      // 令所有在途请求失效
      fetchItemsRequestRef.current += 1;
      fetchFolderContentsRequestRef.current += 1;
      if (loadingTimerRef.current) {
        clearTimeout(loadingTimerRef.current);
        loadingTimerRef.current = null;
      }
    };
  }, []);

  const clearLoadingTimer = useCallback(() => {
    if (loadingTimerRef.current) {
      clearTimeout(loadingTimerRef.current);
      loadingTimerRef.current = null;
    }
  }, []);

  const safeSetFolderContents = useCallback((contents) => {
    if (isMountedRef.current) {
      setFolderContents(contents);
    }
  }, []);

  // 构造缓存上下文（systemFolderCode 区分普通/党建，避免串用）
  const getCacheContext = useCallback(() => {
    const tenantId = isPublic
      ? null
      : (sessionStorage.getItem('tenant_id') || 'default');
    const systemFolderCode = navigationStore.systemFolderCode || null;
    return { isPublic, systemFolderCode, tenantId, folderId };
  }, [isPublic, folderId]);

  // ============================================================
  // 获取文件列表（统一入口）
  // ============================================================
  const fetchItems = useCallback(async (currentPageArg, pageSizeArg, resetSelectedArg, optionsArg) => {
    const opts = resolveFetchItemOptions(currentPageArg, pageSizeArg, resetSelectedArg, optionsArg);

    const requestId = ++fetchItemsRequestRef.current;
    const isActiveRequest = () => (
      isMountedRef.current && requestId === fetchItemsRequestRef.current
    );

    if (isMountedRef.current) setLoadType(opts.loadType);

    const ctx = getCacheContext();
    const cacheKey = buildCacheKey({ ...ctx, page: opts.page, pageSize: opts.pageSize });

    // ----- 缓存命中（仅 navigate/initial 启用）-----
    let cacheHit = false;
    if (opts.useCache && (opts.loadType === 'navigate' || opts.loadType === 'initial')) {
      const cached = folderListCache.get(cacheKey);
      if (cached) {
        if (isMountedRef.current) {
          setItems(cached.items);
          setLoading(false);
          setInteractionDisabled(false);
        }
        cacheHit = true;
      } else if (opts.loadType === 'navigate') {
        // navigate 未命中：禁用旧行交互，等待新数据返回
        // initial 未命中不设（首次无旧内容可禁用，避免空表显示"暂无文件"误判）
        if (isMountedRef.current) setInteractionDisabled(true);
      }
    }

    // ----- refresh 模式失效全部缓存（数据已变更）-----
    if (opts.loadType === 'refresh') {
      invalidateAllFolderCache();
    }

    // ----- 150ms 延迟显示 loading（仅未命中缓存且非 silent/refresh）-----
    const showDelayedLoading = !cacheHit && (
      opts.loadType === 'initial' ||
      opts.loadType === 'navigate' ||
      opts.loadType === 'pagination'
    );
    if (showDelayedLoading) {
      clearLoadingTimer();
      loadingTimerRef.current = setTimeout(() => {
        if (isActiveRequest()) setLoading(true);
      }, LOADING_DELAY);
    }

    try {
      const res = await requestFolderList({
        isPublic,
        folderId,
        page: opts.page,
        pageSize: opts.pageSize,
      });
      const mergedItems = mergeFolderItems(res);

      if (!isActiveRequest()) {
        return {
          items: mergedItems,
          pagination: res.pagination || {},
          cancelled: true,
        };
      }

      // 写入缓存（所有成功请求均更新缓存，保证下次命中是最新数据）
      folderListCache.set(cacheKey, { items: mergedItems, pagination: res.pagination || {} });
      if (folderListCache.size > CACHE_MAX) {
        const firstKey = folderListCache.keys().next().value;
        folderListCache.delete(firstKey);
      }

      setItems(mergedItems);
      setInteractionDisabled(false);
      clearLoadingTimer();
      setLoading(false);

      return {
        items: mergedItems,
        pagination: res.pagination || {},
      };
    } catch (error) {
      console.error('[Explorer] fetchItems error:', error);
      if (!isActiveRequest()) {
        // 过期请求：HTTP 层已通过 skipErrorNotification 抑制弹窗，此处也不提示
        return { items: [], pagination: {}, cancelled: true };
      }
      // silent 模式失败不清空列表（保留现有内容，避免上传刷新把列表清空）
      if (opts.loadType !== 'silent') {
        setItems([]);
      }
      setInteractionDisabled(false);
      clearLoadingTimer();
      setLoading(false);
      if (onError) {
        onError(error);
      } else {
        // HTTP 层已通过 skipErrorNotification 抑制，业务层负责唯一一次提示
        // 使用 antd message.error（http.js 的 showErrorOnce 会去重，但此处是独立调用）
        const msg = typeof error === 'string' ? error : '加载失败';
        // 2 秒内相同消息只提示一次
        if (!window._lastFetchError || window._lastFetchError !== msg || Date.now() - window._lastFetchErrorTime > 2000) {
          window._lastFetchError = msg;
          window._lastFetchErrorTime = Date.now();
          message.error(msg);
        }
      }
      return { items: [], pagination: {} };
    }
  }, [isPublic, folderId, onError, clearLoadingTimer, getCacheContext]);

  // 获取文件夹内容（详情面板用，逻辑不变）
  const fetchFolderContents = useCallback(async (targetFolderId) => {
    const requestId = ++fetchFolderContentsRequestRef.current;
    const isActiveRequest = () => (
      isMountedRef.current && requestId === fetchFolderContentsRequestRef.current
    );

    try {
      const res = await http.get('/api/document/folder/', {
        params: { id: targetFolderId, is_public: isPublic }
      });
      const contents = {
        folders: res.folders || [],
        files: res.files || []
      };
      if (isActiveRequest()) {
        setFolderContents(contents);
      }
      return contents;
    } catch (e) {
      const empty = { folders: [], files: [] };
      if (isActiveRequest()) {
        setFolderContents(empty);
      }
      return empty;
    }
  }, [isPublic]);

  return {
    items,
    loading,
    loadType,
    interactionDisabled,
    folderContents,
    setFolderContents: safeSetFolderContents,
    fetchItems,
    fetchFolderContents,
  };
};

export default useDataFetching;
