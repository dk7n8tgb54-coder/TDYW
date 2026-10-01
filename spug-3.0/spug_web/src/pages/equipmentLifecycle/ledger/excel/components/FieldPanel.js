/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 字段绑定属性面板（Excel/WPS 维护台账路线共享组件，2026-10-01 自模板
 * 导入验证原型迁出；2026-09-29 协议收敛）。
 *
 * 选中单元格后配置维护填写字段属性：名称、输入类型、必填、单位、
 * 候选项；已绑定单元格支持编辑（field_id 保持不变）与 Popconfirm
 * 明确确认后删除绑定。default_value/operation_guide/abnormal_rule/
 * maintenance_cycles 已退役，不再提供控件、不再写入绑定载荷。
 * 父组件以 key={coord+fieldId} 挂载，切换单元格即重置表单。
 */
import React, {useState} from 'react';
import {Button, Checkbox, Input, Popconfirm, Select, Tag} from 'antd';

const INPUT_TYPES = [
  {value: 'text', label: '文本'},
  {value: 'number', label: '数值'},
  {value: 'choice', label: '单选'},
  {value: 'status', label: '正常/异常'},
  {value: 'date', label: '日期'},
];

const panelTitleStyle = {fontWeight: 'bold', margin: '12px 0 6px'};
const itemStyle = {marginBottom: 10};

function initialValues(binding, props) {
  return {
    field_name: binding ? binding.field_name : (props.headerText || ''),
    input_type: binding ? binding.input_type : 'text',
    is_required: binding ? !!binding.is_required : false,
    unit: binding ? binding.unit : '',
    options: binding ? (binding.options || []) : [],
  };
}

/** 字段属性表单区（纯展示，值与变更由面板统一管理）。 */
function BindingFields({form, setField}) {
  return (
    <div>
      <div style={itemStyle}>
        <div>字段名称</div>
        <Input value={form.field_name} maxLength={50} placeholder="如：PS模块"
               onChange={e => setField('field_name', e.target.value)}/>
      </div>
      <div style={itemStyle}>
        <div>输入类型</div>
        <Select style={{width: '100%'}} value={form.input_type}
                onChange={value => setField('input_type', value)}>
          {INPUT_TYPES.map(item => (
            <Select.Option key={item.value} value={item.value}>{item.label}</Select.Option>
          ))}
        </Select>
      </div>
      <div style={itemStyle}>
        <Checkbox checked={form.is_required}
                  onChange={e => setField('is_required', e.target.checked)}>必填字段</Checkbox>
      </div>
      <div style={itemStyle}>
        <div>单位（数值类型）</div>
        <Input value={form.unit} maxLength={20} placeholder="如：V、dB"
               onChange={e => setField('unit', e.target.value)}/>
      </div>
      {form.input_type === 'choice' && (
        <div style={itemStyle}>
          <div>候选项</div>
          <Select mode="tags" style={{width: '100%'}} value={form.options}
                  placeholder="输入后回车添加"
                  onChange={values => setField('options', values)}/>
        </div>
      )}
    </div>
  );
}

export default function FieldPanel(props) {
  const {coord, binding, blockReason, saving, onSave, onRemove} = props;
  const [form, setForm] = useState(() => initialValues(binding, props));
  const setField = (key, value) => setForm(prev => ({...prev, [key]: value}));

  const handleSave = async () => {
    try {
      await onSave(form);
    } catch (e) {
      // 保存失败：公共拦截器已提示，本地已回退；保留当前填写便于修正
    }
  };

  const handleRemove = async () => {
    try {
      await onRemove();
    } catch (e) {
      // 删除失败：公共拦截器已提示
    }
  };

  return (
    <div className="proto-field-panel" style={{width: 300, flexShrink: 0}}>
      <div style={panelTitleStyle}>
        单元格 <Tag color="blue">{coord || '未选择'}</Tag>
        {binding && <Tag color="green">已绑定</Tag>}
      </div>
      {!coord && <div style={{color: '#999'}}>点击左侧表格中的空白单元格进行绑定</div>}
      {coord && blockReason && (
        <div style={{color: '#fa541c', marginBottom: 8}}>{blockReason}</div>
      )}
      {coord && !blockReason && (
        <div>
          <BindingFields form={form} setField={setField}/>
          <div style={{display: 'flex', gap: 8}}>
            <Button type="primary" loading={saving} disabled={!form.field_name.trim()}
                    onClick={handleSave}>
              {binding ? '更新绑定' : '保存绑定'}
            </Button>
            {binding && (
              <Popconfirm title="确定删除该字段绑定？删除后需重新配置。"
                          onConfirm={handleRemove}
                          okText="删除" cancelText="取消">
                <Button danger>删除绑定</Button>
              </Popconfirm>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
