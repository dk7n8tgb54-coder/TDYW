/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 打印设置与预览抽屉（2026-10-19 自 ExcelTemplatePage 拆出，控制主页面
 * 文件规模）：
 * - 打印参数表单（PdfParamsForm）+ 保存（写入草稿，发布随版本快照固定）；
 * - 「应用当前设置并预览」（2026-10-19）：以表单当前值（含未保存修改）+
 *   临时样例数据请求真实 PDF，后端只作用于本次预览副本，不写草稿；
 *   与工作区「预览空白打印稿」（已保存参数）入口区分，未保存修改有
 *   独立提示；
 * - 临时预览数据（可选）：按已绑定字段类型逐项输入（长文本字段用多行
 *   文本框），只用于本次预览，不写模板草稿、不影响发布与台账；
 * - 预览反馈：页数/纸张来自后端真实生成的 PDF，提示为按本次实际参数的
 *   版式预检结果（不伪造预览结果）。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {
  Alert, Button, Drawer, Input, InputNumber, Select, Space,
} from 'antd';
import {FilePdfOutlined} from '@ant-design/icons';

import {formatPaperText} from './excelTemplateStore';
import PdfParamsForm from './PdfParamsForm';

/**
 * 预览反馈 Alert（工作区与抽屉共用）：参数来源 + 实际页数/纸张 +
 * 版式预检提示；无反馈时不渲染。
 */
export function PreviewInfoAlert({info}) {
  if (!info) return null;
  const summaryParts = [];
  if (info.pages) summaryParts.push(`共 ${info.pages} 页`);
  const paperText = formatPaperText(info.paper);
  if (paperText) summaryParts.push(`纸张 ${paperText}`);
  const warnings = info.warnings || [];
  return (
    <Alert data-testid="tpl-pdf-preview-info" showIcon
           style={{marginBottom: 12}}
           type={warnings.length ? 'warning' : 'success'}
           message={`预览已生成（参数来源：${info.source === 'form' ? '当前未保存参数' : '已保存参数'}）${summaryParts.length ? '：' + summaryParts.join('，') : ''}`}
           description={warnings.length ? (
             <div>
               {warnings.map((text, index) => <div key={index}>{text}</div>)}
             </div>
           ) : null}/>
  );
}

@observer
class PdfParamsDrawer extends React.Component {
  get store() {
    return this.props.store;
  }

  /** 预览反馈：抽屉内展示（工作区预览后同样可见该状态）。 */
  renderPreviewInfoAlert() {
    return <PreviewInfoAlert info={this.store.previewInfo}/>;
  }

  /** 样例值编辑器：text 多行文本框 / number 数值 / date 文本 / choice+status 选择。 */
  renderSampleEditor(binding) {
    const store = this.store;
    const value = (store.sampleForm || {})[binding.field_id] || '';
    const testId = `tpl-sample-${binding.field_id}`;
    const setValue = next => store.setSampleValue(binding.field_id, next);
    if (binding.input_type === 'text') {
      return (
        <Input.TextArea rows={3} data-testid={testId} value={value}
                        maxLength={2000}
                        placeholder="输入临时样例内容，验证长文本换行与分页"
                        onChange={e => setValue(e.target.value)}/>
      );
    }
    if (binding.input_type === 'number') {
      return (
        <InputNumber style={{width: '100%'}} data-testid={testId} value={value}
                     onChange={next => setValue(next)}/>
      );
    }
    if (binding.input_type === 'date') {
      return (
        <Input data-testid={testId} value={value} placeholder="YYYY-MM-DD"
               onChange={e => setValue(e.target.value)}/>
      );
    }
    return (
      <Select style={{width: '100%'}} allowClear data-testid={testId}
              value={value || undefined} placeholder="选择临时样例值"
              onChange={next => setValue(next || '')}>
        {(binding.options || []).map(option => (
          <Select.Option key={option} value={option}>{option}</Select.Option>
        ))}
      </Select>
    );
  }

  /**
   * 临时预览数据区（可选）：只用于本次 PDF 预览，不写模板草稿、
   * 不影响发布与台账；留空则预览空白打印稿。
   */
  renderSampleSection() {
    const store = this.store;
    const bindings = store.bindings || [];
    return (
      <div data-testid="tpl-pdf-sample" style={{marginTop: 16, borderTop: '1px solid #f0f0f0', paddingTop: 12}}>
        <div style={{marginBottom: 4}}><strong>临时预览数据（可选）</strong></div>
        <div style={{color: '#999', marginBottom: 10}}>
          只用于本次 PDF 预览（如长文本换行效果），不保存到模板或台账；
          全部留空时预览空白打印稿。
        </div>
        {bindings.length === 0 && (
          <div style={{color: '#999'}}>暂无绑定字段，预览为空白打印稿。</div>
        )}
        {bindings.map(binding => (
          <div key={binding.field_id} style={{marginBottom: 10}}>
            <div style={{marginBottom: 2}}>
              {`${binding.field_name}（${binding.cell_coordinate}${binding.is_required ? ' · 必填' : ''}）`}
            </div>
            {this.renderSampleEditor(binding)}
          </div>
        ))}
      </div>
    );
  }

  render() {
    const store = this.store;
    return (
      <Drawer title="打印设置与预览" width={560} visible={store.pdfDrawerVisible}
              onClose={() => store.closePdfDrawer()}>
        <div style={{color: '#999', marginBottom: 12}}>
          导出 PDF 与草稿预览默认使用以下参数；发布后随版本快照固定，
          历史台账不受后续修改影响。
          「应用当前设置并预览」使用表单当前值（含未保存修改），工作区
          「预览空白打印稿」按钮使用已保存参数；两者都只在临时副本上生成，
          不写入草稿或版本。
        </div>
        {store.pdfFormDirty && (
          <div data-testid="tpl-pdf-dirty" style={{color: '#fa8c16', marginBottom: 8}}>
            当前有未保存修改：预览按表单当前值生成，保存后才对导出与发布生效。
          </div>
        )}
        {store.pdfForm && (
          <PdfParamsForm value={store.pdfForm}
                         onChange={form => store.setPdfForm(form)}/>
        )}
        <div style={{textAlign: 'right', marginTop: 8}}>
          <Space>
            <Button onClick={() => store.closePdfDrawer()}>取消</Button>
            <Button data-testid="tpl-pdf-params-save" type="primary"
                    loading={store.savingPdfParams}
                    onClick={() => store.savePdfParams().catch(() => {})}>
              保存
            </Button>
          </Space>
        </div>
        {this.renderSampleSection()}
        <div style={{borderTop: '1px solid #f0f0f0', marginTop: 12, paddingTop: 12}}>
          <Button data-testid="tpl-pdf-preview-form" icon={<FilePdfOutlined/>}
                  block loading={store.previewing}
                  onClick={() => store.previewWithFormParams().catch(() => {})}>
            应用当前设置并预览
          </Button>
          <div style={{color: '#999', marginTop: 6}}>
            使用上方表单当前值与临时样例数据生成真实 PDF（只读，不保存）。
          </div>
        </div>
        {this.renderPreviewInfoAlert()}
      </Drawer>
    );
  }
}

export default PdfParamsDrawer;
