/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 *
 * VirtualTransferList - 虚拟列表传输列表组件
 * 【重构 2026-06-06】改为 3 Tab：上传中 / 已完成 / 失败（cancelled 归到失败）
 *
 * 关键修复点：
 * 1. 【P0】移除外层滚动，避免双重滚动冲突
 * 2. 【P0】回调函数使用 useCallback 缓存，确保 React.memo 生效
 * 3. 【P1】新增文件自动滚动到可视区
 * 4. 【P1】添加错误边界，防止渲染崩溃
 */
import React, { useMemo, useRef, useCallback, useEffect, useState } from 'react';
import { FixedSizeList as List } from 'react-window';
import { Empty, Button, Tabs, Tooltip } from 'antd';
import {
  ClearOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons';
import { observer } from 'mobx-react';
import { areEqual } from 'react-window'; // 【新增】精确比较函数
import TransferItem from './TransferItem';
import { UPLOAD_CONSTANTS } from '../stores/constants/upload';
import { UPLOAD_STATUS } from '../stores/upload/core/upload-core-constants';
import styles from './VirtualTransferList.module.less';

const { TabPane } = Tabs;

// 从常量读取配置
const {
  ITEM_HEIGHT,
  OVERSCAN_COUNT,
  LIST_MAX_HEIGHT,
  LIST_MIN_HEIGHT
} = UPLOAD_CONSTANTS.VIRTUAL_LIST;

// 【2026-06-11 修复】使用 ResizeObserver 让虚拟列表高度跟随容器自适应
// 之前固定 LIST_MAX_HEIGHT=400,Drawer 拖到 720 时 List 内部留出大片空白
// 解决：List 高度 = 容器实际高度,但不超过 LIST_MAX_HEIGHT

// ==================== 错误边界组件 ====================

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true };
  }

  componentDidCatch(error, errorInfo) {
    console.error('[VirtualTransferList] 渲染错误:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="列表渲染异常，请刷新页面重试"
          style={{ padding: '40px 0' }}
        />
      );
    }
    return this.props.children;
  }
}

// ==================== 虚拟列表行组件 ====================

/**
 * VirtualRow - 虚拟列表行渲染组件
 * 【修复】使用 areEqual 进行精确比较，避免不必要的重渲染
 * 【关键】回调函数通过 ref 传递，避免 itemData 频繁变化
 */
const VirtualRow = React.memo(({ index, style, data }) => {
  const { items, uploadSpeed, callbacksRef } = data;
  const item = items[index];
  const { onPause, onResume, onCancel, onRemove } = callbacksRef.current;

  return (
    <div
      className={styles.listItemWrapper}
      style={style}
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
  );
}, areEqual); // 【关键】使用 react-window 提供的精确比较函数

// ==================== 虚拟列表分页组件 ====================

/**
 * VirtualList - 单个 Tab 的虚拟列表（不再嵌套 Collapse）
 */
