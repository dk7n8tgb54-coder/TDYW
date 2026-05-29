/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useCallback, useState, useEffect, useRef } from 'react';
import { Tag, Input, message } from 'antd';
import { CheckOutlined, CloseOutlined, LoadingOutlined, FileImageOutlined } from '@ant-design/icons';
import { X_TOKEN } from 'libs';
import { isImage, isVideo, formatFileSize, getFileTypeLabel, getFileIcon, isCreatedByAdmin } from '../utils';

/**
 * 【性能优化】懒加载图片缩略图组件
 * 使用 Intersection Observer 实现可视区域加载，避免一次性加载所有图片
 */
const LazyThumbnail = ({ src, alt, style }) => {
  const [isLoaded, setIsLoaded] = useState(false);
  const [isInView, setIsInView] = useState(false);
  const [hasError, setHasError] = useState(false);
  const containerRef = useRef(null);

  useEffect(() => {
    // 使用 Intersection Observer 检测元素是否进入可视区域
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            setIsInView(true);
            observer.disconnect();
          }
        });
      },
      {
        rootMargin: '300px', // 【优化】从100px增加到300px，提前加载更多图片避免快速滚动空白
        threshold: 0,
      }
    );

    if (containerRef.current) {
      observer.observe(containerRef.current);
    }

    return () => observer.disconnect();
  }, []);

  // 容器样式 - 使用相对定位作为定位上下文
  const containerStyle = {
    ...style,
    position: 'relative',
    overflow: 'hidden',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: '#f5f5f5',
    flexShrink: 0,
  };

  // 未进入视图或加载中时显示占位符
  if (!isInView || (!isLoaded && !hasError)) {
    return (
      <div ref={containerRef} style={containerStyle}>
        {!isInView ? (
          // 未进入视图：显示文件图标
          <FileImageOutlined style={{ fontSize: 16, color: '#bfbfbf' }} />
        ) : (
          // 已进入视图但加载中：显示加载动画
          <>
            <LoadingOutlined style={{ fontSize: 14, color: '#1890ff' }} />
            {/* 预加载图片，但不显示 */}
            <img
              src={src}
              alt={alt}
              style={{
                position: 'absolute',
                width: 1,
                height: 1,
                opacity: 0,
                pointerEvents: 'none',
              }}
              onLoad={() => setIsLoaded(true)}
              onError={() => setHasError(true)}
            />
          </>
        )}
      </div>
    );
  }

  // 加载失败：显示错误图标
  if (hasError) {
    return (
      <div style={containerStyle}>
        <FileImageOutlined style={{ fontSize: 16, color: '#ff4d4f' }} />
      </div>
    );
  }

  // 加载完成：显示图片
  return (
    <img
      src={src}
      alt={alt}
      style={{
        ...style,
        opacity: isLoaded ? 1 : 0,
        transition: 'opacity 0.2s ease-in-out',
      }}
      loading="lazy" // 浏览器原生懒加载作为兜底
      onError={(e) => {
        e.target.style.display = 'none';
      }}
    />
  );
};

