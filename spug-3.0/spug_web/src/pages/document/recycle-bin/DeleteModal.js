/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { 
  Modal, 
  Space, 
  Typography, 
  Alert,
  Checkbox,
  Progress,
  Tag
} from 'antd';
import { 
  ExclamationCircleOutlined,
  DeleteOutlined,
  WarningOutlined
} from '@ant-design/icons';
import store from './store';
import * as service from './service';
import styles from './index.module.less';

const { Title, Text, Paragraph } = Typography;

const DeleteModal = observer(function () {
  const [confirmed, setConfirmed] = React.useState(false);

  // 弹窗关闭时重置确认状态
  React.useEffect(() => {
    if (!store.deleteVisible) {
      setConfirmed(false);
    }
  }, [store.deleteVisible]);

  const handleOk = async () => {
    if (!confirmed) {
      return;
    }
    await store.doPermanentDelete();
  };

  // 【P1修复】取消时不应清空选中项，仅成功后才清空
  const handleCancel = () => {
    store.hideDeleteModal();
    // store.clearSelection(); // 【P1修复】取消时不清空选中项
  };

  // 获取选中的文件列表
  const selectedFiles = store.selectedRows.slice(0, 10);
  const hasMoreFiles = store.selectedCount > 10;

  // 判断是否有即将过期的文件
  const hasExpiringFiles = store.selectedRows.some(file => file.retention_days_left <= 7);

  return (
    <Modal
      title={
        <Space>
          <DeleteOutlined />
          <span>彻底删除文件</span>
        </Space>
      }
      visible={store.deleteVisible}
      onOk={handleOk}
      onCancel={handleCancel}
      confirmLoading={store.operationLoading}
      width={550}
      okText="确认删除"
      cancelText="取消"
      okButtonProps={{
        danger: true,
        disabled: !confirmed,
      }}
    >
      <div className={styles.deleteContent}>
        {/* 警告图标和标题 */}
        <div className={styles.deleteWarning}>
          <ExclamationCircleOutlined className={styles.warningIcon} />
          <div className={styles.warningTitle}>确认彻底删除？</div>
          <div className={styles.warningDesc}>
            文件删除后将无法恢复，请谨慎操作！
          </div>
        </div>

        {/* 统计信息 */}
        <div className={styles.deleteStats}>
          <Space size="large">
            <div className={styles.deleteStatItem}>
              <Text type="secondary">已选择</Text>
              <div className={styles.deleteStatValue}>
                {store.selectedCount} 个文件
              </div>
            </div>
            <div className={styles.deleteStatItem}>
              <Text type="secondary">占用空间</Text>
              <div className={styles.deleteStatValue}>
                {service.formatFileSize(store.selectedTotalSize)}
              </div>
            </div>
          </Space>
        </div>

        {/* 文件列表 */}
        <div className={styles.fileListSection}>
          <Text strong>待删除文件列表：</Text>
          <div className={styles.fileListContainer}>
            {selectedFiles.map(file => (
              <div 
                key={file.id} 
                className={`${styles.deleteFileItem} ${file.retention_days_left <= 7 ? styles.deleteFileItemUrgent : ''}`}
              >
                {service.FileIconMap[service.getFileIcon(file.file_type, file.name)] || service.FileIconMap.file}
                <div className={styles.deleteFileInfo}>
                  <div className={styles.deleteFileName} title={file.display_name}>
                    {file.display_name}
                    {file.retention_days_left <= 7 && (
                      <Tag color="error" style={{ marginLeft: 8 }}>
                        {file.retention_days_left}天后自动清理
                      </Tag>
                    )}
                  </div>
                  <div className={styles.deleteFileMeta}>
                    {service.formatFileSize(file.file_size)} · {file.space === 'private' ? '私有空间' : '公共空间'}
                  </div>
                </div>
              </div>
            ))}
            {hasMoreFiles && (
              <div className={styles.moreFiles}>
                还有 {store.selectedCount - 10} 个文件...
              </div>
            )}
          </div>
        </div>

        {/* 即将过期提示 */}
        {hasExpiringFiles && (
          <Alert
            message="包含即将自动清理的文件"
            description="选中的文件中有部分将在7天内被自动清理，您可以等待自动清理，无需手动删除。"
            type="warning"
            showIcon
            icon={<WarningOutlined />}
            style={{ marginTop: 16, marginBottom: 16 }}
          />
        )}

        {/* 批量提示 */}
        {store.selectedCount > 10 && (
          <Alert
            message="大批量删除"
            description={`您选择了${store.selectedCount}个文件，删除操作将使用异步模式处理，请稍后查看结果。`}
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
          />
        )}

        {/* 确认复选框 */}
        <div className={styles.confirmSection}>
          <Checkbox 
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
          >
            <Text type="danger">
              我确认要彻底删除以上文件，并了解此操作不可恢复
            </Text>
          </Checkbox>
        </div>

        {/* 【P1/P2修复】操作进度 */}
        {store.operationLoading && (
          <div className={styles.loadingSection}>
            <Text type="secondary">正在删除，请稍候...</Text>
          </div>
        )}
      </div>
    </Modal>
  );
});

export default DeleteModal;
