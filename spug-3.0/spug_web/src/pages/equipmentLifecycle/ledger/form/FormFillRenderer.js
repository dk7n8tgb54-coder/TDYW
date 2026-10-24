/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 数字表单渲染器（2026-10-21）：填写页与模板预览共用的唯一渲染实现。
 *
 * - 按分组渲染：普通分组（字段列表）、明细组（可增删行卡片）、矩阵组
 *   （行=检查项、列=对比对象 的表格）；
 * - 编辑动作统一经 onEdit(action, ...args) 上抛（action 见文件底部常量），
 *   填写页分发到 store（formLedgerStore.edit 委托 applyFillEdit 纯函数），
 *   预览模式（含试填）传本地临时 values；
 * - normal_abnormal 字段选"异常"时内联显示异常说明（键 <field_id>__desc）；
 *   require_desc_when_abnormal（协议 v2）开启时说明必填，占位与必填星号
 *   如实标注，完成填写由后端终验兜底；矩阵单元格的异常说明集中在表格
 *   下方的"异常说明"区，避免列被撑爆；
 * - 协议 v2 控件（2026-10-23 P2）：textarea 按模板行数 rows 渲染；number
 *   InputNumber 透传模板 min/max/precision；date 升级 DatePicker（提交
 *   仍为 YYYY-MM-DD 字符串，与后端校验一致）；历史 v1 快照缺省键即
 *   原行为，语义不漂移；
 * - 控件宽度契约（2026-10-24）：text/number/date/choice 按 类型 maxWidth
 *   封顶（width:100% 窄容器自适应），矩阵单元格控件同思路限宽；textarea
 *   保持整行宽并以模板 rows 为初值 autoSize 增高，异常说明（普通字段
 *   内联/矩阵集中区）多行可增长，长内容编辑时可见、可继续输入；宽矩阵
 *   表格置于横向滚动容器内，容器不足时组内横向滚动不撑破卡片/弹窗；
 * - 窄屏（<768px）矩阵改为逐列（逐设备）卡片段落，避免横向挤压；
 *   窄屏判定用 useNarrowViewport（resize 监听）；
 * - collectFillUnits 为完成进度/未填定位/必填统计的唯一口径（与后端
 *   missing_required_labels 同构：矩阵单元格不做必填，异常说明必填
 *   覆盖普通/明细/矩阵行三种载体）。
 */
import React, {useEffect, useState} from 'react';
import {Button, DatePicker, Input, InputNumber, Radio, Select, Tooltip} from 'antd';
import {DeleteOutlined, PlusOutlined} from '@ant-design/icons';
import moment from 'moment';
import {
  DESC_SUFFIX, GROUP_KIND, NORMAL_ABNORMAL_OPTIONS,
} from './constants';

// 编辑动作（onEdit 第一参数）
export const EDIT_FIELD = 'field';
export const EDIT_DESC = 'desc';
export const EDIT_ADD_ROW = 'addRow';
export const EDIT_REMOVE_ROW = 'removeRow';
export const EDIT_ROW_FIELD = 'rowField';
export const EDIT_ROW_DESC = 'rowDesc';
export const EDIT_CELL = 'cell';
export const EDIT_CELL_DESC = 'cellDesc';

/** 填写控件宽度上限（px，2026-10-24）：台账填写页/试填预览容器很宽时，
 * 短文本、数字、日期、选项控件不无限拉长；width:100% 保证窄容器仍
 * 自适应。textarea（多行文本）保持整行宽，不设上限。 */
const FIELD_CONTROL_MAX_WIDTH = {
  text: 480, number: 220, date: 220, choice: 320,
};

/** 矩阵单元格控件宽度上限（px）：列较少时单元格被表格均分得很宽，
 * 控件同样封顶；宽矩阵列 minWidth（140）小于该值，横向适配不受影响。 */
const MATRIX_CELL_CONTROL_MAX_WIDTH = 200;

/** 填写判定（与后端 _is_empty 同口径：undefined/null/空串为未填）。 */
export function isFilled(value) {
  if (value === undefined || value === null) return false;
  if (typeof value === 'string') return !!value.trim();
  return true;
}

/** 窄屏判定（矩阵逐列模式的开关）。 */
export function useNarrowViewport(breakpoint = 768) {
  const [narrow, setNarrow] = useState(
    () => typeof window !== 'undefined' && window.innerWidth < breakpoint);
  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < breakpoint);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [breakpoint]);
  return narrow;
}

