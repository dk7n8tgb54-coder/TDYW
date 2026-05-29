/**
 * 右键菜单管理 Hook
 * 【任务4.2】从Explorer组件拆分出来的独立Hook
 * 职责：管理右键菜单的显示、定位和菜单项生成
 */
import { useState, useCallback } from 'react';

// 菜单图标映射
const ICON_MAP = {
  open: '📂',
  download: '⬇️',
  copy: '📋',
  cut: '✂️',
  rename: '✏️',
  delete: '🗑️',
  preview: '👁️',
  newFolder: '📁',
};

/**
 * 获取菜单图标
 * @param {string} key - 菜单项key
 * @returns {string} 图标符号
 */
export const getMenuIcon = (key) => ICON_MAP[key] || '';

/**
 * 右键菜单Hook
 * @returns {Object} 右键菜单状态和操作
 */
export const useContextMenu = () => {
  const [contextMenu, setContextMenu] = useState({
    visible: false,
    position: null,
    items: [],
  });

  /**
   * 显示右键菜单
   * @param {Event} e - 鼠标事件
   * @param {Array} menuItems - 菜单项配置
   */
  const showContextMenu = useCallback((e, menuItems) => {
    if (!e || !e.preventDefault) return;

    e.preventDefault();
    e.stopPropagation();

    let x = e.clientX;
    let y = e.clientY;
    const estimatedWidth = 180;
    const estimatedHeight = Math.max(menuItems.length * 36 + 8, 100);

    // 边界检测
    if (x + estimatedWidth > window.innerWidth) {
      x = window.innerWidth - estimatedWidth - 10;
    }
    if (y + estimatedHeight > window.innerHeight) {
      y = window.innerHeight - estimatedHeight - 10;
    }

    setContextMenu({
      visible: true,
      position: { x, y },
      items: menuItems,
    });
  }, []);

  /**
   * 关闭右键菜单
   */
  const closeContextMenu = useCallback(() => {
    setContextMenu({ visible: false, position: null, items: [] });
  }, []);

  /**
   * 创建空白区域菜单项
   * @param {Function} onNewFolder - 新建文件夹回调
   * @returns {Array} 菜单项
   */
  const createEmptyAreaMenu = useCallback((onNewFolder) => {
    return [
      {
        key: 'newFolder',
        label: '新建文件夹',
        icon: getMenuIcon('newFolder'),
        onClick: onNewFolder,
      },
    ];
  }, []);

  /**
   * 创建单选菜单项
   * @param {Object} record - 当前记录
   * @param {Object} options - 配置选项
   * @returns {Array} 菜单项
   */
  const createSingleSelectMenu = useCallback((record, options) => {
    const {
      canEdit,
      isPublic,
      onOpen,
      onDownload,
      onCopy,
      onCut,
      onRename,
      onDelete,
    } = options;

    const baseItems = record.isFolder
      ? [
          { key: 'open', label: '打开', icon: getMenuIcon('open'), onClick: onOpen },
          { key: 'download', label: '下载', icon: getMenuIcon('download'), onClick: onDownload },
        ]
      : [
          { key: 'open', label: '打开', icon: getMenuIcon('open'), onClick: onOpen },
          { key: 'download', label: '下载', icon: getMenuIcon('download'), onClick: onDownload },
        ];

    const editItems = canEdit
      ? [
          { key: 'copy', label: '复制', icon: getMenuIcon('copy'), onClick: onCopy },
          { key: 'cut', label: '移动', icon: getMenuIcon('cut'), onClick: onCut },
          { key: 'rename', label: '重命名', icon: getMenuIcon('rename'), onClick: onRename },
          { key: 'delete', label: '删除', icon: getMenuIcon('delete'), onClick: onDelete },
        ]
      : [];

    return [...baseItems, ...editItems];
  }, []);

  /**
   * 创建多选菜单项
   * @param {number} selectedCount - 选中数量
   * @param {Object} options - 配置选项
   * @returns {Array} 菜单项
   */
  const createMultiSelectMenu = useCallback((selectedCount, options) => {
    const { canEdit, onBatchDownload, onBatchCopy, onBatchCut, onBatchDelete } = options;

    const items = [
      {
        key: 'download',
        label: `批量下载 (${selectedCount}项)`,
        icon: getMenuIcon('download'),
        onClick: onBatchDownload,
      },
    ];

    if (canEdit) {
      items.push(
        { key: 'copy', label: `批量复制 (${selectedCount}项)`, icon: getMenuIcon('copy'), onClick: onBatchCopy },
        { key: 'cut', label: `批量移动 (${selectedCount}项)`, icon: getMenuIcon('cut'), onClick: onBatchCut },
        { key: 'delete', label: `批量删除 (${selectedCount}项)`, icon: getMenuIcon('delete'), onClick: onBatchDelete }
      );
    }

    return items;
  }, []);

  return {
    contextMenu,
    showContextMenu,
    closeContextMenu,
    createEmptyAreaMenu,
    createSingleSelectMenu,
    createMultiSelectMenu,
    getMenuIcon,
  };
};

export default useContextMenu;
