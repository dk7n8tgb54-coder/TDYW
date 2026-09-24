/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 台账明细行表格（单一系统分组内）：仅填写值录入。LedgerForm（弹窗表单）
 * 与 LedgerWorksheet（常驻工作台）共用，行内交互行为保持一致。
 * 结果/异常说明/现场处理/执行人列已移除（结果由后端按填写值派生）；
 * 操作列仅临时补录行显示移除按钮。
 */
import React from 'react';
import {Input, InputNumber, Select, Table, Tooltip, Space} from 'antd';
import {DeleteOutlined} from '@ant-design/icons';
import {parseFreeValue, rowLooksAbnormal} from './ledgerCommon';

const {Option} = Select;

function ValueControl({row, onSetRow}) {
  switch (row.input_type) {
    case 'number':
      return (
        <InputNumber
          style={{width: '100%'}}
          value={row.value_number}
          onChange={v => onSetRow(row.client_key, {value_number: v})}/>
      );
    case 'choice':
      return (
        <Select
          style={{width: '100%'}} allowClear value={row.value_text || undefined}
          onChange={v => onSetRow(row.client_key, {value_text: v || ''})}>
          {(row.choices || []).map(c => <Option value={c} key={c}>{c}</Option>)}
        </Select>
      );
    case 'multi_choice':
      return (
        <Select
          mode="multiple" style={{width: '100%'}}
          value={row.value_text ? JSON.parse(row.value_text || '[]') : []}
          onChange={v => onSetRow(row.client_key, {value_text: JSON.stringify(v)})}>
          {(row.choices || []).map(c => <Option value={c} key={c}>{c}</Option>)}
        </Select>
      );
    case 'boolean':
      return (
        <Select
          style={{width: '100%'}} allowClear
          value={row.value_bool === null || row.value_bool === undefined ? undefined : !!row.value_bool}
          onChange={v => onSetRow(row.client_key, {value_bool: v === undefined ? null : v})}>
          <Option value={true}>是</Option>
          <Option value={false}>否</Option>
        </Select>
      );
    case 'attachment':
      return <Input disabled placeholder="保存台账后通过明细附件上传" value=""/>;
    default:
      return <Input value={row.value_text} onChange={e => onSetRow(row.client_key, parseFreeValue(e.target.value))}/>;
  }
}

export default function LedgerRowsTable({rows, onSetRow, onRemoveRow}) {
  // 全空列直接裁掉：纯状态确认类台账（项目全是单选）没有单位可填
  const hasUnit = rows.some(r => r.unit);
  // 操作列仅在分组内存在临时补录行时显示（模板展开行不可移除）
  const hasTemporary = rows.some(r => r.is_temporary);
  const columns = [
    {
      title: '检查/维护项目', key: 'item', width: 180,
      render: (t, r) => (
        <Space size={2} direction="vertical" style={{width: '100%'}}>
          {(r.is_temporary || !r.id) && !r.template_item_id ? (
            <Input size="small" placeholder="项目名称" value={r.item_name} onChange={e => onSetRow(r.client_key, {item_name: e.target.value})}/>
          ) : <span>{r.item_name}</span>}
        </Space>
      ),
    },
    ...(hasUnit ? [{title: '单位', dataIndex: 'unit', width: 60, render: v => v || '-'}] : []),
    {title: '填写值', key: 'value', width: 130, render: (t, r) => <ValueControl row={r} onSetRow={onSetRow}/>},
    ...(hasTemporary ? [{
      title: '操作', key: 'action', width: 50, align: 'center',
      render: (t, r) => r.is_temporary ? (
        <Tooltip title="移除该明细">
          <a style={{color: '#f5222d'}} onClick={() => onRemoveRow(r.client_key)}><DeleteOutlined/></a>
        </Tooltip>
      ) : null,
    }] : []),
  ];
  return (
    <Table
      rowKey="client_key" size="small"
      columns={columns} dataSource={rows} pagination={false}
      rowClassName={r => (rowLooksAbnormal(r) ? 'el-ledger-abnormal-row' : '')}/>
  );
}
