/**
 * 矩阵台账录入表单测试（第一阶段行对象树：行方向多级 + 平面列项目）。
 *
 * 真实渲染 LedgerForm（ReactDOM + jsdom）：
 * - 预览生成"行层级独立列 × 平面列项目"矩阵：每级行项目独立成列（第1级/第2级…），
 *   父节点（信道）rowSpan 纵向合并连续子行，收起后子行隐藏；
 * - 主/备电台共享同一组列项目（PS/TX/RX 等只配置一次复用到每个行叶子）；
 * - 新增可重复分组实例（第2信道）后单元格数量随之翻倍；
 * - 单元格填写、异常/未填写筛选、行级完成进度、一键正常；
 * - 提交按系统拆分立账：row_instances 规格与已填单元格（path+column_id）入载荷；
 * - 周月维护不再选择维护周期（2026-09-26）：任何请求均不携带 maintenance_cycle。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: mockHttpPost,
    put: mockHttpPut,
    delete: mockHttpDelete,
  },
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  history: {},
  X_TOKEN: '',
  exportFile: jest.fn(),
}));

if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

const COLUMN_ITEMS = ['PS模块', 'TX模块', 'RX模块', 'BB模块', '显示模块', '备注'].map((name, i) => ({
  id: 100 + i,
  name,
  input_type: i < 5 ? 'choice' : 'text',
  unit: '',
  choices: i < 5 ? ['正常', '不正常'] : [],
  is_required: true,
  operation_guide: '',
}));

const ROW_NODES = [{
  id: 9, parent: null, node_type: 'repeat_group', name: '信道',
  level: 1, path: '信道', is_leaf: false, children_count: 2, display_order: 0,
  children: [
    {id: 10, parent: 9, node_type: 'check', name: '主电台', level: 2, path: '信道 / 主电台',
      is_leaf: true, children_count: 0, display_order: 0, children: []},
    {id: 11, parent: 9, node_type: 'check', name: '备电台', level: 2, path: '信道 / 备电台',
      is_leaf: true, children_count: 0, display_order: 1, children: []},
  ],
}];

function previewEntry() {
  return {
    system: {id: 5, system_code: 'SYS-001', name: '台站通信系统', install_location: '机房A'},
    template: {id: 1, name: '矩阵模板A'},
    is_matrix: true,
    row_nodes: JSON.parse(JSON.stringify(ROW_NODES)),
    items: COLUMN_ITEMS,
  };
}

let container = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  mockHttpGet.mockImplementation(url => {
    if (url.includes('/systems/')) {
      return Promise.resolve({data: [{id: 5, name: '台站通信系统', install_location: '机房A', is_active: true}]});
    }
    if (url.includes('/ledger-templates/available/')) {
      return Promise.resolve({data: [{id: 1, name: '矩阵模板A', items_count: 6}]});
    }
    return Promise.resolve({data: []});
  });
  mockHttpPost.mockImplementation(url => {
    if (url.includes('/preview/')) {
      return Promise.resolve({data: [previewEntry()]});
    }
    return Promise.resolve({data: {}});
  });
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete].forEach(fn => fn.mockReset());
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

function findButtonByText(text) {
  return Array.from(document.querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s+/g, '') === text);
}

function findLinkByText(text) {
  return Array.from(document.querySelectorAll('a'))
    .find(a => a.textContent.replace(/\s+/g, '') === text);
}

async function renderForm(ledgerType = 'week_month') {
  const LedgerForm = require('../LedgerForm').default;
  const store = {
    ledgerType,
    record: {},
    formVisible: true,
    fetchRecords: jest.fn(),
  };
  let instance = null;
  await act(async () => {
    instance = ReactDOM.render(<LedgerForm store={store}/>, container);
  });
  await act(flush);
  return instance;
}

async function generatePreview(instance) {
  await act(async () => {
    instance.setState({templateId: 1});
  });
  await act(async () => {
    instance.generatePreview();
  });
  await act(flush);
}

describe('矩阵台账录入（行对象树 × 平面列项目）', () => {
  it('预览生成矩阵：主/备两个行叶子共享 6 个列项目，共 12 个单元格', async () => {
    const instance = await renderForm();
    await generatePreview(instance);
    // 行路径与列头渲染
    expect(document.body.textContent).toContain('主电台');
    expect(document.body.textContent).toContain('备电台');
    COLUMN_ITEMS.map(c => c.name).forEach(name => expect(document.body.textContent).toContain(name));
    // 6 列 × 2 行叶子 = 12 个填写控件（5 个 choice 下拉 + 1 个文本输入/每叶子）
    const textInputs = document.querySelectorAll('.ant-table input.ant-input:not([disabled])');
    const choiceSelects = document.querySelectorAll('.ant-table .ant-select').length;
    expect(textInputs.length).toBe(2);       // 备注（两个行叶子各一）
    expect(choiceSelects).toBe(10);          // 5 列 × 2 行叶子
  });

  it('行层级独立成列：父节点 rowSpan 合并，收起后子行隐藏', async () => {
    const instance = await renderForm();
    await generatePreview(instance);
    // 行树的每一级对应独立表格列：第1级/第2级；树只有 2 级，未用层级列隐藏
    const headers = Array.from(document.querySelectorAll('.ant-table-thead th'))
      .map(th => th.textContent.trim());
    expect(headers).toContain('第1级');
    expect(headers).toContain('第2级');
    expect(headers.some(h => h.startsWith('第3级'))).toBe(false);
    // 完整路径不放在单一列中：路径列标题不再存在
    expect(headers.some(h => h.includes('行路径'))).toBe(false);
    // 父节点"信道"渲染在第 1 级列，rowSpan 纵向合并两个行叶子行
    // （antd scroll.x 时 tbody 首行是隐藏测量行，合并格按属性直接查找）
    const mergedCell = document.querySelector('.ant-table-tbody td[rowspan="2"]');
    expect(mergedCell).toBeTruthy();
    expect(mergedCell.textContent).toContain('信道');
    // 收起分组：子行隐藏、分组自成一行；再展开恢复
    const clickToggle = async () => {
      await act(async () => {
        // Modal portal 到 document.body，toggle 不在测试 container 内
        document.querySelector('.el-matrix-toggle').click();
      });
      await act(flush);
    };
    await clickToggle();
    expect(document.body.textContent).toContain('信道');
    expect(document.body.textContent).not.toContain('主电台');
    expect(document.body.textContent).not.toContain('备电台');
    await clickToggle();
    expect(document.body.textContent).toContain('主电台');
    expect(document.body.textContent).toContain('备电台');
  });

  it('新增第2信道：行实例翻倍，两信道各自拥有主/备叶子', async () => {
    const instance = await renderForm();
    await generatePreview(instance);
    const addLink = findLinkByText('添加信道');
    expect(addLink).toBeTruthy();
    await act(async () => {
      addLink.click();
    });
    await act(flush);
    // 4 个行叶子 × 6 列 = 24 单元格：文本输入变 4 个（备注列 × 4 叶子）
    const textInputs = document.querySelectorAll('.ant-table input.ant-input:not([disabled])');
    expect(textInputs.length).toBe(4);
  });

  it('单元格填写与提交载荷：row_instances 规格与 path+column_id 预填值入参', async () => {
    const instance = await renderForm();
    await generatePreview(instance);
    // 填写备注列（第一个行叶子的文本框）
    const remarkInput = document.querySelector('.ant-table input.ant-input:not([disabled])');
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, 'value').set;
      setter.call(remarkInput, '机壳清洁');
      remarkInput.dispatchEvent(new Event('input', {bubbles: true}));
    });
    await act(flush);
    // 提交
    await act(async () => {
      findButtonByText('整表一次提交').click();
    });
    await act(flush);
    const submitCalls = mockHttpPost.mock.calls.filter(c => c[0].endsWith('/ledgers/'));
    expect(submitCalls).toHaveLength(1);
    const [url, payload] = submitCalls[0];
    expect(url).toBe('/api/equipment-lifecycle/ledgers/');
    expect(payload.system_id).toBe(5);
    expect(payload.template_id).toBe(1);
    expect(payload.maintenance_cycle).toBeUndefined();
    expect(payload.row_instances).toEqual([{
      template_node: 9, name: '信道',
      children: [
        {template_node: 10, name: '主电台', children: []},
        {template_node: 11, name: '备电台', children: []},
      ],
    }]);
    const filled = payload.values.filter(v => v.value_text);
    expect(filled).toHaveLength(1);
    expect(filled[0].path).toBe('信道 / 主电台');
    expect(filled[0].column_id).toBe(105);
    expect(filled[0].value_text).toBe('机壳清洁');
  });

  it('新增第2信道后提交：row_instances 含两个信道实例', async () => {
    const instance = await renderForm();
    await generatePreview(instance);
    await act(async () => {
      findLinkByText('添加信道').click();
    });
    await act(flush);
    await act(async () => {
      findButtonByText('整表一次提交').click();
    });
    await act(flush);
    const submitCalls = mockHttpPost.mock.calls.filter(c => c[0].endsWith('/ledgers/'));
    const payload = submitCalls[0][1];
    expect(payload.row_instances).toHaveLength(2);
    expect(payload.row_instances[1].name).toBe('信道2');
  });
});

describe('矩阵台账：一键正常与筛选（作用域限定）', () => {

    it('一键正常仅作用于未填写单元格；未填写不被自动转换为正常', async () => {
    const instance = await renderForm();
    await generatePreview(instance);
    // 未填写不被自动转换为正常：所有单元格初始结果为空（提交载荷不含值）
    const leaves = require('../ledgerCommon').flattenPlanned(instance.state.planned)
      .filter(p => p.node_type === 'check');
    const allCells = leaves.flatMap(leaf => instance.state.columns.map(col => ({
      leaf, col, cell: instance.getPlannedCell({key: leaf.key}, col),
    })));
    expect(allCells).toHaveLength(12);
    expect(allCells.every(x => !x.cell.result && !x.cell.value_text)).toBe(true);
    // 一键正常：全部 12 个未填写单元格显式置为正常
    await act(async () => {
      findButtonByText('一键正常（仅未填写）').click();
    });
    await act(flush);
    await act(async () => {
      findButtonByText('整表一次提交').click();
    });
    await act(flush);
    const submitCalls = mockHttpPost.mock.calls.filter(c => c[0].endsWith('/ledgers/'));
    expect(submitCalls).toHaveLength(1);
    const payload = submitCalls[0][1];
    const normals = payload.values.filter(v => v.result === 'normal');
    expect(normals).toHaveLength(12);
    expect(normals.every(v => !v.value_text)).toBe(true);
  });

  it('仅异常/仅未填写筛选：行叶子按单元格状态过滤', async () => {
    const instance = await renderForm();
    await generatePreview(instance);
    // 全部未填写 → 仅未填写模式仍有行叶子；填一个异常后仅异常出现行
    const radioButtons = Array.from(document.querySelectorAll('.ant-radio-button-wrapper'));
    expect(radioButtons.map(r => r.textContent).join('|')).toContain('全部');
    expect(radioButtons.map(r => r.textContent).join('|')).toContain('仅异常');
    expect(radioButtons.map(r => r.textContent).join('|')).toContain('仅未填写');
    // 将主电台 PS 模块填为"不正常"后切到"仅异常"：备电台行被过滤
    // 将主电台 PS 模块填为"不正常"
    const firstSelect = document.querySelector('td .ant-select');
    await act(async () => {
      firstSelect.querySelector('.ant-select-selector').dispatchEvent(
        new MouseEvent('mousedown', {bubbles: true}));
    });
    await act(flush);
    const option = Array.from(document.querySelectorAll('.ant-select-item-option'))
      .find(o => o.title === '不正常');
    await act(async () => {
      option.click();
    });
    await act(flush);
    await act(async () => {
      instance.setState({filterMode: 'abnormal'});
    });
    await act(flush);
    expect(document.body.textContent).toContain('主电台');
    expect(document.body.textContent).not.toContain('备电台');
    // 切回"仅未填写"：备电台（全未填写）回归，主电台（已全填?）——主电台仅一异常格
    await act(async () => {
      instance.setState({filterMode: 'unset'});
    });
    await act(flush);
    expect(document.body.textContent).toContain('主电台');
    expect(document.body.textContent).toContain('备电台');
  });

  it('行级完成进度：填写后进度 x/6 更新', async () => {
    const instance = await renderForm();
    await generatePreview(instance);
    expect(document.body.textContent).toContain('0/6');
    const remarkInput = document.querySelector('.ant-table input.ant-input:not([disabled])');
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, 'value').set;
      setter.call(remarkInput, 'ok');
      remarkInput.dispatchEvent(new Event('input', {bubbles: true}));
    });
    await act(flush);
    expect(document.body.textContent).toContain('1/6');
  });
});

describe('季维护矩阵（维护周期已删除）', () => {
  it('模板加载与预览仅按 ledger_type 区分，不携带 maintenance_cycle', async () => {
    const instance = await renderForm('seasonal');
    // 模板加载 URL
    const availableCall = mockHttpGet.mock.calls.find(c => c[0].includes('/available/'));
    expect(availableCall[0]).toContain('ledger_type=seasonal');
    expect(availableCall[0]).not.toContain('maintenance_cycle');
    await generatePreview(instance);
    const previewCall = mockHttpPost.mock.calls.find(c => c[0].includes('/preview/'));
    expect(previewCall[1].ledger_type).toBe('seasonal');
    expect(previewCall[1].maintenance_cycle).toBeUndefined();
    // 提交载荷同样不携带维护周期
    await act(async () => {
      findButtonByText('整表一次提交').click();
    });
    await act(flush);
    const submitPayload = mockHttpPost.mock.calls.find(c => c[0].endsWith('/ledgers/'))[1];
    expect(submitPayload.maintenance_cycle).toBeUndefined();
  });
});
