/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 列项目配置气泡（模板可视化设计表格）：点击列标题配置该列的填写规则。
 * - 字段：项目名称 / 录入类型 / 必填 / 单位 / 候选项 / 操作指导 /
 *   异常判定规则 / 默认值；
 * - 录入类型收敛为两种：正常/不正常(choice，候选项固定)与数字/文本(text)；
 *   历史类型仅对已有列回显；切换类型时清掉不再适用的字段；
 * - 管理动作：上移/下移（同级排序）、停用/启用、删除（仅新建模板的本地草稿，
 *   编辑模式以停用代替删除，保存时机见模板表单提示）；
 * - 周期维度说明：周月维护已合并（2026-09-26），列项目不再有"仅每周/仅每月"
 *   执行范围，启用列参与台账类型的每一次生成。
 */
import React from 'react';
import {Popover, Input, Select, Checkbox, Tag, Button, Popconfirm} from 'antd';
import {
  SettingOutlined, ArrowUpOutlined, ArrowDownOutlined,
  StopOutlined, PlayCircleOutlined, DeleteOutlined,
} from '@ant-design/icons';
import {
  INPUT_TYPE_TEXT, NORMAL_ABNORMAL_CHOICES, TEMPLATE_INPUT_TYPE_KEYS,
} from './constants';

const {Option} = Select;
const {TextArea} = Input;

/** 切换录入类型时清掉不再适用的字段；正常/不正常候选项固定不可配置。 */
export function typePatch(inputType) {
  const patch = {input_type: inputType};
  if (inputType !== 'text' && inputType !== 'number') {
    patch.unit = '';
  }
  patch.choices = inputType === 'choice' ? [...NORMAL_ABNORMAL_CHOICES] : [];
  return patch;
}

function FieldRow({label, children}) {
  return (
    <div style={{marginBottom: 6}}>
      <div style={{fontSize: 12, color: '#666', marginBottom: 2}}>{label}</div>
      {children}
    </div>
  );
}

/** 列填写规则表单（受控，patch 经 onChange 上抛）。 */
function ConfigForm({item, onChange}) {
  const isMeasure = item.input_type === 'text' || item.input_type === 'number';
  const isHistorical = !TEMPLATE_INPUT_TYPE_KEYS.includes(item.input_type);
  return (
    <div style={{width: 260}}>
      <FieldRow label="项目名称">
        <Input size="small" placeholder="请输入项目名称" value={item.name}
               onChange={e => onChange({name: e.target.value})}/>
      </FieldRow>
      <FieldRow label="录入类型">
        <Select
          size="small" style={{width: '100%'}} value={item.input_type}
          onChange={v => onChange(typePatch(v))}>
          {TEMPLATE_INPUT_TYPE_KEYS.map(k => (
            <Option value={k} key={k}>{INPUT_TYPE_TEXT[k]}</Option>))}
          {isHistorical && (
            <Option value={item.input_type} key={item.input_type}>
              {INPUT_TYPE_TEXT[item.input_type] || item.input_type}（历史）
            </Option>
          )}
        </Select>
      </FieldRow>
      <FieldRow label="必填">
        <Checkbox
          checked={item.is_required}
          onChange={e => onChange({is_required: e.target.checked})}/>
      </FieldRow>
      <FieldRow label="单位">
        {isMeasure ? (
          <Input size="small" placeholder="如 V、dBm" value={item.unit || ''}
                 onChange={e => onChange({unit: e.target.value})}/>
        ) : <span style={{color: '#ccc'}}>—</span>}
      </FieldRow>
      {(item.input_type === 'choice' || item.input_type === 'multi_choice') && (
        <FieldRow label="候选项">
          <Input
            size="small" disabled
            value={item.input_type === 'choice'
              ? `${NORMAL_ABNORMAL_CHOICES.join(' / ')}（固定）`
              : (item.choices || []).join('、')}/>
        </FieldRow>
      )}
      <FieldRow label="操作指导">
        <TextArea
          rows={2} maxLength={500} value={item.operation_guide || ''}
          onChange={e => onChange({operation_guide: e.target.value})}/>
      </FieldRow>
      <FieldRow label="异常判定规则">
        <Input size="small" maxLength={200} value={item.abnormal_rule || ''}
               onChange={e => onChange({abnormal_rule: e.target.value})}/>
      </FieldRow>
      <FieldRow label="默认值">
        <Input size="small" maxLength={200} value={item.default_value || ''}
               onChange={e => onChange({default_value: e.target.value})}/>
      </FieldRow>
    </div>
  );
}

/**
 * 列标题配置气泡：触发元素为列名（含单位与停用标记），
 * onDelete 提供时才展示删除（仅本地草稿）；其余动作可选。
 */
export default function ColumnConfigPopover({
  item, onChange, onMoveUp, onMoveDown, onToggleActive, onDelete,
}) {
  if (!item) return null;
  const displayName = String(item.name || '').trim() || '未命名项目';
  const content = (
    <div>
      <ConfigForm item={item} onChange={onChange}/>
      <div style={{marginTop: 8, paddingTop: 8, borderTop: '1px solid #f0f0f0'}}>
        <Button size="small" type="link" icon={<ArrowUpOutlined/>}
                title="上移" onClick={onMoveUp}/>
        <Button size="small" type="link" icon={<ArrowDownOutlined/>}
                title="下移" onClick={onMoveDown}/>
        {onToggleActive && (
          item.is_active === false ? (
            <Button size="small" type="link" icon={<PlayCircleOutlined/>}
                    onClick={onToggleActive}>启用</Button>
          ) : (
            <Popconfirm
              title="停用后该列不参与台账生成，确定停用？"
              onConfirm={onToggleActive}>
              <Button size="small" type="link" icon={<StopOutlined/>}>停用</Button>
            </Popconfirm>
          )
        )}
        {onDelete && (
          <Popconfirm title="确定删除该列？" onConfirm={onDelete}>
            <Button size="small" type="link" title="删除" icon={<DeleteOutlined/>}
                    style={{color: '#f5222d'}}/>
          </Popconfirm>
        )}
      </div>
    </div>
  );
  return (
    <Popover trigger="click" placement="bottom" content={content}>
      <a
        className="el-design-col-trigger" title="点击配置该列"
        onClick={e => e.stopPropagation()}>
        {displayName}
        {item.unit ? <span style={{color: '#999'}}>（{item.unit}）</span> : null}
        {item.is_active === false && (
          <Tag color="default" style={{marginRight: 0, marginLeft: 4}}>已停用</Tag>
        )}
        <SettingOutlined style={{marginLeft: 4, color: '#1890ff'}}/>
      </a>
    </Popover>
  );
}
