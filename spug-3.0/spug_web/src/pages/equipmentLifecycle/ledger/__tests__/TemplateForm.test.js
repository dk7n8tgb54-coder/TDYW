/**
 * 台账模板项目表单测试：录入类型收敛为两种（2026-09-22 约定）。
 *
 * - 下拉仅提供 正常/不正常(choice) 与 数字/文本(text)，历史类型仅对已有行回显；
 * - 正常/不正常候选项固定为 正常/不正常，不再开放配置（候选项列已移除）；
 * - 模板项目仅剩 名称/录入类型/单位/必填（默认勾选），
 *   标准说明、正常范围、数值上下限、执行范围列已移除
 *   （执行范围随周表/月表合一于 2026-09-26 删除）；
 * - 切换录入类型时清掉不再适用的字段。
 *
 * 沿用 LedgerForm.submit.test.js 的不渲染模式：直接构造组件实例，
 * 驱动 itemColumns() 及列渲染函数，断言控件与状态变化。
 */
import React from 'react';
import TemplateForm from '../TemplateForm';

jest.mock('libs', () => ({
  http: {get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn()},
}));

function item(patch) {
  return {
    key: `k${Math.random()}`, id: undefined,
    name: '', input_type: 'choice',
    unit: '',
    choices: ['正常', '不正常'], is_required: true, display_order: 0,
    ...patch,
  };
}

function makeInstance(items) {
  const store = {record: {}, formVisible: true, fetchRecords: jest.fn()};
  const instance = new TemplateForm({store});
  instance.props = {store};
  instance.state = {
    loading: false,
    items,
    template: {
      name: '测试模板', ledger_type: 'week_month',
      description: '',
    },
  };
  instance.setState = jest.fn(patch => {
    instance.state = {
      ...instance.state,
      ...(typeof patch === 'function' ? patch(instance.state) : patch),
    };
  });
  return instance;
}

function columnByTitle(instance, title) {
  return instance.itemColumns().find(c => c.title === title);
}

function optionValues(selectEl) {
  return React.Children.toArray(selectEl.props.children).map(o => o.props.value);
}

describe('TemplateForm 录入类型收敛', () => {
  test('录入类型仅提供两种选项，历史类型仅对已有行回显', () => {
    const instance = makeInstance([
      item({input_type: 'choice'}),
      item({input_type: 'multi_choice', choices: ['主用', '备用']}),
    ]);
    const typeCol = columnByTitle(instance, '录入类型');
    expect(optionValues(typeCol.render(null, instance.state.items[0]))).toEqual(['choice', 'text']);
    expect(optionValues(typeCol.render(null, instance.state.items[1]))).toEqual(['choice', 'text', 'multi_choice']);
  });

  test('项目表仅剩精简列：标准说明/正常范围/数值上下限列全部移除', () => {
    const instance = makeInstance([
      item({input_type: 'choice'}),
      item({input_type: 'text'}),
    ]);
    const titles = instance.itemColumns().map(c => c.title);
    expect(titles).toEqual(expect.arrayContaining(['项目名称', '录入类型', '单位', '必填']));
    expect(titles).not.toContain('项目编码');
    expect(titles).not.toContain('标准/说明');
    expect(titles).not.toContain('正常范围');
    expect(titles).not.toContain('数值下限/上限');
    expect(titles).not.toContain('候选项（逗号分隔）');
  });

  test('单位列仅对数字/文本行可编辑，正常/不正常行显示占位', () => {
    const instance = makeInstance([
      item({input_type: 'text'}),
      item({input_type: 'choice'}),
    ]);
    const unitCol = columnByTitle(instance, '单位');
    const unitCell = unitCol.render(null, instance.state.items[0]);
    expect(unitCell.props).toHaveProperty('value');
    const placeholderCell = unitCol.render(null, instance.state.items[1]);
    expect(placeholderCell.props.children).toBe('—');
  });

  test('新建项目默认必填', () => {
    const instance = makeInstance([]);
    instance.addItem();
    expect(instance.state.items[0].is_required).toBe(true);
    expect(instance.state.items[0].choices).toEqual(['正常', '不正常']);
  });

  test('数字/文本切回正常/不正常时清掉单位并锁定候选项', () => {
    const instance = makeInstance([
      item({input_type: 'text', unit: 'V'}),
    ]);
    const typeCol = columnByTitle(instance, '录入类型');
    typeCol.render(null, instance.state.items[0]).props.onChange('choice');
    const row = instance.state.items[0];
    expect(row.input_type).toBe('choice');
    expect(row.unit).toBe('');
    expect(row.choices).toEqual(['正常', '不正常']);
  });

  test('正常/不正常切到数字/文本时清掉候选项', () => {
    const instance = makeInstance([item({input_type: 'choice'})]);
    columnByTitle(instance, '录入类型').render(null, instance.state.items[0]).props.onChange('text');
    const row = instance.state.items[0];
    expect(row.input_type).toBe('text');
    expect(row.choices).toEqual([]);
  });
});
