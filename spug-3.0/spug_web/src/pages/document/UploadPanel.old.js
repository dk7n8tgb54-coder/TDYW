/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { List, Progress, Button, Space, Empty, Card, Tooltip, Tag, message } from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  LoadingOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  StopOutlined,
  DeleteOutlined
} from '@ant-design/icons';
import { uploadCoreStore } from './stores';
import navigationStore from './stores/navigation';

// ============================================================
// 纯函数：计算总进度统计（抽离到组件外部，避免重复计算）
// ============================================================
const calculateStats = (uploadQueue) => {
  const stats = {
    uploadingCount: 0,      // 正在上传
    pausedCount: 0,         // 已暂停
    completedCount: 0,        // 已完成
    errorCount: 0,          // 失败
    waitingCount: 0,         // 等待中（多文件并发）
    calculatingCount: 0       // 计算MD5中
  };
  for (let i = 0; i < uploadQueue.length; i++) {
    const status = uploadQueue[i].status;
    if (status === 'uploading') stats.uploadingCount++;
    else if (status === 'paused') stats.pausedCount++;
    else if (status === 'completed') stats.completedCount++;
    else if (status === 'error') stats.errorCount++;
    else if (status === 'waiting') stats.waitingCount++;
    else if (status === 'calculating') stats.calculatingCount++;
  }
  return stats;
};

// ============================================================
// 进度条组件：使用 React.memo 优化（支持所有状态）
// ============================================================
const UploadProgress = React.memo(({ percent, itemStatus }) => {
  if (itemStatus === 'uploading' || itemStatus === 'calculating') {
    return <Progress percent={percent} size="small" status="active" />;
  } else if (itemStatus === 'waiting') {
    // 等待状态：显示空进度条
    return <Progress percent={0} size="small" status="normal" strokeColor="#bfbfbf" />;
  } else if (itemStatus === 'paused') {
    return <Progress percent={percent} size="small" status="normal" strokeColor="#faad14" />;
  } else if (itemStatus === 'completed') {
    return <Progress percent={100} size="small" status="success" showInfo={false} />;
  } else if (itemStatus === 'error') {
    return <Progress percent={percent || 0} size="small" status="exception" showInfo={false} />;
  } else if (itemStatus === 'merging') {
    // 合并中状态：显示进度条
    return <Progress percent={percent} size="small" status="active" />;
  }
  return null;
});

