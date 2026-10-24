/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 数字表单模板编辑画布（2026-10-22；2026-10-23 P1 交互整理）：按填写页的
 * 真实结构呈现表单，点击分组标题、检查项、矩阵行或列即可选中并就地编辑名称。
 *
 * - 填写控件复用 FormFillRenderer 的 FieldInput/AbnormalField/MatrixCellInput，
 *   一律 editable=false 仅展示填写形态；画布不持有任何台账填写值，
 *   示例输入不会进入台账数据；
 * - 选中对象（selection）显示高亮边界与复制/排序/删除操作入口；详细设置
 *   （类型/必填/单位/候选项/说明）在右侧检查器（FormTemplateInspector）；
 *   分组排序主入口在左栏（GroupListPanel），画布不再重复提供；
 * - 复制（字段/分组/矩阵行列）：全部子对象生成全新结构 id（genId），名称
 *   追加"副本"，插入原对象之后并自动选中滚动定位；绝不复用已删除 id，
 *   历史版本快照与台账填写值中的旧 id 不受影响；
 * - 新增字段/矩阵行列/分组后自动选中新对象并滚动定位；
 * - 矩阵呈现为表格：表头编辑对比对象名称、首列编辑检查项名称，行/列的
 *   添加与排序/删除/复制在对应位置操作；
 * - 可重复明细组展示一条填写样例并注明实际填写可新增多条；
 * - 结构变更统一经 updateGroup(groupId, updater) 不可变更新；稳定 id 只在
 *   新增/复制时生成（genId），移动/改名不重新生成 id；
 * - selection 结构：{type: 'group'|'field'|'matrixRow'|'matrixColumn',
 *   groupId, fieldId?, columnId?}。
 */
import React from 'react';
import {Alert, Button, Empty, Input, Popconfirm, Tag, Tooltip} from 'antd';
import {
  ArrowDownOutlined, ArrowLeftOutlined, ArrowRightOutlined, ArrowUpOutlined,
  CopyOutlined, DeleteOutlined, PlusOutlined, QuestionCircleOutlined,
} from '@ant-design/icons';
import {AbnormalField, FieldInput, MatrixCellInput} from './FormFillRenderer';
import {genId, GROUP_KIND, GROUP_KIND_TEXT} from './constants';

const SELECTED_STYLE = {border: '1px solid #91d5ff', background: '#f0f8ff'};
const UNSELECTED_STYLE = {border: '1px solid transparent', background: 'transparent'};

const cellStyle = extra => ({
  border: '1px solid #e8e8e8', padding: '4px 6px', verticalAlign: 'top', ...extra});

