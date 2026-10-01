/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 批量绑定面板（2026-09-29）。
 *
 * 多选单元格（Ctrl/Cmd 加选、拖拽矩形）后，用同一组字段属性一次绑定：
 * - 显示选中数量与「坐标 → 字段名」预览列表；
 * - 字段命名规则：多格=「前缀-坐标」（按行列排序），单格保留前缀原样；
 * - 保存走整体绑定接口（PUT bindings），服务端为校验权威，失败由公共
 *   拦截器提示一次，本地状态由 store 回退；本面板不做最终校验承诺。
 */
import React, {useState} from 'react';
import {Button, Checkbox, Input, Select, Tag} from 'antd';

import {batchFieldNames, sortCoords} from './excelTemplateStore';

const INPUT_TYPES = [
  {value: 'text', label: '文本'},
  {value: 'number', label: '数值'},
  {value: 'choice', label: '单选'},
  {value: 'status', label: '正常/异常'},
  {value: 'date', label: '日期'},
];

const panelTitleStyle = {fontWeight: 'bold', margin: '12px 0 6px'};
const itemStyle = {marginBottom: 10};

export default function BatchBindingPanel(props) {
  const {selectedCells, saving, onSave, onClear} = props;
  const [form, setForm] = useState({
    field_name: '',
    input_type: 'text',
    is_required: false,
    unit: '',
    options: [],
  });
  const setField = (key, value) => setForm(prev => ({...prev, [key]: value}));

  const coords = sortCoords(selectedCells);
  // 单格保留前缀原样；多格生成「前缀-坐标」
  const names = form.field_name.trim()
    ? batchFieldNames(form.field_name.trim(), coords) : [];
  const preview = coords.map((coordinate, index) => ({
    coordinate,
    field_name: names[index] || '',
  }));
  const choiceMissingOptions = form.input_type === 'choice' && !form.options.length;

  const handleSave = async () => {
    try {
      await onSave(form);
    } catch (e) {
      // 保存失败：公共拦截器已提示一次，本地已回退；保留填写便于修正
    }
  };

  return (
    <div className="proto-field-panel" style={{width: 300, flexShrink: 0}}>
      <div style={panelTitleStyle}>
        批量绑定 <Tag color="blue">已选 {coords.length} 格</Tag>
      </div>
      <div style={{color: '#999', marginBottom: 8}}>
        多格生成「前缀-坐标」字段名；仅选一个单元格时直接使用前缀作为字段名。
      </div>
      <div style={itemStyle}>
        <div>字段名称前缀</div>
        <Input data-testid="batch-prefix" value={form.field_name} maxLength={44}
               placeholder="如：主电台 PS"
               onChange={e => setField('field_name', e.target.value)}/>
      </div>
      <div style={itemStyle}>
        <div>输入类型</div>
        <Select data-testid="batch-input-type" style={{width: '100%'}}
                value={form.input_type}
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
        <Input data-testid="batch-unit" value={form.unit} maxLength={20}
               placeholder="如：V、dB"
               onChange={e => setField('unit', e.target.value)}/>
      </div>
      {form.input_type === 'choice' && (
        <div style={itemStyle}>
          <div>候选项</div>
          <Select data-testid="batch-options" mode="tags" style={{width: '100%'}}
                  value={form.options} placeholder="输入后回车添加"
                  onChange={values => setField('options', values)}/>
          {choiceMissingOptions && (
            <div style={{color: '#fa541c'}}>单选类型必须提供候选项</div>
          )}
        </div>
      )}
      <div style={itemStyle}>
        <div>预览（{coords.length} 个字段）</div>
        <div data-testid="batch-preview"
             style={{maxHeight: 180, overflow: 'auto', border: '1px solid #eee',
                     padding: '4px 8px', fontSize: 12}}>
          {preview.map(item => (
            <div key={item.coordinate}>
              {item.coordinate} → {item.field_name}
            </div>
          ))}
        </div>
      </div>
      <div style={{display: 'flex', gap: 8}}>
        <Button data-testid="batch-save" type="primary" loading={saving}
                disabled={!form.field_name.trim() || !coords.length || choiceMissingOptions}
                onClick={handleSave}>
          保存批量绑定
        </Button>
        <Button data-testid="batch-clear" onClick={onClear}>清空选择</Button>
      </div>
    </div>
  );
}
