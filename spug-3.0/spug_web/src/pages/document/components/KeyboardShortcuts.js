/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 *
 * KeyboardShortcuts - 键盘快捷键
 *
 * 快捷键：
 *   - Ctrl+Shift+U : 打开/关闭抽屉（toggle）
 *   - Ctrl+Shift+P : 全部暂停
 *   - Ctrl+Shift+R : 全部开始/继续
 *   - Ctrl+Shift+C : 清空已完成
 *   - ? / Shift+/  : 显示/隐藏快捷键帮助
 *
 * 设计：
 *   - 输入框（input/textarea/contenteditable）聚焦时不响应
 *   - 命令风格匹配，不区分大小写
 *   - 同一时间只挂一个全局监听（避免重复触发）
 *   - 组件卸载时自动解绑
 */
import React, { useEffect, useState, useCallback } from 'react';
import { Modal, Tag } from 'antd';
import { KeyOutlined } from '@ant-design/icons';
import { uploadCoreStore } from '../stores';
import uploadUIStore from '../stores/upload/ui';

/**
 * 快捷键定义
 * key 字段匹配格式: ctrl+shift+字母（小写）
 */
const SHORTCUTS = [
  { key: 'ctrl+shift+u', label: '打开/关闭抽屉', action: 'toggleDrawer' },
  { key: 'ctrl+shift+p', label: '全部暂停', action: 'pauseAll' },
  { key: 'ctrl+shift+r', label: '全部开始/继续', action: 'resumeAll' },
  { key: 'ctrl+shift+c', label: '清空已完成', action: 'clearCompleted' },
  { key: 'shift+/', label: '显示快捷键帮助', action: 'showHelp' },
];

/**
 * 判断当前焦点是否在输入控件
 */
function isInEditableElement() {
  const el = document.activeElement;
  if (!el) return false;
  const tag = el.tagName?.toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return true;
  if (el.isContentEditable) return true;
  return false;
}

/**
 * 将键盘事件序列化为快捷键字符串
 */
function eventToShortcut(e) {
  const parts = [];
  if (e.ctrlKey || e.metaKey) parts.push('ctrl');
  if (e.shiftKey) parts.push('shift');
  if (e.altKey) parts.push('alt');

  // 提取主键
  let mainKey = '';
  if (e.key && e.key.length === 1) {
    mainKey = e.key.toLowerCase();
  } else if (e.key === '?') {
    mainKey = '/'; // Shift+/ 在某些键盘上产生 ?
  } else {
    // 忽略单独修饰键
    if (['Control', 'Shift', 'Alt', 'Meta'].includes(e.key)) return null;
    mainKey = e.key.toLowerCase();
  }
  if (mainKey) parts.push(mainKey);
  return parts.join('+');
}

export { SHORTCUTS };

/**
 * KeyboardShortcuts 组件
 * 挂载后启用全局快捷键
 */
const KeyboardShortcuts = () => {
  const [helpVisible, setHelpVisible] = useState(false);

  /**
   * 执行快捷键动作
   */
  const runAction = useCallback((action) => {
    switch (action) {
      case 'toggleDrawer':
        uploadUIStore.panel.toggle();
        break;
      case 'pauseAll':
        if (uploadCoreStore.activeCount > 0) {
          uploadCoreStore.pauseAll();
        }
        break;
      case 'resumeAll':
        if (uploadCoreStore.pausedCount > 0 || uploadCoreStore.waitingCount > 0) {
          uploadCoreStore.resumeAll();
        }
        break;
      case 'clearCompleted':
        if (uploadCoreStore.completedItems.length > 0) {
          // 复用 UploadPanel 的清空逻辑（通过 store 的 action 触发）
          // 这里直接调用 batchDeleteTransfers 和 removeFromQueue
          const completed = uploadCoreStore.completedItems;
          const transferIds = completed.map((i) => i.transferId).filter((id) => id);
          if (transferIds.length > 0) {
            uploadCoreStore.transferStore.batchDeleteTransfers(transferIds).catch(() => {});
          }
          const tenantId = uploadCoreStore.getCurrentTenantId?.() || 'default';
          completed.forEach((item) => {
            uploadCoreStore.queueStore.removeFromQueue(item.id, tenantId);
          });
        }
        break;
      case 'showHelp':
        setHelpVisible((v) => !v);
        break;
      default:
        break;
    }
  }, []);

  /**
   * 全局键盘事件监听
   */
  useEffect(() => {
    const handler = (e) => {
      // 输入控件聚焦时不响应
      if (isInEditableElement()) return;

      const shortcut = eventToShortcut(e);
      if (!shortcut) return;

      // 查找匹配
      const matched = SHORTCUTS.find((s) => s.key === shortcut);
      if (!matched) return;

      // 阻止浏览器默认行为（如 Ctrl+Shift+U 在某些浏览器触发 view source）
      e.preventDefault();
      e.stopPropagation();

      runAction(matched.action);
    };

    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [runAction]);

  return (
    <Modal
      title={
        <span>
          <KeyOutlined style={{ marginRight: 8 }} />
          键盘快捷键
        </span>
      }
      open={helpVisible}
      onCancel={() => setHelpVisible(false)}
      footer={null}
      width={480}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {SHORTCUTS.map((s) => (
          <div
            key={s.key}
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              padding: '8px 12px',
              background: '#fafafa',
              borderRadius: 4,
            }}
          >
            <span style={{ fontSize: 13, color: '#262626' }}>{s.label}</span>
            <span>
              {s.key.split('+').map((k, i, arr) => (
                <React.Fragment key={i}>
                  <Tag
                    color="blue"
                    style={{
                      fontFamily: 'monospace',
                      fontSize: 12,
                      margin: 0,
                      padding: '2px 8px',
                    }}
                  >
                    {k === 'ctrl' ? 'Ctrl' : k === 'shift' ? 'Shift' : k === 'alt' ? 'Alt' : k.toUpperCase()}
                  </Tag>
                  {i < arr.length - 1 && <span style={{ margin: '0 4px', color: '#8c8c8c' }}>+</span>}
                </React.Fragment>
              ))}
            </span>
          </div>
        ))}
        <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 8, padding: '0 12px' }}>
          提示：在输入框中输入时快捷键自动失效
        </div>
      </div>
    </Modal>
  );
};

export default KeyboardShortcuts;
