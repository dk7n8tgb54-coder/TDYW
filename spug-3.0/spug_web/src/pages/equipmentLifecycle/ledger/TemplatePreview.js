/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 台账模板实时预览（只读矩阵）：有效检查对象（行）× 有效检查项目（列）。
 * - 行来自模板行结构树：过滤停用节点及其子树（停用不参与台账生成），
 *   检查对象（check）为生成填写行的行叶子，与真实矩阵台账口径一致；
 * - 列来自检查项目（未命名项目显示占位）；
 * - 复用 MatrixEditor 只读形态：交叉格不渲染填写控件，与最终生成的表格
 *   结构相同（行层级独立列 + 每个检查项目一列），层级列头显示模板
 *   row_headers 行层级表头名称（未配置的层级显示"第N级"）；
 * - 全部由 props 派生，检查对象/检查项目/层级表头变化后立即更新。
 */
import React from 'react';
import {Empty} from 'antd';
import MatrixEditor from './MatrixEditor';

/** 过滤停用节点及其整个子树。 */
export function pruneInactiveNodes(nodes) {
  return (nodes || [])
    .filter(node => node.is_active !== false)
    .map(node => ({...node, children: pruneInactiveNodes(node.children || [])}));
}

/** 标注生成填写行的行叶子（检查对象），空名称补占位便于预览辨认。 */
export function markCellLeafRows(nodes) {
  return (nodes || []).map(node => ({
    ...node,
    name: String(node.name || '').trim() || '未命名',
    isCellLeaf: node.node_type === 'check',
    children: markCellLeafRows(node.children || []),
  }));
}

export default function TemplatePreview({rows, items, rowHeaders}) {
  const activeRows = markCellLeafRows(pruneInactiveNodes(rows));
  const columns = (items || [])
    .filter(it => it.is_active !== false)
    .map(it => ({
      id: it.id || it.key,
      name: String(it.name || '').trim() || '未命名项目',
      input_type: it.input_type,
      unit: it.unit,
      choices: it.choices,
    }));
  if (!activeRows.length) {
    return <Empty description="暂无检查对象：添加后此处预览表格的行"/>;
  }
  if (!columns.length) {
    return <Empty description="暂无检查项目：添加后此处预览表格的列"/>;
  }
  return (
    <MatrixEditor
      columns={columns}
      rows={activeRows}
      readOnly
      getCell={() => null}
      levelColumnWidth={120}
      levelHeaders={rowHeaders}
    />
  );
}
