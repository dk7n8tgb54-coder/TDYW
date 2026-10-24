/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 数字表单模板检查器（2026-10-22）：右侧选中项详细设置面板。
 *
 * - 只承载选中对象的详细设置（名称/类型/必填/单位/候选项/说明等），
 *   复制/排序与删除入口在画布中选中对象上（见 FormTemplateCanvas）；
 * - selectionInfo 由编辑器经 resolveSelection 解析后传入（含当前对象
 *   引用），失效选中显示占位提示；
 * - 切换字段类型时清理不适用属性（非 number 清单位/范围/小数位、
 *   非 choice 清候选项、非 textarea 清行数、非 normal_abnormal 清
 *   "异常时说明必填"），与后端"不适用键出现即拒绝"约束一致；
 * - 协议 v2 类型化属性（2026-10-23 P2）：textarea 行数 rows、number
 *   数值范围 min/max 与小数位 precision、normal_abnormal 异常时说明
 *   必填（矩阵行同样适用，终验覆盖普通/明细/矩阵行三种载体）；
 * - 桌面为右侧固定面板；窄屏由编辑器放入抽屉渲染，交互一致。
 */
import React from 'react';
import {Checkbox, Empty, Input, InputNumber, Select, Tag} from 'antd';
import {
  FIELD_TYPE_OPTIONS, FIELD_TYPE_TEXT, GROUP_KIND, GROUP_KIND_TEXT,
  MATRIX_ROW_TYPE_OPTIONS, NUMBER_PRECISION_MAX,
  TEXTAREA_ROWS_DEFAULT, TEXTAREA_ROWS_MAX, TEXTAREA_ROWS_MIN,
} from './constants';

function PanelSection({title, extra, children}) {
  return (
    <div style={{marginBottom: 16}}>
      <div style={{fontWeight: 600, marginBottom: 8, display: 'flex',
                   alignItems: 'center', gap: 8}}>
        {title}
        {extra}
      </div>
      {children}
    </div>
  );
}

function FieldLabel({children}) {
  return <div style={{color: '#999', fontSize: 12, margin: '8px 0 4px'}}>{children}</div>;
}

/** 分组详细设置：名称/说明/明细条目名称。 */
function GroupInspector({selectionInfo, updateGroup}) {
  const group = selectionInfo.group;
  const patch = (p, label) => updateGroup(group.id, g => ({...g, ...p}), label);
  return (
    <PanelSection title="分组设置"
                  extra={<Tag>{GROUP_KIND_TEXT[group.kind]}</Tag>}>
      <FieldLabel>分组名称</FieldLabel>
      <Input data-testid="inspector-group-name" value={group.name} maxLength={60}
             onChange={e => patch({name: e.target.value}, `insp:${group.id}:name`)}/>
      <FieldLabel>分组说明（选填）</FieldLabel>
      <Input data-testid="inspector-group-description" value={group.description || ''}
             maxLength={200} placeholder="填写人会在分组标题旁看到该说明"
             onChange={e => patch({description: e.target.value},
               `insp:${group.id}:description`)}/>
      {group.kind === GROUP_KIND.REPEAT && (
        <div>
          <FieldLabel>明细条目名称</FieldLabel>
          <Input data-testid="inspector-group-item-name" value={group.item_name || ''}
                 maxLength={30} placeholder="如：测量项目"
                 onChange={e => patch({item_name: e.target.value},
                   `insp:${group.id}:item_name`)}/>
        </div>
      )}
    </PanelSection>
  );
}

/** 字段详细设置（普通/明细组字段与矩阵行共用；矩阵行无必填）。
 * 切换类型时清理不适用属性：非 number 清单位与 min/max/precision、
 * 非 choice 清候选项、非 textarea 清 rows、非 normal_abnormal 清
 * require_desc_when_abnormal（键值置 undefined，序列化即不提交），
 * 避免无效属性残留提交被后端拒绝。 */
