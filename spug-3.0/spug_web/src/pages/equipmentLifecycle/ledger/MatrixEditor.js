/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 矩阵表格（第一阶段行对象树：行层级独立列 × 平面列项目）。
 * - 行树的每一级渲染为独立表格列（最多 ROW_MAX_LEVEL 级；树未达到的深层级
 *   列自动隐藏）；子节点显示在父节点右侧的下一列，不把完整路径放在单列中；
 * - 连续子行中的父节点使用 rowSpan 纵向合并：数据行 = 可见行叶子（行对象）
 *   + 收起的分组（收起时自成一行）；分组单元格承载展开/收起、完成进度与
 *   实例操作（新增/删除可重复分组实例）；
 * - 只有行叶子（isCellLeaf）与列项目组合的交叉格才渲染填写控件；
 * - 三种形态共用：计划态（新增台账，值存本地）/ 编辑态（草稿/退回，单元格即
 *   台账明细，带实例操作）/ 只读态（详情，渲染填写值与结果标签）；
 * - 列方向第一阶段固定平面结构：每个列项目一列，无列分组表头。
 */
import React, {useEffect, useRef, useState} from 'react';
import {Table, Input, InputNumber, Select, Tag, Tooltip, Empty} from 'antd';
import {CaretDownOutlined, CaretRightOutlined} from '@ant-design/icons';
import {
  NORMAL_ABNORMAL_CHOICES, RESULT_COLOR, RESULT_TEXT, UNSET_RESULT_TEXT,
  ROW_MAX_LEVEL,
} from './constants';
import {cellLooksAbnormal, cellValueEmpty, parseFreeValue, rowValueText} from './ledgerCommon';

const {Option} = Select;

function ResultTag({cell}) {
  if (cellValueEmpty(cell) && !cell.result) return null;
  const text = cell.result ? (RESULT_TEXT[cell.result] || cell.result) : UNSET_RESULT_TEXT;
  return <Tag color={cell.result ? RESULT_COLOR[cell.result] : 'default'} style={{marginRight: 0}}>{text}</Tag>;
}

function EditableControl({column, cell, onChange}) {
  switch (column.input_type) {
    case 'number':
      return (
        <InputNumber
          style={{width: '100%'}}
          value={cell ? cell.value_number : undefined}
          onChange={v => onChange({value_number: v})}/>
      );
    case 'choice':
      return (
        <Select
          style={{width: '100%'}} allowClear
          value={cell && cell.value_text ? cell.value_text : undefined}
          onChange={v => onChange({value_text: v || ''})}>
          {(column.choices && column.choices.length
            ? column.choices : NORMAL_ABNORMAL_CHOICES).map(c => <Option value={c} key={c}>{c}</Option>)}
        </Select>
      );
    case 'multi_choice':
      return (
        <Select
          mode="multiple" style={{width: '100%'}}
          value={cell && cell.value_text ? JSON.parse(cell.value_text || '[]') : []}
          onChange={v => onChange({value_text: JSON.stringify(v)})}>
          {(column.choices || []).map(c => <Option value={c} key={c}>{c}</Option>)}
        </Select>
      );
    case 'boolean':
      return (
        <Select
          style={{width: '100%'}} allowClear
          value={cell && cell.value_bool !== null && cell.value_bool !== undefined ? !!cell.value_bool : undefined}
          onChange={v => onChange({value_bool: v === undefined ? null : v})}>
          <Option value={true}>是</Option>
          <Option value={false}>否</Option>
        </Select>
      );
    case 'attachment':
      return <Input disabled placeholder="保存台账后通过明细附件上传" value=""/>;
    default:
      // 数字/文本：纯数字输入同步产出 value_number（与后端口径一致）
      return (
        <Input
          value={cell ? cell.value_text : ''}
          onChange={e => onChange(parseFreeValue(e.target.value))}/>
      );
  }
}

/**
 * 行树 → 可见行（先序）：展开分组的后代行叶子为数据行，收起分组自成一行；
 * 每个可见行携带 chain（祖先 {row, depth, span, remaining}），remaining === span
 * 表示该行是其某级祖先合并范围的首行（由它渲染 rowSpan=span 的合并单元格）。
 */
