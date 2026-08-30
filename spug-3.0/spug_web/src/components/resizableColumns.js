/**
 * TableCard 列宽拖动公共能力。
 *
 * useResizableColumns(tKey, columns, options) 返回：
 * - resizableColumns: 应用持久化宽度并挂载 onHeaderCell 的列配置
 * - components: 传给 antd Table 的 {header: {cell}} 定制，未启用时为 undefined
 * - resetAllWidths: 恢复当前表格全部列宽
 *
 * 宽度保存在会话内存中（window 上的存储对象，按 tKey 分桶）：
 * SPA 站内路由切换期间保留，整页刷新 / 关闭标签页随 JS 上下文销毁，
 * 列宽随之还原页面默认值；不写 localStorage、不经过后端。
 * 仅 width 为数字、title 为字符串且未声明 fixed 的列参与拖动；
 * 固定列（如行内操作列）右缘没有可扩展空间，整体退出拖拽体系，
 * 宽度保持页面定义。
 * 重置手势统一为双击拖拽柄（表头双击留给排序等表格自身交互）。
 */
import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import styles from './index.module.less';

const DEFAULT_MIN_WIDTH = 60;

// 会话内宽度存储：挂在 window 上（而非模块变量）——生命周期与 JS 上下文一致，
// 站内切页保留、整页刷新即清空；便于测试中直接清理，热更新后也不丢状态。
const sessionStore = () => {
  if (!window.__sessionTableColWidths) window.__sessionTableColWidths = {};
  return window.__sessionTableColWidths;
};

export function ResizableHeaderCell(props) {
  const {width, minWidth, onResize, onResizeEnd, onReset, ...restProps} = props;
  if (!width || !onResize) {
    return <th {...restProps}/>;
  }

  function handleMouseDown(e) {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    const startX = e.clientX;
    const startWidth = width;
    let lastWidth = startWidth;
    let moved = false;

    const prevUserSelect = document.body.style.userSelect;
    const prevCursor = document.body.style.cursor;
    document.body.style.userSelect = 'none';
    document.body.style.cursor = 'col-resize';

    function onMouseMove(moveEvent) {
      const next = Math.max(minWidth, Math.round(startWidth + moveEvent.clientX - startX));
      if (next !== lastWidth) {
        lastWidth = next;
        moved = true;
        onResize(next);
      }
    }

    function onMouseUp() {
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
      document.body.style.userSelect = prevUserSelect;
      document.body.style.cursor = prevCursor;
      if (moved && onResizeEnd) onResizeEnd();
    }

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  }

  return (
    <th {...restProps} className={`${restProps.className || ''} ${styles.resizableHeaderCell}`}>
      {restProps.children}
      <span
        className={styles.resizableHandle}
        title="拖动调整列宽，双击恢复默认宽度"
        onMouseDown={handleMouseDown}
        onClick={e => e.stopPropagation()}
        onDoubleClick={e => {
          e.preventDefault();
          e.stopPropagation();
          if (onReset) onReset();
        }}/>
    </th>
  );
}

export function useResizableColumns(tKey, columns, options = {}) {
  const {enabled = true, defaultMinWidth = DEFAULT_MIN_WIDTH} = options;
  const active = enabled && !!tKey;
  const [widths, setWidths] = useState(() => (active ? sessionStore()[tKey] || {} : {}));
  const widthsRef = useRef(widths);
  widthsRef.current = widths;

  useEffect(() => {
    setWidths(active ? sessionStore()[tKey] || {} : {});
  }, [tKey, active]);

  const resizableColumns = useMemo(() => {
    if (!active) return columns;
    return columns.map(col => {
      if (typeof col.width !== 'number' || typeof col.title !== 'string' || col.fixed) return col;
      const title = col.title;
      const width = widths[title] != null ? widths[title] : col.width;
      const minWidth = Math.max(col.minWidth || defaultMinWidth, DEFAULT_MIN_WIDTH);
      const originalOnHeaderCell = col.onHeaderCell;
      return {
        ...col,
        width,
        onHeaderCell: column => ({
          ...(originalOnHeaderCell ? originalOnHeaderCell(column) : {}),
          width,
          minWidth,
          onResize: next => setWidths(prev => ({...prev, [title]: next})),
          onResizeEnd: () => {
            if (tKey) sessionStore()[tKey] = {...widthsRef.current};
          },
          onReset: () => {
            const updated = {...widthsRef.current};
            delete updated[title];
            widthsRef.current = updated;
            setWidths(updated);
            if (tKey) sessionStore()[tKey] = updated;
          },
        }),
      };
    });
  }, [active, columns, widths, tKey, defaultMinWidth]);

  const resetAllWidths = useCallback(() => {
    widthsRef.current = {};
    setWidths({});
    if (tKey) sessionStore()[tKey] = {};
  }, [tKey]);

  return {
    resizableColumns,
    components: active ? {header: {cell: ResizableHeaderCell}} : undefined,
    resetAllWidths,
  };
}