export function moveItem(list, index, dir) {
  const next = [...list];
  const target = index + dir;
  if (target < 0 || target >= next.length) return next;
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

function newField(prefix, name, type) {
  return {id: genId(prefix), name, type, required: false,
          description: '', unit: '', options: []};
}

/** 新分组业务化默认内容：检查对比表默认"检查项目 / A 机 / B 机"。 */
export function newGroup(kind) {
  const group = {id: genId('g'), name: '填写项目', description: '', kind,
                 item_name: '', columns: [], fields: []};
  if (kind === GROUP_KIND.REPEAT) {
    group.name = '可重复明细';
    group.item_name = '明细条目';
    group.fields = [newField('f', '填写内容 1', 'text')];
  } else if (kind === GROUP_KIND.MATRIX) {
    group.name = '检查项目';
    group.columns = [{id: genId('c'), name: 'A 机'}, {id: genId('c'), name: 'B 机'}];
    group.fields = [newField('r', '外观检查', 'normal_abnormal')];
  } else {
    group.fields = [newField('f', '填写内容 1', 'text')];
  }
  return group;
}

/** 名称追加"副本"后缀（超限时截断原名，总长不超过上限）。 */
export function copyName(name, maxLength) {
  const suffix = ' 副本';
  const merged = `${name || ''}${suffix}`;
  return merged.length > maxLength
    ? merged.slice(0, Math.max(0, maxLength - suffix.length)) + suffix : merged;
}

/** 复制字段：全新 id 与候选项数组，名称追加副本（prefix 按载体给 f/r）。 */
export function cloneField(field, prefix) {
  return {...field, id: genId(prefix), name: copyName(field.name, 100),
          options: [...(field.options || [])]};
}

/** 复制矩阵列。 */
export function cloneColumn(column) {
  return {...column, id: genId('c'), name: copyName(column.name, 30)};
}

/** 复制整组：组与组内字段/列全部生成新结构 id（历史版本旧 id 不受影响）。 */
export function cloneGroup(group) {
  const rowPrefix = group.kind === GROUP_KIND.MATRIX ? 'r' : 'f';
  return {
    ...group,
    id: genId('g'),
    name: copyName(group.name, 60),
    fields: (group.fields || []).map(field => cloneField(field, rowPrefix)),
    columns: (group.columns || []).map(column => cloneColumn(column)),
  };
}

/** 在列表中 matchId 对象之后插入新对象（复制动作的落位规则）。 */
export function insertAfterItem(list, matchId, item) {
  const index = list.findIndex(entry => entry.id === matchId);
  const next = [...list];
  next.splice(index + 1, 0, item);
  return next;
}

/** selection 对应的画布 DOM 锚点（data-testid），供滚动定位。 */
export function selectionAnchorId(selection) {
  if (!selection) return null;
  if (selection.type === 'group') return `canvas-group-${selection.groupId}`;
  if (selection.type === 'matrixColumn') return `canvas-matrix-col-${selection.columnId}`;
  if (selection.type === 'matrixRow') return `canvas-matrix-row-${selection.fieldId}`;
  return `canvas-field-${selection.fieldId}`;
}

/** 选中新对象并滚动定位（jsdom 无 scrollIntoView 时静默跳过）。 */
export function scrollSelectionIntoView(selection) {
  const anchorId = selectionAnchorId(selection);
  if (!anchorId) return;
  setTimeout(() => {
    const el = document.querySelector(`[data-testid="${anchorId}"]`);
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({block: 'center', behavior: 'smooth'});
    }
  }, 0);
}

/** 选中并滚动定位（画布新增/复制的统一收口）。 */
function selectWithScroll(onSelect, selection) {
  onSelect(selection);
  scrollSelectionIntoView(selection);
}

/** 在 form 中解析 selection；指向对象已被删除等失效情形返回 null。 */
export function resolveSelection(form, selection) {
  if (!selection || !selection.groupId) return null;
  const group = (form.groups || []).find(item => item.id === selection.groupId);
  if (!group) return null;
  if (selection.type === 'group') {
    return {type: 'group', group,
            index: form.groups.indexOf(group), total: form.groups.length};
  }
  if (selection.type === 'matrixColumn') {
    const column = (group.columns || []).find(item => item.id === selection.columnId);
    if (!column) return null;
    return {type: 'matrixColumn', group, column,
            index: group.columns.indexOf(column), total: group.columns.length};
  }
  const field = (group.fields || []).find(item => item.id === selection.fieldId);
  if (!field) return null;
  return {type: selection.type === 'matrixRow' ? 'matrixRow' : 'field',
          group, field, index: group.fields.indexOf(field),
          total: group.fields.length};
}

/** 就地名称输入框：聚焦/点击即选中对象（边框less，贴近所见即所得）。 */
function CanvasNameInput({value, onChange, onSelect, testId, maxLength, width}) {
  return (
    <Input size="small" bordered={false} value={value}
           maxLength={maxLength || 100} data-testid={testId} placeholder="名称"
           style={{width: width || 200, padding: '2px 6px', fontWeight: 500}}
           onFocus={onSelect} onClick={onSelect}
           onChange={e => onChange(e.target.value)}/>
  );
}

