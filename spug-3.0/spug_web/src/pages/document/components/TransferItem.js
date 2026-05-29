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
import { Progress, Button, Tooltip, Spin } from 'antd';
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
  PlayCircleFilled,
} from '@ant-design/icons';
import FileTypeIcon from './FileTypeIcon';
import { formatSize, formatSpeed } from '@/utils/format';

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
    text: '计算中',
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

// 【2.3重构】formatSize 和 formatSpeed 已移至 @/utils/format

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
  
  // 计算进度显示
  const percent = Math.round(item.percent || 0);
  const uploadedSize = item.fileSize ? Math.round(item.fileSize * (percent / 100)) : 0;
  
  // 使用传入的速度或 item 中的速度
  const displaySpeed = speed || item.speed || 0;
  
  // 判断显示哪些操作按钮
  const canPause = ['waiting', 'calculating', 'uploading', 'merging'].includes(status);
  const canResume = ['paused', 'error', 'waiting'].includes(status);
  const canCancel = ['waiting', 'calculating', 'uploading', 'paused', 'merging'].includes(status);
  const canRemove = ['completed', 'error', 'cancelled'].includes(status);
  const canRetry = status === 'error';
  
  return (
    <div
      style={{
        // 【关键】固定高度，与 ITEM_HEIGHT (80px) 严格匹配
        height: '80px',
        padding: '12px 16px',
        borderBottom: '1px solid #f0f0f0',
        backgroundColor: status === 'error' ? '#fff2f0' : 'transparent',
        transition: 'background-color 0.3s',
        boxSizing: 'border-box',
        overflow: 'hidden', // 防止内容溢出撑高
      }}
    >
      {/* 第一行：图标 + 文件名 + 百分比 + 操作按钮 */}
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
          
          {/* 状态详情：已传输 / 总大小 • 状态文字 • 速度 */}
          <div style={{ fontSize: 12, color: '#8c8c8c', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            {/* 大小信息 */}
            {item.fileSize ? (
              <span>
                {formatSize(uploadedSize)} / {formatSize(item.fileSize)}
              </span>
            ) : null}
            
            {item.fileSize && <span>•</span>}
            
            {/* 状态文字 */}
            <span style={{ color: config.color, display: 'flex', alignItems: 'center', gap: 4 }}>
              {config.icon}
              {config.text}
            </span>
            
            {/* 上传速度 */}
            {config.showSpeed && displaySpeed > 0 && (
              <>
                <span>•</span>
                <span style={{ color: '#1890ff' }}>{formatSpeed(displaySpeed)}</span>
              </>
            )}
          </div>
        </div>
        
        {/* 百分比 */}
        {config.showProgress && (
          <div
            style={{
              fontSize: 14,
              fontWeight: 500,
              color: config.color,
              minWidth: 45,
              textAlign: 'right',
            }}
          >
            {percent}%
          </div>
        )}
        
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
                style={{ color: '#52c41a' }}
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
      
      {/* 错误提示 */}
      {status === 'error' && item.error && (
        <div
          style={{
            marginTop: 8,
            marginLeft: 52,
            padding: '6px 12px',
            backgroundColor: '#fff',
            borderRadius: 4,
            border: '1px solid #ffccc7',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}
        >
          <span style={{ fontSize: 12, color: '#ff4d4f', flex: 1 }}>
            ⚠️ {item.error}
          </span>
          {canRetry && (
            <Button
              type="link"
              size="small"
              icon={<RedoOutlined />}
              onClick={() => onResume(item.id)}
              style={{ padding: 0, height: 'auto', fontSize: 12 }}
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
    prevItem.error === nextItem.error
  );
});
