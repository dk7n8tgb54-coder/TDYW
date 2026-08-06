/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useCallback, useState, useEffect, useRef } from 'react';
import { Tag, Input, message } from 'antd';
import { CheckOutlined, CloseOutlined, LoadingOutlined, FileImageOutlined } from '@ant-design/icons';
import { isImage, isVideo, formatFileSize, getFileTypeLabel, getFileIcon, getFolderIcon, isCreatedByAdmin } from '../utils';
import { FolderIcon, VideoIcon, getFileTypeIcon } from '../../components/FileTypeIcon';
import PreviewImage from '../../components/PreviewImage';  // 【H-2修复】安全预览组件

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
        // 【2026-07-21 列宽调整】文件名列固定 400px 不伸缩，保证文件名清晰可见；
        //   超长名称单行省略，悬停 title 显示完整名称。
        //   类型/大小/修改时间/创建人 列不设 width，在 tableLayout="fixed" 下弹性伸缩。
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
                <span style={{ width: 36, flexShrink: 0, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', lineHeight: 1 }}><FolderIcon size={24} /></span>
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
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }} onClick={e => e.stopPropagation()}>
                {record.isFolder ? (
                  <span style={{ width: 36, flexShrink: 0, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', lineHeight: 1 }}><FolderIcon size={24} /></span>
                ) : isImage(record.file_type) ? (
                  <PreviewImage
                    fileId={record.id}
                    isPublic={isPublic}
                    thumbnail={!!record.thumbnail_path}
                    alt={record.display_name || text}
                    style={{
                      width: 36,
                      height: 36,
                      objectFit: 'cover',
                      borderRadius: 4,
                      background: '#f0f0f0',
                      flexShrink: 0,
                    }}
                    onError={(e) => { e.target.style.display = 'none'; }}
                  />
                ) : isVideo(record.file_type) ? (
                  <span style={{ width: 36, flexShrink: 0, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', lineHeight: 1 }}><VideoIcon size={24} /></span>
                ) : (
                  <span style={{ width: 36, flexShrink: 0, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', lineHeight: 1 }}>{getFileTypeIcon(record.display_name || record.name, record.file_type, 24)}</span>
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
            <div style={{ display: 'flex', alignItems: 'center', minWidth: 0 }}>
              {record.isFolder ? (
                <span style={{ width: 36, flexShrink: 0, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', lineHeight: 1 }}><FolderIcon size={24} open /></span>
              ) : isImage(record.file_type) ? (
                <PreviewImage
                  fileId={record.id}
                  isPublic={isPublic}
                  thumbnail={!!record.thumbnail_path}
                  alt={record.display_name || text}
                  style={{
                    width: 36,
                    height: 36,
                    marginRight: 0,
                    objectFit: 'cover',
                    borderRadius: 4,
                    flexShrink: 0,
                  }}
                />
              ) : isVideo(record.file_type) ? (
                  <span style={{ width: 36, flexShrink: 0, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', lineHeight: 1 }}><VideoIcon size={24} /></span>
              ) : (
                <span style={{ width: 36, flexShrink: 0, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', lineHeight: 1 }}>{getFileTypeIcon(record.display_name || record.name, record.file_type, 24)}</span>
              )}
              <span title={record.display_name || text} style={{ marginLeft: 8, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{record.display_name || text}</span>
              {isPublic && isCreatedByAdmin(record) && (
                <Tag color="gold" style={{ marginLeft: 8, flexShrink: 0, fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>官方</Tag>
              )}
            </div>
          );
        }
      },
      ...(isSearching ? [{
        title: '路径',
        dataIndex: 'path',
        key: 'path',
        width: 180,
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
        // 【2026-07-21 列宽调整】去掉固定 width，弹性伸缩（文件名列固定 400px）
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
        // 【2026-07-21 列宽调整】去掉固定 width，弹性伸缩（文件名列固定 400px）
        sorter: true,
        showSorterTooltip: false,
        sortOrder: sortOrder.columnKey === 'size' ? sortOrder.order : null,
        render: (text, record) => (record.isFolder ? '-' : formatFileSize(text))
      },
      {
        title: '修改时间',
        dataIndex: 'created_at',
        key: 'created_at',
        // 【2026-07-21 列宽调整】去掉固定 width，弹性伸缩（文件名列固定 400px）
        //   ellipsis:true 强制 white-space:nowrap，杜绝日期时间拆两行撑高行高。
        ellipsis: true,
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
        // 【2026-07-21 列宽调整】去掉固定 width，弹性伸缩（文件名列固定 400px）
        ellipsis: true,
        sorter: true,
        showSorterTooltip: false,
        sortOrder: sortOrder.columnKey === 'created_by' ? sortOrder.order : null,
        render: (text, record) => {
          const name = text || '-';
          const isMine = record.created_by_id === currentUserId;
          return (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, maxWidth: '100%', overflow: 'hidden' }} title={name}>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}>{name}</span>
              {isMine && <Tag color="blue" style={{ flexShrink: 0, fontSize: 10, lineHeight: '16px', padding: '0 4px', margin: 0 }}>我</Tag>}
            </span>
          );
        }
      });
    }

    return columns;
  }, [sortOrder, isSearching, isPublic, currentUserId, creatingFolder, tempFolderName, setTempFolderName, confirmCreateFolder, cancelCreateFolder, renamingRecord, tempRenameValue, setTempRenameValue, confirmRename, cancelRename]);
}
