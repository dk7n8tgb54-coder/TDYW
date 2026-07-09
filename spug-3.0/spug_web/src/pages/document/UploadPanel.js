/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 *
 * 上传面板 - 抽屉模式（仿百度网盘）
 *
 * 形态：
 *   - 默认：底部小条 "正在传输 X 个任务"
 *   - 展开：底部抽屉，显示完整 Tabs 列表
 *   - 收起：拖到底部或点击关闭
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Drawer, Tag, message, Badge, Tooltip } from 'antd';
import {
  CloudUploadOutlined,
  CloudOutlined,
  UpOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  PauseCircleOutlined,
} from '@ant-design/icons';
import { uploadCoreStore } from './stores';
import navigationStore from './stores/navigation';
import uploadUIStore from './stores/upload/ui';
import TransferListContainer from './components/TransferListContainer';
import { PAUSEABLE_STATUSES, DISPLAY_UPLOADING_STATUSES, UPLOAD_STATUS, TERMINAL_STATUSES, PRESSURE_LEVELS } from './stores/upload/core/upload-core-constants';

// 【2026-07-02 动态降级】压力等级 -> 标签展示配置（三态均展示，满足需求第7点）
const PRESSURE_TAG_CONFIG = {
  [PRESSURE_LEVELS.NORMAL]: { color: 'green', text: '正常上传' },
  [PRESSURE_LEVELS.BUSY]: { color: 'orange', text: '服务器繁忙' },
  [PRESSURE_LEVELS.CRITICAL]: { color: 'red', text: '低速上传模式' },
};

@observer
class UploadPanel extends React.Component {
  fileInputRef = React.createRef();
  pendingItemId = null;

  componentDidMount() {
    uploadCoreStore.triggerFileReSelection = this.handleTriggerFileReSelection;
  }

  componentWillUnmount() {
    if (this.fileInputRef.current) {
      this.fileInputRef.current.value = '';
    }
    this.pendingItemId = null;

    const { currentUploadQueue } = uploadCoreStore;
    // 【P0修复 2026-06-27】使用 PAUSEABLE_STATUSES 常量
    // 之前包含 merging，但 merging 不可暂停（状态机无 PAUSE 转换），pauseItem 会静默失败
    const activeItems = currentUploadQueue.filter(
      item => PAUSEABLE_STATUSES.includes(item.status)
    );
    activeItems.forEach(item => uploadCoreStore.pauseItem(item.id));

    if (uploadCoreStore.triggerFileReSelection === this.handleTriggerFileReSelection) {
      uploadCoreStore.triggerFileReSelection = null;
    }
  }

  handleTriggerFileReSelection = (itemId) => {
    this.pendingItemId = itemId;
    setTimeout(() => {
      if (this.fileInputRef.current) {
        this.fileInputRef.current.click();
      }
    }, 100);
  };

  handleFileSelect = async (e) => {
    const file = e.target.files[0];
    if (!file || !this.pendingItemId) return;

    const itemId = this.pendingItemId;
    const item = uploadCoreStore.queueStore.findUploadItemInCurrentTenant(itemId);

    if (!item) {
      message.error('上传项不存在');
      this.pendingItemId = null;
      e.target.value = '';
      return;
    }

    if (file.name !== item.name) {
      message.error(`文件名不匹配，请选择正确的文件: ${item.name}`);
      e.target.value = '';
      return;
    }

    if (file.size !== item.fileSize) {
      message.error('文件大小不匹配，请选择正确的文件');
      e.target.value = '';
      return;
    }

    e.target.value = '';
    this.pendingItemId = null;

    try {
      await uploadCoreStore.replaceFileAndResume(itemId, file);
    } catch (error) {
      console.error('[UploadPanel] 重新选择文件后恢复上传失败:', error);
      message.error('恢复上传失败: ' + (error.message || '未知错误'));
    }
  };

  handlePauseItem = (itemId) => uploadCoreStore.pauseItem(itemId);

  handleResumeItem = async (itemId) => {
    try {
      await uploadCoreStore.resumeItem(itemId);
    } catch (error) {
      console.error('[UploadPanel] 继续上传失败:', error);
      message.error('继续上传失败: ' + (error.message || '未知错误'));
    }
  };

  handleCancelItem = (itemId) => uploadCoreStore.cancelItem(itemId);

  handleRemoveItem = (itemId) => {
    const item = uploadCoreStore.queueStore.findUploadItemInCurrentTenant(itemId);
    if (item?.status === 'error' && item?.file) {
      item.file = null;
    }
    uploadCoreStore.removeItem(itemId);
  };