/** 填写单元收集（进度/必填/定位唯一口径；矩阵单元格不做必填，与后端
 * 一致；"异常时说明必填"产生必填单元：仅值=异常 时计入，与后端终验
 * missing_required_labels 同口径）。 */
export function collectFillUnits(form, values) {
  const units = [];
  for (const group of (form.groups || [])) {
    if (group.kind === GROUP_KIND.MATRIX) {
      const matrix = values[group.id] || {};
      for (const row of (group.fields || [])) {
        for (const column of (group.columns || [])) {
          const cell = (matrix[row.id] || {})[column.id];
          units.push({
            anchor: `anchor-${group.id}`,
            label: `${group.name}｜${row.name}（${column.name}）`,
            required: false,
            filled: isFilled(cell),
          });
          if (row.type === 'normal_abnormal' && row.require_desc_when_abnormal
              && cell === 'abnormal') {
            units.push({
              anchor: `anchor-${group.id}`,
              label: `${group.name}｜${row.name}（${column.name}）异常说明未填写`,
              required: true,
              filled: isFilled((matrix[row.id] || {})[column.id + DESC_SUFFIX]),
            });
          }
        }
      }
      continue;
    }
    if (group.kind === GROUP_KIND.REPEAT) {
      const rows = values[group.id] || [];
      rows.forEach((row, index) => {
        for (const field of (group.fields || [])) {
          units.push({
            anchor: `anchor-${group.id}`,
            label: `${group.name} 第${index + 1}条 / ${field.name}`,
            required: !!field.required,
            filled: isFilled(row[field.id]),
          });
          if (field.type === 'normal_abnormal' && field.require_desc_when_abnormal
              && row[field.id] === 'abnormal') {
            units.push({
              anchor: `anchor-${group.id}`,
              label: `${group.name} 第${index + 1}条 / ${field.name} 异常说明未填写`,
              required: true,
              filled: isFilled(row[field.id + DESC_SUFFIX]),
            });
          }
        }
      });
      continue;
    }
    for (const field of (group.fields || [])) {
      units.push({
        anchor: `anchor-${field.id}`,
        label: `${group.name} / ${field.name}`,
        required: !!field.required,
        filled: isFilled(values[field.id]),
      });
      if (field.type === 'normal_abnormal' && field.require_desc_when_abnormal
          && values[field.id] === 'abnormal') {
        units.push({
          anchor: `anchor-${field.id}`,
          label: `${group.name} / ${field.name} 异常说明未填写`,
          required: true,
          filled: isFilled(values[field.id + DESC_SUFFIX]),
        });
      }
    }
  }
  return units;
}

/** 单字段填写控件（type 分发；模板画布展示填写形态时复用本实现）。
 * 协议 v2：textarea 行数、number 范围/精度透传模板配置、date 用
 * DatePicker（提交仍 YYYY-MM-DD）；缺省键即历史行为（v1 快照兼容）。
 * 宽度契约（2026-10-24）：width:100% + 按类型 maxWidth——窄容器自适应，
 * 宽容器封顶；textarea 以模板 rows 为初值自动增高（超上限后内部滚动），
 * 长内容编辑时始终可见、可继续输入。 */
export function FieldInput({field, value, editable, onChange}) {
  const cap = FIELD_CONTROL_MAX_WIDTH[field.type];
  const common = {
    disabled: !editable,
    'data-testid': `field-control-${field.id}`,
    style: {width: '100%', ...(cap ? {maxWidth: cap} : {})},
  };
  if (field.type === 'textarea') {
    return <Input.TextArea {...common} rows={field.rows || 2} maxLength={2000}
                           autoSize={{minRows: field.rows || 2, maxRows: 12}}
                           value={value || ''} placeholder="请输入"
                           onChange={e => onChange(e.target.value)}/>;
  }
  if (field.type === 'number') {
    return <InputNumber {...common}
                        min={field.min ?? undefined} max={field.max ?? undefined}
                        precision={field.precision ?? undefined}
                        value={value === undefined || value === '' ? null : value}
                        placeholder={field.unit ? `请输入（${field.unit}）` : '请输入'}
                        onChange={v => onChange(v === undefined ? '' : v)}/>;
  }
  if (field.type === 'date') {
    return (
      <DatePicker {...common} value={value ? moment(value, 'YYYY-MM-DD') : null}
                  placeholder="选择日期"
                  onChange={d => onChange(d ? d.format('YYYY-MM-DD') : '')}/>
    );
  }
  if (field.type === 'choice') {
    return (
      <Select {...common} value={value || undefined} allowClear
              placeholder="请选择" onChange={v => onChange(v || '')}>
        {(field.options || []).map(option => (
          <Select.Option key={option} value={option}>{option}</Select.Option>
        ))}
      </Select>
    );
  }
  return <Input {...common} value={value || ''} maxLength={500} placeholder="请输入"
                onChange={e => onChange(e.target.value)}/>;
}

