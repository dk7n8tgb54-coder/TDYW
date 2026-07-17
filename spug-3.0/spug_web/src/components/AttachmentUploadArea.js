/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 公共附件上传区 AttachmentUploadArea
 *
 * 职责：
 * - 提供按钮（button）和拖拽（dragger）两种交互模式；
 * - 单页面 FIFO 串行队列，任意时刻最多执行 1 个 request；
 * - 入队前校验：文件数量、单文件大小、扩展名（不区分大小写）；
 * - 维护本地临时状态列表（等待 / 上传中 / 失败），成功后立即移除；
 * - 失败项支持单独重试和移除，一个失败不阻断后续；
 * - 批次结束后调用一次 onBatchSettled；
 * - 组件卸载后不再 setState。
 *
 * 多账号并发说明：
 *   同一页面同一组件实例严格串行；不同账号在各自浏览器中上传时，
 *   由后端（Gunicorn / 数据库 / 存储层）自然处理跨账号并发。
 */
import React, { useState, useRef, useCallback, useEffect } from 'react';
import { Upload, Button, Tag, List, Typography, message } from 'antd';
import {
  UploadOutlined,
  InboxOutlined,
  LoadingOutlined,
  CloseCircleOutlined,
  RedoOutlined,
  DeleteOutlined,
  PaperClipOutlined,
} from '@ant-design/icons';

const { Dragger } = Upload;
const { Text } = Typography;

const TASK_STATUS = {
  QUEUED: 'queued',
  UPLOADING: 'uploading',
  SUCCESS: 'success',
  ERROR: 'error',
};

let _seq = 0;
function genTaskId() {
  _seq += 1;
  return `att_upload_${Date.now()}_${_seq}`;
}

function getFileExt(name) {
  if (!name) return '';
  const i = name.lastIndexOf('.');
  if (i < 0) return '';
  return name.substring(i).toLowerCase();
}

/**
 * 解析 accept 字符串为扩展名集合（小写带点）。
 * 仅提取 .xxx 形式，忽略 MIME（浏览器 MIME 不可靠，不作唯一依据）。
 * 返回 null 表示不做扩展名校验。
 */
function parseAcceptExts(accept) {
  if (!accept) return null;
  const exts = new Set();
  accept
    .split(',')
    .map(s => s.trim().toLowerCase())
    .filter(Boolean)
    .forEach(token => {
      if (token.startsWith('.')) exts.add(token);
    });
  return exts;
}

