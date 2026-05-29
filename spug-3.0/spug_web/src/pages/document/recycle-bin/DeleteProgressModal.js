/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 * 
 * 【方案一新增】删除进度弹窗组件
 * 显示批量删除任务的实时进度
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Modal, Progress, List, Space, Tag } from 'antd';
import { 
  LoadingOutlined, 
  CheckCircleOutlined, 
  CloseCircleOutlined,
  FileOutlined,
  FolderOutlined
} from '@ant-design/icons';
import store from './store';
import styles from './index.module.less';

/**
 * 获取状态标签
 */
const getStatusTag = (status) => {
  switch (status) {
    case 'PENDING':
      return <Tag icon={<LoadingOutlined />} color="default">等待中</Tag>;
    case 'STARTED':
      return <Tag icon={<LoadingOutlined />} color="processing">开始执行</Tag>;
    case 'PROGRESS':
      return <Tag icon={<LoadingOutlined />} color="processing">进行中</Tag>;
    case 'SUCCESS':
      return <Tag icon={<CheckCircleOutlined />} color="success">完成</Tag>;
    case 'FAILURE':
      return <Tag icon={<CloseCircleOutlined />} color="error">失败</Tag>;
    default:
      return <Tag color="default">{status}</Tag>;
  }
};

/**
 * 获取状态对应的进度条状态
 */
const getProgressStatus = (status) => {
  switch (status) {
    case 'SUCCESS':
      return 'success';
    case 'FAILURE':
      return 'exception';
    case 'PENDING':
    case 'STARTED':
      return 'normal';
    default:
      return 'active';
  }
};

/**
 * 删除进度弹窗
 */
const DeleteProgressModal = observer(function () {
  const { deleteProgressVisible, deleteTasks } = store;
  
  // 转换为数组并计算总体进度
  const taskList = Array.from(deleteTasks.entries()).map(([taskId, task]) => ({
    taskId,
    ...task,
  }));
  
  const totalProgress = taskList.length > 0
    ? Math.round(taskList.reduce((sum, t) => sum + (t.progress || 0), 0) / taskList.length)
    : 0;
  
  const completedCount = taskList.filter(t => t.status === 'SUCCESS' || t.status === 'FAILURE').length;
  const isAllCompleted = taskList.length > 0 && completedCount === taskList.length;

  return (
    <Modal
      title="删除进度"
      visible={deleteProgressVisible}
      footer={null}
      closable={isAllCompleted} // 只有全部完成才能关闭
      maskClosable={isAllCompleted}
      onCancel={() => isAllCompleted && store.hideDeleteProgress()}
      width={500}
    >
      {/* 总体进度 */}
      <div className={styles.totalProgress}>
        <div className={styles.progressHeader}>
          <span className={styles.progressTitle}>总体进度</span>
          <span className={styles.progressCount}>
            {completedCount} / {taskList.length} 完成
          </span>
        </div>
        <Progress 
          percent={totalProgress} 
          status={isAllCompleted ? 'success' : 'active'}
          strokeColor={isAllCompleted ? '#52c41a' : '#1890ff'}
        />
      </div>

      {/* 任务列表 */}
      <List
        className={styles.taskList}
        dataSource={taskList}
        renderItem={({ taskId, fileName, progress, status, message, type }) => (
          <List.Item className={styles.taskItem}>
            <div className={styles.taskContent}>
              {/* 任务头部 */}
              <div className={styles.taskHeader}>
                <Space>
                  {type === 'folder' ? (
                    <FolderOutlined className={styles.folderIcon} />
                  ) : (
                    <FileOutlined className={styles.fileIcon} />
                  )}
                  <span className={styles.taskName} title={fileName}>
                    {fileName}
                  </span>
                </Space>
                {getStatusTag(status)}
              </div>
              
              {/* 进度条 */}
              <Progress 
                percent={progress || 0}
                size="small"
                status={getProgressStatus(status)}
                className={styles.taskProgress}
              />
              
              {/* 状态消息 */}
              {message && (
                <div className={styles.taskMessage} title={message}>
                  {message}
                </div>
              )}
            </div>
          </List.Item>
        )}
      />

      {/* 底部提示 */}
      {!isAllCompleted && (
        <div className={styles.progressHint}>
          正在删除中，请稍候...
        </div>
      )}
    </Modal>
  );
});

export default DeleteProgressModal;