/** normal_abnormal 字段：正常/异常单选 + 选异常时内联异常说明。
 * require_desc_when_abnormal（协议 v2）开启时说明必填：必填星号与占位
 * 文案如实标注（前端提示，后端"完成填写"终验兜底）。 */
export function AbnormalField({field, value, desc, editable, onChange, onDescChange}) {
  const descRequired = !!field.require_desc_when_abnormal;
  return (
    <div>
      <Radio.Group disabled={!editable} value={value || undefined}
                   onChange={e => onChange(e.target.value)}>
        {NORMAL_ABNORMAL_OPTIONS.map(option => (
          <Radio.Button key={option.value} value={option.value}>{option.label}</Radio.Button>
        ))}
      </Radio.Group>
      {(value || '') === 'abnormal' && (
        <div style={{marginTop: 6}}>
          <div style={{marginBottom: 2, fontSize: 12}}>
            {descRequired ? <span style={{color: '#f5222d'}}>*</span> : null}
            <span style={{color: '#999'}}>异常说明</span>
          </div>
          <Input.TextArea
            data-testid={`abnormal-desc-${field.id}`}
            disabled={!editable} rows={2} maxLength={500}
            autoSize={{minRows: 2, maxRows: 8}}
            value={desc || ''}
            placeholder={descRequired ? '异常说明（必填）' : '异常说明（选填）'}
            onChange={e => onDescChange(e.target.value)}/>
        </div>
      )}
    </div>
  );
}

function FieldRow({group, field, values, editable, onEdit}) {
  const value = values[field.id];
  const desc = values[field.id + DESC_SUFFIX];
  const isAbnormal = field.type === 'normal_abnormal';
  return (
    <div id={`anchor-${field.id}`} style={{marginBottom: 14}}>
      <div style={{marginBottom: 4}}>
        <span>{field.required ? <span style={{color: '#f5222d'}}>*</span> : null}</span>
        <span style={{fontWeight: 500}}>{field.name}</span>
        {field.unit ? <span style={{color: '#999', marginLeft: 4}}>({field.unit})</span> : null}
        {field.description ? (
          <Tooltip title={field.description}>
            <span style={{color: '#1890ff', marginLeft: 6, cursor: 'help', fontSize: 12}}>说明</span>
          </Tooltip>
        ) : null}
      </div>
      {isAbnormal ? (
        <AbnormalField field={field} value={value} desc={desc} editable={editable}
                       onChange={v => onEdit(EDIT_FIELD, field.id, v)}
                       onDescChange={v => onEdit(EDIT_DESC, field.id, v)}/>
      ) : (
        <FieldInput field={field} value={value} editable={editable}
                    onChange={v => onEdit(EDIT_FIELD, field.id, v)}/>
      )}
    </div>
  );
}

