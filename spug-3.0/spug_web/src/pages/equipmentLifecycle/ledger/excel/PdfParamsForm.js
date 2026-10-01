/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * PDF 打印参数表单（受控组件，2026-09-30；2026-10-01 打印模式扩展）。
 *
 * 模板工作区「PDF参数」抽屉与台账导出「高级设置」弹窗共用：value 为
 * normalizePdfParams 产出的表单态，onChange 回传新表单态；提交序列化
 * （serializePdfParams）由调用方负责。字段口径与后端 excel_pdf_params
 * 校验一致，最终以服务端校验为准。
 *
 * 打印模式（preset）：
 * - original（原始 Excel 打印设置）：详细字段全部禁用——导出时服务端
 *   整体跳过参数应用，完全沿用上传文件页面设置；
 * - a4_auto / single_page：选择时自动填充对应纸张/方向/缩放字段，
 *   详细字段仍可微调（模式作为默认值模板）；
 * - custom：逐项自定义。
 */
import React from 'react';
import {Checkbox, Col, Input, InputNumber, Radio, Row, Select} from 'antd';
import {
  MARGIN_FIELDS,
  ORIENTATION_OPTIONS,
  PAGE_ORDER_OPTIONS,
  PAPER_SIZE_OPTIONS,
  PRESET_OPTIONS,
  SCALE_MODE_OPTIONS,
  presetFieldValues,
} from './pdfParams';

const itemStyle = {marginBottom: 10};

function Field({label, children}) {
  return (
    <div style={itemStyle}>
      <div>{label}</div>
      {children}
    </div>
  );
}

/** 纸张/方向/页边距（页面设置组）。 */
function PageSetupFields({value, disabled, set, setMargin}) {
  const margins = value.margins || {};
  return (
    <div>
      <Row gutter={12}>
        <Col span={12}>
          <Field label="纸张大小">
            <Select style={{width: '100%'}} value={value.paper_size}
                    disabled={disabled}
                    onChange={next => set('paper_size', next)}>
              {PAPER_SIZE_OPTIONS.map(item => (
                <Select.Option key={item.value} value={item.value}>
                  {item.label}
                </Select.Option>
              ))}
            </Select>
          </Field>
        </Col>
        <Col span={12}>
          <Field label="纸张方向">
            <Radio.Group value={value.orientation} disabled={disabled}
                         onChange={e => set('orientation', e.target.value)}>
              {ORIENTATION_OPTIONS.map(item => (
                <Radio key={item.value} value={item.value}>{item.label}</Radio>
              ))}
            </Radio.Group>
          </Field>
        </Col>
      </Row>
      <Field label="页边距（厘米，0-10）">
        <Row gutter={8}>
          {MARGIN_FIELDS.map(item => (
            <Col span={8} key={item.key} style={{marginBottom: 8}}>
              <div style={{fontSize: 12, color: '#888'}}>{item.label}</div>
              <InputNumber style={{width: '100%'}} min={0} max={10} step={0.1}
                           value={margins[item.key]} disabled={disabled}
                           onChange={next => setMargin(item.key, next)}/>
            </Col>
          ))}
        </Row>
      </Field>
    </div>
  );
}

/** 缩放/重复表头/打印区域/分页/居中（分页与输出组）。 */
function ScaleAndPaginationFields({value, disabled, set}) {
  return (
    <div>
      <Row gutter={12}>
        <Col span={value.scale_mode === 'percent' ? 12 : 24}>
          <Field label="缩放方式">
            <Select style={{width: '100%'}} value={value.scale_mode}
                    disabled={disabled}
                    onChange={next => set('scale_mode', next)}>
              {SCALE_MODE_OPTIONS.map(item => (
                <Select.Option key={item.value} value={item.value}>
                  {item.label}
                </Select.Option>
              ))}
            </Select>
          </Field>
        </Col>
        {value.scale_mode === 'percent' && (
          <Col span={12}>
            <Field label="缩放百分比（10-400）">
              <InputNumber style={{width: '100%'}} min={10} max={400}
                           value={value.scale_percent} disabled={disabled}
                           onChange={next => set('scale_percent', next)}/>
            </Field>
          </Col>
        )}
      </Row>
      <Field label="重复表头行（每页顶部重复，如 1:2；留空不重复）">
        <Input value={value.repeat_header_rows} maxLength={20}
               placeholder="如 1:2" disabled={disabled}
               onChange={e => set('repeat_header_rows', e.target.value)}/>
      </Field>
      <Field label="打印区域（如 A1:E25；留空保持源文件设置）">
        <Input value={value.print_area} maxLength={200}
               placeholder="如 A1:E25" disabled={disabled}
               onChange={e => set('print_area', e.target.value)}/>
      </Field>
      <Row gutter={12}>
        <Col span={12}>
          <Field label="分页顺序">
            <Select style={{width: '100%'}} value={value.page_order}
                    disabled={disabled}
                    onChange={next => set('page_order', next)}>
              {PAGE_ORDER_OPTIONS.map(item => (
                <Select.Option key={item.value} value={item.value}>
                  {item.label}
                </Select.Option>
              ))}
            </Select>
          </Field>
        </Col>
        <Col span={12}>
          <Field label="手动分页行（逗号分隔行号，可留空）">
            <Input value={value.row_breaks_text} maxLength={200}
                   placeholder="如 20,40" disabled={disabled}
                   onChange={e => set('row_breaks_text', e.target.value)}/>
          </Field>
        </Col>
      </Row>
      <Field label="页面居中">
        <span>
          <Checkbox checked={!!value.horizontal_centered} disabled={disabled}
                    onChange={e => set('horizontal_centered', e.target.checked)}>
            水平居中
          </Checkbox>
          <Checkbox checked={!!value.vertical_centered} disabled={disabled}
                    onChange={e => set('vertical_centered', e.target.checked)}>
            垂直居中
          </Checkbox>
        </span>
      </Field>
    </div>
  );
}

export default function PdfParamsForm({value, onChange, disabled}) {
  const original = value.preset === 'original';
  const set = (key, next) => onChange({...value, [key]: next});
  const setMargin = (key, next) => onChange(
    {...value, margins: {...value.margins, [key]: next}});
  const changePreset = preset => onChange(
    {...value, preset, ...presetFieldValues(preset)});
  return (
    <div className="pdf-params-form" data-testid="pdf-params-form">
      <Field label="打印模式">
        <Select style={{width: '100%'}} value={value.preset || 'custom'}
                disabled={disabled} onChange={changePreset}>
          {PRESET_OPTIONS.map(item => (
            <Select.Option key={item.value} value={item.value}>
              {item.label}
            </Select.Option>
          ))}
        </Select>
      </Field>
      {original && (
        <div style={{color: '#999', marginBottom: 10}}>
          使用上传文件已有的页面设置（纸张/方向/边距/缩放以 Excel/WPS 中
          的打印设置为准），以下详细字段不生效。
        </div>
      )}
      <PageSetupFields value={value} disabled={disabled || original}
                       set={set} setMargin={setMargin}/>
      <ScaleAndPaginationFields value={value} disabled={disabled || original}
                                set={set}/>
    </div>
  );
}