const VirtualList = React.memo(({
  items,
  uploadSpeed,
  onPause,
  onResume,
  onCancel,
  onRemove,
}) => {
  const listRef = useRef(null);
  const containerRef = useRef(null);
  const prevLengthRef = useRef(items.length);
  const [containerHeight, setContainerHeight] = useState(LIST_MAX_HEIGHT);

  // 【2026-06-11 修复】用 ResizeObserver 监听容器高度,List 高度跟随
  // 容器高度 ∈ [LIST_MIN_HEIGHT, LIST_MAX_HEIGHT]
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => {
      const h = el.clientHeight;
      setContainerHeight(Math.min(LIST_MAX_HEIGHT, Math.max(LIST_MIN_HEIGHT, h)));
    };
    update();
    // ResizeObserver 监听父级 flex 容器尺寸变化（Drawer 拖拽改变高度时）
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // 【P0关键修复】使用 ref 保存回调函数，避免 itemData 频繁变化导致重渲染
  const callbacksRef = useRef({ onPause, onResume, onCancel, onRemove });
  callbacksRef.current = { onPause, onResume, onCancel, onRemove };

  // 【P0关键修复】itemData 只包含数据，不包含回调函数引用
  const itemData = useMemo(() => ({
    items,
    uploadSpeed,
    callbacksRef, // 通过 ref 传递回调，避免频繁重建
  }), [items, uploadSpeed]); // 【关键】不依赖回调函数

  // 【P1新增】新文件自动滚动到可视区
  useEffect(() => {
    if (items.length > prevLengthRef.current && listRef.current) {
      // 文件数量增加，自动滚动到最新文件
      listRef.current.scrollToItem(items.length - 1, 'smart');
    }
    prevLengthRef.current = items.length;
  }, [items.length]);

  if (items.length === 0) {
    return (
      <div ref={containerRef} style={{ flex: 1, minHeight: 0 }}>
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="暂无任务"
          style={{ padding: '40px 0' }}
        />
      </div>
    );
  }

  return (
    <div ref={containerRef} style={{ flex: 1, minHeight: 0 }}>
      <List
        ref={listRef}
        height={containerHeight}
        itemCount={items.length}
        itemSize={ITEM_HEIGHT}
        itemData={itemData}
        overscanCount={OVERSCAN_COUNT}
        width="100%"
      >
        {VirtualRow}
      </List>
    </div>
  );
});

// ==================== 主组件 ====================

/**
 * VirtualTransferList - 虚拟列表传输列表主组件
 * 【重构 2026-06-06】3 Tab 结构：上传中 / 已完成 / 失败
 * 【P0修复】
 * 1. 移除外层滚动容器，避免双重滚动冲突
 * 2. 回调函数使用 useCallback 缓存
 * 3. 添加错误边界
 */
