/**
 * DocumentDropUploadLayer - 资料库拖拽上传投放层
 *
 * 职责（单一）：
 *   1. 在 .explorerArea 上监听 dragenter/dragleave/dragover/drop 事件
 *   2. 拖拽深度计数，避免子元素间移动闪烁
 *   3. 只在 dataTransfer.types 包含 Files 时显示遮罩（过滤页面内 DOM 拖动）
 *   4. drop 时调用 onDrop 回调，把收集结果交给 uploadCoreStore
 *   5. 禁用场景提示（无权限/搜索中/党建未就绪）
 *   6. 阻止浏览器默认打开文件行为
 *
 * 不负责：
 *   - 上传请求（由 uploadCoreStore 处理）
 *   - 队列状态（由 queueStore 处理）
 *   - 目录递归解析（由 dropUpload.js 处理）
 *   - 目标上下文捕获（由 uploadCoreStore.captureUploadTargetContext 处理）
 *
 * 复用原则：
 *   - 拖拽任务和按钮选择任务进入同一套 uploadCoreStore
 *   - 不新增第二个上传队列或传输列表
 *   - 状态只展示在现有 MiniBar / UploadPanel
 */
import React from 'react';
import { InboxOutlined, FolderOpenOutlined, LockOutlined, SearchOutlined } from '@ant-design/icons';
import { collectDroppedItems, hasFilesType, isEmptyFolderBatch, isPlainFilesOnly } from '../utils/dropUpload';
import { formatMaxFileSizeDisplay } from '../utils/upload-utils';
import styles from './DocumentDropUploadLayer.module.less';

/**
 * @param {Object} props
 * @param {boolean} props.canUpload - 是否有上传权限
 * @param {boolean} props.isPartyBuildingDocuments - 是否党建工作模式
 * @param {boolean} props.isPartyBuildingDocumentsReady - 党建工作是否初始化完成
 * @param {boolean} props.isSearching - 是否处于搜索结果模式
 * @param {string} props.targetPathLabel - 当前目标目录显示文本（如 "我的文件 / 子目录" 或 "党建工作 / 子目录"）
 * @param {Function} props.captureTargetContext - 调用 uploadCoreStore.captureUploadTargetContext 捕获不可变上下文
 * @param {Function} props.onDrop - drop 回调 (collected, targetContext) => void
 * @param {React.ReactNode} props.children - 包裹的 Explorer 组件
 */