function formatSize(bytes) {
  if (!bytes || bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return (bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
}

function toErrorMessage(err) {
  if (!err) return '上传失败';
  if (typeof err === 'string') return err;
  if (err.message) return err.message;
  return '上传失败';
}

function buildDefaultHint(accept, maxFileSizeMB) {
  const parts = [];
  if (accept) {
    const exts = parseAcceptExts(accept);
    if (exts && exts.size > 0) {
      parts.push('支持 ' + Array.from(exts).join('/'));
    }
  }
  if (maxFileSizeMB) {
    parts.push(`单文件最大 ${maxFileSizeMB}MB`);
  }
  return parts.join('，');
}

/**
 * 串行上传队列 hook
 * 维护 FIFO 任务队列、批次统计与卸载保护，任意时刻最多执行 1 个 request。
 */
function useSerialUploadQueue(options) {
  const {
    accept, maxFileSizeMB, maxFilesPerBatch, disabled,
    request, onFileSuccess, onFileError, onBatchSettled,
  } = options;

  const [tasks, setTasks] = useState([]);
  const mountedRef = useRef(true);
  const runningRef = useRef(false);
  const tasksRef = useRef([]);
  const activeCountRef = useRef(0);
  const batchStatsRef = useRef(null);
  const requestRef = useRef(request);
  const onFileSuccessRef = useRef(onFileSuccess);
  const onFileErrorRef = useRef(onFileError);
  const onBatchSettledRef = useRef(onBatchSettled);

  useEffect(() => {
    requestRef.current = request;
    onFileSuccessRef.current = onFileSuccess;
    onFileErrorRef.current = onFileError;
    onBatchSettledRef.current = onBatchSettled;
  });
  useEffect(() => { tasksRef.current = tasks; }, [tasks]);
  useEffect(() => () => { mountedRef.current = false; }, []);

  const validateFile = useCallback((file) => {
    if (!file) return '文件无效';
    if (file.size === 0) return '文件为空，无法上传';
    if (maxFileSizeMB && file.size > maxFileSizeMB * 1024 * 1024) {
      return `文件大小不能超过 ${maxFileSizeMB}MB`;
    }
    const exts = parseAcceptExts(accept);
    if (exts && exts.size > 0) {
      const ext = getFileExt(file.name);
      if (!ext || !exts.has(ext)) {
        return `不支持的文件类型: ${ext || '无扩展名'}`;
      }
    }
    return null;
  }, [accept, maxFileSizeMB]);

  const ensureBatch = useCallback(() => {
    if (!batchStatsRef.current) {
      batchStatsRef.current = { total: 0, successCount: 0, failedCount: 0, results: [], errors: [] };
    }
  }, []);

  const enqueueFile = useCallback((file) => {
    ensureBatch();
    batchStatsRef.current.total += 1;
    activeCountRef.current += 1;
    const task = { id: genTaskId(), file, status: TASK_STATUS.QUEUED, error: null, result: null };
    setTasks(prev => [...prev, task]);
  }, [ensureBatch]);

  // 串行调度：从 tasks 中取下一个 queued 任务执行
  const scheduleNext = useCallback(() => {
    if (!mountedRef.current || runningRef.current) return;
    const next = tasksRef.current.find(t => t.status === TASK_STATUS.QUEUED);
    if (!next) return;

    runningRef.current = true;
    setTasks(prev => prev.map(t => (
      t.id === next.id ? { ...t, status: TASK_STATUS.UPLOADING, error: null } : t
    )));

    const exec = async () => {
      try {
        const result = await requestRef.current(next.file, { task: next });
        if (!mountedRef.current) return;
        if (onFileSuccessRef.current) onFileSuccessRef.current(result, next.file);
        if (batchStatsRef.current) {
          batchStatsRef.current.successCount += 1;
          batchStatsRef.current.results.push(result);
        }
        // 成功后立即从临时列表移除（正式表由调用方更新）
        setTasks(prev => prev.filter(t => t.id !== next.id));
      } catch (err) {
        if (!mountedRef.current) return;
        const errMsg = toErrorMessage(err);
        if (onFileErrorRef.current) onFileErrorRef.current(err, next.file);
        if (batchStatsRef.current) {
          batchStatsRef.current.failedCount += 1;
          batchStatsRef.current.errors.push({ id: next.id, file_name: next.file.name, error: errMsg });
        }
        setTasks(prev => prev.map(t => (
          t.id === next.id ? { ...t, status: TASK_STATUS.ERROR, error: errMsg } : t
        )));
      } finally {
        runningRef.current = false;
        activeCountRef.current = Math.max(0, activeCountRef.current - 1);
        // 批次结束判定：活跃任务归零
        if (activeCountRef.current === 0 && batchStatsRef.current) {
          const summary = { ...batchStatsRef.current };
          batchStatsRef.current = null;
          if (onBatchSettledRef.current && mountedRef.current) {
            onBatchSettledRef.current(summary);
          }
        }
        if (mountedRef.current) scheduleNext();
      }
    };
    exec();
  }, []);

  // 监听 tasks 变化，触发调度
  useEffect(() => { scheduleNext(); }, [tasks, scheduleNext]);

  const retryTask = useCallback((id) => {
    if (!mountedRef.current) return;
    ensureBatch();
    batchStatsRef.current.total += 1;
    activeCountRef.current += 1;
    setTasks(prev => prev.map(t => (
      t.id === id ? { ...t, status: TASK_STATUS.QUEUED, error: null } : t
    )));
  }, [ensureBatch]);

  const removeTask = useCallback((id) => {
    if (!mountedRef.current) return;
    setTasks(prev => prev.filter(t => t.id !== id));
  }, []);

  // antd Upload beforeUpload：校验 + 入队，始终返回 false 阻止 antd 自动上传
  const handleBeforeUpload = useCallback((file, fileList) => {
    if (disabled) return false;
    if (fileList && fileList.length > maxFilesPerBatch) {
      if (file === fileList[0]) message.error(`一次最多上传 ${maxFilesPerBatch} 个文件`);
      return false;
    }
    const err = validateFile(file);
    if (err) {
      message.error(`${file.name}: ${err}`);
      return false;
    }
    enqueueFile(file);
    return false;
  }, [disabled, maxFilesPerBatch, validateFile, enqueueFile]);

  return { tasks, handleBeforeUpload, retryTask, removeTask };
}

function UploadTrigger({ mode, uploadProps, disabled, buttonText, hint }) {
  if (mode === 'dragger') {
    return (
      <Dragger {...uploadProps} style={{ padding: '12px 16px' }}>
        <p className="ant-upload-drag-icon" style={{ marginBottom: 8 }}>
          <InboxOutlined />
        </p>
        <p className="ant-upload-text" style={{ fontSize: 13, marginBottom: 4 }}>
          将附件拖到这里，或点击选择文件
        </p>
        {hint && (
          <p className="ant-upload-hint" style={{ fontSize: 12, color: '#999', marginBottom: 0 }}>
            {hint}
          </p>
        )}
      </Dragger>
    );
  }
  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
      <Upload {...uploadProps}>
        <Button icon={<UploadOutlined />} disabled={disabled}>
          {buttonText}
        </Button>
      </Upload>
      {hint && (
        <Text type="secondary" style={{ fontSize: 12 }}>{hint}</Text>
      )}
    </div>
  );
}

function TaskListItem({ task, onRetry, onRemove }) {
  const isUploading = task.status === TASK_STATUS.UPLOADING;
  const isQueued = task.status === TASK_STATUS.QUEUED;
  const isError = task.status === TASK_STATUS.ERROR;

  let icon;
  let statusText;
  let statusColor;
  if (isQueued) {
    icon = <PaperClipOutlined style={{ color: '#999' }} />;
    statusText = '等待上传';
    statusColor = 'default';
  } else if (isUploading) {
    icon = <LoadingOutlined style={{ color: '#1890ff' }} />;
    statusText = '上传中';
    statusColor = 'processing';
  } else if (isError) {
    icon = <CloseCircleOutlined style={{ color: '#ff4d4f' }} />;
    statusText = '上传失败';
    statusColor = 'error';
  } else {
    icon = <PaperClipOutlined />;
    statusText = '';
    statusColor = 'default';
  }

  return (
    <List.Item
      key={task.id}
      style={{ padding: '6px 0' }}
      actions={
        isError ? [
          <Button key="retry" type="link" size="small" icon={<RedoOutlined />} onClick={() => onRetry(task.id)}>
            重试
          </Button>,
          <Button key="remove" type="link" size="small" danger icon={<DeleteOutlined />} onClick={() => onRemove(task.id)}>
            移除
          </Button>,
        ] : undefined
      }
    >
      <List.Item.Meta
        avatar={icon}
        title={
          <span style={{ fontSize: 13 }}>
            <span style={{ marginRight: 8 }}>{task.file.name}</span>
            <Tag color={statusColor} style={{ marginLeft: 4 }}>{statusText}</Tag>
            {isError && task.error && (
              <Text type="danger" style={{ fontSize: 12, marginLeft: 8 }}>{task.error}</Text>
            )}
          </span>
        }
        description={<span style={{ fontSize: 11, color: '#999' }}>{formatSize(task.file.size)}</span>}
      />
    </List.Item>
  );
}

export default function AttachmentUploadArea(props) {
  const {
    mode = 'button', multiple = false, accept, maxFileSizeMB,
    maxFilesPerBatch = 20, disabled = false, request,
    onFileSuccess, onFileError, onBatchSettled,
    buttonText = '上传附件', hint,
  } = props;

  const { tasks, handleBeforeUpload, retryTask, removeTask } = useSerialUploadQueue({
    accept, maxFileSizeMB, maxFilesPerBatch, disabled,
    request, onFileSuccess, onFileError, onBatchSettled,
  });

  const uploadProps = {
    accept, multiple, disabled, showUploadList: false, beforeUpload: handleBeforeUpload,
  };
  const effectiveHint = hint !== undefined ? hint : buildDefaultHint(accept, maxFileSizeMB);
  const visibleTasks = tasks.filter(t => t.status !== TASK_STATUS.SUCCESS);

  return (
    <div className="attachment-upload-area">
      <UploadTrigger
        mode={mode}
        uploadProps={uploadProps}
        disabled={disabled}
        buttonText={buttonText}
        hint={effectiveHint}
      />
      {visibleTasks.length > 0 && (
        <div style={{ marginTop: mode === 'dragger' ? 8 : 0, marginBottom: 8 }}>
          <List
            size="small"
            split={false}
            dataSource={visibleTasks}
            renderItem={task => (
              <TaskListItem task={task} onRetry={retryTask} onRemove={removeTask} />
            )}
            locale={{ emptyText: null }}
          />
        </div>
      )}
    </div>
  );
}
