/**
 * Explorer工具栏组件
 * 【任务4.2】可选工具栏组件
 * 职责：提供文件操作按钮组
 */
import React from 'react';
import { Button, Space } from 'antd';
import {
  PlusOutlined,
  DownloadOutlined,
  CopyOutlined,
  ScissorOutlined,
  DeleteOutlined,
} from '@ant-design/icons';

/**
 * Explorer工具栏组件
 * @param {Object} props - 组件属性
 * @param {number} props.selectedCount - 选中数量
 * @param {boolean} props.canEdit - 是否有编辑权限
 * @param {Function} props.onNewFolder - 新建文件夹回调
 * @param {Function} props.onDownload - 下载回调
 * @param {Function} props.onCopy - 复制回调
 * @param {Function} props.onCut - 剪切回调
 * @param {Function} props.onDelete - 删除回调
 */
const ExplorerToolbar = ({
  selectedCount = 0,
  canEdit = false,
  onNewFolder,
  onDownload,
  onCopy,
  onCut,
  onDelete,
}) => {
  const hasSelection = selectedCount > 0;

  return (
    <Space style={{ marginBottom: 16 }}>
      {canEdit && (
        <Button type="primary" icon={<PlusOutlined />} onClick={onNewFolder}>
          新建文件夹
        </Button>
      )}
      
      {hasSelection && (
        <>
          <Button icon={<DownloadOutlined />} onClick={onDownload}>
            下载{selectedCount > 1 ? ` (${selectedCount})` : ''}
          </Button>
          
          {canEdit && (
            <>
              <Button icon={<CopyOutlined />} onClick={onCopy}>
                复制{selectedCount > 1 ? ` (${selectedCount})` : ''}
              </Button>
              <Button icon={<ScissorOutlined />} onClick={onCut}>
                移动{selectedCount > 1 ? ` (${selectedCount})` : ''}
              </Button>
              <Button danger icon={<DeleteOutlined />} onClick={onDelete}>
                删除{selectedCount > 1 ? ` (${selectedCount})` : ''}
              </Button>
            </>
          )}
        </>
      )}
    </Space>
  );
};

export default ExplorerToolbar;
