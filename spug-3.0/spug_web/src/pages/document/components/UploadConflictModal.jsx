/**
 * UploadConflictModal - 上传冲突处理对话框
 * 参照阿里云盘/百度网盘：同名文件冲突时弹窗让用户选择
 *   - 替换：删除旧文件后上传新文件
 *   - 保留两者：正常上传（后端自动给 logical_name 加后缀）
 *   - 跳过：不上传
 *
 * 触发条件：文件名相同但文件大小不同（同名+同大小则直接跳过不弹窗）
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Modal, Table, Radio, Button, Space, Typography } from 'antd';
import { uploadCoreStore } from '../stores';

const { Text } = Typography;

const formatSize = (bytes) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
};

const UploadConflictModal = observer(() => {
  const { conflictDialogVisible, pendingConflicts } = uploadCoreStore;

  const columns = [
    {
      title: '文件名',
      dataIndex: 'fileName',
      key: 'fileName',
      ellipsis: true,
      width: '35%',
    },
    {
      title: '原文件大小',
      dataIndex: 'existingSize',
      key: 'existingSize',
      width: '20%',
      render: (size) => <Text type="secondary">{formatSize(size)}</Text>,
    },
    {
      title: '新文件大小',
      dataIndex: 'fileSize',
      key: 'fileSize',
      width: '20%',
      render: (size) => <Text>{formatSize(size)}</Text>,
    },
    {
      title: '操作',
      dataIndex: 'action',
      key: 'action',
      width: '25%',
      render: (action, _, index) => (
        <Radio.Group
          value={action}
          onChange={(e) => uploadCoreStore.updateConflictAction(index, e.target.value)}
          size="small"
        >
          <Radio.Button value="replace">替换</Radio.Button>
          <Radio.Button value="keep">保留两者</Radio.Button>
          <Radio.Button value="skip">跳过</Radio.Button>
        </Radio.Group>
      ),
    },
  ];

  const handleConfirm = async () => {
    await uploadCoreStore.resolveConflicts();
  };

  const handleCancel = () => {
    uploadCoreStore.closeConflictDialog();
  };

  const setAll = (action) => {
    uploadCoreStore.setAllConflictActions(action);
  };

  return (
    <Modal
      title="上传冲突"
      visible={conflictDialogVisible}
      onCancel={handleCancel}
      width={720}
      zIndex={1100}
      maskClosable={false}
      destroyOnClose
      footer={[
        <Space key="batch" style={{ marginRight: 'auto' }}>
          <Button size="small" onClick={() => setAll('replace')}>全部替换</Button>
          <Button size="small" onClick={() => setAll('keep')}>全部保留</Button>
          <Button size="small" onClick={() => setAll('skip')}>全部跳过</Button>
        </Space>,
        <Button key="cancel" onClick={handleCancel}>取消</Button>,
        <Button key="confirm" type="primary" onClick={handleConfirm}>确定</Button>,
      ]}
    >
      <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
        以下文件与目标文件夹中的文件同名但大小不同，请选择处理方式：
      </Text>
      <Table
        dataSource={pendingConflicts.slice()}
        columns={columns}
        rowKey={(_, index) => index}
        pagination={false}
        size="small"
        scroll={{ y: 360 }}
      />
    </Modal>
  );
});

export default UploadConflictModal;
