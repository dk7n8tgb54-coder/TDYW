/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { 
  Modal, 
  Radio, 
  Space, 
  Typography, 
  Alert,
  Spin,
  TreeSelect,
  message
} from 'antd';
import { 
  RollbackOutlined, 
  FolderOutlined,
  GlobalOutlined
} from '@ant-design/icons';
import store from './store';
import * as service from './service';
import styles from './index.module.less';

const { Title, Text } = Typography;

const RestoreModal = observer(function () {
  const [folderTree, setFolderTree] = React.useState([]);
  const [treeLoading, setTreeLoading] = React.useState(false);

  // 加载文件夹树
  React.useEffect(() => {
    if (store.restoreVisible && store.restoreMode === 'custom') {
      loadFolderTree();
    }
  }, [store.restoreVisible, store.restoreMode]);

  const loadFolderTree = async () => {
    setTreeLoading(true);
    try {
      // 从document模块导入文件夹服务
      const http = (await import('libs/http')).default;
      const [privateFolders, publicFolders] = await Promise.all([
        http.get('/api/document/folder/', { params: { space: 'private' } }),
        http.get('/api/document/folder/', { params: { space: 'public' } }),
      ]);

      const treeData = [
        {
          title: '私有空间',
          value: 'private_root',
          key: 'private_root',
          icon: <FolderOutlined />,
          children: buildTree(privateFolders.folders || []),
          disabled: true,
        },
        {
          title: '公共空间',
          value: 'public_root',
          key: 'public_root',
          icon: <GlobalOutlined />,
          children: buildTree(publicFolders.folders || []),
          disabled: true,
        },
      ];
      setFolderTree(treeData);
    } catch (error) {
      message.error('加载文件夹列表失败');
    } finally {
      setTreeLoading(false);
    }
  };

  // 【P1/P2修复】构建树形结构 - 添加深度限制防止无限递归
  const buildTree = (folders, parentId = null, depth = 0) => {
    // 【P1修复】限制递归深度为10层，防止循环引用导致栈溢出
    if (depth > 10) {
      console.warn('[RestoreModal] 文件夹树深度超过10层，停止递归');
      return [];
    }
    
    return folders
      .filter(f => f.parent === parentId)
      .map(f => ({
        title: f.name,
        value: f.id,
        key: f.id,
        icon: <FolderOutlined />,
        children: buildTree(folders, f.id, depth + 1),
      }));
  };

  const handleModeChange = (e) => {
    store.setRestoreMode(e.target.value);
    if (e.target.value === 'custom') {
      store.setTargetFolderId(null);
    }
  };

  const handleFolderChange = (value) => {
    // 排除根节点
    if (value === 'private_root' || value === 'public_root') {
      store.setTargetFolderId(null);
      return;
    }
    store.setTargetFolderId(value);
  };

  const handleOk = async () => {
    if (store.restoreMode === 'custom' && !store.targetFolderId) {
      message.warning('请选择目标文件夹');
      return;
    }
    await store.doRestore();
  };

  // 【P1修复】取消时不应清空选中项，仅成功后才清空
  const handleCancel = () => {
    store.hideRestoreModal();
    // store.clearSelection(); // 【P1修复】取消时不清空选中项
  };

  // 获取选中的文件列表
  const selectedFiles = store.selectedRows.slice(0, 5);
  const hasMoreFiles = store.selectedCount > 5;

  return (
    <Modal
      title={
        <Space>
          <RollbackOutlined />
          <span>恢复项目</span>
        </Space>
      }
      visible={store.restoreVisible}
      onOk={handleOk}
      onCancel={handleCancel}
      confirmLoading={store.operationLoading}
      width={600}
      okText="确认恢复"
      cancelText="取消"
    >
      <div className={styles.restoreContent}>
        {/* 已选择的项目 */}
        <div className={styles.selectedSection}>
          <Text strong>已选择 {store.selectedCount} 个项目：</Text>
          <div className={styles.fileList}>
            {selectedFiles.map(item => {
              const isFolder = item.type === 'folder';
              return (
                <div key={item.id} className={styles.fileItem}>
                  {isFolder ? (
                    <span className={styles.folderIcon}>📁</span>
                  ) : (
                    service.FileIconMap[service.getFileIcon(item.file_type, item.name)] || service.FileIconMap.file
                  )}
                  <div className={styles.fileInfo}>
                    <div className={styles.fileNameText} title={isFolder ? item.name : (item.display_name || item.name)}>
                      {isFolder ? item.name : (item.display_name || item.name)}
                    </div>
                    <div className={styles.fileSize}>
                      {service.formatFileSize(isFolder ? item.total_size : item.file_size)}
                    </div>
                  </div>
                </div>
              );
            })}
            {hasMoreFiles && (
              <div className={styles.moreFiles}>
                还有 {store.selectedCount - 5} 个项目...
              </div>
            )}
          </div>
        </div>

        {/* 恢复选项 */}
        <div className={styles.restoreOptions}>
          <Text strong>恢复到：</Text>
          <Radio.Group 
            value={store.restoreMode} 
            onChange={handleModeChange}
            style={{ width: '100%', marginTop: 16 }}
          >
            <Space direction="vertical" style={{ width: '100%' }}>
              <Radio value="original">
                <Space direction="vertical" size={0} style={{ marginLeft: 8 }}>
                  <Text>原位置</Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    恢复到删除前的文件夹（如果原文件夹已删除，则恢复到根目录）
                  </Text>
                </Space>
              </Radio>
              
              <Radio value="current">
                <Space direction="vertical" size={0} style={{ marginLeft: 8 }}>
                  <Text>当前浏览的文件夹</Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    恢复到当前正在浏览的文件夹位置
                  </Text>
                </Space>
              </Radio>
              
              <Radio value="custom">
                <Space direction="vertical" size={0} style={{ marginLeft: 8, width: '100%' }}>
                  <Text>指定文件夹</Text>
                  <div style={{ marginTop: 8, marginLeft: 24 }}>
                    <Spin spinning={treeLoading}>
                      <TreeSelect
                        style={{ width: 300 }}
                        value={store.targetFolderId}
                        dropdownStyle={{ maxHeight: 400, overflow: 'auto' }}
                        treeData={folderTree}
                        placeholder="请选择目标文件夹"
                        treeDefaultExpandAll
                        onChange={handleFolderChange}
                        disabled={store.restoreMode !== 'custom'}
                        treeIcon
                      />
                    </Spin>
                  </div>
                </Space>
              </Radio>
            </Space>
          </Radio.Group>
        </div>

        {/* 提示信息 */}
        <Alert
          message="提示"
          description="如果恢复的目标位置存在同名文件，系统将自动为新文件添加序号后缀。"
          type="info"
          showIcon
          style={{ marginTop: 16 }}
        />
      </div>
    </Modal>
  );
});

export default RestoreModal;
