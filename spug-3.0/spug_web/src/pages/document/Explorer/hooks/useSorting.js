/**
 * 表格排序 Hook
 * 【任务4.2】从Explorer组件拆分出来的独立Hook
 * 职责：处理表格数据的排序逻辑
 */
import { useMemo, useCallback } from 'react';
import { naturalCompare } from '../../utils/naturalSort';

/**
 * 默认排序：名称升序（档案管理型定位）
 * 与后端列表接口 order_by('name'/'display_name', 'id') 保持一致
 */
export const DEFAULT_SORT_ORDER = { columnKey: 'name', order: 'ascend' };

/**
 * 排序比较函数
 * @param {*} a - 值A
 * @param {*} b - 值B
 * @param {string} order - 排序方向
 * @returns {number} 比较结果
 */
const compareValues = (a, b, order) => {
  if (a == null) a = '';
  if (b == null) b = '';

  // 字符串比较（自然排序，数字按数值比较："2" < "11"；与文件夹树共用 naturalCompare）
  if (typeof a === 'string' && typeof b === 'string') {
    return order === 'ascend' ? naturalCompare(a, b) : naturalCompare(b, a);
  }

  // 数字比较
  if (typeof a === 'number' && typeof b === 'number') {
    return order === 'ascend' ? a - b : b - a;
  }

  // 日期比较
  if (a instanceof Date && b instanceof Date) {
    return order === 'ascend'
      ? a.getTime() - b.getTime()
      : b.getTime() - a.getTime();
  }

  return 0;
};

/**
 * 处理文件夹优先的排序
 * @param {Object} a - 项A
 * @param {Object} b - 项B
 * @param {string} columnKey - 排序列
 * @param {string} order - 排序方向
 * @returns {number} 比较结果
 */
const compareWithFolderPriority = (a, b, columnKey, order) => {
  // 文件夹恒排在文件之前（档案管理型惯例，与后端"文件夹在前、文件在后"分页分组一致，
  // 不随排序方向变化——Windows/OneDrive/百度网盘均为文件夹恒置顶）
  if (a.isFolder !== b.isFolder) {
    return a.isFolder ? -1 : 1;
  }

  // 获取比较值
  let aValue = a[columnKey];
  let bValue = b[columnKey];

  // 名称列使用display_name
  if (columnKey === 'name') {
    aValue = a.display_name || a.name;
    bValue = b.display_name || b.name;
  }

  // 日期列转为时间戳
  if (columnKey === 'created_at') {
    aValue = new Date(aValue).getTime();
    bValue = new Date(bValue).getTime();
  }

  return compareValues(aValue, bValue, order);
};

/**
 * 排序Hook
 * @param {Array} items - 原始数据
 * @param {Object} sortOrder - 排序配置 { columnKey, order }
 * @param {boolean} creatingFolder - 是否正在创建文件夹
 * @returns {Array} 排序后的数据
 */
export const useSorting = (items, sortOrder, creatingFolder = false) => {
  return useMemo(() => {
    let data = [...(items || [])];

    const { columnKey, order } = sortOrder || {};

    // 执行排序
    if (columnKey && order) {
      data.sort((a, b) => compareWithFolderPriority(a, b, columnKey, order));
    }

    // 如果正在创建文件夹，在第一行插入临时项
    if (creatingFolder) {
      data.unshift({
        key: 'temp-new-folder',
        id: null,
        name: '',
        display_name: '',
        isFolder: true,
        isTemp: true,
      });
    }

    return data;
  }, [items, sortOrder, creatingFolder]);
};

/**
 * 表格变化处理Hook
 * @param {Function} onSortChange - 排序变化回调
 * @returns {Object} 表格事件处理函数
 */
export const useTableHandlers = (onSortChange) => {
  const handleTableChange = useCallback(
    (_pagination, _filters, sorter) => {
      if (sorter?.columnKey) {
        onSortChange({
          columnKey: sorter.columnKey,
          order: sorter.order,
        });
      } else {
        onSortChange({ columnKey: null, order: null });
      }
    },
    [onSortChange]
  );

  return { handleTableChange };
};

export default useSorting;
