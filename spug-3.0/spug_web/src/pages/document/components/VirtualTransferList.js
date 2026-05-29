/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 *
 * VirtualTransferList - 虚拟列表传输列表组件
 * 【修复】解决大批量文件上传时的渲染性能问题
 *
 * 关键修复点：
 * 1. 【P0】移除外层滚动，避免双重滚动冲突
 * 2. 【P0】回调函数使用 useCallback 缓存，确保 React.memo 生效
 * 3. 【P1】新增文件自动滚动到可视区
 * 4. 【P1】添加错误边界，防止渲染崩溃
 */
import React, { useMemo, useRef, useCallback, useEffect } from 'react';
import { FixedSizeList as List } from 'react-window';
import { Empty, Button, Tooltip, Collapse, Badge } from 'antd';
import {
  ClearOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  CheckCircleFilled,
  CloseCircleFilled,
  LoadingOutlined,
} from '@ant-design/icons';
import { observer } from 'mobx-react';
import { areEqual } from 'react-window'; // 【新增】精确比较函数
import TransferItem from './TransferItem';
import { UPLOAD_CONSTANTS } from '../stores/constants/upload';
import styles from './VirtualTransferList.module.less';

const { Panel } = Collapse;

// 从常量读取配置
const {
  ITEM_HEIGHT,
  OVERSCAN_COUNT,
  LIST_MAX_HEIGHT,
  LIST_MIN_HEIGHT
} = UPLOAD_CONSTANTS.VIRTUAL_LIST;

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

// ==================== 虚拟列表分组组件 ====================

/**
 * VirtualGroup - 虚拟列表分组组件
 * 【修复】
 * 1. 回调函数使用 useCallback 缓存
 * 2. itemData 精确控制依赖，避免频繁更新
 * 3. 新增文件自动滚动到可视区
 */
const VirtualGroup = React.memo(({
  title,
  icon,
  items,
  uploadSpeed,
  extra,
  defaultExpanded = true,
  onPause,
  onResume,
  onCancel,
  onRemove,
  groupKey, // 用于样式标识和自动滚动
}) => {
  const listRef = useRef(null);
  const prevLengthRef = useRef(items.length);

  // 【关键】计算列表高度：最小高度100px，最大400px
  const listHeight = useMemo(() => {
    return Math.min(LIST_MAX_HEIGHT, Math.max(LIST_MIN_HEIGHT, items.length * ITEM_HEIGHT));
  }, [items.length]);

  // 【P0关键修复】使用 ref 保存回调函数，避免 itemData 频繁变化导致重渲染
  const callbacksRef = useRef({ onPause, onResume, onCancel, onRemove });
  callbacksRef.current = { onPause, onResume, onCancel, onRemove };

  // 【P0关键修复】itemData 只包含数据，不包含回调函数引用
  // 回调函数通过 ref 传递，确保 itemData 只在 items/uploadSpeed 变化时更新
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

  // 根据颜色类型获取样式类名
  const groupClass = `${styles.groupContainer} ${styles[groupKey] || ''}`;

  // 根据 groupKey 获取 badge 颜色
  const getBadgeColor = () => {
    switch (groupKey) {
      case 'active': return '#1890ff';
      case 'paused': return '#faad14';
      case 'error': return '#ff4d4f';
      case 'completed': return '#52c41a';
      default: return '#1890ff';
    }
  };

  return (
    <div className={groupClass}>
      <Collapse
        defaultActiveKey={defaultExpanded ? ['group'] : []}
        ghost
        bordered={false}
      >
        <Panel
          header={
            <div className={styles.groupHeader}>
              <div className={styles.groupTitle}>
                {icon}
                <span className={styles.title}>{title}</span>
                <Badge
                  count={items.length}
                  style={{ backgroundColor: getBadgeColor(), fontSize: 11 }}
                />
              </div>
            </div>
          }
          key="group"
          extra={extra}
        >
          <List
            ref={listRef}
            height={listHeight}
            itemCount={items.length}
            itemSize={ITEM_HEIGHT}
            itemData={itemData}
            overscanCount={OVERSCAN_COUNT}
            width="100%"
          >
            {VirtualRow}
          </List>
        </Panel>
      </Collapse>
    </div>
  );
});

// ==================== 主组件 ====================

/**
 * VirtualTransferList - 虚拟列表传输列表主组件
 * 【P0修复】
 * 1. 移除外层滚动容器，避免双重滚动冲突
 * 2. 回调函数使用 useCallback 缓存
 * 3. 添加错误边界
 */
