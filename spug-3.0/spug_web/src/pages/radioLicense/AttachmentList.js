/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { observer } from 'mobx-react';
import { Upload, Button, Table, Tag, message, Popconfirm, Space, Select } from 'antd';
import { UploadOutlined, DownloadOutlined, DeleteOutlined, PaperClipOutlined } from '@ant-design/icons';
import { http, hasPermission, X_TOKEN } from 'libs';
import store from './store';

const ATTACHMENT_TYPE_MAP = {
  license: {color: 'blue', text: '执照'},
  permit: {color: 'green', text: '许可证'},
  approval: {color: 'orange', text: '许可批复'},
  other: {color: 'default', text: '其他'},
};

function formatFileSize(bytes) {
  if (!bytes || bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return (bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
}

export default observer(function AttachmentList({ licenseId }) {
  const [attachments, setAttachments] = useState([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [attachmentType, setAttachmentType] = useState('other');

  useEffect(() => {
    if (licenseId) {
      fetchAttachments();
    }
  }, [licenseId]);

  function fetchAttachments() {
    setLoading(true);
    http.get(`/api/radio-license/${licenseId}/attachments/`)
      .then(data => {
        setAttachments(data);
      })
      .catch(e => {
        console.error('[电台执照] 获取附件列表失败:', e);
      })
      .finally(() => setLoading(false));
  }

  function handleUpload(options) {
    const { file } = options;
    setUploading(true);
    const formData = new FormData();
    formData.append('file', file);
    formData.append('attachment_type', attachmentType);

    http.post(`/api/radio-license/${licenseId}/attachments/`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
      .then(data => {
        message.success('上传成功');
        setAttachments(prev => [data, ...prev]);
      })
      .catch(e => {
        console.error('[电台执照] 上传附件失败:', e);
        message.error(e?.message || '上传失败');
      })
      .finally(() => setUploading(false));
  }

  function handleDownload(att) {
    // 使用 x-token GET 参数鉴权下载（项目中间件支持）
    const url = `/api/radio-license/attachments/${att.id}/download/?x-token=${X_TOKEN}`;
    const link = document.createElement('a');
    link.href = url;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  function handleDelete(att) {
    http.delete(`/api/radio-license/attachments/?id=${att.id}`)
      .then(() => {
        message.success('删除成功');
        setAttachments(prev => prev.filter(a => a.id !== att.id));
      })
      .catch(e => {
        console.error('[电台执照] 删除附件失败:', e);
        message.error(e?.message || '删除失败');
      });
  }

  const columns = [
    {
      title: '文件名',
      dataIndex: 'file_name',
      key: 'file_name',
      render: (text, record) => (
        <Space>
          <PaperClipOutlined />
          <a onClick={() => handleDownload(record)}>{text}</a>
        </Space>
      ),
    },
    {
      title: '类型',
      dataIndex: 'attachment_type',
      key: 'attachment_type',
      width: 100,
      render: type => {
        const info = ATTACHMENT_TYPE_MAP[type] || ATTACHMENT_TYPE_MAP.other;
        return <Tag color={info.color}>{info.text}</Tag>;
      },
    },
    {
      title: '大小',
      dataIndex: 'file_size',
      key: 'file_size',
      width: 100,
      render: size => formatFileSize(size),
    },
    {
      title: '上传人',
      dataIndex: 'uploaded_by_name',
      key: 'uploaded_by_name',
      width: 100,
    },
    {
      title: '上传时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 150,
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_, record) => (
        <Space>
          {hasPermission('radio_license.attachment.download') && (
            <Button
              type="link"
              size="small"
              icon={<DownloadOutlined />}
              onClick={() => handleDownload(record)}
            >
              下载
            </Button>
          )}
          {hasPermission('radio_license.attachment.upload') && (
            <Popconfirm title="确定删除此附件？" onConfirm={() => handleDelete(record)}>
              <Button type="link" size="small" danger icon={<DeleteOutlined />}>
                删除
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div>
      {hasPermission('radio_license.attachment.upload') && (
        <Space style={{marginBottom: 12}}>
          <Select
            value={attachmentType}
            onChange={setAttachmentType}
            style={{width: 120}}
          >
            {Object.entries(ATTACHMENT_TYPE_MAP).map(([key, info]) => (
              <Select.Option key={key} value={key}>{info.text}</Select.Option>
            ))}
          </Select>
          <Upload
            customRequest={handleUpload}
            showUploadList={false}
            accept=".pdf,.jpg,.jpeg,.png,.gif,.bmp,.webp,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.zip,.rar,.7z"
          >
            <Button icon={<UploadOutlined />} loading={uploading}>
              上传附件
            </Button>
          </Upload>
        </Space>
      )}
      <Table
        columns={columns}
        dataSource={attachments}
        rowKey="id"
        loading={loading}
        size="small"
        pagination={false}
        locale={{emptyText: '暂无附件'}}
      />
    </div>
  );
})