  handlePauseAll = () => uploadCoreStore.pauseAll();
  handleResumeAll = () => uploadCoreStore.resumeAll();

  handleClearCompleted = async () => {
    const { currentUploadQueue } = uploadCoreStore;
    const completedItems = currentUploadQueue.filter(item => item.status === 'completed');
    const transferIds = completedItems.map(item => item.transferId).filter(id => id);
    if (transferIds.length > 0) {
      try {
        await uploadCoreStore.transferStore.batchDeleteTransfers(transferIds);
      } catch (error) {
        console.error('[UploadPanel] 批量删除后端传输记录失败:', error);
      }
    }
    const tenantId = uploadCoreStore.getCurrentTenantId?.() || 'default';
    completedItems.forEach(item => {
      uploadCoreStore.queueStore.removeFromQueue(item.id, tenantId);
    });
    setTimeout(() => uploadCoreStore.replenishDisplayQueue(), 0);
    message.success(`已清空 ${completedItems.length} 个已完成任务`);
  };

  handleClearErrors = async () => {
    const { currentUploadQueue } = uploadCoreStore;
    const errorItems = currentUploadQueue.filter(item => item.status === 'error');
    const transferIds = errorItems.map(item => item.transferId).filter(id => id);
    if (transferIds.length > 0) {
      try {
        await uploadCoreStore.transferStore.batchDeleteTransfers(transferIds);
      } catch (error) {
        console.error('[UploadPanel] 批量删除后端传输记录失败:', error);
      }
    }
    const tenantId = uploadCoreStore.getCurrentTenantId?.() || 'default';
    errorItems.forEach(item => {
      uploadCoreStore.queueStore.removeFromQueue(item.id, tenantId);
    });
    message.success(`已清空 ${errorItems.length} 个失败任务`);
  };

  handleClearCancelled = async () => {
    const { currentUploadQueue } = uploadCoreStore;
    const cancelledItems = currentUploadQueue.filter(item => item.status === 'cancelled');
    const transferIds = cancelledItems.map(item => item.transferId).filter(id => id);
    if (transferIds.length > 0) {
      try {
        await uploadCoreStore.transferStore.batchDeleteTransfers(transferIds);
      } catch (error) {
        console.error('[UploadPanel] 批量删除后端传输记录失败:', error);
      }
    }
    const tenantId = uploadCoreStore.getCurrentTenantId?.() || 'default';
    cancelledItems.forEach(item => {
      uploadCoreStore.queueStore.removeFromQueue(item.id, tenantId);
    });
    message.success(`已清空 ${cancelledItems.length} 个已取消任务`);
  };

  render() {
    const {
      uploadingItems,
      completedItems,
      errorItems,
      cancelledItems,
      activeCount,
      pausedCount,
      currentUploadQueue,
      pressureLevel,
      pressureMessage,
    } = uploadCoreStore;

    void uploadCoreStore.uploadRefreshTrigger;
    void uploadCoreStore.folderUploadProgress;

    // 【2026-07-02】压力标签（仅 busy/critical 显示）
    const pressureTag = PRESSURE_TAG_CONFIG[pressureLevel];

    const spaceType = navigationStore.lockedRootFolderName || (navigationStore.isPublic ? '公共共享库' : '我的文件');
    const spaceColor = navigationStore.isPublic ? 'gold' : 'blue';
    const spaceIcon = navigationStore.isPublic ? <CloudOutlined /> : <CloudUploadOutlined />;

    const totalTaskCount = currentUploadQueue.length;
    const failedCount = errorItems.length + cancelledItems.length;
    const uploadingTotal = activeCount + pausedCount;
    const completedTotal = completedItems.length;
    const drawerWidth = 560;

    return (
      <>
        {/* 隐藏的文件选择输入框（用于断点续传） */}
        <input
          ref={this.fileInputRef}
          type="file"
          style={{ display: 'none' }}
          onChange={this.handleFileSelect}
          accept="*/*"
        />

        {/* 抽屉 - 展开时显示完整列表 */}
        <Drawer
          title={
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Tag
                icon={spaceIcon}
                color={spaceColor}
                style={{ margin: 0, fontSize: 12, borderRadius: 4 }}
              >
                {spaceType}
              </Tag>
              {pressureTag && (
                <Tag
                  color={pressureTag.color}
                  style={{ margin: 0, fontSize: 12, borderRadius: 4 }}
                  title={pressureMessage || pressureTag.text}
                >
                  {pressureTag.text}
                </Tag>
              )}
              <span style={{ fontSize: 12, color: '#8c8c8c' }}>
                共 {totalTaskCount} 个 | 上传中: {uploadingTotal} | 已完成: {completedTotal} | 失败: {failedCount}
              </span>
            </div>
          }
          placement="right"
          width={drawerWidth}
          visible={uploadUIStore.panel.expanded}
          onClose={() => uploadUIStore.panel.collapse()}
          closable={true}
          mask={true}
          maskClosable={true}
          destroyOnClose={false}
          headerStyle={{ padding: '12px 16px', minHeight: 52, borderBottom: '1px solid #f0f0f0' }}
          bodyStyle={{ padding: 0, overflow: 'hidden', height: 'calc(100vh - 52px)' }}
          getContainer={false}
          push={false}
        >
          {/* 【新增】抽屉顶部拖拽把手 */}
          <TransferListContainer
            uploadingItems={uploadingItems}
            completedItems={completedItems}
            errorItems={errorItems}
            cancelledItems={cancelledItems}
            uploadSpeed={uploadCoreStore.fileUploadStore?.uploadSpeed || {}}
            onPause={this.handlePauseItem}
            onResume={this.handleResumeItem}
            onCancel={this.handleCancelItem}
            onRemove={this.handleRemoveItem}
            onPauseAll={this.handlePauseAll}
            onResumeAll={this.handleResumeAll}
            onClearCompleted={this.handleClearCompleted}
            onClearErrors={this.handleClearErrors}
            onClearCancelled={this.handleClearCancelled}
          />
        </Drawer>
      </>
    );
  }
}

