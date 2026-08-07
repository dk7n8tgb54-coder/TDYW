/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 * 
 * 传输列表项组件 - 网盘风格
 * 仿阿里云盘、百度网盘设计
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Progress, Button, Tooltip } from 'antd';
import {
  PauseOutlined,
  CaretRightOutlined,
  CloseOutlined,
  DeleteOutlined,
  RedoOutlined,
  LoadingOutlined,
  CheckCircleFilled,
  CloseCircleFilled,
  PauseCircleFilled,
  ClockCircleFilled,
} from '@ant-design/icons';
import FileTypeIcon from './FileTypeIcon';
import { formatSpeed } from '@/utils/format';
import {
  ERROR_CODES,
  RETRYABLE_ERROR_CODES,
  NON_RETRYABLE_ERROR_CODES,
  ERROR_CODE_MESSAGES,
  PAUSEABLE_STATUSES,
  TERMINAL_STATUSES,
  UPLOAD_STATUS,
} from '../stores/upload/core/upload-core-constants';

// 状态配置 - 网盘风格
const STATUS_CONFIG = {
  waiting: {
    text: '等待中',
    color: '#8c8c8c',
    strokeColor: '#8c8c8c',
    showProgress: true,
    showSpeed: false,
    icon: <ClockCircleFilled />,
  },
  calculating: {
    text: '准备上传',
    color: '#fa8c16',
    strokeColor: '#fa8c16',
    showProgress: true,
    showSpeed: false,
    icon: <LoadingOutlined spin />,
  },
  uploading: {
    text: '上传中',
    color: '#1890ff',
    strokeColor: '#1890ff',
    showProgress: true,
    showSpeed: true,
    icon: <LoadingOutlined spin />,
  },
  paused: {
    text: '已暂停',
    color: '#faad14',
    strokeColor: '#faad14',
    showProgress: true,
    showSpeed: false,
    icon: <PauseCircleFilled />,
  },
  completed: {
    text: '已完成',
    color: '#52c41a',
    strokeColor: '#52c41a',
    showProgress: true,
    showSpeed: false,
    icon: <CheckCircleFilled />,
  },
  error: {
    text: '上传失败',
    color: '#ff4d4f',
    strokeColor: '#ff4d4f',
    showProgress: true,
    showSpeed: false,
    icon: <CloseCircleFilled />,
  },
  merging: {
    text: '合并中',
    color: '#722ed1',
    strokeColor: '#722ed1',
    showProgress: true,
    showSpeed: false,
    icon: <LoadingOutlined spin />,
  },
  cancelled: {
    text: '已取消',
    color: '#8c8c8c',
    strokeColor: '#8c8c8c',
    showProgress: false,
    showSpeed: false,
    icon: <CloseCircleFilled />,
  },
};

/**
 * 传输列表项组件 - 网盘风格
 * @param {Object} props
 * @param {Object} props.item - 传输项数据
 * @param {number} props.speed - 上传速度（字节/秒）
 * @param {Function} props.onPause - 暂停回调
 * @param {Function} props.onResume - 继续/重试回调
 * @param {Function} props.onCancel - 取消回调
 * @param {Function} props.onRemove - 删除回调
 */
