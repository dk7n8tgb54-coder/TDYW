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
 *     module="upgrade"          // 业务模块标识
 *     objectType="record"       // 业务对象类型
 *     recordId={store.record.id} // 业务对象 ID（未创建时传空，组件自动隐藏）
 *     listUrl={`/api/upgrade/records/${id}/attachments/`}
 *     uploadUrl={`/api/upgrade/records/${id}/attachments/`}
 *     deleteUrl={`/api/upgrade/attachments/`}
 *     downloadUrlPrefix={`/api/upgrade/attachments/`}  // 下载会拼 `${prefix}${id}/download/?x-token=...`
 *     previewUrlPrefix={`/api/upgrade/attachments/`}   // 预览会拼 `${prefix}${id}/preview-url/`
 *     readOnly={viewMode}       // 只读模式隐藏上传/删除
 *     uploadPerm="upgrade.upgrade.edit"
 *     deletePerm="upgrade.upgrade.edit"
 *     previewPerm="upgrade.upgrade.view"
 *     maxFileSize={500}         // MB，前端预校验
 *     accept=".zip,.exe,..."
 *     onCountChange={setAttachmentCount}
 *   />
 *
 * 设计原则：
 * - 接口路径由调用方传入，组件不硬编码任何模块
 * - 权限码由调用方传入，复用项目 hasPermission 体系
 * - 下载走 x-token GET 参数鉴权（项目中间件支持）
 * - 预览走 kkFileView，通过 preview-url 接口获取地址
 * - 上传用 antd Upload customRequest，支持大文件长超时
 */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Upload, Button, Table, Tag, message, Popconfirm, Space, Modal } from 'antd';
import { UploadOutlined, DownloadOutlined, DeleteOutlined, PaperClipOutlined, EyeOutlined } from '@ant-design/icons';
import { http, hasPermission, X_TOKEN } from 'libs';

const DEFAULT_PREVIEWABLE_EXTENSIONS = [
  '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
  '.pdf', '.txt', '.md', '.csv',
  '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp',
];

const DEFAULT_ACCEPT = '.zip,.rar,.7z,.tar,.gz,.bz2,.exe,.msi,.deb,.rpm,.iso,.img,.sh,.py,.sql,.json,.yaml,.yml,.conf,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.md,.jpg,.jpeg,.png,.gif,.bmp,.webp';