/** 选中对象的复制/排序/删除操作入口（阻止事件冒泡避免改选父对象）。
 * 分组排序主入口在左栏，分组卡不传 onUp/onDown。 */
function ItemActions({testPrefix, upDisabled, downDisabled, removeTitle,
                      removeDesc, onUp, onDown, onRemove, onCopy, extra}) {
  const confirmTitle = (
    <div>
      <div>{removeTitle}</div>
      {removeDesc ? (
        <div style={{color: '#999', fontSize: 12, maxWidth: 260, whiteSpace: 'normal'}}>
          {removeDesc}
        </div>
      ) : null}
    </div>
  );
  return (
    <span style={{whiteSpace: 'nowrap'}} onClick={e => e.stopPropagation()}>
      {extra}
      {onCopy && (
        <Tooltip title="复制">
          <Button size="small" type="text" icon={<CopyOutlined/>}
                  data-testid={`${testPrefix}-copy`} onClick={onCopy}/>
        </Tooltip>
      )}
      {onUp && (
        <Button size="small" type="text" icon={<ArrowUpOutlined/>}
                data-testid={`${testPrefix}-up`} disabled={upDisabled} onClick={onUp}/>
      )}
      {onDown && (
        <Button size="small" type="text" icon={<ArrowDownOutlined/>}
                data-testid={`${testPrefix}-down`} disabled={downDisabled} onClick={onDown}/>
      )}
      <Popconfirm title={confirmTitle} okText="删除" cancelText="取消" onConfirm={onRemove}>
        <Button size="small" type="text" danger icon={<DeleteOutlined/>}
                data-testid={`${testPrefix}-del`}/>
      </Popconfirm>
    </span>
  );
}

/** 填写形态展示控件（禁用态；画布不保存任何填写值）。 */
function FillWidget({field}) {
  if (field.type === 'normal_abnormal') {
    return <AbnormalField field={field} value={undefined} desc={undefined}
                          editable={false} onChange={() => {}}
                          onDescChange={() => {}}/>;
  }
  return <FieldInput field={field} value={undefined} editable={false}
                     onChange={() => {}}/>;
}

/** 普通/明细组内的字段行：名称就地编辑 + 填写形态展示 + 复制/排序/删除。 */
function FieldCanvasRow({group, field, index, total, selection, onSelect, updateGroup}) {
  const selected = !!selection && selection.type === 'field'
    && selection.groupId === group.id && selection.fieldId === field.id;
  const patchField = (patch, label) => updateGroup(group.id, g => ({
    ...g, fields: g.fields.map(f => f.id === field.id ? {...f, ...patch} : f)}), label);
  const select = () => onSelect({type: 'field', groupId: group.id, fieldId: field.id});
  const copyField = () => {
    const clone = cloneField(field, 'f');
    updateGroup(group.id, g => ({
      ...g, fields: insertAfterItem(g.fields, field.id, clone)}));
    selectWithScroll(onSelect, {type: 'field', groupId: group.id, fieldId: clone.id});
  };
  return (
    <div data-testid={`canvas-field-${field.id}`} onClick={select}
         style={{display: 'flex', alignItems: 'flex-start', gap: 8,
                 padding: '6px 8px', marginBottom: 6, borderRadius: 4,
                 cursor: 'pointer', flexWrap: 'wrap',
                 ...(selected ? SELECTED_STYLE : UNSELECTED_STYLE)}}>
      <div style={{width: 220, flexShrink: 0}}>
        <CanvasNameInput value={field.name} testId={`canvas-field-name-${field.id}`}
                         onSelect={select}
                         onChange={name => patchField({name}, `rename:${group.id}:${field.id}`)}/>
      </div>
      <span style={{flexShrink: 0, paddingTop: 5, minWidth: 10}}>
        {field.required ? <span style={{color: '#f5222d'}}>*</span> : null}
      </span>
      <div style={{flex: '1 1 220px', minWidth: 200, paddingTop: 2}}>
        <FillWidget field={field}/>
      </div>
      <div style={{flexShrink: 0, paddingTop: 5, minWidth: 60}}>
        {field.unit ? <span style={{color: '#999'}}>({field.unit})</span> : null}
        {field.description ? (
          <Tooltip title={field.description}>
            <QuestionCircleOutlined style={{color: '#1890ff', marginLeft: 6}}/>
          </Tooltip>
        ) : null}
      </div>
      {selected && (
        <ItemActions
          testPrefix={`canvas-field-${field.id}`}
          upDisabled={index === 0} downDisabled={index === total - 1}
          removeTitle={`删除字段「${field.name}」？`}
          removeDesc="该内容仅从当前草稿移除，保存草稿后生效；已发布版本与历史台账不受影响。"
          onCopy={copyField}
          onUp={() => updateGroup(group.id, g => ({
            ...g, fields: moveItem(g.fields, index, -1)}))}
          onDown={() => updateGroup(group.id, g => ({
            ...g, fields: moveItem(g.fields, index, 1)}))}
          onRemove={() => updateGroup(group.id, g => ({
            ...g, fields: g.fields.filter(f => f.id !== field.id)}))}/>
      )}
    </div>
  );
}