const VirtualTransferList = ({
  uploadingItems = [],
  completedItems = [],
  errorItems = [],
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
  onClearCancelled, // 兼容旧调用
}) => {
  const [activeTab, setActiveTab] = useState('uploading');

  // 【P0关键修复】使用 useMemo 缓存分组结果，避免每次渲染重新计算
  const { uploadingList, completedList, failedList } = useMemo(() => {
    // 失败 = error + cancelled
    const failed = [...errorItems, ...cancelledItems];
    return {
      uploadingList: uploadingItems,
      completedList: completedItems,
      failedList: failed,
    };
  }, [uploadingItems, completedItems, errorItems, cancelledItems]);

  // 【关键修复】回调函数使用 useCallback 缓存
  const handlePauseAll = useCallback((e) => {
    if (e) e.stopPropagation();
    if (onPauseAll) onPauseAll();
  }, [onPauseAll]);

  const handleResumeAll = useCallback((e) => {
    if (e) e.stopPropagation();
    if (onResumeAll) onResumeAll();
  }, [onResumeAll]);

  const handleClearFailed = useCallback((e) => {
    if (e) e.stopPropagation();
    if (onClearErrors) onClearErrors();
    if (onClearCancelled) onClearCancelled();
  }, [onClearErrors, onClearCancelled]);

  const handleClearCompleted = useCallback((e) => {
    if (e) e.stopPropagation();
    if (onClearCompleted) onClearCompleted();
  }, [onClearCompleted]);

  // 上传中是否显示"全部开始/暂停"
  const pausedCount = uploadingList.filter((i) => i.status === UPLOAD_STATUS.PAUSED).length;
  const activeCount = uploadingList.length - pausedCount;

  const uploadingTabExtra = uploadingList.length > 0 && (
    <div onClick={(e) => e.stopPropagation()} style={{ display: 'flex', gap: 4 }}>
      {pausedCount > 0 && (
        <Tooltip title="全部开始">
          <Button
            type="text"
            size="small"
            icon={<PlayCircleOutlined />}
            onClick={handleResumeAll}
            style={{ color: '#faad14' }}
          />
        </Tooltip>
      )}
      {activeCount > 0 && (
        <Tooltip title="全部暂停">
          <Button
            type="text"
            size="small"
            icon={<PauseCircleOutlined />}
            onClick={handlePauseAll}
            style={{ color: '#1890ff' }}
          />
        </Tooltip>
      )}
    </div>
  );

  return (
    <ErrorBoundary>
      {/* 【P0关键修复】移除外层 overflowY: auto，由 react-window 内部处理滚动 */}
      <div
        className={styles.virtualTransferList}
        // 【2026-06-11 修复】与 TransferList 对齐：宽度上限 960 + 居中
        style={{ width: '100%' }}
      >
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          size="small"
          // 【2026-06-11 修复】关闭 Tab 切换动画
          // 原因：默认 animated=true 会让 antd 在切换时短暂同时显示多个 TabPane，
          // 造成 react-window 节点叠加，视觉上"残留"
          animated={false}
          style={{
            // 【2026-06-11 修复】Tabs 容器 minHeight: 0 让 flex 子项正确收缩
            minHeight: 0,
            overflow: 'hidden',
          }}
          tabBarStyle={{ margin: 0, padding: '0 12px' }}
        >
          <TabPane
            tab={`上传中 ${uploadingList.length > 0 ? `(${uploadingList.length})` : ''}`}
            key="uploading"
            style={{ minHeight: 0 }}
          >
            {uploadingTabExtra && (
              <div style={{ padding: '0 12px 8px', display: 'flex', justifyContent: 'flex-end' }}>
                {uploadingTabExtra}
              </div>
            )}
            {/* 【2026-06-11 修复】用 key={activeTab} 强制 VirtualList 重新挂载
                原因：3 个 TabPane 同时挂载时，react-window 实例会复用容器，
                切 Tab 时上一个 List 的滚动位置/高度状态会瞬时显示。
                用 key 切换时 React 会 unmount 旧 List 再 mount 新 List，避免残留。 */}
            {activeTab === 'uploading' && (
              <VirtualList
                key={`vlist-${activeTab}`}
                items={uploadingList}
                uploadSpeed={uploadSpeed}
                onPause={onPause}
                onResume={onResume}
                onCancel={onCancel}
                onRemove={onRemove}
              />
            )}
          </TabPane>

          <TabPane
            tab={`已完成 ${completedList.length > 0 ? `(${completedList.length})` : ''}`}
            key="completed"
            style={{ minHeight: 0 }}
          >
            {completedList.length > 0 && (
              <div style={{ padding: '0 12px 8px', display: 'flex', justifyContent: 'flex-end' }}>
                <Tooltip title="清空已完成">
                  <Button
                    type="text"
                    size="small"
                    icon={<ClearOutlined />}
                    onClick={handleClearCompleted}
                    style={{ fontSize: 12, color: '#8c8c8c' }}
                  >
                    清空
                  </Button>
                </Tooltip>
              </div>
            )}
            {activeTab === 'completed' && (
              <VirtualList
                key={`vlist-${activeTab}`}
                items={completedList}
                uploadSpeed={uploadSpeed}
                onPause={onPause}
                onResume={onResume}
                onCancel={onCancel}
                onRemove={onRemove}
              />
            )}
          </TabPane>

          <TabPane
            tab={`失败 ${failedList.length > 0 ? `(${failedList.length})` : ''}`}
            key="failed"
            style={{ minHeight: 0 }}
          >
            {failedList.length > 0 && (
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
            {activeTab === 'failed' && (
              <VirtualList
                key={`vlist-${activeTab}`}
                items={failedList}
                uploadSpeed={uploadSpeed}
                onPause={onPause}
                onResume={onResume}
                onCancel={onCancel}
                onRemove={onRemove}
              />
            )}
          </TabPane>
        </Tabs>
      </div>
    </ErrorBoundary>
  );
};

export default observer(VirtualTransferList);