/**
 * MiniBar - 底部小条组件（默认态）
 * 仿百度网盘：有任务时显示在底部，点击展开抽屉
 *
 * 增强功能（2026-06-06）：
 * 1. 总体进度条：显示所有进行中任务的平均进度
 * 2. 闪烁提示：完成/失败时 MiniBar 闪烁 1.5s 提醒用户
 */
@observer
class MiniBar extends React.Component {
  componentDidMount() {
    this._lastCompleted = 0;
    this._lastFailed = 0;
  }

  /**
   * 计算总体平均进度
   * 只统计有 fileSize 的进行中任务
   */
  calcOverallPercent(queue) {
    let totalPercent = 0;
    let count = 0;
    for (const item of queue) {
      // 【P0修复 2026-06-27】使用 DISPLAY_UPLOADING_STATUSES 常量（排除 paused，暂停不贡献进度）
      if (DISPLAY_UPLOADING_STATUSES.includes(item.status) &&
          item.status !== UPLOAD_STATUS.PAUSED &&
          typeof item.percent === 'number') {
        totalPercent += item.percent;
        count++;
      }
    }
    return count > 0 ? Math.round(totalPercent / count) : 0;
  }

  render() {
    const { currentUploadQueue, pressureLevel, pressureMessage } = uploadCoreStore;
    const total = currentUploadQueue.length;

    // 计算各状态数量
    // 【P0修复 2026-06-27】使用常量替代硬编码数组
    let active = 0, paused = 0, completed = 0, failed = 0;
    for (const item of currentUploadQueue) {
      if (DISPLAY_UPLOADING_STATUSES.includes(item.status) && item.status !== UPLOAD_STATUS.PAUSED) active++;
      else if (item.status === UPLOAD_STATUS.PAUSED) paused++;
      else if (item.status === UPLOAD_STATUS.COMPLETED) completed++;
      else if (TERMINAL_STATUSES.includes(item.status) && item.status !== UPLOAD_STATUS.COMPLETED) failed++;
    }

    const hasActive = active > 0;
    const overallPercent = this.calcOverallPercent(currentUploadQueue);

    // 【新增】闪烁提示：完成/失败数量增加时闪烁
    const completedDelta = completed - (this._lastCompleted || 0);
    const failedDelta = failed - (this._lastFailed || 0);
    const shouldFlash = (completedDelta > 0 || failedDelta > 0) && !uploadUIStore.panel.expanded;
    // 用 ref 持久化计数（避免渲染时重置）
    if (!this._lastCompleted && this._lastCompleted !== 0) this._lastCompleted = 0;
    if (!this._lastFailed && this._lastFailed !== 0) this._lastFailed = 0;

    // 在渲染中比较新值与持久值，更新持久值
    // 注意：这里用 componentDidUpdate 模式更严谨，但用状态 hook 也可以
    const prevCompleted = this._lastCompleted;
    const prevFailed = this._lastFailed;
    if (completed !== prevCompleted || failed !== prevFailed) {
      // 标记待更新（避免在 render 中 setState）
      setTimeout(() => {
        this._lastCompleted = completed;
        this._lastFailed = failed;
      }, 0);
    }

    const flashColor = failedDelta > 0 ? '#ff4d4f' : '#52c41a';
    const baseGradient = shouldFlash
      ? `linear-gradient(135deg, ${flashColor} 0%, ${flashColor} 100%)`
      : 'linear-gradient(135deg, #1890ff 0%, #096dd9 100%)';
    const hoverGradient = shouldFlash
      ? `linear-gradient(135deg, ${flashColor} 0%, ${flashColor} 100%)`
      : 'linear-gradient(135deg, #40a9ff 0%, #1890ff 100%)';

    return (
      <div
        onClick={() => uploadUIStore.panel.expand()}
        style={{
          position: 'fixed',
          bottom: 0,
          left: '50%',
          transform: 'translateX(-50%)',
          background: baseGradient,
          color: '#fff',
          padding: '6px 20px 8px',
          borderRadius: '8px 8px 0 0',
          boxShadow: '0 -2px 12px rgba(0, 0, 0, 0.15)',
          cursor: 'pointer',
          zIndex: 1000,
          minWidth: 420,
          maxWidth: 720,
          userSelect: 'none',
          transition: 'background 0.3s',
          animation: shouldFlash ? 'minibarFlash 1.5s ease-out' : 'none',
        }}
        onMouseEnter={(e) => {
          if (!shouldFlash) e.currentTarget.style.background = hoverGradient;
        }}
        onMouseLeave={(e) => {
          if (!shouldFlash) e.currentTarget.style.background = baseGradient;
        }}
        title="点击查看传输任务"
      >
        {/* 【新增】闪烁动画 keyframes - 注入到全局一次 */}
        {shouldFlash && (
          <style>{`
            @keyframes minibarFlash {
              0% { box-shadow: 0 -2px 12px rgba(0, 0, 0, 0.15); }
              20% { box-shadow: 0 -4px 24px ${flashColor}; transform: translateX(-50%) translateY(-3px); }
              100% { box-shadow: 0 -2px 12px rgba(0, 0, 0, 0.15); transform: translateX(-50%) translateY(0); }
            }
          `}</style>
        )}

        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          {/* 图标 + 主信息 */}
          <CloudUploadOutlined style={{ fontSize: 16 }} />
          <span style={{ fontSize: 13, fontWeight: 500 }}>
            {hasActive ? '正在传输' : failed > 0 ? '传输异常' : '传输完成'}
          </span>

          {/* 总体进度（仅在有进行中任务时显示） */}
          {hasActive && (
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 4,
              fontSize: 12,
              opacity: 0.95,
            }}>
              <div style={{
                width: 80,
                height: 4,
                background: 'rgba(255, 255, 255, 0.3)',
                borderRadius: 2,
                overflow: 'hidden',
              }}>
                <div style={{
                  width: `${overallPercent}%`,
                  height: '100%',
                  background: '#fff',
                  transition: 'width 0.3s',
                }} />
              </div>
              <span style={{ minWidth: 32, textAlign: 'right' }}>{overallPercent}%</span>
            </div>
          )}

