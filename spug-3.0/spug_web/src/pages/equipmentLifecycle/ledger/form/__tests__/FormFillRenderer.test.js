/**
 * 数字表单渲染器与填写 Store 行为测试（2026-10-21 数字表单路线）。
 *
 * 真实渲染（ReactDOM + jsdom，antd 真组件）+ mock libs/http，验证：
 * - FormFillRenderer：普通字段/异常说明联动/明细组增删行/矩阵（桌面表格
 *   与窄屏逐列卡片）真实渲染与编辑分发；
 * - collectFillUnits：必填统计/进度口径与后端 missing_required_labels 同构
 *   （矩阵不做必填）；
 * - FormLedgerStore.edit：字段/异常说明/明细组/矩阵的编辑动作真实改写
 *   values 结构（field_id / <id>__desc / 组 id 行数组 / 组 id 行列嵌套）。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const h = React.createElement;

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: (...args) => mockHttpGet(...args),
    post: (...args) => mockHttpPost(...args),
    put: (...args) => mockHttpPut(...args),
    delete: jest.fn(),
  },
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  history: {},
  X_TOKEN: '',
  exportFile: jest.fn(),
}));

jest.mock('components', () => {
  const React = require('react');
  const Shell = (props) => React.createElement('div', null, props.children);
  return {
    AuthDiv: Shell, AuthButton: (props) => React.createElement('button', {
      type: 'button', 'data-testid': props['data-testid'], onClick: props.onClick,
    }, props.children),
    AuthCard: Shell, AuthFragment: Shell, Breadcrumb: Shell, SearchForm: Shell,
  };
});

if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

const FormFillRenderer = require('../FormFillRenderer').default;
const {collectFillUnits} = require('../FormFillRenderer');
const {FormLedgerStore} = require('../formLedgerStore');

export const FORM = {
  protocol_version: 1,
  groups: [
    {
      id: 'g_base', name: '基本信息', kind: 'fields',
      fields: [
        {id: 'f_date', name: '维护日期', type: 'date', required: true,
         description: '', unit: '', options: []},
        {id: 'f_abn', name: '外观', type: 'normal_abnormal', required: true,
         description: '', unit: '', options: []},
      ],
    },
    {
      id: 'g_measure', name: '测量', kind: 'repeat', item_name: '测量项目',
      fields: [
        {id: 'f_item', name: '项目名称', type: 'text', required: true,
         description: '', unit: '', options: []},
      ],
    },
    {
      id: 'g_matrix', name: '多机对比', kind: 'matrix',
      columns: [{id: 'c_a', name: 'A 机'}, {id: 'c_b', name: 'B 机'}],
      fields: [
        {id: 'r_volt', name: '电压', type: 'number', required: false,
         description: '', unit: 'V', options: []},
        {id: 'r_link', name: '通讯', type: 'normal_abnormal', required: false,
         description: '', unit: '', options: []},
      ],
    },
  ],
};

function render(element) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = ReactDOM.render(element, container);
  return {
    container, root,
    cleanup: () => {
      ReactDOM.unmountComponentAtNode(container);
      container.remove();
    },
  };
}
const flush = () => new Promise(resolve => setTimeout(resolve, 0));

function setText(input, value) {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value').set;
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event('input', {bubbles: true}));
  });
}

// ==================== collectFillUnits 口径 ====================

describe('collectFillUnits 必填/进度口径', () => {
  test('普通字段逐项收集、明细组按行收集、矩阵逐格收集且不做必填', () => {
    const units = collectFillUnits(FORM, {
      g_measure: [{f_item: '驻波比', _rid: 'r1'}],
    });
    const labels = units.map(u => u.label);
    expect(labels.some(l => l.includes('基本信息 / 维护日期'))).toBe(true);
    expect(labels.some(l => l.includes('测量 第1条 / 项目名称'))).toBe(true);
    expect(labels.some(l => l.includes('多机对比｜电压（A 机）'))).toBe(true);
    // 矩阵格不做必填；普通字段 f_date/f_abn 必填
    const matrixUnits = units.filter(u => u.label.includes('多机对比'));
    expect(matrixUnits.length).toBe(4);
    expect(matrixUnits.every(u => u.required === false)).toBe(true);
    const required = units.filter(u => u.required);
    expect(required.length).toBe(3); // f_date + f_abn + 明细行内 f_item
    // 行内 f_item 已填；未填必填 = f_date + f_abn 两项
    expect(required.filter(u => !u.filled).length).toBe(2);
    expect(required.find(u => u.label.includes('项目名称')).filled).toBe(true);
  });

  test('空明细组不产生必填单元（与后端"空明细组不拦"同口径）', () => {
    const units = collectFillUnits(FORM, {});
    expect(units.filter(u => u.label.includes('测量')).length).toBe(0);
  });

  test('异常时说明必填单元：仅值=异常时计入，说明已填即通过（与后端终验同口径）', () => {
    const form = {
      protocol_version: 2,
      groups: [
        {id: 'g_p', name: '检查', kind: 'fields', fields: [
          {id: 'f_abn3', name: '外观', type: 'normal_abnormal',
           require_desc_when_abnormal: true,
           description: '', unit: '', options: []}]},
        {id: 'g_m', name: '对比', kind: 'matrix',
         columns: [{id: 'c_a', name: 'A 机'}],
         fields: [
           {id: 'r_abn1', name: '通讯', type: 'normal_abnormal',
            require_desc_when_abnormal: true,
            description: '', unit: '', options: []},
           {id: 'r_abn2', name: '供电', type: 'normal_abnormal',
            require_desc_when_abnormal: true,
            description: '', unit: '', options: []}]},
      ],
    };
    // 全部未判定：不产生说明单元（规则仅在判定异常时生效）
    expect(collectFillUnits(form, {}).filter(u => u.label.includes('异常说明')).length)
      .toBe(0);
    // 外观+通讯=异常且未说明 → 2 个必填未填单元；供电=异常已说明 → 通过
    const units = collectFillUnits(form, {
      f_abn3: 'abnormal',
      g_m: {r_abn1: {c_a: 'abnormal'},
            r_abn2: {c_a: 'abnormal', 'c_a__desc': '电压不稳'}},
    });
    const descUnits = units.filter(u => u.label.includes('异常说明'));
    expect(descUnits.length).toBe(3);
    expect(descUnits.filter(u => !u.filled).length).toBe(2);
    expect(descUnits.find(u => u.label.includes('供电')).filled).toBe(true);
    expect(descUnits.every(u => u.required)).toBe(true);
  });
});

// ==================== FormFillRenderer 渲染与交互 ====================

describe('FormFillRenderer 渲染与编辑分发', () => {
  test('date 字段用 DatePicker：面板点选提交，仍以 YYYY-MM-DD 字符串上抛', async () => {
    const onEdit = jest.fn();
    const view = render(h(FormFillRenderer, {
      form: FORM, values: {}, editable: true, onEdit,
    }));
    const dateInput = view.container.querySelector('#anchor-f_date input');
    expect(dateInput).toBeTruthy();
    // 聚焦并点击输入框打开日期面板（rc-picker）
    await act(async () => {
      dateInput.focus();
      dateInput.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
      dateInput.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
      dateInput.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    const cell = document.querySelector(
      '.ant-picker-cell-in-view .ant-picker-cell-inner');
    expect(cell).toBeTruthy();
    // 断言依据 = 所点单元格的真实日期（td title 为 YYYY-MM-DD）
    const cellDate = cell.closest('td').getAttribute('title');
    expect(cellDate).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    await act(async () => {
      cell.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(onEdit).toHaveBeenCalledWith('field', 'f_date', cellDate);
    view.cleanup();
  });

  test('textarea 按模板 rows 渲染（v2 键；缺省回退 2 行=v1 行为）', () => {
    const form = {
      protocol_version: 2,
      groups: [{id: 'g1', name: '组', kind: 'fields', fields: [
        {id: 'f_a', name: '多行A', type: 'textarea', rows: 5,
         description: '', unit: '', options: []},
        {id: 'f_b', name: '多行B', type: 'textarea',
         description: '', unit: '', options: []},
      ]}],
    };
    const view = render(h(FormFillRenderer, {form, values: {}, editable: true}));
    const textareas = view.container.querySelectorAll('textarea');
    expect(textareas[0].getAttribute('rows')).toBe('5');
    expect(textareas[1].getAttribute('rows')).toBe('2');
    view.cleanup();
  });

  test('异常时说明必填（require_desc_when_abnormal）：必填星号与占位如实标注', () => {
    const form = {
      protocol_version: 2,
      groups: [{id: 'g1', name: '组', kind: 'fields', fields: [
        {id: 'f_abn2', name: '机壳外观', type: 'normal_abnormal',
         required: true, require_desc_when_abnormal: true,
         description: '', unit: '', options: []},
      ]}],
    };
    const view = render(h(FormFillRenderer, {
      form, values: {f_abn2: 'abnormal'}, editable: true, onEdit: jest.fn()}));
    const desc = document.querySelector('[data-testid="abnormal-desc-f_abn2"]');
    expect(desc.placeholder).toContain('必填');
    view.cleanup();
  });

  test('normal_abnormal 选异常后异常说明出现并上抛（desc 动作），正常时不显示', () => {
    const onEdit = jest.fn();
    const view = render(h(FormFillRenderer, {
      form: FORM, values: {}, editable: true, onEdit,
    }));
    expect(document.querySelector('[data-testid="abnormal-desc-f_abn"]')).toBeNull();
    const radioInput = view.container.querySelector('#anchor-f_abn input[value="abnormal"]');
    act(() => { radioInput.click(); });
    expect(onEdit).toHaveBeenCalledWith('field', 'f_abn', 'abnormal');
    // 值回填后异常说明输入出现（用受控值重渲染）
    const view2 = render(h(FormFillRenderer, {
      form: FORM, values: {f_abn: 'abnormal'}, editable: true, onEdit,
    }));
    const desc = document.querySelector('[data-testid="abnormal-desc-f_abn"]');
    expect(desc).toBeTruthy();
    view.cleanup();
    view2.cleanup();
  });

  test('明细组：添加行/删除行/行内字段编辑', () => {
    const onEdit = jest.fn();
    const view = render(h(FormFillRenderer, {
      form: FORM, values: {g_measure: [{_rid: 'r1', f_item: ''}]},
      editable: true, onEdit,
    }));
    const addBtn = document.querySelector('[data-testid="repeat-add-g_measure"]');
    expect(addBtn).toBeTruthy();
    act(() => { addBtn.click(); });
    expect(onEdit).toHaveBeenCalledWith('addRow', FORM.groups[1]);
    const removeBtn = document.querySelector('[data-testid="repeat-remove-g_measure"]');
    act(() => { removeBtn.click(); });
    expect(onEdit).toHaveBeenCalledWith('removeRow', 'g_measure', 0);
    const itemInput = view.container.querySelector('#anchor-g_measure input');
    setText(itemInput, '驻波比');
    expect(onEdit).toHaveBeenCalledWith('rowField', 'g_measure', 0, 'f_item', '驻波比');
    view.cleanup();
  });
});

describe('FormFillRenderer 矩阵渲染与编辑分发', () => {
  test('矩阵：桌面表格渲染行列并可编辑；只读模式输入禁用', () => {
    const onEdit = jest.fn();
    const view = render(h(FormFillRenderer, {
      form: FORM, values: {}, editable: true, onEdit, narrow: false,
    }));
    const table = view.container.querySelector('table');
    expect(table).toBeTruthy();
    expect(table.textContent).toContain('A 机');
    expect(table.textContent).toContain('电压');
    const cellInput = table.querySelectorAll('tbody tr td input')[0];
    setText(cellInput, '3.5');
    // 数字类型经 InputNumber 规范化为数值
    expect(onEdit).toHaveBeenCalledWith('cell', 'g_matrix', 'r_volt', 'c_a', 3.5);
    view.cleanup();

    const readonly = render(h(FormFillRenderer, {
      form: FORM, values: {}, editable: false, narrow: false,
    }));
    const readonlyInput = readonly.container.querySelector('table tbody input');
    expect(readonlyInput.disabled).toBe(true);
    readonly.cleanup();
  });

  test('窄屏（narrow）矩阵改为逐列卡片，无横向表格', () => {
    const view = render(h(FormFillRenderer, {
      form: FORM, values: {}, editable: true, onEdit: jest.fn(), narrow: true,
    }));
    expect(view.container.querySelector('table')).toBeNull();
    expect(view.container.textContent).toContain('A 机');
    expect(view.container.textContent).toContain('B 机');
    view.cleanup();
  });

  test('矩阵异常说明区：取值为异常的单元格集中显示说明输入', () => {
    const onEdit = jest.fn();
    const view = render(h(FormFillRenderer, {
      form: FORM,
      values: {g_matrix: {r_link: {c_a: 'abnormal'}}},
      editable: true, onEdit, narrow: false,
    }));
    expect(view.container.textContent).toContain('异常说明');
    expect(view.container.textContent).toContain('通讯（A 机）');
    const descInput = view.container.querySelector('textarea');
    act(() => {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, 'value').set;
      setter.call(descInput, 'A 机通讯中断');
      descInput.dispatchEvent(new Event('input', {bubbles: true}));
    });
    expect(onEdit).toHaveBeenCalledWith(
      'cellDesc', 'g_matrix', 'r_link', 'c_a', 'A 机通讯中断');
    view.cleanup();
  });
});

describe('FormFillRenderer 矩阵行说明渲染（对齐 PDF 行头说明）', () => {
  test('行说明随行头展示，桌面表格与窄屏逐列一致', () => {
    const form = {
      protocol_version: 1,
      groups: [{
        id: 'g_matrix2', name: '多机对比', kind: 'matrix',
        columns: [{id: 'c_a', name: 'A 机'}],
        fields: [{id: 'r_volt', name: '电压', type: 'number', required: false,
                  description: '按额定输出电压测量', unit: 'V', options: []}],
      }],
    };
    const wide = render(h(FormFillRenderer, {
      form, values: {}, editable: false, narrow: false,
    }));
    expect(wide.container.textContent).toContain('按额定输出电压测量');
    wide.cleanup();
    const narrowView = render(h(FormFillRenderer, {
      form, values: {}, editable: false, narrow: true,
    }));
    expect(narrowView.container.textContent).toContain('按额定输出电压测量');
    narrowView.cleanup();
  });
});

// ==================== FormLedgerStore.edit 结构改写 ====================

describe('FormLedgerStore.edit 值结构', () => {
  test('field/desc 写入平铺键与 __desc 键', () => {
    const store = new FormLedgerStore();
    store.edit('field', 'f_date', '2026-10-21');
    store.edit('desc', 'f_abn', '外壳裂纹');
    expect(store.values.f_date).toBe('2026-10-21');
    expect(store.values.f_abn__desc).toBe('外壳裂纹');
  });

  test('addRow/removeRow/rowField 维护行数组与 _rid 行标识', () => {
    const store = new FormLedgerStore();
    store.edit('addRow', FORM.groups[1]);
    expect(store.values.g_measure.length).toBe(1);
    expect(store.values.g_measure[0]._rid).toBeTruthy();
    expect(store.values.g_measure[0].f_item).toBe('');
    store.edit('rowField', 'g_measure', 0, 'f_item', '驻波比');
    store.edit('rowDesc', 'g_measure', 0, 'f_item', '偏高');
    expect(store.values.g_measure[0].f_item).toBe('驻波比');
    expect(store.values.g_measure[0].f_item__desc).toBe('偏高');
    store.edit('removeRow', 'g_measure', 0);
    expect(store.values.g_measure.length).toBe(0);
  });

  test('cell/cellDesc 维护矩阵 行→列 嵌套结构', () => {
    const store = new FormLedgerStore();
    store.edit('cell', 'g_matrix', 'r_volt', 'c_a', 3.5);
    store.edit('cellDesc', 'g_matrix', 'r_link', 'c_b', 'B 机中断');
    expect(store.values.g_matrix.r_volt.c_a).toBe(3.5);
    expect(store.values.g_matrix.r_link.c_b__desc).toBe('B 机中断');
  });

  test('valuesDirty/hasUnsaved：脏值跟踪与只读态不参与未保存保护', async () => {
    mockHttpGet.mockResolvedValue({data: {
      id: 55, status: 'draft',
      form: {values: {f_date: ''}, editable: true, version: {form: FORM}},
    }});
    const store = new FormLedgerStore();
    await store.fetchDetail(55);
    expect(store.hasUnsaved).toBe(false);
    store.edit('field', 'f_date', '2026-10-21');
    expect(store.valuesDirty).toBe(true);
    expect(store.hasUnsaved).toBe(true);
    mockHttpPut.mockResolvedValue({data: {
      id: 55, status: 'draft',
      form: {values: {f_date: '2026-10-21'}, editable: true, version: {form: FORM}},
    }});
    await store.saveValues();
    expect(mockHttpPut).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/form-ledgers/55/', {
        values: expect.objectContaining({f_date: '2026-10-21'})});
    expect(store.valuesDirty).toBe(false);
    // 完成态只读：即使值有差异也不参与未保存保护
    const doneStore = new FormLedgerStore();
    mockHttpGet.mockResolvedValue({data: {
      id: 55, status: 'completed',
      form: {values: {f_date: ''}, editable: false, version: {form: FORM}},
    }});
    await doneStore.fetchDetail(55);
    doneStore.values = {f_date: 'x'};
    expect(doneStore.hasUnsaved).toBe(false);
  });
});