/** 可重复明细组：展示一条填写样例 + "实际可新增多条"说明。 */
function RepeatGroupBody({group, selection, onSelect, updateGroup}) {
  const itemName = group.item_name || '明细条目';
  return (
    <div>
      <div style={{border: '1px dashed #d9d9d9', borderRadius: 4, padding: '8px 10px'}}>
        <div style={{color: '#999', marginBottom: 6, fontSize: 12}}>
          {itemName} 示例（第 1 条）
        </div>
        {(group.fields || []).map((field, index) => (
          <FieldCanvasRow key={field.id} group={group} field={field} index={index}
                          total={group.fields.length} selection={selection}
                          onSelect={onSelect} updateGroup={updateGroup}/>
        ))}
      </div>
      <div style={{color: '#999', fontSize: 12, marginTop: 6}}>
        实际填写时可按需新增多条{itemName}；此处仅展示填写样例，样例内容不会保存。
      </div>
    </div>
  );
}

/** 矩阵列（表头）单元格：名称就地编辑 + 选中时的复制/排序/删除入口。 */
function MatrixColumnHeader({group, column, index, total, selected, onSelect, updateGroup}) {
  const patchColumn = (patch, label) => updateGroup(group.id, g => ({
    ...g, columns: g.columns.map(c => c.id === column.id ? {...c, ...patch} : c)}), label);
  const select = () => onSelect({type: 'matrixColumn', groupId: group.id,
                                 columnId: column.id});
  const copyColumn = () => {
    const clone = cloneColumn(column);
    updateGroup(group.id, g => ({
      ...g, columns: insertAfterItem(g.columns, column.id, clone)}));
    selectWithScroll(onSelect, {type: 'matrixColumn', groupId: group.id,
                                columnId: clone.id});
  };
  return (
    <th style={cellStyle({minWidth: 150, background: '#fafafa'})}
        onClick={select} data-testid={`canvas-matrix-col-${column.id}`}>
      <CanvasNameInput value={column.name} testId={`canvas-matrix-col-name-${column.id}`}
                       width={120} maxLength={30} onSelect={select}
                       onChange={name => patchColumn({name}, `rename:${group.id}:${column.id}`)}/>
      {selected && (
        <div onClick={e => e.stopPropagation()}>
          <Button size="small" type="text" icon={<ArrowLeftOutlined/>}
                  data-testid={`canvas-matrix-col-${column.id}-left`}
                  disabled={index === 0}
                  onClick={() => updateGroup(group.id, g => ({
                    ...g, columns: moveItem(g.columns, index, -1)}))}/>
          <Button size="small" type="text" icon={<ArrowRightOutlined/>}
                  data-testid={`canvas-matrix-col-${column.id}-right`}
                  disabled={index === total - 1}
                  onClick={() => updateGroup(group.id, g => ({
                    ...g, columns: moveItem(g.columns, index, 1)}))}/>
          <Tooltip title="复制">
            <Button size="small" type="text" icon={<CopyOutlined/>}
                    data-testid={`canvas-matrix-col-${column.id}-copy`}
                    onClick={copyColumn}/>
          </Tooltip>
          <Popconfirm title={`删除对比对象「${column.name}」？`}
                      description="该内容仅从当前草稿移除，保存草稿后生效；已发布版本与历史台账不受影响。"
                      okText="删除" cancelText="取消"
                      onConfirm={() => updateGroup(group.id, g => ({
                        ...g, columns: g.columns.filter(c => c.id !== column.id)}))}>
            <Button size="small" type="text" danger icon={<DeleteOutlined/>}
                    data-testid={`canvas-matrix-col-${column.id}-del`}/>
          </Popconfirm>
        </div>
      )}
    </th>
  );
}