function DocumentDropUploadLayer({
  canUpload = true,
  isPartyBuildingDocuments = false,
  isPartyBuildingDocumentsReady = true,
  isSearching = false,
  targetPathLabel = '',
  captureTargetContext,
  onDrop,
  children,
}) {
  // 拖拽深度计数：dragenter +1，dragleave -1，>0 时显示遮罩
  // 用 ref 避免子元素间移动导致闪烁（子元素 enter/leave 配对，计数最终正确）
  const dragDepthRef = React.useRef(0);
  const [isDragOver, setIsDragOver] = React.useState(false);
  // 防止 drop 事件因冒泡或重复监听触发多次入队
  const dropHandledRef = React.useRef(false);

  // 禁用原因（优先级：无权限 > 搜索中 > 党建未就绪）
  const getDisabledReason = () => {
    if (!canUpload) return 'noPermission';
    if (isSearching) return 'searching';
    if (isPartyBuildingDocuments && !isPartyBuildingDocumentsReady) return 'partyNotReady';
    return null;
  };

  const disabledReason = getDisabledReason();

  // 是否允许投放（非禁用状态）
  const canAcceptDrop = disabledReason === null;

  // ============ 事件处理 ============

  const handleDragEnter = React.useCallback((e) => {
    // 只有 Files 类型才进入上传拖拽状态（过滤页面内 DOM 拖动/链接/文字）
    if (!hasFilesType(e.dataTransfer)) return;

    e.preventDefault(); // 阻止默认，让 drop 能触发
    dragDepthRef.current += 1;
    if (dragDepthRef.current === 1) {
      setIsDragOver(true);
    }
  }, []);

  const handleDragLeave = React.useCallback((e) => {
    if (!hasFilesType(e.dataTransfer)) return;

    e.preventDefault();
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) {
      setIsDragOver(false);
    }
  }, []);

  const handleDragOver = React.useCallback((e) => {
    // dragover 必须 preventDefault，否则 drop 事件不会触发
    if (hasFilesType(e.dataTransfer)) {
      e.preventDefault();
      // 显式设置 dropEffect，给用户视觉反馈
      e.dataTransfer.dropEffect = canAcceptDrop ? 'copy' : 'none';
    }
  }, [canAcceptDrop]);

  const handleDrop = React.useCallback(async (e) => {
    // 必须阻止默认（浏览器会打开文件），即使禁用也要阻止
    e.preventDefault();
    e.stopPropagation();

    // 深度归零，隐藏遮罩
    dragDepthRef.current = 0;
    setIsDragOver(false);

    // 防止重复入队：同一 drop 事件只处理一次
    if (dropHandledRef.current) return;
    if (!hasFilesType(e.dataTransfer)) return;

    // 禁用场景：阻止入队，原因已通过遮罩展示
    if (!canAcceptDrop) return;

    dropHandledRef.current = true;
    // 下一轮事件循环重置标志，允许后续新的 drop
    setTimeout(() => { dropHandledRef.current = false; }, 0);

    // 立即捕获不可变目标上下文（在 drop 事件同步阶段，导航状态尚未变化）
    let targetContext = null;
    if (typeof captureTargetContext === 'function') {
      try {
        targetContext = captureTargetContext();
      } catch (err) {
        // 捕获失败不应阻塞上传，uploadCoreStore 入口会兜底捕获
        targetContext = null;
      }
    }

    // 收集拖入的文件/文件夹（异步递归解析目录）
    let collected;
    try {
      collected = await collectDroppedItems(e.dataTransfer);
    } catch (err) {
      // 解析失败，不入队
      return;
    }

    if (!collected || (collected.files.length === 0 && collected.entries.length === 0)) {
      return;
    }

    // 空文件夹批次：交给 onDrop 决定是否提示（onDrop 内部会判断 isEmptyFolderBatch）
    if (typeof onDrop === 'function') {
      onDrop(collected, targetContext);
    }
  }, [canAcceptDrop, captureTargetContext, onDrop]);

  // ============ 卸载/失焦清理 ============

  React.useEffect(() => {
    const handleWindowBlur = () => {
      // 窗口失焦时拖拽可能被取消，清理遮罩
      dragDepthRef.current = 0;
      setIsDragOver(false);
    };
    window.addEventListener('blur', handleWindowBlur);
    return () => {
      window.removeEventListener('blur', handleWindowBlur);
      // 卸载时清理状态，避免内存泄漏
      dragDepthRef.current = 0;
    };
  }, []);

  // ============ 遮罩渲染 ============

  const renderMaskContent = () => {
    if (disabledReason === 'noPermission') {
      return (
        <div className={styles.maskContent}>
          <LockOutlined className={styles.maskIcon} />
          <div className={styles.maskTitle}>无上传权限</div>
          <div className={styles.maskHint}>请联系管理员开通上传权限</div>
        </div>
      );
    }
    if (disabledReason === 'searching') {
      return (
        <div className={styles.maskContent}>
          <SearchOutlined className={styles.maskIcon} />
          <div className={styles.maskTitle}>搜索结果模式下无法上传</div>
          <div className={styles.maskHint}>请退出搜索后上传</div>
        </div>
      );
    }
    if (disabledReason === 'partyNotReady') {
      return (
        <div className={styles.maskContent}>
          <FolderOpenOutlined className={styles.maskIcon} />
          <div className={styles.maskTitle}>党建工作初始化中</div>
          <div className={styles.maskHint}>请稍候再上传</div>
        </div>
      );
    }
    // 正常投放提示
    return (
      <div className={styles.maskContent}>
        <InboxOutlined className={styles.maskIcon} />
        <div className={styles.maskTitle}>
          松开鼠标，上传到{isPartyBuildingDocuments ? '党建工作' : ''}
        </div>
        <div className={styles.maskPath} title={targetPathLabel}>
          {targetPathLabel || (isPartyBuildingDocuments ? '党建工作' : '当前目录')}
        </div>
        <div className={styles.maskHint}>支持多文件和文件夹</div>
        <div className={styles.maskHint}>支持单文件最大 {formatMaxFileSizeDisplay()}</div>
      </div>
    );
  };

  return (
    <div
      className={styles.dropLayerWrapper}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {children}
      {isDragOver && (
        <div
          className={`${styles.dropMask} ${canAcceptDrop ? '' : styles.dropMaskDisabled}`}
          aria-live="polite"
        >
          {renderMaskContent()}
        </div>
      )}
    </div>
  );
}

export default React.memo(DocumentDropUploadLayer);
