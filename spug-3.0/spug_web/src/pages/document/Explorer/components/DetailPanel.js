/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Button, Empty, Tag } from 'antd';
import { LeftOutlined, RightOutlined, DownloadOutlined, EditOutlined, EyeOutlined, DeleteOutlined } from '@ant-design/icons';
import { formatFileSize, formatDate, getFileTypeLabel, getFileIcon } from '../utils';
import { FolderIcon, FileIcon as FileTypeIcon } from '../../components/FileTypeIcon';
import styles from '../../DocumentLayout.module.less';

export default function DetailPanel({
  expanded,
  onToggle,
  selectedItem,
  selectedCount,
  folderContents,
  onAction,
}) {
  return (
    <div className={`${styles.detailPanel} ${expanded ? styles.expanded : styles.collapsed}`}>
      <div className={styles.detailPanelContent}>
        {/* 面板顶部 */}
        <div className={styles.detailPanelHeader}>
          <span>
            {selectedItem ? (
              selectedCount > 1 ?
                `已选中 ${selectedCount} 个项目` :
                (selectedItem.isFolder ? '文件夹详情' : '文件详情')
            ) : '详情'}
          </span>
          <Button
            type="text"
            icon={expanded ? <RightOutlined /> : <LeftOutlined />}
            onClick={onToggle}
            style={{ fontSize: 12 }}
          />
        </div>

        {/* 面板内容 */}
        <div className={styles.detailPanelBody}>
          {selectedItem ? (
            selectedCount > 1 ? (
              <div className={styles.multiSelectInfo}>
                <div className={styles.multiSelectCount}>
                  已选中 {selectedCount} 个项目
                </div>
                <div className={styles.multiSelectHint}>
                  请选择单个项目查看详情
                </div>
              </div>
            ) : selectedItem.isFolder ? (
              <FolderDetail folderContents={folderContents} selectedItem={selectedItem} />
            ) : (
              <FileDetail selectedItem={selectedItem} onAction={onAction} />
            )
          ) : (
            <Empty
              image={<span style={{ display: 'inline-flex', lineHeight: 1 }}><FileTypeIcon size={48} /></span>}
              description={
                <span className={styles.emptyHint}>
                  选中文件 / 文件夹，查看详情
                </span>
              }
            />
          )}
        </div>
      </div>
    </div>
  );
}

function FolderDetail({ folderContents, selectedItem }) {
  if (!folderContents) {
    return (
      <div style={{ textAlign: 'center', color: '#999', padding: 20 }}>
        加载中...
      </div>
    );
  }

  return (
    <div>
      {/* 文件夹基本信息 */}
      <div className={styles.metaSection}>
        <div className={styles.metaLabel}>文件夹名</div>
        <div className={styles.metaValue} style={{ display: 'flex', alignItems: 'center' }}>
          <span style={{ marginRight: 8, display: 'inline-flex', alignItems: 'center', lineHeight: 1 }}><FolderIcon size={16} open /></span>
          {selectedItem.name}
        </div>
      </div>

      <div className={styles.metaSection}>
        <div className={styles.metaLabel}>创建时间</div>
        <div className={styles.metaValue}>{formatDate(selectedItem.created_at)}</div>
      </div>

      {/* 【2026-07-17 布局优化】文件夹创建人从树节点转移到详情面板展示 */}
      {selectedItem.created_by && (
        <div className={styles.metaSection}>
          <div className={styles.metaLabel}>创建人</div>
          <div className={styles.metaValue}>{selectedItem.created_by}</div>
        </div>
      )}

      <div className={styles.metaSection}>
        <div className={styles.metaLabel}>修改时间</div>
        <div className={styles.metaValue}>{formatDate(selectedItem.updated_at)}</div>
      </div>

      {/* 文件夹内容统计 */}
      <div className={styles.metaSection}>
        <div className={styles.metaLabel}>包含内容</div>
        <div className={styles.metaValue}>
          {folderContents.folders.length} 个文件夹，{folderContents.files.length} 个文件
        </div>
      </div>

      {folderContents.folders.length > 0 && (
        <div className={styles.folderContentSection}>
          <div className={styles.folderContentSectionTitle}>
            子文件夹 ({folderContents.folders.length})
          </div>
          {folderContents.folders.map(folder => (
            <div key={folder.id} className={styles.folderContentItem}>
              <span className={styles.folderContentIcon}><FolderIcon size={14} /></span>
              <span className={styles.folderContentName}>{folder.name}</span>
            </div>
          ))}
        </div>
      )}

      {folderContents.files.length > 0 && (
        <div className={styles.folderContentSection}>
          <div className={styles.folderContentSectionTitle}>
            文件 ({folderContents.files.length})
          </div>
          {folderContents.files.map(file => (
            <div key={file.id} className={styles.folderContentItem}>
              <span className={styles.folderContentIcon}>
                {getFileIcon(file.display_name || file.name, file.file_type, 14)}
              </span>
              <span className={styles.folderContentName}>{file.display_name || file.name}</span>
              <span className={styles.folderContentSize}>
                {formatFileSize(file.size)}
              </span>
            </div>
          ))}
        </div>
      )}

      {folderContents.folders.length === 0 && folderContents.files.length === 0 && (
        <Empty
          image={null}
          description={<span style={{ color: '#999', fontSize: 12 }}>文件夹为空</span>}
        />
      )}
    </div>
  );
}