/** 矩阵表格：表头=对比对象、首列=检查项，行/列在对应位置添加、复制与排序删除。 */
function MatrixGroupBody({group, selection, onSelect, updateGroup}) {
  const columns = group.columns || [];
  const rows = group.fields || [];
  const selectedRowId = selection && selection.type === 'matrixRow'
    && selection.groupId === group.id ? selection.fieldId : null;
  const selectedColumnId = selection && selection.type === 'matrixColumn'
    && selection.groupId === group.id ? selection.columnId : null;
  const addRow = () => {
    const row = newField('r', '新检查项', 'normal_abnormal');
    updateGroup(group.id, g => ({...g, fields: [...g.fields, row]}));
    selectWithScroll(onSelect, {type: 'matrixRow', groupId: group.id, fieldId: row.id});
  };
  const addColumn = () => {
    const column = {id: genId('c'), name: '新对比对象'};
    updateGroup(group.id, g => ({...g, columns: [...g.columns, column]}));
    selectWithScroll(onSelect, {type: 'matrixColumn', groupId: group.id,
                                columnId: column.id});
  };
  const copyRow = row => {
    const clone = cloneField(row, 'r');
    updateGroup(group.id, g => ({
      ...g, fields: insertAfterItem(g.fields, row.id, clone)}));
    selectWithScroll(onSelect, {type: 'matrixRow', groupId: group.id,
                                fieldId: clone.id});
  };
  return (
    <div data-testid={`canvas-matrix-${group.id}`} style={{overflowX: 'auto'}}>
      <table style={{width: '100%', borderCollapse: 'collapse'}}>
        <thead>
          <tr>
            <th style={cellStyle({width: 190, background: '#fafafa', textAlign: 'left'})}>
              {group.name}
            </th>
            {columns.map((column, index) => (
              <MatrixColumnHeader key={column.id} group={group} column={column}
                                  index={index} total={columns.length}
                                  selected={selectedColumnId === column.id}
                                  onSelect={onSelect} updateGroup={updateGroup}/>
            ))}
            <th style={cellStyle({width: 110, background: '#fafafa'})}>操作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => {
            const rowSelected = selectedRowId === row.id;
            const selectRow = () => onSelect({type: 'matrixRow', groupId: group.id,
                                              fieldId: row.id});
            return (
              <tr key={row.id} data-testid={`canvas-matrix-row-${row.id}`}>
                <td style={cellStyle(rowSelected ? {background: '#f0f8ff'} : null)}
                    onClick={selectRow}>
                  <CanvasNameInput value={row.name}
                                   testId={`canvas-matrix-row-name-${row.id}`}
                                   width={170} onSelect={selectRow}
                                   onChange={name => updateGroup(
                                     group.id,
                                     g => ({...g, fields: g.fields.map(
                                       f => f.id === row.id ? {...f, name} : f)}),
                                     `rename:${group.id}:${row.id}`)}/>
                </td>
                {columns.map(column => (
                  <td key={column.id} style={cellStyle()} onClick={selectRow}>
                    <MatrixCellInput field={row} value={undefined} editable={false}
                                     onChange={() => {}}/>
                  </td>
                ))}
                <td style={cellStyle({textAlign: 'center'})} onClick={selectRow}>
                  {rowSelected && (
                    <ItemActions
                      testPrefix={`canvas-matrix-row-${row.id}`}
                      upDisabled={rowIndex === 0} downDisabled={rowIndex === rows.length - 1}
                      removeTitle={`删除检查项「${row.name}」？`}
                      removeDesc="该内容仅从当前草稿移除，保存草稿后生效；已发布版本与历史台账不受影响。"
                      onCopy={() => copyRow(row)}
                      onUp={() => updateGroup(group.id, g => ({
                        ...g, fields: moveItem(g.fields, rowIndex, -1)}))}
                      onDown={() => updateGroup(group.id, g => ({
                        ...g, fields: moveItem(g.fields, rowIndex, 1)}))}
                      onRemove={() => updateGroup(group.id, g => ({
                        ...g, fields: g.fields.filter(f => f.id !== row.id)}))}/>
                  )}
                </td>
              </tr>
            );
          })}
          <tr style={{background: '#fafafa'}}>
            <td style={cellStyle()}>
              <Button size="small" type="dashed" icon={<PlusOutlined/>}
                      data-testid={`canvas-matrix-add-row-${group.id}`}
                      onClick={addRow}>添加检查项目</Button>
            </td>
            {columns.map(column => (
              <td key={column.id} style={cellStyle({textAlign: 'center'})}>
                {selectedColumnId === column.id ? (
                  <span style={{color: '#1890ff', fontSize: 12}}>正在编辑该列</span>
                ) : null}
              </td>
            ))}
            <td style={cellStyle({textAlign: 'center'})}>
              <Button size="small" type="dashed" icon={<PlusOutlined/>}
                      data-testid={`canvas-matrix-add-col-${group.id}`}
                      onClick={addColumn}>添加对象</Button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

