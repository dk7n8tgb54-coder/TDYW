/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 批量绑定/修改面板（2026-09-29；2026-10-19 名称自动生成；同日混合选区改版）。
 *
 * 多选单元格（Ctrl/Cmd 加选、拖拽矩形，已绑定与未绑定格可混合）后统一保存：
 * - 摘要行显示选中总数、已绑定数与未绑定数；
 * - 已绑定格保留 field_id 与自定义字段名称，仅更新在本面板明确修改过的
 *   属性（输入类型/必填/单位/候选项，touched 语义，由 store 落实）；
 * - 字段命名规则（仅作用于未绑定的新建格）：名称前缀可选——留空时每格
 *   默认名「工作表名 · 坐标」；填写前缀后多格=「前缀-坐标」（按行列
 *   排序）、单格保留前缀原样；
 * - 批量解绑为独立操作：Popconfirm 确认后才移除选区内已绑定字段；
 * - 保存走整体绑定接口（PUT bindings），服务端为校验权威，失败由公共
 *   拦截器提示一次，本地状态由 store 回退；本面板不做最终校验承诺。
 */
import React, {useState} from 'react';
import {Button, Checkbox, Input, Popconfirm, Select, Tag} from 'antd';

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

/** 批量字段属性表单区（纯展示，值与变更经 setField 统一上报 touched）。 */
function BatchAttributeFields({form, setField, choiceMissingOptions}) {
  return (
    <div>
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
    </div>
  );
}

export default function BatchBindingPanel(props) {
  const {selectedCells, sheetName, bindingByCell, saving, onSave, onUnbind, onClear} = props;
  const [form, setForm] = useState({
    field_name: '',
    input_type: 'text',
    is_required: false,
    unit: '',
    options: [],
  });
  // 用户在本面板明确修改过的属性（仅这些属性会更新到选区内已有绑定，
  // 名称/编号始终保留；新绑定不受影响，未触碰属性使用表单默认值）
  const [touched, setTouched] = useState({});
  const setField = (key, value) => {
    setForm(prev => ({...prev, [key]: value}));
    setTouched(prev => (prev[key] ? prev : {...prev, [key]: true}));
  };

  const coords = sortCoords(selectedCells);
  const boundByCoord = {};
  const freshCoords = [];
  coords.forEach(coordinate => {
    const binding = (bindingByCell || {})[`${sheetName}!${coordinate}`];
    if (binding) boundByCoord[coordinate] = binding;
    else freshCoords.push(coordinate);
  });
  // 未绑定格按命名规则生成名称；已绑定格预览保留其自定义名称
  const freshNames = batchFieldNames(form.field_name, freshCoords, sheetName);
  const preview = coords.map(coordinate => ({
    coordinate,
    bound: !!boundByCoord[coordinate],
    field_name: boundByCoord[coordinate]
      ? boundByCoord[coordinate].field_name
      : freshNames[freshCoords.indexOf(coordinate)] || '',
  }));
  const boundCount = coords.length - freshCoords.length;
  const choiceMissingOptions = form.input_type === 'choice' && !form.options.length;

  const handleSave = async () => {
    try {
      await onSave({...form, touched});
    } catch (e) {
      // 保存失败：公共拦截器已提示一次，本地已回退；保留填写便于修正
    }
  };

  const handleUnbind = async () => {
    try {
      await onUnbind();
    } catch (e) {
      // 解绑失败：公共拦截器已提示，本地已回退
    }
  };

  return (
    <div className="proto-field-panel" style={{width: 300, flexShrink: 0}}>
      <div style={panelTitleStyle}>
        批量绑定 <Tag color="blue">已选 {coords.length} 格</Tag>
      </div>
      <div data-testid="batch-selection-summary" style={{marginBottom: 8}}>
        已选 {coords.length} 格：已绑定 {boundCount} · 未绑定 {freshCoords.length}
      </div>
      <div style={{color: '#999', marginBottom: 8}}>
        已绑定格保留字段名称与编号，仅更新下方明确修改过的属性；未绑定格新建绑定：
        名称留空时每格自动生成「工作表 · 坐标」；填写前缀则生成「前缀-坐标」，
        单格直接使用前缀。
      </div>
      <div style={itemStyle}>
        <div>新绑定字段名称前缀（可选）</div>
        <Input data-testid="batch-prefix" value={form.field_name} maxLength={44}
               placeholder="留空自动生成「工作表 · 坐标」"
               onChange={e => setField('field_name', e.target.value)}/>
      </div>
      <BatchAttributeFields form={form} setField={setField}
                            choiceMissingOptions={choiceMissingOptions}/>
      <div style={itemStyle}>
        <div>预览（{coords.length} 个字段）</div>
        <div data-testid="batch-preview"
             style={{maxHeight: 180, overflow: 'auto', border: '1px solid #eee',
                     padding: '4px 8px', fontSize: 12}}>
          {preview.map(item => (
            <div key={item.coordinate}>
              {item.coordinate} → {item.field_name}
              {item.bound ? '（已绑定·名称保留）' : ''}
            </div>
          ))}
        </div>
      </div>
      <div style={{display: 'flex', gap: 8, flexWrap: 'wrap'}}>
        <Button data-testid="batch-save" type="primary" loading={saving}
                disabled={!coords.length || choiceMissingOptions}
                onClick={handleSave}>
          保存批量绑定
        </Button>
        <Popconfirm
          title={`将解绑选区内 ${boundCount} 个已绑定字段，解绑后需重新配置，确定？`}
          onConfirm={handleUnbind} okText="解绑" cancelText="取消">
          <Button data-testid="batch-unbind" danger
                  disabled={saving || !boundCount}>
            批量解绑
          </Button>
        </Popconfirm>
        <Button data-testid="batch-clear" onClick={onClear}>清空选择</Button>
      </div>
    </div>
  );
}
