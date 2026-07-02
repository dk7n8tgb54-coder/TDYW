/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Progress, Tooltip, Badge } from 'antd';
import { useDiskSpace } from '../hooks/useDiskSpace';

/**
 * 磁盘状态显示组件
 * 显示服务器磁盘整体使用情况和资料库占用
 * @param {object} props
 * @param {boolean} props.isPublic - 是否为公共空间
 */
export function DiskStatus({ isPublic }) {
  const {
    available_gb,
    total_gb,
    used_gb,
    warning,
    loading
  } = useDiskSpace(isPublic);

  if (loading) return null;

  // 计算磁盘实际使用率（整个服务器的使用情况）
  // total_gb - available_gb = 磁盘已使用的总空间（包括所有应用）
  const diskUsedGB = total_gb - available_gb;
  const diskUsagePercent = total_gb > 0 
    ? Math.round((diskUsedGB / total_gb) * 100) 
    : 0;

  const status = warning ? 'exception' : diskUsagePercent > 80 ? 'warning' : 'success';
  const badgeStatus = warning ? 'error' : 'success';
  const text = warning 
    ? `磁盘空间不足(${available_gb.toFixed(1)}GB)` 
    : '磁盘正常';

  return (
    <Tooltip 
      title={
        <div>
          <div><strong>服务器磁盘</strong></div>
          <div>总容量: {total_gb.toFixed(1)}GB</div>
          <div>已使用: {diskUsedGB.toFixed(1)}GB ({diskUsagePercent}%)</div>
          <div>可用: {available_gb.toFixed(1)}GB</div>
          <div style={{ marginTop: 8, borderTop: '1px solid #eee', paddingTop: 8 }}>
            <div><strong>资料库占用</strong></div>
            <div>{used_gb.toFixed(1)}GB</div>
          </div>
        </div>
      }
    >
      <div style={{ 
        display: 'flex', 
        alignItems: 'center', 
        gap: 8,
        padding: '4px 12px',
        background: warning ? '#fff2f0' : '#f6ffed',
        borderRadius: 4,
        border: `1px solid ${warning ? '#ffccc7' : '#b7eb8f'}`
      }}>
        <Badge status={badgeStatus} text={text} />
        <Progress 
          percent={diskUsagePercent} 
          size="small" 
          style={{ width: 80, margin: 0 }}
          status={status}
          showInfo={false}
        />
        <span style={{ 
          fontSize: 12, 
          color: warning ? '#cf1322' : '#52c41a',
          fontWeight: warning ? 500 : 'normal'
        }}>
          {available_gb.toFixed(1)}GB 可用
        </span>
      </div>
    </Tooltip>
  );
}

export default DiskStatus;
