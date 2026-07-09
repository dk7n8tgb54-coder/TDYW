/**
 * 右键菜单管理 Hook
 * 【任务4.2】从Explorer组件拆分出来的独立Hook
 * 职责：管理右键菜单的显示、定位和菜单项生成
 */
import React, { useState, useCallback } from 'react';
import { MenuIcons } from '../../components/FileTypeIcon';

// 菜单图标映射（SVG 图标组件）
const ICON_MAP = {
  open: <MenuIcons.open />,
  download: <MenuIcons.download />,
  copy: <MenuIcons.copy />,
  cut: <MenuIcons.cut />,
  rename: <MenuIcons.rename />,
  delete: <MenuIcons.delete />,
  preview: <MenuIcons.preview />,
  properties: <MenuIcons.properties />,
  newFolder: <MenuIcons.newFolder />,
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
      perms = {},
      onOpen,
      onDownload,
      onCopy,
      onCut,
      onRename,
      onDelete,
      onProperties,
    } = options;

    // 下载按 perms.download 控制（未传则默认允许，兼容普通模式）
    const allowDownload = perms.download !== false;
    const allowCopy = canEdit && perms.copy !== false;
    const allowMove = canEdit && perms.move !== false;
    const allowRename = canEdit && perms.rename !== false;
    const allowDelete = canEdit && perms.delete !== false;

    const baseItems = record.isFolder
      ? [
          { key: 'open', label: '打开', icon: getMenuIcon('open'), onClick: onOpen },
          ...(allowDownload ? [{ key: 'download', label: '下载', icon: getMenuIcon('download'), onClick: onDownload }] : []),
        ]
      : [
          { key: 'open', label: '打开', icon: getMenuIcon('open'), onClick: onOpen },
          ...(allowDownload ? [{ key: 'download', label: '下载', icon: getMenuIcon('download'), onClick: onDownload }] : []),
        ];

    const editItems = [];
    if (allowCopy) editItems.push({ key: 'copy', label: '复制', icon: getMenuIcon('copy'), onClick: onCopy });
    if (allowMove) editItems.push({ key: 'cut', label: '移动', icon: getMenuIcon('cut'), onClick: onCut });
    if (allowRename) editItems.push({ key: 'rename', label: '重命名', icon: getMenuIcon('rename'), onClick: onRename });
    if (allowDelete) editItems.push({ key: 'delete', label: '删除', icon: getMenuIcon('delete'), onClick: onDelete });

    const propertyItem = [
      { key: 'properties', label: '属性', icon: getMenuIcon('properties'), onClick: onProperties },
    ];

    return [...baseItems, ...editItems, ...propertyItem];
  }, []);

  /**
   * 创建多选菜单项
   * @param {number} selectedCount - 选中数量
   * @param {Object} options - 配置选项
   * @returns {Array} 菜单项
   */
  const createMultiSelectMenu = useCallback((selectedCount, options) => {
    const { canEdit, perms = {}, onBatchDownload, onBatchCopy, onBatchCut, onBatchDelete } = options;

    const allowDownload = perms.download !== false;
    const items = [];

    if (allowDownload) {
      items.push({
        key: 'download',
        label: `批量下载 (${selectedCount}项)`,
        icon: getMenuIcon('download'),
        onClick: onBatchDownload,
      });
    }

    if (canEdit) {
      if (perms.copy !== false) items.push({ key: 'copy', label: `批量复制 (${selectedCount}项)`, icon: getMenuIcon('copy'), onClick: onBatchCopy });
      if (perms.move !== false) items.push({ key: 'cut', label: `批量移动 (${selectedCount}项)`, icon: getMenuIcon('cut'), onClick: onBatchCut });
      if (perms.delete !== false) items.push({ key: 'delete', label: `批量删除 (${selectedCount}项)`, icon: getMenuIcon('delete'), onClick: onBatchDelete });
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
