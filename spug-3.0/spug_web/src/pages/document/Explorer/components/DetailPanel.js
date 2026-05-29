/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Button, Empty, Descriptions, Tag } from 'antd';
import { LeftOutlined, RightOutlined } from '@ant-design/icons';
import { formatFileSize, formatDate, getFileTypeLabel, getFileIcon } from '../utils';

export default function DetailPanel({
  expanded,
  onToggle,
  selectedItem,
  selectedCount,
  folderContents,
}) {
  return (
    <div
      className="detail-panel"
      style={{
        width: expanded ? 400 : 0,
        overflow: 'hidden',
        transition: 'width 0.3s ease',
        borderLeft: expanded ? '1px solid #d9d9d9' : 'none',
        background: '#fafafa',
        flexShrink: 0,
        minWidth: 0
      }}
    >
      <div className="detail-panel-content">
        {/* 面板顶部 */}
        <div
          className="detail-panel-header"
          style={{
            padding: '12px 16px',
            borderBottom: '1px solid #e8e8e8',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            background: '#fff'
          }}
        >
          <span style={{ fontWeight: 500, fontSize: 14 }}>
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
        <div style={{ padding: 16, overflow: 'auto', height: 'calc(100% - 50px)' }}>
          {selectedItem ? (
            selectedCount > 1 ? (
              <div style={{ textAlign: 'center', padding: '20px 0' }}>
                <div style={{ fontSize: 16, color: '#333', marginBottom: 8 }}>
                  已选中 {selectedCount} 个项目
                </div>
                <div style={{ fontSize: 13, color: '#999' }}>
                  请选择单个项目查看详情
                </div>
              </div>
            ) : selectedItem.isFolder ? (
              <FolderDetail folderContents={folderContents} />
            ) : (
              <FileDetail selectedItem={selectedItem} />
            )
          ) : (
            <Empty
              image={<span style={{ fontSize: 48 }} role="img" aria-label="文件">📄</span>}
              description={
                <span style={{ color: '#999', fontSize: 14 }}>
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

function FolderDetail({ folderContents }) {
  if (!folderContents) {
    return (
      <div style={{ textAlign: 'center', color: '#999', padding: 20 }}>
        加载中...
      </div>
    );
  }

  return (
    <div>
      <div style={{ marginBottom: 16, fontWeight: 500 }}>文件夹内容</div>
      
      {folderContents.folders.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 12, color: '#999', marginBottom: 8 }}>
            文件夹 ({folderContents.folders.length})
          </div>
          {folderContents.folders.map(folder => (
            <div
              key={folder.id}
              style={{
                padding: '8px 12px',
                marginBottom: 4,
                background: '#f5f5f5',
                borderRadius: 4,
                display: 'flex',
                alignItems: 'center',
                fontSize: 13
              }}
            >
              <span style={{ marginRight: 8, fontSize: 16 }} role="img" aria-label="文件夹">📂</span>
              <span style={{ flex: 1 }}>{folder.name}</span>
            </div>
          ))}
        </div>
      )}

      {folderContents.files.length > 0 && (
        <div>
          <div style={{ fontSize: 12, color: '#999', marginBottom: 8 }}>
            文件 ({folderContents.files.length})
          </div>
          {folderContents.files.map(file => (
            <div
              key={file.id}
              style={{
                padding: '8px 12px',
                marginBottom: 4,
                background: '#f5f5f5',
                borderRadius: 4,
                display: 'flex',
                alignItems: 'center',
                fontSize: 13
              }}
            >
              {getFileIcon(file.display_name || file.name, file.file_type)}
              <span style={{ flex: 1 }}>{file.display_name || file.name}</span>
              <span style={{ fontSize: 12, color: '#999', marginLeft: 8 }}>
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

function FileDetail({ selectedItem }) {
  return (
    <Descriptions column={1} size="small" bordered>
      <Descriptions.Item label="文件名">
        <div style={{ display: 'flex', alignItems: 'center' }}>
          {getFileIcon(selectedItem.display_name || selectedItem.name, selectedItem.file_type)}
          <span style={{ wordBreak: 'break-all' }}>{selectedItem.display_name || selectedItem.name}</span>
        </div>
      </Descriptions.Item>
      <Descriptions.Item label="文件格式">
        <Tag color="blue">{getFileTypeLabel(selectedItem.file_type)}</Tag>
      </Descriptions.Item>
      <Descriptions.Item label="文件大小">
        {formatFileSize(selectedItem.size)}
      </Descriptions.Item>
      <Descriptions.Item label="创建时间">
        <span style={{ fontSize: 12 }}>{formatDate(selectedItem.created_at)}</span>
      </Descriptions.Item>
      <Descriptions.Item label="最后修改时间">
        <span style={{ fontSize: 12 }}>{formatDate(selectedItem.updated_at)}</span>
      </Descriptions.Item>
      <Descriptions.Item label="所在目录">
        <span style={{ fontSize: 12 }}>
          {selectedItem.parent_id ? `文件夹ID: ${selectedItem.parent_id}` : '根目录'}
        </span>
      </Descriptions.Item>
    </Descriptions>
  );
}