function formatFileSize(bytes) {
  if (!bytes || bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return (bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
}

function isPreviewable(fileName, previewableExtensions) {
  if (!fileName) return false;
  const dotIdx = fileName.lastIndexOf('.');
  if (dotIdx < 0) return false;
  const ext = fileName.substring(dotIdx).toLowerCase();
  return previewableExtensions.includes(ext);
}

function getPreviewable(record, previewableExtensions) {
  return record.previewable !== undefined
    ? record.previewable
    : isPreviewable(record.file_name, previewableExtensions);
}

function AttachmentToolbar({ canUpload, accept, uploading, maxFileSize, onUpload }) {
  if (!canUpload) return null;

  return (
    <Space style={{ marginBottom: 12 }}>
      <Upload customRequest={onUpload} showUploadList={false} accept={accept}>
        <Button icon={<UploadOutlined />} loading={uploading}>
          上传附件
        </Button>
      </Upload>
      <Tag color="blue" style={{ marginLeft: 8 }}>
        单文件最大 {maxFileSize}MB
      </Tag>
    </Space>
  );
}

function AttachmentPreviewModal({ visible, fileName, previewUrl, onClose }) {
  return (
    <Modal
      title={`预览：${fileName}`}
      visible={visible}
      onCancel={onClose}
      footer={null}
      width="90%"
      style={{ top: 20 }}
      bodyStyle={{ height: '80vh' }}
      destroyOnClose
    >
      {previewUrl && (
        <iframe
          src={previewUrl}
          style={{ width: '100%', height: '100%', border: 'none' }}
          title="附件预览"
        />
      )}
    </Modal>
  );
}

function buildAttachmentColumns(options) {
  const {
    canDelete,
    canPreview,
    previewUrlPrefix,
    previewableExtensions,
    onDelete,
    onDownload,
    onPreview,
    onFileNameClick,
  } = options;

  return [
    {
      title: '文件名',
      dataIndex: 'file_name',
      key: 'file_name',
      render: (text, record) => (
        <Space>
          <PaperClipOutlined />
          <Button type="link" style={{ padding: 0 }} onClick={() => onFileNameClick(record)}>
            {text}
          </Button>
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
      width: 200,
      render: (_, record) => {
        const previewable = getPreviewable(record, previewableExtensions);
        return (
          <Space>
            {previewable && canPreview && previewUrlPrefix && (
              <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => onPreview(record)}>
                预览
              </Button>
            )}
            <Button type="link" size="small" icon={<DownloadOutlined />} onClick={() => onDownload(record)}>
              下载
            </Button>
            {canDelete && (
              <Popconfirm title="确定删除此附件？" onConfirm={() => onDelete(record)}>
                <Button type="link" size="small" danger icon={<DeleteOutlined />}>
                  删除
                </Button>
              </Popconfirm>
            )}
          </Space>
        );
      },
    },
  ];
}

export default function AttachmentManager(props) {
  const {
    module = '',
    recordId,
    listUrl,
    uploadUrl,
    deleteUrl,
    downloadUrlPrefix,
    previewUrlPrefix,
    readOnly = false,
    uploadPerm = '',
    deletePerm = '',
    previewPerm = '',
    maxFileSize = 500,
    accept = DEFAULT_ACCEPT,
    previewableExtensions = DEFAULT_PREVIEWABLE_EXTENSIONS,
    emptyText = '暂无附件',
    onCountChange,
  } = props;

  const [attachments, setAttachments] = useState([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [previewVisible, setPreviewVisible] = useState(false);
  const [previewUrl, setPreviewUrl] = useState('');
  const [previewFileName, setPreviewFileName] = useState('');

  const canUpload = !readOnly && (!uploadPerm || hasPermission(uploadPerm));
  const canDelete = !readOnly && (!deletePerm || hasPermission(deletePerm));
  const canPreview = !previewPerm || hasPermission(previewPerm);

  const updateAttachments = useCallback((updater) => {
    setAttachments(prev => {
      const next = typeof updater === 'function' ? updater(prev) : updater;
      if (onCountChange) onCountChange(next.length);
      return next;
    });
  }, [onCountChange]);

  const fetchAttachments = useCallback(() => {
    if (!recordId || !listUrl) {
      updateAttachments([]);
      return;
    }
    setLoading(true);
    http.get(listUrl)
      .then(data => updateAttachments(data || []))
      .catch(e => {
        console.error(`[AttachmentManager:${module}] 获取附件列表失败:`, e);
      })
      .finally(() => setLoading(false));
  }, [recordId, listUrl, module, updateAttachments]);

  useEffect(() => {
    fetchAttachments();
  }, [fetchAttachments]);

  const handleUpload = useCallback((options) => {
    const { file, onSuccess, onError } = options;
    if (file.size > maxFileSize * 1024 * 1024) {
      message.error(`文件大小不能超过 ${maxFileSize}MB`);
      return;
    }

    setUploading(true);
    const formData = new FormData();
    formData.append('file', file);

    http.post(uploadUrl, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 600000,
    })
      .then(data => {
        message.success('上传成功');
        updateAttachments(prev => [data, ...prev]);
        if (onSuccess) onSuccess(data, file);
      })
      .catch(e => {
        console.error(`[AttachmentManager:${module}] 上传附件失败:`, e);
        message.error(e?.message || '上传失败');
        if (onError) onError(e);
      })
      .finally(() => setUploading(false));
  }, [maxFileSize, module, uploadUrl, updateAttachments]);

  const handleDownload = useCallback((att) => {
    const url = `${downloadUrlPrefix}${att.id}/download/?x-token=${X_TOKEN}`;
    const link = document.createElement('a');
    link.href = url;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }, [downloadUrlPrefix]);

  const handlePreview = useCallback((att) => {
    if (!previewUrlPrefix) {
      message.warning('预览功能未配置');
      return;
    }
    http.get(`${previewUrlPrefix}${att.id}/preview-url/`)
      .then(data => {
        setPreviewUrl(data.preview_url);
        setPreviewFileName(data.file_name || att.file_name);
        setPreviewVisible(true);
      })
      .catch(e => {
        console.error(`[AttachmentManager:${module}] 获取预览地址失败:`, e);
        message.error(e?.message || '获取预览地址失败');
      });
  }, [module, previewUrlPrefix]);

  const handleDelete = useCallback((att) => {
    http.delete(`${deleteUrl}?id=${att.id}`)
      .then(() => {
        message.success('删除成功');
        updateAttachments(prev => prev.filter(item => item.id !== att.id));
      })
      .catch(e => {
        console.error(`[AttachmentManager:${module}] 删除附件失败:`, e);
        message.error(e?.message || '删除失败');
      });
  }, [deleteUrl, module, updateAttachments]);

  const handleFileNameClick = useCallback((att) => {
    const previewable = getPreviewable(att, previewableExtensions);
    if (previewable && canPreview && previewUrlPrefix) {
      handlePreview(att);
    } else {
      handleDownload(att);
    }
  }, [canPreview, handleDownload, handlePreview, previewUrlPrefix, previewableExtensions]);

  const columns = useMemo(() => buildAttachmentColumns({
    canDelete,
    canPreview,
    previewUrlPrefix,
    previewableExtensions,
    onDelete: handleDelete,
    onDownload: handleDownload,
    onPreview: handlePreview,
    onFileNameClick: handleFileNameClick,
  }), [
    canDelete,
    canPreview,
    previewUrlPrefix,
    previewableExtensions,
    handleDelete,
    handleDownload,
    handlePreview,
    handleFileNameClick,
  ]);

  const closePreview = useCallback(() => {
    setPreviewVisible(false);
    setPreviewUrl('');
  }, []);

  return (
    <div>
      <AttachmentToolbar
        canUpload={canUpload}
        accept={accept}
        uploading={uploading}
        maxFileSize={maxFileSize}
        onUpload={handleUpload}
      />
      <Table
        columns={columns}
        dataSource={attachments}
        rowKey="id"
        loading={loading}
        size="small"
        pagination={false}
        locale={{ emptyText }}
      />
      <AttachmentPreviewModal
        visible={previewVisible}
        fileName={previewFileName}
        previewUrl={previewUrl}
        onClose={closePreview}
      />
    </div>
  );
}