export default function useColumns({
  sortOrder,
  isSearching,
  isPublic,
  currentUserId,
  creatingFolder,
  tempFolderName,
  setTempFolderName,
  confirmCreateFolder,
  cancelCreateFolder,
  renamingRecord,
  tempRenameValue,
  setTempRenameValue,
  confirmRename,
  cancelRename,
}) {
  return useCallback(() => {
    const columns = [
      {
        title: '文件名',
        dataIndex: 'name',
        key: 'name',
        width: 400,
        ellipsis: true,
        sorter: true,
        showSorterTooltip: false,
        sortOrder: sortOrder.columnKey === 'name' ? sortOrder.order : null,
        render: (text, record) => {
          // 临时文件夹行内编辑模式
          if (record.isTemp) {
            return (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 16 }} role="img" aria-label="文件夹">📁</span>
                <Input
                  autoFocus
                  size="small"
                  value={tempFolderName}
                  onChange={(e) => setTempFolderName(e.target.value)}
                  onPressEnter={() => {
                    if (tempFolderName.trim()) {
                      confirmCreateFolder(tempFolderName.trim());
                    } else {
                      message.warning('请输入文件夹名称');
                    }
                  }}
                  onBlur={() => {
                    // 延迟失焦，避免点击按钮时先触发失焦
                    setTimeout(() => {
                      if (!tempFolderName.trim()) {
                        cancelCreateFolder();
                      }
                    }, 200);
                  }}
                  placeholder="请输入文件夹名称"
                  style={{ width: 200 }}
                />
                <CheckOutlined
                  style={{ color: '#52c41a', cursor: 'pointer', fontSize: 14 }}
                  onClick={() => {
                    if (tempFolderName.trim()) {
                      confirmCreateFolder(tempFolderName.trim());
                    } else {
                      message.warning('请输入文件夹名称');
                    }
                  }}
                />
                <CloseOutlined
                  style={{ color: '#ff4d4f', cursor: 'pointer', fontSize: 14 }}
                  onClick={cancelCreateFolder}
                />
              </div>
            );
          }

          // 行内重命名模式
          if (renamingRecord && renamingRecord.key === record.key) {
            return (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {record.isFolder ? (
                  <span style={{ fontSize: 16 }} role="img" aria-label="文件夹">📁</span>
                ) : isImage(record.file_type) ? (
                  <img
                    src={`/api/document/preview/?id=${record.id}&is_public=${isPublic}&x-token=${X_TOKEN}`}
                    alt={record.display_name || text}
                    style={{
                      width: 32,
                      height: 32,
                      objectFit: 'cover',
                      borderRadius: 4,
                      background: '#f0f0f0'
                    }}
                    onError={(e) => { e.target.style.display = 'none'; }}
                  />
                ) : isVideo(record.file_type) ? (
                  <span style={{ fontSize: 16 }} role="img" aria-label="视频">🎬</span>
                ) : (
                  getFileIcon(record.display_name || record.name, record.file_type)
                )}
                <Input
                  autoFocus
                  size="small"
                  value={tempRenameValue}
                  onChange={(e) => setTempRenameValue(e.target.value)}
                  onPressEnter={() => {
                    if (tempRenameValue.trim()) {
                      confirmRename(record, tempRenameValue.trim());
                    } else {
                      message.warning(`请输入${record.isFolder ? '文件夹' : '文件'}名称`);
                    }
                  }}
                  onBlur={() => {
                    // 延迟失焦，避免点击按钮时先触发失焦
                    setTimeout(() => {
                      if (!tempRenameValue.trim()) {
                        cancelRename();
                      }
                    }, 200);
                  }}
                  placeholder={`请输入${record.isFolder ? '文件夹' : '文件'}名称`}
                  style={{ width: 200 }}
                />
                <CheckOutlined
                  style={{ color: '#52c41a', cursor: 'pointer', fontSize: 14 }}
                  onClick={() => {
                    if (tempRenameValue.trim()) {
                      confirmRename(record, tempRenameValue.trim());
                    } else {
                      message.warning(`请输入${record.isFolder ? '文件夹' : '文件'}名称`);
                    }
                  }}
                />
                <CloseOutlined
                  style={{ color: '#ff4d4f', cursor: 'pointer', fontSize: 14 }}
                  onClick={cancelRename}
                />
              </div>
            );
          }

          return (
            <div style={{ display: 'flex', alignItems: 'center' }}>
              {record.isFolder ? (
                <span style={{ marginRight: 8, fontSize: 16 }} role="img" aria-label="打开的文件夹" title="打开的文件夹">📂</span>
              ) : isImage(record.file_type) ? (
                <LazyThumbnail
                  src={`/api/document/preview/?id=${record.id}&is_public=${isPublic}&x-token=${X_TOKEN}`}
                  alt={record.display_name || text}
                  style={{
                    width: 32,
                    height: 32,
                    marginRight: 8,
                    objectFit: 'cover',
                    borderRadius: 4,
                  }}
                />
              ) : isVideo(record.file_type) ? (
                <span style={{ marginRight: 8, fontSize: 16 }} role="img" aria-label="视频" title="视频">🎬</span>
              ) : (
                getFileIcon(record.display_name || record.name, record.file_type)
              )}
              <span title={record.display_name || text}>{record.display_name || text}</span>
              {isPublic && record.created_by_id === currentUserId && (
                <Tag color="blue" style={{ marginLeft: 8, fontSize: 12 }}>我的</Tag>
              )}
              {isPublic && isCreatedByAdmin(record) && (
                <Tag color="gold" style={{ marginLeft: 8, fontSize: 12 }}>官方</Tag>
              )}
            </div>
          );
        }
      },
      ...(isSearching ? [{
        title: '路径',
        dataIndex: 'path',
        key: 'path',
        width: 200,
        ellipsis: true,
        render: (text) => (
          <span style={{ color: '#666', fontSize: 12 }}>
            {text || '-'}
          </span>
        )
      }] : []),
      {
        title: '类型',
        dataIndex: 'file_type',
        key: 'file_type',
        width: 120,
        ellipsis: true,
        sorter: true,
        showSorterTooltip: false,
        sortOrder: sortOrder.columnKey === 'file_type' ? sortOrder.order : null,
        render: (text, record) => (record.isFolder ? '文件夹' : getFileTypeLabel(text))
      },
      {
        title: '大小',
        dataIndex: 'size',
        key: 'size',
        width: 100,
        sorter: true,
        showSorterTooltip: false,
        sortOrder: sortOrder.columnKey === 'size' ? sortOrder.order : null,
        render: (text, record) => (record.isFolder ? '-' : formatFileSize(text))
      },
      {
        title: '修改时间',
        dataIndex: 'created_at',
        key: 'created_at',
        width: 180,
        sorter: true,
        showSorterTooltip: false,
        sortOrder: sortOrder.columnKey === 'created_at' ? sortOrder.order : null
      }
    ];

    if (isPublic) {
      columns.push({
        title: '创建人',
        dataIndex: 'created_by',
        key: 'created_by',
        width: 100,
        sorter: true,
        showSorterTooltip: false,
        sortOrder: sortOrder.columnKey === 'created_by' ? sortOrder.order : null,
        render: (text) => text || '-'
      });
    }

    return columns;
  }, [sortOrder, isSearching, isPublic, currentUserId, creatingFolder, tempFolderName, setTempFolderName, confirmCreateFolder, cancelCreateFolder, renamingRecord, tempRenameValue, setTempRenameValue, confirmRename, cancelRename]);
}