function FieldInspector({selectionInfo, updateGroup, isMatrixRow}) {
  const field = selectionInfo.field;
  const group = selectionInfo.group;
  const labelPrefix = `insp:${group.id}:${field.id}`;
  const patch = (p, label) => updateGroup(group.id, g => ({
    ...g, fields: g.fields.map(f => f.id === field.id ? {...f, ...p} : f)}), label);
  const changeType = type => patch({
    type,
    unit: type === 'number' ? (field.unit || '') : '',
    options: type === 'choice' ? (field.options || []) : [],
    rows: type === 'textarea'
      ? (field.rows || TEXTAREA_ROWS_DEFAULT) : undefined,
    min: type === 'number' ? (field.min ?? null) : undefined,
    max: type === 'number' ? (field.max ?? null) : undefined,
    precision: type === 'number' ? (field.precision ?? null) : undefined,
    require_desc_when_abnormal:
      type === 'normal_abnormal' ? !!field.require_desc_when_abnormal : undefined,
  });
  const typeOptions = isMatrixRow ? MATRIX_ROW_TYPE_OPTIONS : FIELD_TYPE_OPTIONS;
  return (
    <PanelSection title={isMatrixRow ? '检查项（行）设置' : '填写项设置'}
                  extra={<Tag>{FIELD_TYPE_TEXT[field.type] || field.type}</Tag>}>
      <FieldLabel>{isMatrixRow ? '检查项名称' : '名称'}</FieldLabel>
      <Input data-testid="inspector-field-name" value={field.name} maxLength={100}
             onChange={e => patch({name: e.target.value}, `${labelPrefix}:name`)}/>
      <FieldLabel>填写类型</FieldLabel>
      <Select style={{width: '100%'}} value={field.type} options={typeOptions}
              data-testid="inspector-field-type"
              onChange={changeType}/>
      {!isMatrixRow && (
        <div style={{marginTop: 8}}>
          <Checkbox checked={!!field.required}
                    data-testid="inspector-field-required"
                    onChange={e => patch({required: e.target.checked})}>必填</Checkbox>
        </div>
      )}
      {field.type === 'number' && (
        <div>
          <FieldLabel>单位（如 V、A、℃）</FieldLabel>
          <Input data-testid="inspector-field-unit" value={field.unit || ''} maxLength={20}
                 onChange={e => patch({unit: e.target.value}, `${labelPrefix}:unit`)}/>
          <FieldLabel>数值范围（选填，闭区间）</FieldLabel>
          <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
            <InputNumber style={{width: '100%'}} placeholder="最小值"
                         data-testid="inspector-field-min"
                         value={field.min ?? null}
                         onChange={v => patch({min: v ?? null}, `${labelPrefix}:min`)}/>
            <span style={{color: '#999'}}>~</span>
            <InputNumber style={{width: '100%'}} placeholder="最大值"
                         data-testid="inspector-field-max"
                         value={field.max ?? null}
                         onChange={v => patch({max: v ?? null}, `${labelPrefix}:max`)}/>
          </div>
          <FieldLabel>小数位（选填，0~{NUMBER_PRECISION_MAX}；0 表示只能整数）</FieldLabel>
          <InputNumber style={{width: '100%'}} min={0} max={NUMBER_PRECISION_MAX}
                       placeholder="不限" data-testid="inspector-field-precision"
                       value={field.precision ?? null}
                       onChange={v => patch({precision: v ?? null},
                         `${labelPrefix}:precision`)}/>
        </div>
      )}
      {field.type === 'textarea' && (
        <div>
          <FieldLabel>行数（{TEXTAREA_ROWS_MIN}~{TEXTAREA_ROWS_MAX}）</FieldLabel>
          <InputNumber style={{width: '100%'}} min={TEXTAREA_ROWS_MIN}
                       max={TEXTAREA_ROWS_MAX}
                       data-testid="inspector-field-rows"
                       value={field.rows || TEXTAREA_ROWS_DEFAULT}
                       onChange={v => patch(
                         {rows: v || TEXTAREA_ROWS_DEFAULT},
                         `${labelPrefix}:rows`)}/>
        </div>
      )}
      {field.type === 'choice' && (
        <div>
          <FieldLabel>候选项（回车添加）</FieldLabel>
          <Select mode="tags" style={{width: '100%'}} value={field.options || []}
                  data-testid="inspector-field-options" placeholder="输入后回车添加"
                  onChange={options => patch({options}, `${labelPrefix}:options`)}/>
        </div>
      )}
      {field.type === 'normal_abnormal' && (
        <div style={{marginTop: 8}}>
          <Checkbox checked={!!field.require_desc_when_abnormal}
                    data-testid="inspector-field-require-desc"
                    onChange={e => patch(
                      {require_desc_when_abnormal: e.target.checked})}>
            异常时说明必填
          </Checkbox>
          <div style={{color: '#999', fontSize: 12, marginTop: 2}}>
            填写人选择"异常"时必须填写异常说明，完成填写时后端校验。
          </div>
        </div>
      )}
      <FieldLabel>说明（选填，填写时展示为提示）</FieldLabel>
      <Input data-testid="inspector-field-description" value={field.description || ''}
             maxLength={200}
             onChange={e => patch({description: e.target.value},
               `${labelPrefix}:description`)}/>
    </PanelSection>
  );
}

/** 矩阵列（对比对象）详细设置（排序/删除/复制在画布表头的列操作入口）。 */
function MatrixColumnInspector({selectionInfo, updateGroup}) {
  const column = selectionInfo.column;
  const group = selectionInfo.group;
  const patch = (p, label) => updateGroup(group.id, g => ({
    ...g, columns: g.columns.map(c => c.id === column.id ? {...c, ...p} : c)}), label);
  return (
    <PanelSection title="对比对象（列）设置">
      <FieldLabel>对象名称</FieldLabel>
      <Input data-testid="inspector-column-name" value={column.name} maxLength={30}
             onChange={e => patch({name: e.target.value},
               `insp:${group.id}:${column.id}:name`)}/>
      <div style={{color: '#999', fontSize: 12, marginTop: 8}}>
        列的排序与删除使用表头中该列下方的操作按钮。
      </div>
    </PanelSection>
  );
}

/** 未选中对象时的占位提示。 */
function EmptyInspector() {
  return (
    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} style={{paddingTop: 40}}
           description="点击画布中的分组、字段或表格行列，在此设置详细属性"/>
  );
}

/**
 * 检查器主体：按 selection 类型分发到对应设置面板。
 * 排序/删除入口在画布中，此处不重复提供（矩阵列左右移除外，因表头空间有限）。
 */
export default function FormTemplateInspector({selectionInfo, updateGroup}) {
  if (!selectionInfo) return <EmptyInspector/>;
  if (selectionInfo.type === 'group') {
    return <GroupInspector selectionInfo={selectionInfo} updateGroup={updateGroup}/>;
  }
  if (selectionInfo.type === 'matrixColumn') {
    return <MatrixColumnInspector selectionInfo={selectionInfo} updateGroup={updateGroup}/>;
  }
  return (
    <FieldInspector selectionInfo={selectionInfo} updateGroup={updateGroup}
                    isMatrixRow={selectionInfo.type === 'matrixRow'}/>
  );
}
