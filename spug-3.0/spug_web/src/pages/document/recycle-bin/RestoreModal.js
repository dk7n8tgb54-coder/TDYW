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
  message
} from 'antd';
import {
  RollbackOutlined
} from '@ant-design/icons';
import store from './store';
import * as service from './service';
import styles from './index.module.less';

const { Title, Text } = Typography;

const RestoreModal = observer(function () {
  const handleOk = async () => {
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

        {/* 恢复选项 - 简化为只保留原位置 */}
        <div className={styles.restoreOptions}>
          <Text strong>恢复到：</Text>
          <Radio.Group
            value={store.restoreMode}
            style={{ width: '100%', marginTop: 16 }}
          >
            <Radio value="original" style={{ width: '100%' }}>
              <Space direction="vertical" size={0} style={{ marginLeft: 8 }}>
                <Text>原位置</Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  恢复到删除前的文件夹（如果原文件夹已删除，则恢复到根目录）
                </Text>
              </Space>
            </Radio>
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
