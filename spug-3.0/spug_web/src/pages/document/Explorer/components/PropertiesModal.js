/**
 * 属性弹窗组件
 * 右键菜单"属性"对应的详情弹窗，展示文件/文件夹的完整属性信息
 * 文件夹属性会递归统计所有层级的子文件夹和文件
 */
import React, { useState, useEffect } from 'react';
import { Modal, Descriptions, Tag, Spin } from 'antd';
import { formatFileSize, formatDate, getFileTypeLabel, getFileIcon } from '../utils';
import http from 'libs/http';

export default function PropertiesModal({ visible, record, isPublic, onClose }) {
  const [folderStats, setFolderStats] = useState(null);
  const [loading, setLoading] = useState(false);

  const isFolder = record?.isFolder;

  // 文件夹打开时调用递归统计 API
  useEffect(() => {
    if (visible && isFolder && record?.id) {
      setLoading(true);
      setFolderStats(null);
      http.get('/api/document/folder/properties/', {
        params: { id: record.id, is_public: isPublic }
      })
        .then(res => {
          setFolderStats(res);
        })
        .catch(() => {
          setFolderStats(null);
        })
        .finally(() => {
          setLoading(false);
        });
    } else {
      setFolderStats(null);
    }
  }, [visible, isFolder, record?.id, isPublic]);

  if (!record) return null;

  return (
    <Modal
      title={isFolder ? '文件夹属性' : '文件属性'}
      visible={visible}
      onCancel={onClose}
      footer={null}
      width={480}
      destroyOnClose
    >
      <Spin spinning={loading}>
        <Descriptions column={1} size="small" bordered style={{ marginTop: 8 }}>
          {/* 名称 */}
          <Descriptions.Item label={isFolder ? '文件夹名' : '文件名'}>
            <div style={{ display: 'flex', alignItems: 'center' }}>
              {isFolder
                ? <span style={{ marginRight: 8, fontSize: 18 }} role="img" aria-label="文件夹">📂</span>
                : getFileIcon(record.display_name || record.name, record.file_type)
              }
              <span style={{ wordBreak: 'break-all', fontWeight: 500 }}>
                {isFolder ? record.name : (record.display_name || record.name)}
              </span>
            </div>
          </Descriptions.Item>

          {/* 文件特有字段 */}
          {!isFolder && (
            <>
              <Descriptions.Item label="文件类型">
                <Tag color="blue">{getFileTypeLabel(record.file_type)}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="文件大小">
                {formatFileSize(record.size)}
                {record.size > 0 && (
                  <span style={{ color: '#999', fontSize: 12, marginLeft: 8 }}>
                    ({record.size.toLocaleString()} 字节)
                  </span>
                )}
              </Descriptions.Item>
            </>
          )}

          {/* 所在位置 */}
          <Descriptions.Item label="所在位置">
            <span style={{ fontSize: 12 }}>
              {isFolder
                ? (record.parent_id ? `文件夹ID: ${record.parent_id}` : '根目录')
                : (record.folder_id ? `文件夹ID: ${record.folder_id}` : (record.parent_id ? `文件夹ID: ${record.parent_id}` : '根目录'))
              }
            </span>
          </Descriptions.Item>

          {/* 文件夹内容统计（递归所有层级） */}
          {isFolder && (
            <Descriptions.Item label="包含内容">
              {folderStats ? (
                <span style={{ fontSize: 13 }}>
                  {folderStats.sub_folder_count} 个文件夹，{folderStats.file_count} 个文件
                  {folderStats.total_size > 0 && (
                    <span style={{ color: '#999', marginLeft: 8 }}>
                      (共 {formatFileSize(folderStats.total_size)})
                    </span>
                  )}
                </span>
              ) : !loading ? (
                <span style={{ color: '#999' }}>无法获取统计信息</span>
              ) : null}
            </Descriptions.Item>
          )}

          {/* 创建者 */}
          <Descriptions.Item label="创建者">
            {(isFolder && folderStats?.created_by) || record.created_by || '未知'}
          </Descriptions.Item>

          {/* 创建时间 */}
          <Descriptions.Item label="创建时间">
            <span style={{ fontSize: 12 }}>
              {formatDate((isFolder && folderStats?.created_at) || record.created_at)}
            </span>
          </Descriptions.Item>

          {/* 修改时间 */}
          <Descriptions.Item label="修改时间">
            <span style={{ fontSize: 12 }}>
              {formatDate((isFolder && folderStats?.updated_at) || record.updated_at)}
            </span>
          </Descriptions.Item>
        </Descriptions>
      </Spin>
    </Modal>
  );
}