/** 单个分组卡片：标题就地编辑 + 选中边界与复制/删除入口 + 分组主体。
 * 分组排序主入口在左栏（GroupListPanel），画布不重复提供。 */
function GroupCard({group, selection, onSelect, updateGroup, removeGroup, copyGroup}) {
  const selected = !!selection && selection.type === 'group'
    && selection.groupId === group.id;
  const kindColor = group.kind === GROUP_KIND.MATRIX ? 'geekblue'
    : group.kind === GROUP_KIND.REPEAT ? 'cyan' : 'default';
  const removeDesc = group.kind === GROUP_KIND.MATRIX
    ? `删除该对比表及其下 ${group.fields.length} 行 × ${group.columns.length} 列填写格，`
      + '保存草稿后生效；已发布版本与历史台账不受影响。'
    : `删除该分组及其下 ${group.fields.length} 个填写项，保存草稿后生效；`
      + '已发布版本与历史台账不受影响。';
  const addField = () => {
    const field = newField('f', '新填写项', 'text');
    updateGroup(group.id, g => ({...g, fields: [...g.fields, field]}));
    selectWithScroll(onSelect, {type: 'field', groupId: group.id, fieldId: field.id});
  };
  return (
    <div data-testid={`canvas-group-${group.id}`}
         style={{border: selected ? '1px solid #91d5ff' : '1px solid #e8e8e8',
                 borderRadius: 6, padding: '10px 12px', marginBottom: 14,
                 background: '#fff', boxShadow: selected ? '0 1px 4px rgba(24,144,255,.25)' : 'none'}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 8,
                   marginBottom: 8, flexWrap: 'wrap'}}>
        <Tag color={kindColor}>{GROUP_KIND_TEXT[group.kind]}</Tag>
        <CanvasNameInput value={group.name} width={260}
                         testId={`canvas-group-name-${group.id}`}
                         onSelect={() => onSelect({type: 'group', groupId: group.id})}
                         onChange={name => updateGroup(
                           group.id, g => ({...g, name}), `rename:${group.id}`)}/>
        {group.description ? (
          <span style={{color: '#999', fontSize: 12}}>{group.description}</span>
        ) : null}
        <span style={{flex: 1}}/>
        {selected && (
          <ItemActions testPrefix={`canvas-group-${group.id}`}
                       removeTitle={`删除分组「${group.name}」？`} removeDesc={removeDesc}
                       onCopy={() => copyGroup(group.id)}
                       onRemove={() => removeGroup(group.id)}/>
        )}
      </div>
      {group.kind === GROUP_KIND.MATRIX ? (
        <MatrixGroupBody group={group} selection={selection} onSelect={onSelect}
                         updateGroup={updateGroup}/>
      ) : group.kind === GROUP_KIND.REPEAT ? (
        <RepeatGroupBody group={group} selection={selection} onSelect={onSelect}
                         updateGroup={updateGroup}/>
      ) : (
        <div>
          {(group.fields || []).map((field, fieldIndex) => (
            <FieldCanvasRow key={field.id} group={group} field={field}
                            index={fieldIndex} total={group.fields.length}
                            selection={selection} onSelect={onSelect}
                            updateGroup={updateGroup}/>
          ))}
        </div>
      )}
      {group.kind !== GROUP_KIND.MATRIX && (
        <Button size="small" type="dashed" icon={<PlusOutlined/>}
                data-testid={`canvas-add-field-${group.id}`}
                onClick={addField}>
          添加填写项
        </Button>
      )}
    </div>
  );
}