export function emitVisibleRows(rows, isExpanded) {
  const visibleCount = row => {
    const kids = row.children || [];
    if (!kids.length || !isExpanded(row)) return 1;
    return kids.reduce((acc, kid) => acc + visibleCount(kid), 0);
  };
  const out = [];
  const walk = (list, depth, chain) => {
    (list || []).forEach(row => {
      const kids = row.children || [];
      if (kids.length && isExpanded(row)) {
        const span = kids.reduce((acc, kid) => acc + visibleCount(kid), 0);
        walk(kids, depth + 1, [...chain, {row, depth, span, remaining: span}]);
      } else {
        out.push({row, depth, chain: chain.map(entry => ({...entry}))});
        chain.forEach(entry => { entry.remaining -= 1; });
      }
    });
  };
  walk(rows, 1, []);
  return out;
}

/** 受控展开：初始展开全部分组，后追加的分组自动展开，用户可收起。 */
function useAutoExpandedKeys(rows) {
  const parentKeys = (function collect(list, out) {
    (list || []).forEach(r => {
      if ((r.children || []).length) {
        out.push(r.key);
        collect(r.children, out);
      }
    });
    return out;
  })(rows, []);
  const [expandedKeys, setExpandedKeys] = useState(parentKeys);
  const seenKeysRef = useRef(null);
  if (seenKeysRef.current === null) {
    seenKeysRef.current = new Set(parentKeys);
  }
  useEffect(() => {
    const fresh = parentKeys.filter(k => !seenKeysRef.current.has(k));
    if (fresh.length) {
      fresh.forEach(k => seenKeysRef.current.add(k));
      setExpandedKeys(prev => Array.from(new Set([...prev, ...fresh])));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows]);
  return [expandedKeys, setExpandedKeys];
}

/** 行层级列：第 level 级一行层级列；祖先分组命中 chain 且为合并首行时 rowSpan。
 * 列头名称：renderLevelTitle 自定义（设计器内联编辑）> levelHeaders[level-1]
 * （模板行层级表头名称）> 默认"第N级"。 */
function buildLevelColumns(options) {
  const {maxDepth, levelColumnWidth, renderGroupTitle, renderLeafTitle,
    levelHeaders, renderLevelTitle} = options;
  const columns = [];
  for (let level = 1; level <= maxDepth; level += 1) {
    columns.push({
      title: renderLevelTitle
        ? renderLevelTitle(level)
        : (levelHeaders && levelHeaders[level - 1]) || `第${level}级`,
      key: `row_level_${level}`,
      width: levelColumnWidth,
      onCell: record => {
        if (record.depth === level) return {rowSpan: 1};
        const entry = record.chain.find(e => e.depth === level);
        if (entry) return {rowSpan: entry.remaining === entry.span ? entry.span : 0};
        return {rowSpan: 1};
      },
      render: (t, record) => {
        if (record.depth === level) {
          return record.row.isCellLeaf
            ? renderLeafTitle(record.row) : renderGroupTitle(record.row);
        }
        const entry = record.chain.find(e => e.depth === level);
        if (entry && entry.remaining === entry.span) return renderGroupTitle(entry.row);
        return null;
      },
    });
  }
  return columns;
}

/** 列项目数据列：仅行叶子交叉格渲染填写控件（只读态渲染值与结果标签）。
 * 列头：renderColumnTitle 自定义（设计器"点击列标题配置"）> 默认名称+单位。 */
function buildDataColumns(options) {
  const {columns, editable, getCell, onCellChange, renderCellExtra, renderColumnTitle} = options;
  return columns.map(col => ({
    title: renderColumnTitle
      ? renderColumnTitle(col)
      : (
        <Tooltip title={col.operation_guide || col.name}>
          <span>{col.name}{col.unit ? <span style={{color: '#999'}}>（{col.unit}）</span> : null}</span>
        </Tooltip>
      ),
    key: `col_${col.id}`,
    width: 150,
    render: (t, record) => {
      const row = record.row;
      if (!row.isCellLeaf) return null;
      const cell = getCell(row, col);
      if (!editable) {
        if (!cell) return null;
        return (
          <div>
            <div>{rowValueText(cell) || '-'}</div>
            <ResultTag cell={cell}/>
          </div>
        );
      }
      return (
        <div>
          <EditableControl column={col} cell={cell}
                           onChange={patch => onCellChange(row, col, patch)}/>
          {renderCellExtra ? renderCellExtra(row, col, cell) : null}
        </div>
      );
    },
  }));
}

/**
 * rows：树形行（children 嵌套），叶子行 isCellLeaf=true 才渲染单元格；
 * getCell(row, column) 返回单元格数据（或 null）；
 * onCellChange(row, column, patch) 缺省或 readOnly 时为只读态；
 * renderRowActions(row) 渲染在分组合并单元格内（实例新增/删除等）；
 * levelHeaders：行层级表头名称数组（模板 row_headers，如 ['信道','电台']），
 * 未配置的层级回退"第N级"；
 * renderRowName(row)：自定义行名称渲染（设计器内联改名）；
 * renderLevelTitle(level)/renderColumnTitle(col)：层级列/数据列自定义列头
 * （模板设计器使用；缺省为名称文本）。
 */
export default function MatrixEditor({
  columns, rows, getCell, onCellChange, readOnly,
  renderRowActions, renderRowTitle, renderCellExtra, tableKey,
  levelColumnWidth = 150, levelHeaders,
  renderRowName, renderLevelTitle, renderColumnTitle,
}) {
  const editable = !readOnly && typeof onCellChange === 'function';
  const [expandedKeys, setExpandedKeys] = useAutoExpandedKeys(rows);
  const toggleKey = key => setExpandedKeys(prev => (
    prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key]));
  const isExpanded = row => !row.children || !row.children.length
    || expandedKeys.includes(row.key);
  // 行/列均为空才整体空态：设计器可能先配置列（此时仍渲染列头供点击配置）；
  // 设计器（renderLevelTitle）空表时也保留层级列供编辑行层级表头
  if ((!rows || !rows.length) && (!columns || !columns.length) && !renderLevelTitle) {
    return <Empty description="暂无行数据"/>;
  }
  const emitted = rows && rows.length ? emitVisibleRows(rows, isExpanded) : [];
  // 设计器（renderLevelTitle）空树时也保留第 1 级层级列，供编辑层级表头
  const maxDepth = Math.min(
    Math.max(emitted.reduce((max, record) => Math.max(max, record.depth), 0),
      renderLevelTitle ? 1 : 0),
    ROW_MAX_LEVEL);

  const renderGroupTitle = row => (
    <span>
      {(row.children || []).length > 0 && (
        <a
          style={{marginRight: 2}} className="el-matrix-toggle"
          onClick={() => toggleKey(row.key)}>
          {expandedKeys.includes(row.key)
            ? <CaretDownOutlined style={{fontSize: 11}}/>
            : <CaretRightOutlined style={{fontSize: 11}}/>}
        </a>
      )}
      <Tooltip title={row.path} placement="topLeft">
        <span>{renderRowName ? renderRowName(row) : row.name}</span>
      </Tooltip>
      {renderRowTitle && <span style={{marginLeft: 8}}>{renderRowTitle(row)}</span>}
      {renderRowActions && <span style={{marginLeft: 8}}>{renderRowActions(row)}</span>}
    </span>
  );

  const renderLeafTitle = row => (
    <Tooltip title={row.path} placement="topLeft">
      <span>
        <span>{renderRowName ? renderRowName(row) : row.name}</span>
        {renderRowTitle && <span style={{marginLeft: 8}}>{renderRowTitle(row)}</span>}
        {renderRowActions && <span style={{marginLeft: 8}}>{renderRowActions(row)}</span>}
      </span>
    </Tooltip>
  );

  const levelColumns = buildLevelColumns({
    maxDepth, levelColumnWidth, renderGroupTitle, renderLeafTitle,
    levelHeaders, renderLevelTitle,
  });
  const tableColumns = [
    ...levelColumns,
    ...buildDataColumns({columns, editable, getCell, onCellChange, renderCellExtra,
      renderColumnTitle}),
  ];
  return (
    <Table
      key={tableKey || 'matrix'}
      rowKey={record => record.row.key} size="small"
      columns={tableColumns}
      dataSource={emitted}
      pagination={false}
      bordered
      scroll={{x: levelColumns.length * levelColumnWidth + columns.length * 150}}
      rowClassName={record => (record.row.isCellLeaf
        && columns.some(col => cellLooksAbnormal(getCell(record.row, col)))
        ? 'el-ledger-abnormal-row' : '')}
    />
  );
}