const TransferItem = ({
  item,
  speed = 0,
  onPause,
  onResume,
  onCancel,
  onRemove,
}) => {
  const status = item.status;
  const config = STATUS_CONFIG[status];
  
  // 计算进度显示（仅用于进度条；百分比文字已在重构中移除避免冗余）
  const percent = Math.round(item.percent || 0);

  // 使用传入的速度或 item 中的速度
  const displaySpeed = speed || item.speed || 0;
  
  // 判断显示哪些操作按钮
  // 【P0修复 2026-06-27】使用语义化常量替代硬编码数组
  const canPause = PAUSEABLE_STATUSES.includes(status);
  const canResume = ['paused', 'error', 'waiting'].includes(status);
  // 可取消 = 可暂停 + paused + merging（合并中允许取消但不允许暂停）
  const canCancel = [...PAUSEABLE_STATUSES, UPLOAD_STATUS.PAUSED, UPLOAD_STATUS.MERGING].includes(status);
  const canRemove = TERMINAL_STATUSES.includes(status);
  // 【重构 2026-06-06】根据 errorCode 决定是否可重试，而非单纯 status === 'error'
  // 缺省（无 errorCode）→ 默认可重试（向后兼容老错误）
  const errorCode = item.errorCode;
  const canRetry = status === 'error' && (
    !errorCode ||                                  // 老错误无 code，默认可重试
    RETRYABLE_ERROR_CODES.has(errorCode)           // 新错误按 code 分类
  );
  // 不可重试的错误：权限/配额/客户端错，不显示重试按钮
  const isNonRetryable = status === 'error' && errorCode && NON_RETRYABLE_ERROR_CODES.has(errorCode);
  // 用户友好错误文案：有 errorCode 时优先用 ERROR_CODE_MESSAGES，否则用 item.error
  const displayError = errorCode && ERROR_CODE_MESSAGES[errorCode]
    ? ERROR_CODE_MESSAGES[errorCode]
    : item.error;
  
  return (
    <div
      // 【2026-06-11 修复】改用 minHeight 而非 height
      // 原因：错误态需要展示错误文案 + 进度条，行高会撑高
      // 父组件 react-window ITEM_HEIGHT 80px 是普通态高度，错误态允许超出
      className="transfer-item"
      style={{
        minHeight: '72px',
        padding: '12px 16px',
        backgroundColor: status === 'error' ? '#fff2f0' : 'transparent',
        transition: 'background-color 0.3s',
        boxSizing: 'border-box',
        overflow: 'hidden',
      }}
    >
      {/* 第一行：图标 + 文件名 + 操作按钮 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        {/* 文件图标 */}
        <FileTypeIcon
          fileName={item.name || item.fileName || 'unknown'}
          mimeType={item.mimeType || item.fileType}
          isFolder={item.isFolder || false}
          size={40}
        />

        {/* 文件名和状态信息 */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontSize: 14,
              fontWeight: 500,
              color: status === 'error' ? '#ff4d4f' : '#262626',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              marginBottom: 4,
            }}
            title={item.name}
          >
            {item.name}
          </div>

          {/* 状态详情：状态文字 + 速度（一行，不换行） */}
          <div style={{ fontSize: 12, color: '#8c8c8c', display: 'flex', alignItems: 'center', gap: 8, overflow: 'hidden', whiteSpace: 'nowrap' }}>
            {/* 状态文字 - calculating 状态加 tooltip 解释（避免用户困惑） */}
            {status === 'calculating' ? (
              <Tooltip title="计算文件指纹以支持断点续传，大文件可能需要几秒">
                <span style={{ color: config.color, display: 'flex', alignItems: 'center', gap: 4, cursor: 'help' }}>
                  {config.icon}
                  {config.text}
                </span>
              </Tooltip>
            ) : (
              <span style={{ color: config.color, display: 'flex', alignItems: 'center', gap: 4 }}>
                {config.icon}
                {config.text}
              </span>
            )}

            {/* 上传速度 */}
            {config.showSpeed && displaySpeed > 0 && (
              <span style={{ color: '#1890ff' }}>{formatSpeed(displaySpeed)}</span>
            )}
          </div>
        </div>

        {/* 操作按钮组 */}
        <div style={{ display: 'flex', gap: 4 }}>
          {/* 暂停按钮 */}
          {canPause && (
            <Tooltip title="暂停">
              <Button
                type="text"
                size="small"
                icon={<PauseOutlined />}
                onClick={() => onPause(item.id)}
                style={{ color: '#595959' }}
              />
            </Tooltip>
          )}

          {/* 开始/重试按钮 */}
          {canResume && (
            <Tooltip title={status === 'error' ? '重试' : '开始'}>
              <Button
                type="text"
                size="small"
                icon={<CaretRightOutlined />}
                onClick={() => onResume(item.id)}
                style={{ color: status === 'error' ? '#ff4d4f' : '#52c41a' }}
              />
            </Tooltip>
          )}

          {/* 取消按钮 */}
          {canCancel && (
            <Tooltip title="取消">
              <Button
                type="text"
                size="small"
                danger
                icon={<CloseOutlined />}
                onClick={() => onCancel(item.id)}
              />
            </Tooltip>
          )}

          {/* 删除按钮 */}
          {canRemove && (
            <Tooltip title="删除">
              <Button
                type="text"
                size="small"
                danger
                icon={<DeleteOutlined />}
                onClick={() => onRemove(item.id)}
              />
            </Tooltip>
          )}
        </div>
      </div>

      {/* 第二行：进度条 */}
      {config.showProgress && (
        <div style={{ marginTop: 8, marginLeft: 52 }}>
          <Progress
            percent={percent}
            size={{ height: 4 }}
            strokeColor={config.strokeColor}
            trailColor="#f0f0f0"
            showInfo={false}
            status={status === 'error' ? 'exception' : undefined}
          />
        </div>
      )}

      {/* 错误提示 - B 步重构：扁平错误条，hover 显示重试按钮 */}
      {status === 'error' && displayError && (
        <div
          // 关键：单行结构，不抢进度条位置
          style={{
            marginTop: 6,
            marginLeft: 52,
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            fontSize: 12,
            color: '#ff4d4f',
            lineHeight: '20px',
            overflow: 'hidden',
          }}
        >
          <span style={{ flexShrink: 0 }} role="img" aria-label="警告">⚠️</span>
          <span
            style={{
              flex: 1,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
            title={displayError}
          >
            {displayError}
          </span>
          {canRetry && (
            <Button
              type="link"
              size="small"
              icon={<RedoOutlined />}
              onClick={() => onResume(item.id)}
              style={{ padding: 0, height: 'auto', fontSize: 12, flexShrink: 0 }}
            >
              重试
            </Button>
          )}
        </div>
      )}
    </div>
  );
};

// 【P1关键修复】自定义比较函数，仅在状态/进度/速度变化时更新
// 使用 observer + memo 组合，确保 MobX 响应式 + 避免不必要的重渲染
const ObservedTransferItem = observer(TransferItem);
export default React.memo(ObservedTransferItem, (prevProps, nextProps) => {
  // 比较关键属性
  const prevItem = prevProps.item;
  const nextItem = nextProps.item;

  return (
    prevItem.status === nextItem.status &&
    prevItem.percent === nextItem.percent &&
    prevProps.speed === nextProps.speed &&
    prevItem.error === nextItem.error &&
    prevItem.errorCode === nextItem.errorCode
  );
});