/** 三种内容结构新增入口（统一词汇与一句话用途说明，设计稿 2.3）。
 * 本轮不新增 fixed_table（条件性 P3）。 */
const GROUP_ENTRIES = [
  {kind: GROUP_KIND.FIELDS, label: '添加固定填写项',
   hint: '一组固定字段，每份台账填写一次'},
  {kind: GROUP_KIND.REPEAT, label: '添加可重复明细',
   hint: '同一结构可填写多条记录，条数由填写人增减'},
  {kind: GROUP_KIND.MATRIX, label: '添加检查对比表',
   hint: '行=检查项目，列=对比对象，逐格横向填写'},
];

/**
 * 模板编辑画布主体：上方模式说明，中间分组卡片流，底部业务语言新增入口。
 * addGroup(kind) 由编辑器注入（新增后自动选中新分组并滚动定位）；
 * copyGroup(groupId) 复制整组（全部新 id）插入原组之后并选中定位。
 */
export default function FormTemplateCanvas({form, selection, onSelect, updateGroup,
                                            addGroup, removeGroup, copyGroup}) {
  const groups = form.groups || [];
  return (
    <div data-testid="form-template-canvas">
      <Alert type="info" showIcon style={{marginBottom: 12}}
             message="模板编辑模式"
             description="灰色控件仅展示填写形态，此处不保存任何台账数据；实际填写在创建台账后进行。点击分组、字段或表格行列可选中，详细设置显示在右侧。"/>
      {groups.length ? groups.map(group => (
        <GroupCard key={group.id} group={group}
                   selection={selection} onSelect={onSelect} updateGroup={updateGroup}
                   removeGroup={removeGroup} copyGroup={copyGroup}/>
      )) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} style={{padding: '24px 0'}}
               description="该模板还没有表单内容，请从下方添加第一个分组"/>
      )}
      <div style={{display: 'flex', gap: 24, flexWrap: 'wrap'}}>
        {GROUP_ENTRIES.map(entry => (
          <div key={entry.kind}>
            <Button type="dashed" icon={<PlusOutlined/>}
                    data-testid={`editor-add-group-${entry.kind}`}
                    onClick={() => addGroup(entry.kind)}>{entry.label}</Button>
            <div style={{color: '#999', fontSize: 12, marginTop: 4, maxWidth: 230}}>
              {entry.hint}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