          {/* 状态徽章组 */}
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {/* 【2026-07-02】服务器压力提示（三态均展示，满足需求第7点） */}
            {(() => {
              const tagCfg = PRESSURE_TAG_CONFIG[pressureLevel];
              if (!tagCfg) return null;
              const tipMsg = pressureMessage || tagCfg.text;
              const colorMap = {
                [PRESSURE_LEVELS.NORMAL]: '#d9f7be',
                [PRESSURE_LEVELS.BUSY]: '#ffe7ba',
                [PRESSURE_LEVELS.CRITICAL]: '#ffccc7',
              };
              return (
                <Tooltip title={tipMsg}>
                  <span style={{
                    fontSize: 12,
                    color: colorMap[pressureLevel] || '#fff',
                    fontWeight: pressureLevel === PRESSURE_LEVELS.NORMAL ? 400 : 500,
                    opacity: pressureLevel === PRESSURE_LEVELS.NORMAL ? 0.85 : 1,
                  }}>
                    {tagCfg.text}
                  </span>
                </Tooltip>
              );
            })()}
            {active > 0 && (
              <Badge
                count={active}
                style={{ backgroundColor: '#fff', color: '#1890ff' }}
                title={`${active} 个进行中`}
              />
            )}
            {paused > 0 && (
              <Tooltip title={`${paused} 个已暂停`}>
                <span style={{ display: 'flex', alignItems: 'center', gap: 2, fontSize: 12 }}>
                  <PauseCircleOutlined /> {paused}
                </span>
              </Tooltip>
            )}
            {completed > 0 && (
              <Tooltip title={`${completed} 个已完成${completedDelta > 0 ? `（+${completedDelta}）` : ''}`}>
                <span style={{
                  display: 'flex', alignItems: 'center', gap: 2, fontSize: 12,
                  color: completedDelta > 0 ? '#fff' : 'inherit',
                  fontWeight: completedDelta > 0 ? 600 : 'normal',
                }}>
                  <CheckCircleOutlined /> {completed}
                </span>
              </Tooltip>
            )}
            {failed > 0 && (
              <Tooltip title={`${failed} 个失败${failedDelta > 0 ? `（+${failedDelta}）` : ''}`}>
                <span style={{
                  display: 'flex', alignItems: 'center', gap: 2, fontSize: 12,
                  color: completedDelta === 0 && failedDelta > 0 ? '#fff' : 'inherit',
                  fontWeight: failedDelta > 0 ? 600 : 'normal',
                }}>
                  <CloseCircleOutlined /> {failed}
                </span>
              </Tooltip>
            )}
          </div>