function RepeatGroup({group, values, editable, onEdit}) {
  const rows = values[group.id] || [];
  return (
    <div>
      {rows.map((row, index) => (
        <div key={row._rid || index} id={`anchor-${group.id}`}
             style={{border: '1px solid #e8e8e8', borderRadius: 4,
                     padding: '10px 12px', marginBottom: 8, position: 'relative'}}>
          <div style={{color: '#999', marginBottom: 6, fontSize: 12}}>
            {group.item_name || '明细条目'} {index + 1}
          </div>
          {editable && (
            <Button size="small" type="link" danger
                    data-testid={`repeat-remove-${group.id}`}
                    style={{position: 'absolute', top: 6, right: 8}}
                    icon={<DeleteOutlined/>}
                    onClick={() => onEdit(EDIT_REMOVE_ROW, group.id, index)}/>
          )}
          {(group.fields || []).map(field => {
            const isAbnormal = field.type === 'normal_abnormal';
            return (
              <div key={field.id} style={{marginBottom: 8}}>
                <div style={{marginBottom: 2}}>
                  {field.required ? <span style={{color: '#f5222d'}}>*</span> : null}
                  <span>{field.name}</span>
                  {field.unit ? <span style={{color: '#999', marginLeft: 4}}>({field.unit})</span> : null}
                </div>
                {isAbnormal ? (
                  <AbnormalField field={field} value={row[field.id]}
                                 desc={row[field.id + DESC_SUFFIX]} editable={editable}
                                 onChange={v => onEdit(EDIT_ROW_FIELD, group.id, index, field.id, v)}
                                 onDescChange={v => onEdit(EDIT_ROW_DESC, group.id, index, field.id, v)}/>
                ) : (
                  <FieldInput field={field} value={row[field.id]} editable={editable}
                              onChange={v => onEdit(EDIT_ROW_FIELD, group.id, index, field.id, v)}/>
                )}
              </div>
            );
          })}
        </div>
      ))}
      {editable && (
        <Button type="dashed" block icon={<PlusOutlined/>}
                data-testid={`repeat-add-${group.id}`}
                onClick={() => onEdit(EDIT_ADD_ROW, group)}>
          添加{group.item_name || '明细条目'}
        </Button>
      )}
    </div>
  );
}

/** 矩阵单元格填写控件（模板画布展示填写形态时复用本实现）。
 * number 行的模板 min/max/precision 同样透传（后端对矩阵单元格值执行
 * 同一校验，输入端不一致会造成"能输入但保存被拒"）。
 * 宽度契约（2026-10-24）：与普通字段同思路，单元格控件 width:100% +
 * maxWidth 封顶，列少时单元格不被撑到数百像素宽。 */
export function MatrixCellInput({field, value, editable, onChange, testId}) {
  const common = {
    disabled: !editable,
    'data-testid': testId,
    style: {width: '100%', maxWidth: MATRIX_CELL_CONTROL_MAX_WIDTH},
  };
  if (field.type === 'number') {
    return <InputNumber size="small" {...common}
                        min={field.min ?? undefined} max={field.max ?? undefined}
                        precision={field.precision ?? undefined}
                        value={value === undefined || value === '' ? null : value}
                        onChange={v => onChange(v === undefined ? '' : v)}/>;
  }
  if (field.type === 'choice') {
    return (
      <Select size="small" {...common}
              value={value || undefined} allowClear
              onChange={v => onChange(v || '')}>
        {(field.options || []).map(option => (
          <Select.Option key={option} value={option}>{option}</Select.Option>
        ))}
      </Select>
    );
  }
  if (field.type === 'normal_abnormal') {
    return (
      <Select size="small" {...common}
              value={value || undefined} allowClear
              data-testid={`matrix-cell-${value === 'abnormal' ? 'abnormal' : 'normal'}`}
              onChange={v => onChange(v || '')}>
        {NORMAL_ABNORMAL_OPTIONS.map(option => (
          <Select.Option key={option.value} value={option.value}>{option.label}</Select.Option>
        ))}
      </Select>
    );
  }
  return <Input size="small" {...common} maxLength={200}
                value={value || ''}
                onChange={e => onChange(e.target.value)}/>;
}

/** 矩阵异常说明区：所有取值为"异常"的单元格集中在此填写说明。
 * 行配置 require_desc_when_abnormal（协议 v2）时说明必填，星号如实标注。 */
function MatrixAbnormalDescs({group, values, editable, onEdit}) {
  const matrix = values[group.id] || {};
  const abnormalCells = [];
  for (const row of (group.fields || [])) {
    if (row.type !== 'normal_abnormal') continue;
    for (const column of (group.columns || [])) {
      if (((matrix[row.id] || {})[column.id]) === 'abnormal') {
        abnormalCells.push({row, column});
      }
    }
  }
  if (!abnormalCells.length) return null;
  return (
    <div style={{marginTop: 8, borderTop: '1px dashed #e8e8e8', paddingTop: 8}}>
      <div style={{color: '#fa8c16', marginBottom: 6, fontSize: 12}}>异常说明</div>
      {abnormalCells.map(({row, column}) => (
        <div key={row.id + '-' + column.id} style={{marginBottom: 6}}>
          <div style={{fontSize: 12, color: '#666'}}>
            {row.require_desc_when_abnormal
              ? <span style={{color: '#f5222d'}}>*</span> : null}
            {row.name}（{column.name}）
          </div>
          <Input.TextArea rows={1} disabled={!editable} maxLength={500}
                          autoSize={{minRows: 1, maxRows: 4}}
                          value={(matrix[row.id] || {})[column.id + DESC_SUFFIX] || ''}
                          placeholder={row.require_desc_when_abnormal
                            ? '异常说明（必填）' : '异常说明（选填）'}
                          onChange={e => onEdit(
                            EDIT_CELL_DESC, group.id, row.id, column.id, e.target.value)}/>
        </div>
      ))}
    </div>
  );
}