function FileDetail({ selectedItem, onAction }) {
  return (
    <div>
      {/* 文件图标 + 文件名 */}
      <div className={styles.metaSection} style={{ textAlign: 'center', padding: '8px 0 16px' }}>
        <div style={{ display: 'inline-flex', lineHeight: 1, marginBottom: 8 }}>
          {getFileIcon(selectedItem.display_name || selectedItem.name, selectedItem.file_type, 48)}
        </div>
        <div className={styles.metaValue} style={{ fontWeight: 500, fontSize: 14 }}>
          {selectedItem.display_name || selectedItem.name}
        </div>
      </div>

      {/* 快捷动作 */}
      <div className={styles.detailActions}>
        <Button size="small" icon={<EyeOutlined />} onClick={() => onAction && onAction('preview', selectedItem)}>
          预览
        </Button>
        <Button size="small" icon={<DownloadOutlined />} onClick={() => onAction && onAction('download', selectedItem)}>
          下载
        </Button>
        <Button size="small" icon={<EditOutlined />} onClick={() => onAction && onAction('rename', selectedItem)}>
          重命名
        </Button>
        <Button size="small" danger icon={<DeleteOutlined />} onClick={() => onAction && onAction('delete', selectedItem)}>
          删除
        </Button>
      </div>

      {/* 元数据 */}
      <div className={styles.metaSection}>
        <div className={styles.metaLabel}>文件类型</div>
        <div className={styles.metaValue}>
          <Tag color="blue">{getFileTypeLabel(selectedItem.file_type)}</Tag>
        </div>
      </div>

      <div className={styles.metaSection}>
        <div className={styles.metaLabel}>文件大小</div>
        <div className={styles.metaValue}>{formatFileSize(selectedItem.size)}</div>
      </div>

      <div className={styles.metaSection}>
        <div className={styles.metaLabel}>创建者</div>
        <div className={styles.metaValue}>{selectedItem.created_by || '未知'}</div>
      </div>

      <div className={styles.metaSection}>
        <div className={styles.metaLabel}>创建时间</div>
        <div className={styles.metaValue}>{formatDate(selectedItem.created_at)}</div>
      </div>

      <div className={styles.metaSection}>
        <div className={styles.metaLabel}>修改时间</div>
        <div className={styles.metaValue}>{formatDate(selectedItem.updated_at)}</div>
      </div>
    </div>
  );
}
