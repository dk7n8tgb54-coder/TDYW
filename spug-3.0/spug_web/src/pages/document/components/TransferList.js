/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 *
 * 传输列表组件 - 网盘风格（3 Tab）
 * 参考阿里云盘设计：上传中 / 已完成 / 失败
 *
 * 状态归类：
 *   - 上传中：waiting, calculating, uploading, paused, merging
 *   - 已完成：completed
 *   - 失败：error
 *   - cancelled 视为失败（用户主动取消的项目放在"失败"Tab）
 */
import React, { useState, useMemo } from 'react';
import { Empty, Button, Tabs, Tooltip } from 'antd';
import {
  ClearOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons';
import TransferItem from './TransferItem';
import { UPLOAD_STATUS, ACTIVE_STATUSES, PENDING_STATUSES } from '../stores/upload/core/upload-core-constants';

const { TabPane } = Tabs;

/**
 * 上传中状态的判定（包含 paused）
 */
const isUploadingStatus = (status) =>
  ACTIVE_STATUSES.includes(status) ||
  status === UPLOAD_STATUS.PAUSED ||
  PENDING_STATUSES.includes(status);

/**
 * 失败状态的判定（error + cancelled 归到"失败"Tab）
 */
const isFailedStatus = (status) =>
  status === UPLOAD_STATUS.ERROR || status === UPLOAD_STATUS.CANCELLED;

// 【2026-06-11 修复】传输列表布局常量
// 行业惯例：抽屉宽度上限 960px，与底部 MiniBar (maxWidth 720) 视觉对齐
const LIST_MAX_WIDTH = 960;

/**
 * Tab 内容区内层列表的容器样式
 * 关键：用 flex: 1 + minHeight: 0 让 flex 子项正确收缩，触发 overflowY 滚动
 * 之前用 maxHeight: 460 在嵌套 Tabs/Drawer 下被父级 flex 撑开后不出现滚动条
 */
const listContainerStyle = {
  flex: 1,
  minHeight: 0,
  overflowY: 'auto',
  overflowX: 'hidden',
};

/**
 * 分组传输列表组件
 */
const TransferList = ({
  uploadingItems = [],
  completedItems = [],
  errorItems = [],   // 仅 error
  cancelledItems = [], // 兼容旧调用，内部并入失败 Tab
  uploadSpeed = {},
  onPause,
  onResume,
  onCancel,
  onRemove,
  onPauseAll,
  onResumeAll,
  onClearCompleted,
  onClearErrors,
  onClearCancelled,  // 兼容旧调用
}) => {
  // Tab 激活状态（受控），默认进入"上传中"
  const [activeTab, setActiveTab] = useState('uploading');

  // 将 cancelledItems 并入失败组，统一从"失败"Tab 清理
  const failedItems = useMemo(
    () => [...errorItems, ...cancelledItems],
    [errorItems, cancelledItems]
  );

  // 上传中分组：再细分为"进行中"和"已暂停"（仅头部角标和按钮用，列表项合并展示）
  const { activeItems, pausedItems } = useMemo(() => ({
    activeItems: uploadingItems.filter(
      (item) => isUploadingStatus(item.status) && item.status !== UPLOAD_STATUS.PAUSED
    ),
    pausedItems: uploadingItems.filter((item) => item.status === UPLOAD_STATUS.PAUSED),
  }), [uploadingItems]);

  const uploadingCount = activeItems.length + pausedItems.length;
  const completedCount = completedItems.length;
  const failedCount = failedItems.length;

  const handleClearFailed = (e) => {
    if (e) e.stopPropagation();
    onClearErrors && onClearErrors();
    onClearCancelled && onClearCancelled();
  };

  // 上传中 Tab 的头部 extra 按钮
  const uploadingTabExtra = uploadingCount > 0 && (
    <div onClick={(e) => e.stopPropagation()} style={{ display: 'flex', gap: 4 }}>
      {pausedItems.length > 0 && (
        <Tooltip title="全部开始">
          <Button
            type="text"
            size="small"
            icon={<PlayCircleOutlined />}
            onClick={onResumeAll}
            style={{ color: '#faad14' }}
          />
        </Tooltip>
      )}
      {activeItems.length > 0 && (
        <Tooltip title="全部暂停">
          <Button
            type="text"
            size="small"
            icon={<PauseCircleOutlined />}
            onClick={onPauseAll}
            style={{ color: '#1890ff' }}
          />
        </Tooltip>
      )}
    </div>
  );

  // 渲染"上传中"列表项
  const renderUploadingList = () => {
    if (uploadingCount === 0) {
      return (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="暂无传输任务"
          style={{ padding: '40px 0' }}
        />
      );
    }
    return (
      <div style={listContainerStyle}>
        {[...activeItems, ...pausedItems].map((item, index, arr) => (
          <div
            key={item.id}
            style={{
              borderBottom: index < arr.length - 1 ? '1px solid #f0f0f0' : 'none',
            }}
          >
            <TransferItem
              item={item}
              speed={uploadSpeed[item.id]}
              onPause={onPause}
              onResume={onResume}
              onCancel={onCancel}
              onRemove={onRemove}
            />
          </div>
        ))}
      </div>
    );
  };

  // 渲染"已完成"列表
  const renderCompletedList = () => {
    if (completedCount === 0) {
      return (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="暂无已完成任务"
          style={{ padding: '40px 0' }}
        />
      );
    }
    return (
      <div style={listContainerStyle}>
        {completedItems.map((item, index) => (
          <div
            key={item.id}
            style={{
              borderBottom: index < completedItems.length - 1 ? '1px solid #f0f0f0' : 'none',
            }}
          >
            <TransferItem
              item={item}
              speed={uploadSpeed[item.id]}
              onPause={onPause}
              onResume={onResume}
              onCancel={onCancel}
              onRemove={onRemove}
            />
          </div>
        ))}
      </div>
    );
  };

  // 渲染"失败"列表
  const renderFailedList = () => {
    if (failedCount === 0) {
      return (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="暂无失败任务"
          style={{ padding: '40px 0' }}
        />
      );
    }
    return (
      <div style={listContainerStyle}>
        {failedItems.map((item, index) => (
          <div
            key={item.id}
            style={{
              borderBottom: index < failedItems.length - 1 ? '1px solid #f0f0f0' : 'none',
            }}
          >
            <TransferItem
              item={item}
              speed={uploadSpeed[item.id]}
              onPause={onPause}
              onResume={onResume}
              onCancel={onCancel}
              onRemove={onRemove}
            />
          </div>
        ))}
      </div>
    );
  };

  return (
    <div
      style={{
        // 【2026-06-11 修复】宽度限制 + 居中
        // 行业惯例：抽屉列表宽度上限 960px，避免宽屏下拉伸到两端
        // 与底部 MiniBar (maxWidth 720) 视觉对齐
        width: '100%',
        height: '100%',
        overflow: 'hidden',
        // 【2026-06-11 修复】minHeight: 0 是 flex 子项正确收缩的关键
        // 不加这个，flex: 1 子项不会被压缩，overflow 失效
        minHeight: 0,
      }}
    >
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        size="small"
        // 【2026-06-11 修复】关闭 Tab 切换动画，避免 antd 短暂叠加多个 TabPane
        animated={false}
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          // 【2026-06-11 修复】Tabs 容器自身需 minHeight: 0
          // 否则 Tab 内容区继承不到 flex 收缩
          minHeight: 0,
          overflow: 'hidden',
        }}
        tabBarStyle={{ margin: 0, padding: '0 12px' }}
      >
        <TabPane
          tab={`上传中 ${uploadingCount > 0 ? `(${uploadingCount})` : ''}`}
          key="uploading"
          closeIcon={null}
          style={{ minHeight: 0 }}
        >
          <div style={{ padding: '8px 0', display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
            {uploadingTabExtra && (
              <div style={{ padding: '0 12px 8px', display: 'flex', justifyContent: 'flex-end' }}>
                {uploadingTabExtra}
              </div>
            )}
            {renderUploadingList()}
          </div>
        </TabPane>

        <TabPane
          tab={`已完成 ${completedCount > 0 ? `(${completedCount})` : ''}`}
          key="completed"
          closeIcon={null}
          style={{ minHeight: 0 }}
        >
          <div style={{ padding: '8px 0', display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
            {completedCount > 0 && (
              <div style={{ padding: '0 12px 8px', display: 'flex', justifyContent: 'flex-end' }}>
                <Tooltip title="清空已完成">
                  <Button
                    type="text"
                    size="small"
                    icon={<ClearOutlined />}
                    onClick={(e) => {
                      e.stopPropagation();
                      onClearCompleted && onClearCompleted();
                    }}
                    style={{ fontSize: 12, color: '#8c8c8c' }}
                  >
                    清空
                  </Button>
                </Tooltip>
              </div>
            )}
            {renderCompletedList()}
          </div>
        </TabPane>

        <TabPane
          tab={`失败 ${failedCount > 0 ? `(${failedCount})` : ''}`}
          key="failed"
          closeIcon={null}
          style={{ minHeight: 0 }}
        >
          <div style={{ padding: '8px 0', display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
            {failedCount > 0 && (
              <div style={{ padding: '0 12px 8px', display: 'flex', justifyContent: 'flex-end' }}>
                <Tooltip title="清空失败任务">
                  <Button
                    type="text"
                    size="small"
                    icon={<ClearOutlined />}
                    onClick={handleClearFailed}
                    style={{ fontSize: 12, color: '#8c8c8c' }}
                  >
                    清空
                  </Button>
                </Tooltip>
              </div>
            )}
            {renderFailedList()}
          </div>
        </TabPane>
      </Tabs>
    </div>
  );
};

export default TransferList;
