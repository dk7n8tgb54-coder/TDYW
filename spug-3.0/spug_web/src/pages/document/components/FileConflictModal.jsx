/**
 * FileConflictModal - 通用文件冲突处理对话框
 * 用于上传、复制、移动操作的冲突处理
 *   - 替换：删除目标文件后执行操作
 *   - 保留两者：生成唯一名称
 *   - 跳过：不执行任何操作
 */
import React, { useState, useEffect } from 'react';
import { Modal, Table, Radio, Button, Space, Typography } from 'antd';

const { Text } = Typography;

const formatSize = (bytes) => {
  if (!bytes) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
};

const FileConflictModal = ({
  visible,
  conflicts,
  onConfirm,
  onCancel,
  title = '文件冲突',
}) => {
  const [actions, setActions] = useState([]);

  useEffect(() => {
    if (conflicts && conflicts.length > 0) {
      setActions(conflicts.map(() => 'replace'));
    }
  }, [conflicts]);

  const columns = [
    {
      title: '文件名',
      dataIndex: 'new_name',
      key: 'new_name',
      ellipsis: true,
      width: '35%',
    },
    {
      title: '原文件大小',
      dataIndex: 'existing_size',
      key: 'existing_size',
      width: '20%',
      render: (size) => <Text type="secondary">{formatSize(size)}</Text>,
    },
    {
      title: '新文件大小',
      dataIndex: 'new_size',
      key: 'new_size',
      width: '20%',
      render: (size) => <Text>{formatSize(size)}</Text>,
    },
    {
      title: '操作',
      key: 'action',
      width: '25%',
      render: (_, __, index) => (
        <Radio.Group
          value={actions[index]}
          onChange={(e) => {
            const next = [...actions];
            next[index] = e.target.value;
            setActions(next);
          }}
          size="small"
        >
          <Radio.Button value="replace">替换</Radio.Button>
          <Radio.Button value="keep">保留两者</Radio.Button>
          <Radio.Button value="skip">跳过</Radio.Button>
        </Radio.Group>
      ),
    },
  ];

  const setAll = (action) => {
    setActions((conflicts || []).map(() => action));
  };

  const handleConfirm = () => {
    onConfirm(actions);
  };

  return (
    <Modal
      title={title}
      visible={visible}
      onCancel={onCancel}
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
        <Button key="cancel" onClick={onCancel}>取消</Button>,
        <Button key="confirm" type="primary" onClick={handleConfirm}>确定</Button>,
      ]}
    >
      <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
        以下文件与目标文件夹中的文件同名，请选择处理方式：
      </Text>
      <Table
        dataSource={conflicts || []}
        columns={columns}
        rowKey={(_, index) => index}
        pagination={false}
        size="small"
        scroll={{ y: 360 }}
      />
    </Modal>
  );
};

export default FileConflictModal;
