/**
 * 文件夹选择对话框组件
 * 用于复制/移动操作时选择目标文件夹
 */
import React from 'react';
import { Modal, Button } from 'antd';
import { RightOutlined } from '@ant-design/icons';
import { FolderIcon } from './FileTypeIcon';
import { sortByName } from '../utils/naturalSort';

const FolderTreeSelector = ({
  visible,
  title,
  allFolders,
  onConfirm,
  onCancel,
  confirmText = '确认',
  rootFolderId = null
}) => {
  const [currentFolderId, setCurrentFolderId] = React.useState(rootFolderId);
  const [viewFolder, setViewFolder] = React.useState(null);
  const [confirmLoading, setConfirmLoading] = React.useState(false);

  // 重置状态
  React.useEffect(() => {
    if (visible) {
      setCurrentFolderId(rootFolderId);
      setViewFolder(null);
      setConfirmLoading(false);
    }
  }, [visible, rootFolderId]);

  // 包装 onConfirm，防止重复提交并显示 loading
  const handleConfirm = React.useCallback(async (targetFolderId) => {
    if (confirmLoading) return;
    setConfirmLoading(true);
    try {
      await onConfirm(targetFolderId);
    } finally {
      setConfirmLoading(false);
    }
  }, [confirmLoading, onConfirm]);

  // 查找文件夹
  const findFolder = (id) => allFolders.find(f => f.id === id);

  // 获取从根到当前文件夹的路径
  const getFolderPath = (folderId) => {
    const path = [];
    let currentId = folderId;
    while (currentId) {
      const folder = findFolder(currentId);
      if (folder) {
        path.unshift(folder);
        currentId = folder.parent_id;
      } else {
        break;
      }
    }
    return path;
  };

  // 根目录信息
  const rootFolder = findFolder(rootFolderId);
  const breadcrumbRootName = rootFolder ? rootFolder.name : '全部文件';
  const emptyStateRootName = rootFolder ? rootFolder.name : '根目录';

  // 渲染路径导航
  const renderPath = (folderId) => {
    const path = getFolderPath(folderId);
    const currentFolder = findFolder(folderId);

    // rootFolderId 之上的层级截断不显示
    const displayPath = rootFolderId
      ? path.filter(f => f.id !== rootFolderId)
      : path;
    const atRoot = rootFolderId ? (folderId === rootFolderId) : (path.length === 0);

    return (
      <div style={{ display: 'flex', alignItems: 'center' }}>
        {!atRoot && (
          <>
            <span
              style={{
                color: '#1890ff',
                cursor: 'pointer',
                fontWeight: 500,
                marginRight: 8
              }}
              onClick={() => {
                const parentId = currentFolder?.parent_id;
                // 党建模式：父级为 rootFolderId 时回到根；非党建模式 parentId 为 null 时回到 null
                setCurrentFolderId(parentId || rootFolderId);
                setViewFolder(null);
              }}
            >
              返回上一级
            </span>
            <span style={{ margin: '0 8px', color: '#999' }}>|</span>
          </>
        )}
        <span
          style={{
            color: '#1890ff',
            cursor: 'pointer'
          }}
          onClick={() => {
            setCurrentFolderId(rootFolderId);
            setViewFolder(null);
          }}
        >
          {breadcrumbRootName}
        </span>
        {displayPath.map((folder, index) => (
          <React.Fragment key={folder.id}>
            <span style={{ margin: '0 8px', color: '#999' }}>{'>'}</span>
            {index === displayPath.length - 1 ? (
              <span style={{ color: '#999' }}>{folder.name}</span>
            ) : (
              <span
                style={{
                  color: '#1890ff',
                  cursor: 'pointer'
                }}
                onClick={() => {
                  setCurrentFolderId(folder.id);
                  setViewFolder(null);
                }}
              >
                {folder.name}
              </span>
            )}
          </React.Fragment>
        ))}
      </div>
    );
  };

  // 渲染空文件夹视图
  const renderViewFolder = () => {
    return (
      <div style={{ height: 400, display: 'flex', flexDirection: 'column' }}>
        {/* 顶部区域 - 路径导航栏 */}
        <div style={{
          marginBottom: 16,
          paddingBottom: 12,
          borderBottom: '1px solid #e8e8e8',
          fontSize: 14,
          flexShrink: 0
        }}>
          {renderPath(viewFolder.id)}
        </div>

        {/* 中间主体区域 */}
        <div style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '20px'
        }}>
          <span style={{ fontSize: 100, marginBottom: 24, filter: 'drop-shadow(0 4px 8px rgba(0,0,0,0.1))', display: 'inline-flex', lineHeight: 1 }}>
            <FolderIcon size={100} />
          </span>
          <div style={{ fontSize: 16, color: '#666', textAlign: 'center' }}>
            {title} {viewFolder.name} 文件夹
          </div>
        </div>

        {/* 底部操作区 */}
        <div style={{
          padding: '16px 24px',
          borderTop: '1px solid #e8e8e8',
          display: 'flex',
          justifyContent: 'flex-end',
          gap: '12px',
          flexShrink: 0
        }}>
          <Button onClick={onCancel}>取消</Button>
          <Button type="primary" loading={confirmLoading} onClick={() => handleConfirm(viewFolder.id)}>
            {confirmText}
          </Button>
        </div>
      </div>
    );
  };

  // 渲染文件夹列表视图
  const renderFolderList = () => {
    const currentFolder = findFolder(currentFolderId);
    // 按名称自然排序（后端扁平列表为字典序，"文件夹11"会排在"文件夹2"前）
    const subFolders = sortByName(allFolders.filter(f => f.parent_id === currentFolderId));

    return (
      <div style={{ height: 400, display: 'flex', flexDirection: 'column' }}>
        {/* 路径显示 */}
        <div style={{
          marginBottom: 16,
          paddingBottom: 12,
          borderBottom: '1px solid #e8e8e8',
          fontSize: 14,
          flexShrink: 0
        }}>
          {renderPath(currentFolderId)}
        </div>

        {/* 文件夹列表 */}
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {subFolders.length === 0 ? (
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              height: '100%'
            }}>
              <span style={{ fontSize: 80, marginBottom: 16, display: 'inline-flex', lineHeight: 1 }}><FolderIcon size={80} open /></span>
              <div style={{ fontSize: 16, color: '#666' }}>
                {title} {currentFolder ? currentFolder.name : emptyStateRootName} 文件夹
              </div>
            </div>
          ) : (
            <div>
              {subFolders.map(folder => (
                <div
                  key={folder.id}
                  onClick={() => {
                    setCurrentFolderId(folder.id);
                  }}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    padding: '12px 16px',
                    cursor: 'pointer',
                    borderRadius: 4,
                    transition: 'background 0.2s'
                  }}
                  onMouseEnter={(e) => e.currentTarget.style.background = '#f5f5f5'}
                  onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
                >
                  <span style={{ fontSize: 16, marginRight: 8, display: 'inline-flex', lineHeight: 1 }}>
                    <FolderIcon size={16} />
                  </span>
                  <span style={{ fontSize: 14 }}>{folder.name}</span>
                  <RightOutlined style={{ marginLeft: 'auto', fontSize: 12, color: '#999' }} />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  };

  return (
    <Modal
      visible={visible}
      title={title}
      onCancel={onCancel}
      onOk={() => {
        const targetFolderId = viewFolder ? viewFolder.id : currentFolderId;
        handleConfirm(targetFolderId);
      }}
      confirmLoading={confirmLoading}
      okText={confirmText}
      cancelText="取消"
      width={600}
      footer={viewFolder ? null : undefined} // 空文件夹视图使用自定义footer
    >
      {viewFolder ? renderViewFolder() : renderFolderList()}
    </Modal>
  );
};

export default FolderTreeSelector;
