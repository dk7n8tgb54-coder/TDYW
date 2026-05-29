/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { useState, useEffect, useCallback } from 'react';
import http from 'libs/http';

/**
 * 磁盘空间监控 Hook
 * @param {boolean} isPublic - 是否为公共空间
 * @param {number} interval - 轮询间隔（毫秒），默认30秒
 * @returns {object} 磁盘空间信息和状态
 */
export function useDiskSpace(isPublic, interval = 30000) {
  const [diskInfo, setDiskInfo] = useState({
    available_gb: 0,
    total_gb: 0,
    used_gb: 0,
    usage_percent: 0,
    loading: true,
  });
  const [warning, setWarning] = useState(false);

  const fetchDiskSpace = useCallback(async () => {
    try {
      const res = await http.get('/api/document/disk_usage/', {
        params: { is_public: isPublic }
      });
      
      const usagePercent = res.total_gb > 0 
        ? Math.round((res.used_gb / res.total_gb) * 100) 
        : 0;
      
      setDiskInfo({
        available_gb: res.available_gb || 0,
        total_gb: res.total_gb || 0,
        used_gb: res.used_gb || 0,
        usage_percent: usagePercent,
        loading: false,
      });
      
      // 剩余空间 < 10GB 或使用率 > 90% 触发告警
      setWarning(res.available_gb < 10 || usagePercent > 90);
    } catch (error) {
      console.error('获取磁盘空间失败:', error);
      setDiskInfo(prev => ({ ...prev, loading: false }));
    }
  }, [isPublic]);

  useEffect(() => {
    // 立即执行一次
    fetchDiskSpace();
    
    // 定时轮询
    const timer = setInterval(fetchDiskSpace, interval);
    
    return () => clearInterval(timer);
  }, [fetchDiskSpace, interval]);

  return { 
    ...diskInfo, 
    warning, 
    refresh: fetchDiskSpace 
  };
}

export default useDiskSpace;
