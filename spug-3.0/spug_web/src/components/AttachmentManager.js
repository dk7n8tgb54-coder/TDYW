/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 通用附件管理组件 AttachmentManager
 *
 * 旧调用方完全向后兼容（未传新增 Props 时按钮式单文件上传、旧 URL 拼装规则不变）。
 *
 * 适配器优先级：请求适配器 > 旧 URL Props 默认实现。
 *   传了 deleteRequest 就不再读取 deleteUrl；未传则继续使用旧 DELETE ${deleteUrl}?id=${id}。
 *
 * 权限计算：
 *   canUpload   = !readOnly && (!uploadPerm   || hasPermission(uploadPerm))
 *   canDelete   = !readOnly && (!deletePerm   || hasPermission(deletePerm))
 *   canPreview  = !previewPerm  || hasPermission(previewPerm)
 *   canDownload = !downloadPerm || hasPermission(downloadPerm)
 *
 * 预览优先级：
 *   - 传入 previewRequest 时，所有可预览文件（含图片/PDF）都走 previewRequest，
 *     不再绕到下载接口；支持后端返回 preview_type: native | image | pdf | kkfileview。
 *   - 未传 previewRequest 时，保持旧逻辑：图片/PDF 走下载接口 inline 模式，
 *     其他类型走 previewUrlPrefix 的 preview-url。
 */
import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { Button, Table, Tag, message, Popconfirm, Space, Modal } from 'antd';
import {
  DownloadOutlined,
  DeleteOutlined,
  PaperClipOutlined,
  EyeOutlined,
} from '@ant-design/icons';
import { http, hasPermission, X_TOKEN } from 'libs';
import AttachmentUploadArea from './AttachmentUploadArea';

const DEFAULT_PREVIEWABLE_EXTENSIONS = [
  '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
  '.pdf', '.txt', '.md', '.csv',
  '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp',
];

// 浏览器原生可预览的文件类型（未传 previewRequest 时走下载接口 inline 模式）
const IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'];
const PDF_EXTENSIONS = ['.pdf'];

const DEFAULT_ACCEPT = '.zip,.rar,.7z,.tar,.gz,.bz2,.exe,.msi,.deb,.rpm,.iso,.img,.sh,.py,.sql,.json,.yaml,.yml,.conf,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.md,.jpg,.jpeg,.png,.gif,.bmp,.webp';

