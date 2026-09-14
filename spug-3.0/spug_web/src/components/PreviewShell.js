/**
 * 统一预览外壳 PreviewShell
 *
 * 只负责 Modal 外壳、尺寸与最大化交互；文件加载、类型判断和错误处理由调用方完成。
 *
 * 尺寸规则：
 * - 桌面默认大窗：96vw 宽、上下各约 14px 安全间距、正文占满标题栏之外的可用视口。
 * - 点击标题栏“铺满视口”图标进入 CSS 视口级全屏（100vw × 100dvh，vh 兜底），
 *   不调用浏览器 Fullscreen API；再次点击还原为默认大窗。
 * - 窄屏（<768px）自动采用全屏布局。
 *
 * 不变量：
 * - 切换铺满/还原只改外壳样式，不重挂载 children（iframe 不刷新、阅读位置不丢）。
 * - 关闭后重置最大化状态；Blob URL 等资源清理仍由调用方负责。
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Button, Modal, Tooltip } from 'antd';
import {
  CloseOutlined,
  FullscreenExitOutlined,
  FullscreenOutlined,
} from '@ant-design/icons';
import styles from './PreviewShell.module.less';

const NARROW_VIEWPORT_BREAKPOINT = 768;
// 上下安全间距与 PreviewShell.module.less 中的标题栏高度保持一致
const DEFAULT_TOP_GAP = 14;

function useNarrowViewport() {
  const [isNarrow, setIsNarrow] = useState(
    () => typeof window !== 'undefined' && window.innerWidth < NARROW_VIEWPORT_BREAKPOINT
  );

  useEffect(() => {
    const handleResize = () => setIsNarrow(window.innerWidth < NARROW_VIEWPORT_BREAKPOINT);
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  return isNarrow;
}

export default function PreviewShell({
  visible,
  fileName,
  onClose,
  children,
  destroyOnClose = true,
  maskClosable = true,
}) {
  const [maximized, setMaximized] = useState(false);
  const isNarrow = useNarrowViewport();
  // 窄屏强制铺满；手动最大化只作用于桌面尺寸
  const fullscreen = maximized || isNarrow;

  // 关闭后重置最大化状态，下次打开回到默认大窗
  useEffect(() => {
    if (!visible) setMaximized(false);
  }, [visible]);

  const toggleMaximize = useCallback(() => setMaximized(prev => !prev), []);

  const handleAfterClose = useCallback(() => {
    if (document.activeElement instanceof HTMLElement) {
      document.activeElement.blur();
    }
  }, []);

  const titleBar = (
    <div className={styles.titleBar}>
      <span className={styles.titleText} title={fileName}>{fileName || '预览'}</span>
      <span className={styles.titleActions}>
        <Tooltip title={fullscreen ? '还原' : '铺满视口'}>
          <Button
            type="text"
            size="small"
            className={styles.iconBtn}
            aria-label={fullscreen ? '还原' : '铺满视口'}
            icon={fullscreen ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
            onClick={toggleMaximize}
          />
        </Tooltip>
        <Tooltip title="关闭">
          <Button
            type="text"
            size="small"
            className={styles.iconBtn}
            aria-label="关闭"
            icon={<CloseOutlined />}
            onClick={onClose}
          />
        </Tooltip>
      </span>
    </div>
  );

  // 正文高度 = 视口 - 顶距 - 标题栏（- 底距），见 PreviewShell.module.less；
  // Esc 关闭由 Modal keyboard 默认开启
  return (
    <Modal
      visible={visible}
      onCancel={onClose}
      title={titleBar}
      footer={null}
      closable={false}
      keyboard
      maskClosable={maskClosable}
      destroyOnClose={destroyOnClose}
      width={fullscreen ? '100vw' : '96vw'}
      style={{ top: fullscreen ? 0 : DEFAULT_TOP_GAP, paddingBottom: 0 }}
      className={`${styles.modal} ${fullscreen ? styles.modalMax : ''}`}
      afterClose={handleAfterClose}
    >
      {children}
    </Modal>
  );
}
