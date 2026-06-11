/**
 * 文件网格视图组件
 * 缩略图/网格模式展示文件列表
 */
import React, { useMemo, useState, useCallback, useRef, useEffect } from 'react';
import { Empty, Checkbox, Tag, Pagination } from 'antd';
import { isImage, isVideo, formatFileSize, getFileTypeLabel, isCreatedByAdmin } from '../utils';
import { FolderIcon, VideoIcon, getFileTypeIcon } from '../../components/FileTypeIcon';
import PreviewImage from '../../components/PreviewImage';  // 【H-2修复】安全预览组件
import styles from './FileGrid.module.less';

/**
 * 网格项缩略图组件
 * 【性能优化】使用 React.memo 避免不必要的重渲染
 */
const GridThumbnail = React.memo(({ record, isPublic }) => {
  const [hasError, setHasError] = useState(false);

  if (record.isFolder) {
    return (
      <div className={styles.thumbnailFolder}>
        <FolderIcon size={46} open />
      </div>
    );
  }

  if (isImage(record.file_type) && !hasError) {
    // 【H-2修复】使用短时效 preview_token 替代 x-token
    return (
      <PreviewImage
        fileId={record.id}
        isPublic={isPublic}
        thumbnail={!!record.thumbnail_path}
        alt={record.display_name || record.name}
        style={{ width: '100%', height: '100%', objectFit: 'cover' }}
        onError={() => setHasError(true)}
      />
    );
  }

  if (isVideo(record.file_type)) {
    return (
      <div className={styles.thumbnailIcon}>
        <VideoIcon size={44} />
      </div>
    );
  }

  return (
    <div className={styles.thumbnailIcon}>
      {getFileTypeIcon(record.display_name || record.name, record.file_type, 44)}
    </div>
  );
});

/**
 * 文件网格视图组件
 */
const FileGrid = ({
  dataSource,
  loading,
  selectedRowKeys,
  onSelectChange,
  onRow,
  isPublic,
  currentUserId,
  pagination,
}) => {
  // 【性能优化】使用 ref 存储 selectedRowKeys，避免闭包导致的重复计算
  const selectedRowKeysRef = useRef(Array.isArray(selectedRowKeys) ? selectedRowKeys : []);
  useEffect(() => {
    selectedRowKeysRef.current = selectedRowKeys;
  }, [selectedRowKeys]);

  // 【性能优化】使用 ref 版本的 isSelected，避免每次 selectedRowKeys 变化都重算
  const isSelected = useCallback((key) =>
    selectedRowKeysRef.current.includes(key)
  , []);  // 空依赖，因为使用 ref

  const handleSelect = useCallback((key, e) => {
    e.stopPropagation();
    // 【性能优化】使用 ref 获取最新选中状态
    const currentKeys = selectedRowKeysRef.current;
    const newKeys = currentKeys.includes(key)
      ? currentKeys.filter(k => k !== key)
      : [...currentKeys, key];
    if (onSelectChange) onSelectChange(newKeys);
  }, [onSelectChange]);  // 空依赖，因为使用 ref

  const handleClick = useCallback((record) => {
    const rowHandlers = onRow ? onRow(record) : null;
    if (rowHandlers && rowHandlers.onClick) rowHandlers.onClick();
  }, [onRow]);

  const handleDoubleClick = useCallback((record) => {
    const rowHandlers = onRow ? onRow(record) : null;
    if (rowHandlers && rowHandlers.onDoubleClick) rowHandlers.onDoubleClick();
  }, [onRow]);

  const handleContextMenu = useCallback((e, record) => {
    if (!isSelected(record.key)) {
      if (onSelectChange) onSelectChange([record.key]);
    }
    const rowHandlers = onRow ? onRow(record) : null;
    if (rowHandlers && rowHandlers.onContextMenu) rowHandlers.onContextMenu(e);
  }, [isSelected, onSelectChange, onRow]);

  if (!loading && (!dataSource || dataSource.length === 0)) {
    return (
      <div className={styles.emptyState}>
        <Empty
          description={
            isPublic
              ? <div><div style={{ fontSize: 16, marginBottom: 8 }}>暂无公共共享文件</div><div style={{ fontSize: 14, color: '#999' }}>快来上传第一个文件吧</div></div>
              : <div><div style={{ fontSize: 16, marginBottom: 8 }}>暂无文件</div><div style={{ fontSize: 14, color: '#999' }}>点击上传按钮开始上传</div></div>
          }
        />
      </div>
    );
  }

  return (
    <div className={styles.gridContainer}>
      {loading && (
        <div className={styles.loadingOverlay}>
          <span role="img" aria-label="加载中" style={{ fontSize: 32 }}>⏳</span>
        </div>
      )}
      <div className={styles.grid}>
        {dataSource?.map((record) => (
          <div
            key={record.key}
            className={`${styles.gridItem} ${isSelected(record.key) ? styles.gridItemSelected : ''}`}
            onClick={() => handleClick(record)}
            onDoubleClick={() => handleDoubleClick(record)}
            onContextMenu={(e) => handleContextMenu(e, record)}
          >
            <div className={styles.checkWrapper} onClick={(e) => handleSelect(record.key, e)}>
              <Checkbox checked={isSelected(record.key)} />
            </div>
            <div className={styles.thumbnailArea}>
              <GridThumbnail record={record} isPublic={isPublic} />
            </div>
            <div className={styles.fileInfo}>
              <div className={styles.fileName} title={record.display_name || record.name}>
                {record.display_name || record.name}
              </div>
              <div className={styles.fileMeta}>
                {record.isFolder ? '文件夹' : (
                  <>
                    <span className={styles.fileType}>{getFileTypeLabel(record.file_type)}</span>
                    {record.size && <span className={styles.fileSize}>{formatFileSize(record.size)}</span>}
                  </>
                )}
                {isPublic && record.created_by_id === currentUserId && (
                  <Tag color="blue" style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>我</Tag>
                )}
                {isPublic && isCreatedByAdmin(record) && (
                  <Tag color="gold" style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>官方</Tag>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
      {pagination && (
        <div className={styles.paginationWrapper}>
          <Pagination
            current={pagination.current || 1}
            pageSize={pagination.pageSize || 20}
            total={pagination.total || 0}
            onChange={pagination.onChange}
            showSizeChanger
            showQuickJumper
            pageSizeOptions={['10', '20', '50', '100']}
            showTotal={(total, range) => `${range[0]}-${range[1]} 项 / 共 ${total} 项`}
            size="small"
          />
        </div>
      )}
    </div>
  );
};

export default React.memo(FileGrid);