const VirtualTransferList = ({
  uploadingItems = [],
  completedItems = [],
  errorItems = [],
  uploadSpeed = {},
  onPause,
  onResume,
  onCancel,
  onRemove,
  onPauseAll,
  onResumeAll,
  onClearCompleted,
  onClearErrors,
}) => {
  // 【P0关键修复】使用 useMemo 缓存分组结果，避免每次渲染重新计算
  const { activeItems, pausedItems } = useMemo(() => ({
    activeItems: uploadingItems.filter(
      item => ['waiting', 'calculating', 'uploading', 'merging'].includes(item.status)
    ),
    pausedItems: uploadingItems.filter(
      item => item.status === 'paused'
    ),
  }), [uploadingItems]);

  // 【关键修复】回调函数使用 useCallback 缓存
  const handlePauseAll = useCallback((e) => {
    if (e) e.stopPropagation();
    if (onPauseAll) onPauseAll();
  }, [onPauseAll]);

  const handleResumeAll = useCallback((e) => {
    if (e) e.stopPropagation();
    if (onResumeAll) onResumeAll();
  }, [onResumeAll]);

  const handleClearErrors = useCallback((e) => {
    if (e) e.stopPropagation();
    if (onClearErrors) onClearErrors();
  }, [onClearErrors]);

  const handleClearCompleted = useCallback((e) => {
    if (e) e.stopPropagation();
    if (onClearCompleted) onClearCompleted();
  }, [onClearCompleted]);

  // 空状态
  const isEmpty = uploadingItems.length === 0 && completedItems.length === 0 && errorItems.length === 0;
  if (isEmpty) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="暂无传输任务"
        style={{ padding: '60px 0' }}
      />
    );
  }

  return (
    <ErrorBoundary>
      {/* 【P0关键修复】移除外层 overflowY: auto，由 react-window 内部处理滚动 */}
      <div className={styles.virtualTransferList}>
        {/* 正在传输 */}
        {activeItems.length > 0 && (
          <VirtualGroup
            groupKey="active"
            title="正在传输"
            icon={<LoadingOutlined style={{ color: '#1890ff', fontSize: 16 }} />}
            items={activeItems}
            uploadSpeed={uploadSpeed}
            onPause={onPause}
            onResume={onResume}
            onCancel={onCancel}
            onRemove={onRemove}
            extra={
              <Tooltip title="全部暂停">
                <Button
                  type="primary"
                  ghost
                  size="small"
                  icon={<PauseCircleOutlined />}
                  onClick={handlePauseAll}
                  style={{ fontSize: 12, borderRadius: 4 }}
                >
                  全部暂停
                </Button>
              </Tooltip>
            }
          />
        )}

        {/* 已暂停 */}
        {pausedItems.length > 0 && (
          <VirtualGroup
            groupKey="paused"
            title="已暂停"
            icon={<PauseCircleOutlined style={{ color: '#faad14', fontSize: 16 }} />}
            items={pausedItems}
            uploadSpeed={uploadSpeed}
            onPause={onPause}
            onResume={onResume}
            onCancel={onCancel}
            onRemove={onRemove}
            extra={
              <Button
                type="primary"
                ghost
                size="small"
                icon={<PlayCircleOutlined />}
                onClick={handleResumeAll}
                style={{ fontSize: 12, borderRadius: 4, borderColor: '#faad14', color: '#faad14' }}
              >
                全部开始
              </Button>
            }
          />
        )}

        {/* 传输失败 */}
        {errorItems.length > 0 && (
          <VirtualGroup
            groupKey="error"
            title="传输失败"
            icon={<CloseCircleFilled style={{ color: '#ff4d4f', fontSize: 16 }} />}
            items={errorItems}
            uploadSpeed={uploadSpeed}
            onPause={onPause}
            onResume={onResume}
            onCancel={onCancel}
            onRemove={onRemove}
            defaultExpanded={true}
            extra={
              <Tooltip title="清空失败任务">
                <Button
                  type="text"
                  size="small"
                  icon={<ClearOutlined />}
                  onClick={handleClearErrors}
                  style={{ fontSize: 12, color: '#8c8c8c' }}
                >
                  清空
                </Button>
              </Tooltip>
            }
          />
        )}

        {/* 已完成 */}
        {completedItems.length > 0 && (
          <VirtualGroup
            groupKey="completed"
            title="已完成"
            icon={<CheckCircleFilled style={{ color: '#52c41a', fontSize: 16 }} />}
            items={completedItems}
            uploadSpeed={uploadSpeed}
            onPause={onPause}
            onResume={onResume}
            onCancel={onCancel}
            onRemove={onRemove}
            defaultExpanded={false}
            extra={
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
            }
          />
        )}
      </div>
    </ErrorBoundary>
  );
};

export default observer(VirtualTransferList);