          <span style={{ fontSize: 12, opacity: 0.85 }}>
            共 {total} 个任务
          </span>

          {/* 展开箭头 */}
          <UpOutlined style={{ fontSize: 12, marginLeft: 'auto' }} />
        </div>
      </div>
    );
  }
}

/**
 * DrawerDragHandle - 抽屉顶部拖拽把手
 *
 * 仿百度网盘：用户可拖拽调整抽屉高度
 * 限制范围：240px ~ 720px（由父组件 panel.setDrawerHeight 强制约束）
 *
 * 行为：
 *   - mousedown：记录初始 Y 和当前 drawerHeight
 *   - mousemove：deltaY（向下为正）→ 新高度 = drawerHeight - deltaY
 *   - mouseup：解绑事件；高度 < 120 触发收起
 */
class DrawerDragHandle extends React.Component {
  constructor(props) {
    super(props);
    this.state = { dragging: false, startY: 0, startHeight: 0 };
  }

  handleMouseDown = (e) => {
    if (e.button !== 0) return;
    e.preventDefault();

    this.setState({
      dragging: true,
      startY: e.clientY,
      startHeight: this.props.height,
    });

    document.addEventListener('mousemove', this.handleMouseMove);
    document.addEventListener('mouseup', this.handleMouseUp);
  };

  handleMouseMove = (e) => {
    if (!this.state.dragging) return;
    const deltaY = e.clientY - this.state.startY;
    const newHeight = this.state.startHeight - deltaY;
    this.props.onChange(newHeight);
  };

  handleMouseUp = () => {
    if (!this.state.dragging) return;
    this.setState({ dragging: false });
    document.removeEventListener('mousemove', this.handleMouseMove);
    document.removeEventListener('mouseup', this.handleMouseUp);

    // 拖到顶部（高度 < 120）触发收起
    if (this.props.height < 120) {
      this.props.onCollapse();
    }
  };

  componentWillUnmount() {
    document.removeEventListener('mousemove', this.handleMouseMove);
    document.removeEventListener('mouseup', this.handleMouseUp);
  }

  render() {
    const { dragging } = this.state;
    return (
      <div
        onMouseDown={this.handleMouseDown}
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          height: 8,
          cursor: dragging ? 'row-resize' : 'n-resize',
          zIndex: 10,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: dragging ? 'rgba(24, 144, 255, 0.1)' : 'transparent',
          transition: 'background 0.15s',
        }}
        onMouseEnter={(e) => {
          if (!dragging) e.currentTarget.style.background = 'rgba(24, 144, 255, 0.08)';
        }}
        onMouseLeave={(e) => {
          if (!dragging) e.currentTarget.style.background = 'transparent';
        }}
        title="拖动调整高度，往上拖到底部收起"
      >
        <div style={{
          width: 36,
          height: 3,
          background: '#d9d9d9',
          borderRadius: 2,
          transition: 'all 0.15s',
        }} />
      </div>
    );
  }
}

export { MiniBar };
export default UploadPanel;