/** 矩阵行头：名称 + 单位 + 行说明（与 PDF _field_label_html 同语义——
 * 行说明随行头呈现，此前网页未渲染属"死配置"，2026-10-23 对齐）。 */
function MatrixRowLabel({row}) {
  return (
    <div>
      <div>
        {row.name}
        {row.unit ? <span style={{color: '#999', marginLeft: 4}}>({row.unit})</span> : null}
      </div>
      {row.description ? (
        <div style={{color: '#999', fontSize: 12, whiteSpace: 'pre-wrap'}}>
          {row.description}
        </div>
      ) : null}
    </div>
  );
}

function MatrixGroup({group, values, editable, onEdit, narrow}) {
  const matrix = values[group.id] || {};
  if (narrow) {
    return (
      <div>
        {(group.columns || []).map(column => (
          <div key={column.id} style={{border: '1px solid #e8e8e8', borderRadius: 4,
                                       padding: '10px 12px', marginBottom: 8}}>
            <div style={{fontWeight: 500, marginBottom: 8}}>{column.name}</div>
            {(group.fields || []).map(row => (
              <div key={row.id} style={{marginBottom: 8}}>
                <MatrixRowLabel row={row}/>
                <MatrixCellInput field={row} editable={editable}
                                 testId={`cell-control-${row.id}-${column.id}`}
                                 value={(matrix[row.id] || {})[column.id]}
                                 onChange={v => onEdit(EDIT_CELL, group.id, row.id, column.id, v)}/>
              </div>
            ))}
          </div>
        ))}
        <MatrixAbnormalDescs group={group} values={values} editable={editable} onEdit={onEdit}/>
      </div>
    );
  }
  return (
    <div>
      {/* 宽矩阵横向滚动容器（2026-10-24）：列 minWidth 之和超过容器
       * （预览弹窗 820px / 窄桌面卡片）时在组内横向滚动，不撑破卡片与
       * 弹窗——浏览器实测 8 列表格 1172px 曾渲染到弹窗盒与视口之外，
       * 最右列不可见不可填。 */}
      <div data-testid={`matrix-table-scroll-${group.id}`}
           style={{overflowX: 'auto'}}>
        <table style={{width: '100%', borderCollapse: 'collapse'}}>
          <thead>
            <tr>
              <th style={{border: '1px solid #e8e8e8', padding: '6px 8px', background: '#fafafa',
                          textAlign: 'left', width: 180}}>
                {group.name}
              </th>
              {(group.columns || []).map(column => (
                <th key={column.id} style={{border: '1px solid #e8e8e8', padding: '6px 8px',
                                            background: '#fafafa', minWidth: 140}}>
                  {column.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(group.fields || []).map(row => (
              <tr key={row.id}>
                <td style={{border: '1px solid #e8e8e8', padding: '6px 8px'}}>
                  <MatrixRowLabel row={row}/>
                </td>
                {(group.columns || []).map(column => (
                  <td key={column.id} style={{border: '1px solid #e8e8e8', padding: '4px 6px'}}>
                    <MatrixCellInput field={row} editable={editable}
                                     testId={`cell-control-${row.id}-${column.id}`}
                                     value={(matrix[row.id] || {})[column.id]}
                                     onChange={v => onEdit(EDIT_CELL, group.id, row.id, column.id, v)}/>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <MatrixAbnormalDescs group={group} values={values} editable={editable} onEdit={onEdit}/>
    </div>
  );
}

/**
 * 填写编辑动作纯函数（台账 store 与试填预览共用，2026-10-23 提炼）：
 * values 不可变更新，行为与原 formLedgerStore.edit 完全一致——
 * field/desc 顶层键、addRow/removeRow 明细行（新行初始化所有字段为空串
 * 并携带运行时行标识 _rid）、rowField/rowDesc 行内键、cell/cellDesc
 * 矩阵行→列嵌套。调用方（store action 或弹窗本地 state）自行落值。
 */
export function makeRowId() {
  let tail = '';
  while (tail.length < 8) tail += Math.random().toString(36).slice(2);
  return 'r' + tail.slice(0, 8).replace(/[^a-z0-9]/g, '0');
}

export function applyFillEdit(values, kind, ...args) {
  const next = {...(values || {})};
  if (kind === EDIT_FIELD) {
    const [fieldId, value] = args;
    next[fieldId] = value;
  } else if (kind === EDIT_DESC) {
    const [fieldId, value] = args;
    next[fieldId + DESC_SUFFIX] = value;
  } else if (kind === EDIT_ADD_ROW) {
    const [group] = args;
    const rows = [...(next[group.id] || [])];
    const row = {_rid: makeRowId()};
    (group.fields || []).forEach(field => { row[field.id] = ''; });
    rows.push(row);
    next[group.id] = rows;
  } else if (kind === EDIT_REMOVE_ROW) {
    const [groupId, index] = args;
    const rows = [...(next[groupId] || [])];
    rows.splice(index, 1);
    next[groupId] = rows;
  } else if (kind === EDIT_ROW_FIELD) {
    const [groupId, index, fieldId, value] = args;
    const rows = [...(next[groupId] || [])];
    rows[index] = {...(rows[index] || {}), [fieldId]: value};
    next[groupId] = rows;
  } else if (kind === EDIT_ROW_DESC) {
    const [groupId, index, fieldId, value] = args;
    const rows = [...(next[groupId] || [])];
    rows[index] = {...(rows[index] || {}), [fieldId + DESC_SUFFIX]: value};
    next[groupId] = rows;
  } else if (kind === EDIT_CELL) {
    const [groupId, rowId, colId, value] = args;
    const matrix = {...(next[groupId] || {})};
    matrix[rowId] = {...(matrix[rowId] || {}), [colId]: value};
    next[groupId] = matrix;
  } else if (kind === EDIT_CELL_DESC) {
    const [groupId, rowId, colId, value] = args;
    const matrix = {...(next[groupId] || {})};
    matrix[rowId] = {...(matrix[rowId] || {}), [colId + DESC_SUFFIX]: value};
    next[groupId] = matrix;
  }
  return next;
}

/**
 * 表单渲染主体：form 结构 + values → 分组段落。
 * onEdit 缺省 no-op（预览/只读）；editable 控制输入禁用。
 * 分组角标与 PDF 样张（后端 _KIND_TAG）、编辑器词汇统一（设计方案 2.3）。
 */
export default function FormFillRenderer({form, values, editable = false, onEdit, narrow = false}) {
  const noop = () => {};
  const handleEdit = editable ? (onEdit || noop) : noop;
  return (
    <div>
      {(form.groups || []).map(group => (
        <div key={group.id} style={{marginBottom: 20}}>
          <div style={{marginBottom: 10, paddingBottom: 6, borderBottom: '1px solid #f0f0f0'}}>
            <span style={{fontSize: 14, fontWeight: 600}}>{group.name}</span>
            {group.kind === GROUP_KIND.REPEAT ? (
              <span style={{color: '#999', marginLeft: 8, fontSize: 12}}>可重复明细</span>
            ) : null}
            {group.kind === GROUP_KIND.MATRIX ? (
              <span style={{color: '#999', marginLeft: 8, fontSize: 12}}>检查对比表</span>
            ) : null}
            {group.description ? (
              <span style={{color: '#999', marginLeft: 8, fontSize: 12}}>{group.description}</span>
            ) : null}
          </div>
          {group.kind === GROUP_KIND.MATRIX ? (
            <MatrixGroup group={group} values={values} editable={editable}
                         onEdit={handleEdit} narrow={narrow}/>
          ) : group.kind === GROUP_KIND.REPEAT ? (
            <RepeatGroup group={group} values={values} editable={editable} onEdit={handleEdit}/>
          ) : (
            <div>
              {(group.fields || []).map(field => (
                <FieldRow key={field.id} group={group} field={field} values={values}
                          editable={editable} onEdit={handleEdit}/>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
