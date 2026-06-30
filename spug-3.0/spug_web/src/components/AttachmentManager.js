/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 通用附件管理组件
 *
 * 用法：
 *   <AttachmentManager
 *     module="upgrade"          // 业务模块标识（用于日志/将来扩展）
 *     recordId={store.record.id} // 业务对象 ID（未创建时传空，组件自动隐藏）
 *     listUrl={`/api/upgrade/records/${id}/attachments/`}
 *     uploadUrl={`/api/upgrade/records/${id}/attachments/`}
 *     deleteUrl={`/api/upgrade/attachments/`}
 *     downloadUrlPrefix={`/api/upgrade/attachments/`}  // 下载会拼 `${prefix}${id}/download/?x-token=...`
 *     readOnly={viewMode}       // 只读模式隐藏上传/删除
 *     uploadPerm="upgrade.upgrade.add"
 *     deletePerm="upgrade.upgrade.add"
 *     maxFileSize={500}         // MB，前端预校验
 *     accept=".zip,.exe,..."
 *   />
 *
 * 设计原则（参考 radioLicense/AttachmentList.js 抽象）：
 * - 接口路径由调用方传入，组件不硬编码任何模块
 * - 权限码由调用方传入，复用项目 hasPermission 体系
 * - 下载走 x-token GET 参数鉴权（项目中间件支持）
 * - 上传用 antd Upload customRequest，支持大文件长超时
 */
import React, { useState, useEffect, useCallback } from 'react';
import { Upload, Button, Table, Tag, message, Popconfirm, Space } from 'antd';
import { UploadOutlined, DownloadOutlined, DeleteOutlined, PaperClipOutlined } from '@ant-design/icons';
import { http, hasPermission, X_TOKEN } from 'libs';

function formatFileSize(bytes) {
  if (!bytes || bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return (bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
}

export default function AttachmentManager(props) {
  const {
    module = '',
    recordId,
    listUrl,
    uploadUrl,
    deleteUrl,
    downloadUrlPrefix,
    readOnly = false,
    uploadPerm = '',
    deletePerm = '',
    maxFileSize = 500, // MB
    accept = '.zip,.rar,.7z,.tar,.gz,.bz2,.exe,.msi,.deb,.rpm,.iso,.img,.sh,.py,.sql,.json,.yaml,.yml,.conf,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.md,.jpg,.jpeg,.png,.gif,.bmp,.webp',
    emptyText = '暂无附件',
    onCountChange, // 可选：附件数量变化回调 (count) => void
  } = props;

  const [attachments, setAttachments] = useState([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);

  const canUpload = !readOnly && (!uploadPerm || hasPermission(uploadPerm));
  const canDelete = !readOnly && (!deletePerm || hasPermission(deletePerm));

  const fetchAttachments = useCallback(() => {
    if (!recordId || !listUrl) {
      setAttachments([]);
      return;
    }
    setLoading(true);
    http.get(listUrl)
      .then(data => {
        const list = data || [];
        setAttachments(list);
        if (onCountChange) onCountChange(list.length);
      })
      .catch(e => {
        console.error(`[AttachmentManager:${module}] 获取附件列表失败:`, e);
      })
      .finally(() => setLoading(false));
  }, [recordId, listUrl, module, onCountChange]);

  useEffect(() => {
    fetchAttachments();
  }, [fetchAttachments]);

  function handleUpload(options) {
    const { file } = options;

    // 前端预校验大小
    if (file.size > maxFileSize * 1024 * 1024) {
      message.error(`文件大小不能超过 ${maxFileSize}MB`);
      return;
    }

    setUploading(true);
    const formData = new FormData();
    formData.append('file', file);

    http.post(uploadUrl, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 600000, // 10 分钟，兜底大文件
    })
      .then(data => {
        message.success('上传成功');
        setAttachments(prev => {
          const next = [data, ...prev];
          if (onCountChange) onCountChange(next.length);
          return next;
        });
      })
      .catch(e => {
        console.error(`[AttachmentManager:${module}] 上传附件失败:`, e);
        message.error(e?.message || '上传失败');
      })
      .finally(() => setUploading(false));
  }

  function handleDownload(att) {
    const url = `${downloadUrlPrefix}${att.id}/download/?x-token=${X_TOKEN}`;
    const link = document.createElement('a');
    link.href = url;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  function handleDelete(att) {
    http.delete(`${deleteUrl}?id=${att.id}`)
      .then(() => {
        message.success('删除成功');
        setAttachments(prev => {
          const next = prev.filter(a => a.id !== att.id);
          if (onCountChange) onCountChange(next.length);
          return next;
        });
      })
      .catch(e => {
        console.error(`[AttachmentManager:${module}] 删除附件失败:`, e);
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
      width: 160,
    },
    {
      title: '操作',
      key: 'action',
      width: 140,
      render: (_, record) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<DownloadOutlined />}
            onClick={() => handleDownload(record)}
          >
            下载
          </Button>
          {canDelete && (
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
      {canUpload && (
        <Space style={{ marginBottom: 12 }}>
          <Upload
            customRequest={handleUpload}
            showUploadList={false}
            accept={accept}
          >
            <Button icon={<UploadOutlined />} loading={uploading}>
              上传附件
            </Button>
          </Upload>
          <Tag color="blue" style={{ marginLeft: 8 }}>
            单文件最大 {maxFileSize}MB
          </Tag>
        </Space>
      )}
      <Table
        columns={columns}
        dataSource={attachments}
        rowKey="id"
        loading={loading}
        size="small"
        pagination={false}
        locale={{ emptyText: emptyText }}
      />
    </div>
  );
}