// ============================================================
// 单个上传项组件：使用 observer + React.memo 优化
// ============================================================
const UploadItem = observer(({ item, onPause, onResume, onCancel, onRemove }) => {
  // 状态图标映射（避免在渲染时重复创建对象）
  // 添加 waiting 和 calculating 状态（多文件并发）
  const statusIcons = {
    waiting: <PauseCircleOutlined style={{ color: '#bfbfbf' }} />,  // 等待中（灰色）
    calculating: <LoadingOutlined style={{ color: '#faad14' }} />,  // 计算MD5中（橙色）
    uploading: <LoadingOutlined style={{ color: '#1890ff' }} />,
    paused: <PauseCircleOutlined style={{ color: '#faad14' }} />,
    completed: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
    error: <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
  };

  // 【P0修复】隐藏的文件选择输入框
  const fileInputRef = React.useRef(null);

  // 使用 useCallback 缓存事件处理函数（避免因函数重新创建导致子组件重渲染）
  const handlePauseClick = React.useCallback(() => onPause(item.id), [item.id, onPause]);
  const handleResumeClick = React.useCallback(() => onResume(item.id), [item.id, onResume]);
  const handleCancelClick = React.useCallback(() => onCancel(item.id), [item.id, onCancel]);
  const handleRemoveClick = React.useCallback(() => onRemove(item.id), [item.id, onRemove]);

  // 【断点续传优化】重新选择文件的处理 - 含文件名、大小、MD5三重校验
  const handleReplaceFile = React.useCallback(async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    // 【边界处理】验证文件名是否匹配
    if (file.name !== item.name) {
      message.error('文件名不匹配，请选择相同的文件');
      return;
    }
    
    // 【边界处理】验证文件大小是否匹配
    if (file.size !== item.fileSize) {
      message.error('文件大小不匹配，请选择相同的文件');
      return;
    }
    
    // 【边界处理】如果已有fileHash，计算新文件MD5进行校验
    if (item.fileHash) {
      message.loading('正在校验文件...', 0);
      try {
        // 使用 md5Store 计算文件MD5
        const newFileHash = await uploadCoreStore.md5Store?.calculateFileMD5(file);
        message.destroy();
        
        if (newFileHash !== item.fileHash) {
          message.error('文件内容已修改，请选择原文件');
          return;
        }
      } catch (error) {
        message.destroy();
        console.error('[UploadItem] MD5计算失败:', error);
        // MD5校验失败时，允许继续但给出警告
        message.warning('文件校验失败，将继续上传');
      }
    }
    
    // 校验通过，调用store方法替换文件并恢复上传
    await uploadCoreStore.replaceFileAndResume(item.id, file);
  }, [item.id, item.name, item.fileSize, item.fileHash]);

  const handleReuploadClick = React.useCallback(() => {
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  }, []);

  return (
    <List.Item
      style={{
        padding: '12px',
        borderBottom: '1px solid #f0f0f0'
      }}
    >
      {/* 【P0修复】隐藏的文件选择输入框 */}
      <input
        ref={fileInputRef}
        type="file"
        style={{ display: 'none' }}
        onChange={handleReplaceFile}
        accept="*/*"
      />
      <div style={{ width: '100%' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
          <span style={{ fontSize: 13, fontWeight: 500, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {item.name}
          </span>
          <Space size={4}>
            {statusIcons[item.status]}
            {/* 【P0修复】waiting 状态：显示开始和取消按钮 */}
            {item.status === 'waiting' && (
              <>
                {/* 【P0修复】有 file 对象才能直接开始，否则需要重新选择文件（即使有fileHash也需要，因为刷新后丢失了file对象） */}
                {item.file ? (
                  <Tooltip title="开始">
                    <Button
                      type="link"
                      size="small"
                      icon={<PlayCircleOutlined />}
                      onClick={handleResumeClick}
                      style={{ padding: 0, minWidth: 'auto', height: 'auto', lineHeight: 1, color: '#52c41a' }}
                    />
                  </Tooltip>
                ) : (
                  <Tooltip title={item.fileHash ? "重新选择文件以继续上传" : "需重新添加文件"}>
                    <Button
                      type="link"
                      size="small"
                      icon={<PlayCircleOutlined />}
                      onClick={handleReuploadClick}
                      disabled={!item.fileHash}
                      style={{
                        padding: 0,
                        minWidth: 'auto',
                        height: 'auto',
                        lineHeight: 1,
                        color: item.fileHash ? '#faad14' : '#52c41a',
                        opacity: item.fileHash ? 1 : 0.4
                      }}
                    />
                  </Tooltip>
                )}
                <Tooltip title="取消">
                  <Button
                    type="link"
                    size="small"
                    danger
                    icon={<StopOutlined />}
                    onClick={handleCancelClick}
                    style={{ padding: 0, minWidth: 'auto', height: 'auto', lineHeight: 1 }}
                  />
                </Tooltip>
              </>
            )}
            {/* calculating 状态：无操作按钮 */}
            {item.status === 'calculating' && (
              <Tooltip title="取消">
                <Button
                  type="link"
                  size="small"
                  danger
                  icon={<StopOutlined />}
                  onClick={handleCancelClick}
                  style={{ padding: 0, minWidth: 'auto', height: 'auto', lineHeight: 1 }}
                />
              </Tooltip>
            )}
            {item.status === 'uploading' && (
              <>
                <Tooltip title="暂停">
                  <Button
                    type="link"
                    size="small"
                    icon={<PauseCircleOutlined />}
                    onClick={handlePauseClick}
                    style={{ padding: 0, minWidth: 'auto', height: 'auto', lineHeight: 1 }}
                  />
                </Tooltip>
                <Tooltip title="取消">
                  <Button
                    type="link"
                    size="small"
                    danger
                    icon={<StopOutlined />}
                    onClick={handleCancelClick}
                    style={{ padding: 0, minWidth: 'auto', height: 'auto', lineHeight: 1 }}
                  />
                </Tooltip>
              </>
            )}
            {item.status === 'paused' && (
              <>
                {/* 【P0修复】有 file 对象才能直接开始，否则需要重新选择文件（即使有fileHash也需要，因为刷新后丢失了file对象） */}
                {item.file ? (
                  <Tooltip title="开始">
                    <Button
                      type="link"
                      size="small"
                      icon={<PlayCircleOutlined />}
                      onClick={handleResumeClick}
                      style={{ padding: 0, minWidth: 'auto', height: 'auto', lineHeight: 1, color: '#52c41a' }}
                    />
                  </Tooltip>
                ) : (
                  <Tooltip title="重新选择文件以继续上传">
                    <Button
                      type="link"
                      size="small"
                      icon={<PlayCircleOutlined />}
                      onClick={handleReuploadClick}
                      style={{ padding: 0, minWidth: 'auto', height: 'auto', lineHeight: 1, color: '#faad14' }}
                    />
                  </Tooltip>
                )}
                <Tooltip title="取消">
                  <Button
                    type="link"
                    size="small"
                    danger
                    icon={<StopOutlined />}
                    onClick={handleCancelClick}
                    style={{ padding: 0, minWidth: 'auto', height: 'auto', lineHeight: 1 }}
                  />
                </Tooltip>
              </>
            )}
            {item.status === 'error' && (
              <>
                {/* 【P0修复】有 file 对象才能直接重试，否则需要重新选择文件（即使有fileHash也需要，因为刷新后丢失了file对象） */}
                {item.file ? (
                  <Tooltip title="重试">
                    <Button
                      type="link"
                      size="small"
                      icon={<PlayCircleOutlined />}
                      onClick={handleResumeClick}
                      style={{
                        padding: 0,
                        minWidth: 'auto',
                        height: 'auto',
                        lineHeight: 1,
                        color: '#52c41a'
                      }}
                    />
                  </Tooltip>
                ) : (
                  <Tooltip title={item.fileHash ? "重新选择文件以继续上传" : "需重新添加文件"}>
                    <Button
                      type="link"
                      size="small"
                      icon={<PlayCircleOutlined />}
                      onClick={handleReuploadClick}
                      disabled={!item.fileHash}
                      style={{
                        padding: 0,
                        minWidth: 'auto',
                        height: 'auto',
                        lineHeight: 1,
                        color: item.fileHash ? '#faad14' : '#52c41a',
                        opacity: item.fileHash ? 1 : 0.4
                      }}
                    />
                  </Tooltip>
                )}
                <Tooltip title="删除">
                  <Button
                    type="link"
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={handleRemoveClick}
                    style={{ padding: 0, minWidth: 'auto', height: 'auto', lineHeight: 1 }}
                  />
                </Tooltip>
              </>
            )}
            {item.status === 'completed' && (
              <Tooltip title="删除">
                <Button
                  type="link"
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={handleRemoveClick}
                  style={{ padding: 0, minWidth: 'auto', height: 'auto', lineHeight: 1 }}
                />
              </Tooltip>
            )}
          </Space>
        </div>
        <UploadProgress percent={item.percent} itemStatus={item.status} />
        {(item.status === 'paused' || item.status === 'error') && (
          <div style={{ fontSize: 12, color: item.status === 'paused' ? '#faad14' : '#ff4d4f', marginTop: 4 }}>
            {item.error || (item.status === 'paused' ? '已暂停' : '上传失败')}
          </div>
        )}
      </div>
    </List.Item>
  );
});

// ============================================================
// 主上传面板组件
// ============================================================
class UploadPanel extends React.Component {
  // 使用 useCallback 缓存事件处理函数（避免因函数重新创建导致 UploadItem 重渲染）
  handlePauseItem = (itemId) => {
    uploadCoreStore.pauseItem(itemId);
  };

  // 缓存回调函数，避免每次渲染都创建新函数
  // 使用 useCallback 在组件级别缓存，确保引用稳定
  getCachedCallbacks = () => {
    if (!this._cachedCallbacks) {
      this._cachedCallbacks = {
        onPause: (itemId) => this.handlePauseItem(itemId),
        onResume: (itemId) => uploadCoreStore.resumeItem(itemId),
        onCancel: (itemId) => uploadCoreStore.cancelItem(itemId),
        onRemove: (itemId) => uploadCoreStore.removeItem(itemId)
      };
    }
    return this._cachedCallbacks;
  };

  handleResumeItem = async (itemId) => {
    await uploadCoreStore.resumeItem(itemId);
  };

  handleCancelItem = (itemId) => {
    uploadCoreStore.cancelItem(itemId);
  };

  handleRemoveItem = (itemId) => {
    uploadCoreStore.removeItem(itemId);
  };

  render() {
    const { currentUploadQueue, isPaused, pauseAll, resumeAll, cancelAll, removeAll, uploadRefreshTrigger, folderUploadProgress } = uploadCoreStore;

    // 访问 uploadRefreshTrigger 以确保 observer 追踪到变化（仅用于进度UI更新）
    void uploadRefreshTrigger;
    // 访问 folderUploadProgress 以确保 observer 追踪到变化（文件夹上传全局进度）
    void folderUploadProgress;

    // 获取当前空间信息（用于标题显示）
    const spaceType = navigationStore.isPublic ? '公共共享库' : '我的文件';
    const spaceColor = navigationStore.isPublic ? 'gold' : 'blue';

    // 使用纯函数计算统计信息（抽离到外部避免重复计算）
    const { uploadingCount, pausedCount, completedCount, errorCount, waitingCount, calculatingCount } = calculateStats(currentUploadQueue);

    // 计算文件夹上传进度百分比
    const folderProgressPercent = folderUploadProgress.total > 0
      ? Math.round((folderUploadProgress.current / folderUploadProgress.total) * 100)
      : 0;

    // 获取缓存的回调函数（避免每次渲染创建新函数）
    const callbacks = this.getCachedCallbacks();

    return (
      <Card
        size="small"
        style={{ width: 400, height: 500, display: 'flex', flexDirection: 'column' }}
        bodyStyle={{ padding: 0, flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}
        title={
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <Tag color={spaceColor} style={{ margin: 0 }}>
              {spaceType}
            </Tag>
            <span style={{ fontSize: 12, color: '#999' }}>
              共 {currentUploadQueue.length} 个任务
            </span>
          </div>
        }
      >
        {currentUploadQueue.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="暂无传输任务"
            style={{ padding: '40px 0' }}
          />
        ) : (
          <>
            {/* 【体验优化】文件夹上传全局进度条 */}
            {folderUploadProgress.total > 0 && (
              <div style={{ padding: '8px 12px', borderBottom: '1px solid #f0f0f0', flexShrink: 0 }}>
                <Space style={{ width: '100%' }}>
                  <span style={{ fontSize: 12, color: '#666' }}>
                    文件夹上传进度 ({folderUploadProgress.current}/{folderUploadProgress.total}个文件)
                  </span>
                </Space>
                <Progress
                  percent={folderProgressPercent}
                  size="small"
                  status="active"
                  strokeColor="#52c41a"
                  style={{ marginTop: 8 }}
                />
              </div>
            )}
            {/* 【布局优化】统计信息 - 固定顶部 */}
            <div style={{ padding: '8px 12px', borderBottom: '1px solid #f0f0f0', flexShrink: 0 }}>
              <Space>
                <span>传输中: {uploadingCount}</span>
                {waitingCount > 0 && <span>等待中: {waitingCount}</span>}
                {calculatingCount > 0 && <span>计算中: {calculatingCount}</span>}
                {pausedCount > 0 && <span>已暂停: {pausedCount}</span>}
                <span>已完成: {completedCount}</span>
                <span>失败: {errorCount}</span>
              </Space>
            </div>
            {/* 【布局优化】列表区域 - 可滚动 */}
            <div style={{ flex: 1, overflow: 'auto' }}>
              <List
                size="small"
                dataSource={currentUploadQueue}
                renderItem={(item) => (
                  <UploadItem
                    item={item}
                    onPause={callbacks.onPause}
                    onResume={callbacks.onResume}
                    onCancel={callbacks.onCancel}
                    onRemove={callbacks.onRemove}
                  />
                )}
                rowKey={(item) => item.id}
              />
            </div>
            {/* 【布局优化】控制按钮 - 固定底部 */}
            {currentUploadQueue.length > 0 && (
              <div style={{ padding: '12px', borderTop: '1px solid #f0f0f0', flexShrink: 0, backgroundColor: '#fafafa' }}>
                <Space style={{ width: '100%', justifyContent: 'center', flexWrap: 'wrap' }}>
                  {uploadingCount > 0 || pausedCount > 0 ? (
                    <>
                      <Tooltip title={isPaused ? '继续上传' : '暂停上传'}>
                        <Button
                          size="small"
                          icon={isPaused ? <PlayCircleOutlined /> : <PauseCircleOutlined />}
                          onClick={() => isPaused ? resumeAll() : pauseAll()}
                        >
                          {isPaused ? '全部开始' : '全部暂停'}
                        </Button>
                      </Tooltip>
                      {uploadingCount > 0 && (
                        <Tooltip title="取消所有正在上传的任务">
                          <Button
                            size="small"
                            danger
                            icon={<StopOutlined />}
                            onClick={() => cancelAll()}
                            disabled={uploadingCount === 0}
                          >
                            全部取消
                          </Button>
                        </Tooltip>
                      )}
                    </>
                  ) : null}
                  <Tooltip title="清空已完成、暂停和失败的任务">
                    <Button
                      size="small"
                      icon={<DeleteOutlined />}
                      onClick={() => removeAll()}
                      disabled={completedCount + pausedCount + errorCount === 0}
                    >
                      清空列表
                    </Button>
                  </Tooltip>
                </Space>
              </div>
            )}
          </>
        )}
      </Card>
    );
  }
}

export default observer(UploadPanel);