function formatFileSize(bytes) {
  if (!bytes || bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return (bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
}

function getFileExt(fileName) {
  if (!fileName) return '';
  const dotIdx = fileName.lastIndexOf('.');
  if (dotIdx < 0) return '';
  return fileName.substring(dotIdx).toLowerCase();
}

function isImageFile(fileName) {
  return IMAGE_EXTENSIONS.includes(getFileExt(fileName));
}

function isPdfFile(fileName) {
  return PDF_EXTENSIONS.includes(getFileExt(fileName));
}

function isPreviewable(fileName, previewableExtensions) {
  if (!fileName) return false;
  return previewableExtensions.includes(getFileExt(fileName));
}

function getPreviewable(record, previewableExtensions) {
  return record.previewable !== undefined
    ? record.previewable
    : isPreviewable(record.file_name, previewableExtensions);
}

function toErrorMessage(err) {
  if (!err) return '操作失败';
  if (typeof err === 'string') return err;
  if (err.message) return err.message;
  return '操作失败';
}

function AttachmentPreviewModal({ visible, fileName, previewUrl, previewType, onClose }) {
  // previewType: image | native | pdf | kkfileview | 其他
  const isImage = previewType === 'image';
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
      {previewUrl && isImage && (
        <div style={{ height: '100%', textAlign: 'center', overflow: 'auto' }}>
          <img src={previewUrl} alt={fileName} style={{ maxWidth: '100%', maxHeight: '80vh' }} />
        </div>
      )}
      {previewUrl && !isImage && (
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
    canDelete, canPreview, canDownload, hasPreviewCapability,
    previewableExtensions, onDelete, onDownload, onPreview,
    onFileNameClick, renderExtraActions, extraActionsContext,
  } = options;

  return [
    {
      title: '文件名',
      dataIndex: 'file_name',
      key: 'file_name',
      render: (text, record) => {
        const previewable = getPreviewable(record, previewableExtensions);
        // 可预览且可预览权限 → 点击预览；否则可下载 → 点击下载；都无 → 纯文本
        const clickPreview = previewable && canPreview && hasPreviewCapability;
        const clickDownload = !clickPreview && canDownload;
        const clickable = clickPreview || clickDownload;
        return (
          <Space>
            <PaperClipOutlined />
            {clickable ? (
              <Button type="link" style={{ padding: 0 }} onClick={() => onFileNameClick(record)}>
                {text}
              </Button>
            ) : (
              <span>{text}</span>
            )}
          </Space>
        );
      },
    },
    { title: '大小', dataIndex: 'file_size', key: 'file_size', width: 100, render: size => formatFileSize(size) },
    { title: '上传人', dataIndex: 'uploaded_by_name', key: 'uploaded_by_name', width: 100 },
    { title: '上传时间', dataIndex: 'created_at', key: 'created_at', width: 160 },
    {
      title: '操作',
      key: 'action',
      width: 200,
      render: (_, record) => {
        const previewable = getPreviewable(record, previewableExtensions);
        return (
          <Space>
            {previewable && canPreview && hasPreviewCapability && (
              <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => onPreview(record)}>
                预览
              </Button>
            )}
            {canDownload && (
              <Button type="link" size="small" icon={<DownloadOutlined />} onClick={() => onDownload(record)}>
                下载
              </Button>
            )}
            {canDelete && (
              <Popconfirm title="确定删除此附件？" onConfirm={() => onDelete(record)}>
                <Button type="link" size="small" danger icon={<DeleteOutlined />}>
                  删除
                </Button>
              </Popconfirm>
            )}
            {renderExtraActions && renderExtraActions(record, extraActionsContext)}
          </Space>
        );
      },
    },
  ];
}

/**
 * 附件列表状态与加载 hook
 */
function useAttachmentList({ module, recordId, listUrl, listRequest, normalizeAttachment, onCountChange }) {
  const [attachments, setAttachments] = useState([]);
  const [loading, setLoading] = useState(false);
  const attachmentsRef = useRef([]);

  useEffect(() => { attachmentsRef.current = attachments; }, [attachments]);

  const normalize = useCallback((raw) => {
    if (!normalizeAttachment) return raw;
    return normalizeAttachment(raw);
  }, [normalizeAttachment]);

  const updateAttachments = useCallback((updater) => {
    setAttachments(prev => {
      const next = typeof updater === 'function' ? updater(prev) : updater;
      if (onCountChange) onCountChange(next.length);
      return next;
    });
  }, [onCountChange]);

  const fetchAttachments = useCallback(() => {
    if (!recordId) { updateAttachments([]); return; }
    if (listRequest) {
      setLoading(true);
      listRequest()
        .then(data => updateAttachments((data || []).map(normalize)))
        .catch(e => console.error(`[AttachmentManager:${module}] 获取附件列表失败:`, e))
        .finally(() => setLoading(false));
      return;
    }
    if (!listUrl) { updateAttachments([]); return; }
    setLoading(true);
    http.get(listUrl)
      .then(data => updateAttachments((data || []).map(normalize)))
      .catch(e => console.error(`[AttachmentManager:${module}] 获取附件列表失败:`, e))
      .finally(() => setLoading(false));
  }, [recordId, listUrl, listRequest, module, updateAttachments, normalize]);

  useEffect(() => { fetchAttachments(); }, [fetchAttachments]);

  return { attachments, loading, normalize, updateAttachments };
}

/**
 * 附件预览 hook：适配器优先，未传适配器时保持旧 inline / kkFileView 逻辑
 */
function useAttachmentPreview({ module, previewRequest, previewUrlPrefix, downloadUrlPrefix }) {
  const [previewVisible, setPreviewVisible] = useState(false);
  const [previewUrl, setPreviewUrl] = useState('');
  const [previewFileName, setPreviewFileName] = useState('');
  const [previewType, setPreviewType] = useState('kkfileview');

  const handlePreview = useCallback((att) => {
    // 适配器优先：所有可预览文件都走 previewRequest，不绕下载接口
    if (previewRequest) {
      previewRequest(att)
        .then(data => {
          setPreviewUrl(data.preview_url || '');
          setPreviewFileName(data.file_name || att.file_name);
          setPreviewType(data.preview_type || 'kkfileview');
          setPreviewVisible(true);
        })
        .catch(() => { /* http.js 已弹错误 */ });
      return;
    }
    // 旧逻辑：图片/PDF 走下载接口 inline 模式
    if (isImageFile(att.file_name) || isPdfFile(att.file_name)) {
      if (!downloadUrlPrefix) { message.warning('下载地址未配置，无法预览'); return; }
      const inlineUrl = `${downloadUrlPrefix}${att.id}/download/?x-token=${X_TOKEN}&inline=1`;
      setPreviewUrl(inlineUrl);
      setPreviewFileName(att.file_name);
      setPreviewType(isImageFile(att.file_name) ? 'image' : 'pdf');
      setPreviewVisible(true);
      return;
    }
    // 其他类型走 kkFileView
    if (!previewUrlPrefix) { message.warning('预览功能未配置'); return; }
    http.get(`${previewUrlPrefix}${att.id}/preview-url/`)
      .then(data => {
        setPreviewUrl(data.preview_url);
        setPreviewFileName(data.file_name || att.file_name);
        setPreviewType('kkfileview');
        setPreviewVisible(true);
      })
      .catch(e => console.error(`[AttachmentManager:${module}] 获取预览地址失败:`, e));
  }, [previewRequest, previewUrlPrefix, downloadUrlPrefix, module]);

  const closePreview = useCallback(() => {
    // 仅释放组件自己创建的 Blob URL，外部/后端 token URL 不 revoke
    if (previewUrl && previewUrl.indexOf('blob:') === 0) {
      try { URL.revokeObjectURL(previewUrl); } catch (e) { /* ignore */ }
    }
    setPreviewVisible(false);
    setPreviewUrl('');
    setPreviewType('kkfileview');
  }, [previewUrl]);

  return { previewVisible, previewUrl, previewFileName, previewType, handlePreview, closePreview };
}

/**
 * 上传 / 下载 / 删除动作 hook
 */
function useAttachmentActions({
  module, multiple, uploadRequest, uploadUrl,
  downloadRequest, downloadUrlPrefix,
  deleteRequest, deleteUrl, normalize, updateAttachments,
}) {
  // 上传：AttachmentUploadArea 的 request 适配器
  const handleUploadRequest = useCallback((file) => {
    if (uploadRequest) return uploadRequest(file);
    const formData = new FormData();
    formData.append('file', file);
    return http.post(uploadUrl, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 600000,
    });
  }, [uploadRequest, uploadUrl]);

  const handleFileSuccess = useCallback((result, file) => {
    const normalized = normalize(result);
    updateAttachments(prev => [normalized, ...prev]);
    if (!multiple) message.success('上传成功');
  }, [normalize, updateAttachments, multiple]);

  const handleFileError = useCallback((err, file) => {
    if (!multiple) message.error(toErrorMessage(err));
  }, [multiple]);

  const handleBatchSettled = useCallback((summary) => {
    if (!multiple) return; // 单文件模式已由 onFileSuccess/onFileError 弹单条
    if (!summary) return;
    const { successCount, failedCount } = summary;
    if (failedCount === 0) {
      message.success(`${successCount} 个附件上传成功`);
    } else if (successCount === 0) {
      message.error(`${failedCount} 个附件上传失败`);
    } else {
      message.warning(`${successCount} 个附件上传成功，${failedCount} 个失败`);
    }
  }, [multiple]);

  // 下载
  const handleDownload = useCallback((att) => {
    if (downloadRequest) {
      // 适配器自行处理下载（创建 a 标签、revoke），组件不重复弹错误
      downloadRequest(att).catch(() => { /* http.js 已弹错误 */ });
      return;
    }
    if (!downloadUrlPrefix) { message.warning('下载地址未配置'); return; }
    const url = `${downloadUrlPrefix}${att.id}/download/?x-token=${X_TOKEN}`;
    const link = document.createElement('a');
    link.href = url;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }, [downloadRequest, downloadUrlPrefix]);

  // 删除
  const handleDelete = useCallback((att) => {
    const doDelete = deleteRequest
      ? () => deleteRequest(att)
      : () => http.delete(`${deleteUrl}?id=${att.id}`);
    doDelete()
      .then(() => {
        message.success('删除成功');
        updateAttachments(prev => prev.filter(item => item.id !== att.id));
      })
      .catch(e => {
        console.error(`[AttachmentManager:${module}] 删除附件失败:`, e);
        // http.js 已弹错误，避免重复
      });
  }, [deleteRequest, deleteUrl, module, updateAttachments]);

  return {
    handleUploadRequest, handleFileSuccess, handleFileError, handleBatchSettled,
    handleDownload, handleDelete,
  };
}

export default function AttachmentManager(props) {
  const {
    module = '', recordId, listUrl, uploadUrl, deleteUrl,
    downloadUrlPrefix, previewUrlPrefix, readOnly = false,
    uploadPerm = '', deletePerm = '', previewPerm = '', downloadPerm = '',
    maxFileSize = 500, accept = DEFAULT_ACCEPT,
    previewableExtensions = DEFAULT_PREVIEWABLE_EXTENSIONS,
    emptyText = '暂无附件', onCountChange,
    uploadMode = 'button', multiple = false, maxFilesPerBatch = 20, uploadHint,
    listRequest, uploadRequest, deleteRequest, downloadRequest, previewRequest,
    normalizeAttachment, renderExtraActions, hiddenColumns,
  } = props;

  const canUpload = !readOnly && (!uploadPerm || hasPermission(uploadPerm));
  const canDelete = !readOnly && (!deletePerm || hasPermission(deletePerm));
  const canPreview = !previewPerm || hasPermission(previewPerm);
  const canDownload = !downloadPerm || hasPermission(downloadPerm);
  // 预览能力：传入 previewRequest 即具备；否则需要旧 URL prefix
  const hasPreviewCapability = !!(previewRequest || previewUrlPrefix || downloadUrlPrefix);

  const { attachments, loading, normalize, updateAttachments } = useAttachmentList({
    module, recordId, listUrl, listRequest, normalizeAttachment, onCountChange,
  });

  const {
    previewVisible, previewUrl, previewFileName, previewType, handlePreview, closePreview,
  } = useAttachmentPreview({ module, previewRequest, previewUrlPrefix, downloadUrlPrefix });

  const {
    handleUploadRequest, handleFileSuccess, handleFileError, handleBatchSettled,
    handleDownload, handleDelete,
  } = useAttachmentActions({
    module, multiple, uploadRequest, uploadUrl,
    downloadRequest, downloadUrlPrefix,
    deleteRequest, deleteUrl, normalize, updateAttachments,
  });

  // 文件名点击：可预览+canPreview→预览；否则 canDownload→下载；都无→纯文本
  const handleFileNameClick = useCallback((att) => {
    const previewable = getPreviewable(att, previewableExtensions);
    if (previewable && canPreview && hasPreviewCapability) {
      handlePreview(att);
      return;
    }
    if (canDownload) handleDownload(att);
  }, [previewableExtensions, canPreview, canDownload, hasPreviewCapability, handlePreview, handleDownload]);

  const columns = useMemo(() => {
    const all = buildAttachmentColumns({
      canDelete, canPreview, canDownload, hasPreviewCapability, previewableExtensions,
      onDelete: handleDelete, onDownload: handleDownload, onPreview: handlePreview,
      onFileNameClick: handleFileNameClick, renderExtraActions,
      extraActionsContext: { attachments },
    });
    if (!hiddenColumns || hiddenColumns.length === 0) return all;
    return all.filter(col => !(col.dataIndex && hiddenColumns.includes(col.dataIndex)));
  }, [
    canDelete, canPreview, canDownload, hasPreviewCapability, previewableExtensions,
    handleDelete, handleDownload, handlePreview, handleFileNameClick,
    renderExtraActions, attachments, hiddenColumns,
  ]);

  // 上传区 hint：button 模式由外层 Tag 提示（保持旧视觉），dragger 模式由 AttachmentUploadArea 生成
  const uploadAreaHint = uploadMode === 'dragger'
    ? (uploadHint !== undefined ? uploadHint : undefined)
    : null;

  return (
    <div>
      {canUpload && (
        <div style={{ marginBottom: uploadMode === 'dragger' ? 12 : 0 }}>
          <AttachmentUploadArea
            mode={uploadMode}
            multiple={multiple}
            accept={accept}
            maxFileSizeMB={maxFileSize}
            maxFilesPerBatch={maxFilesPerBatch}
            disabled={false}
            request={handleUploadRequest}
            onFileSuccess={handleFileSuccess}
            onFileError={handleFileError}
            onBatchSettled={handleBatchSettled}
            buttonText="上传附件"
            hint={uploadAreaHint}
          />
          {uploadMode === 'button' && (
            <Tag color="blue" style={{ marginLeft: 8 }}>
              单文件最大 {maxFileSize}MB
            </Tag>
          )}
        </div>
      )}
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
        previewType={previewType}
        onClose={closePreview}
      />
    </div>
  );
}
