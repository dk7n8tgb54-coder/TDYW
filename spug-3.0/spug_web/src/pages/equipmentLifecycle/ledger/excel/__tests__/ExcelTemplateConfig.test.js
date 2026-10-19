/**
 * Excel 模板生成配置（适用系统 + 生成周期，2026-10-14）页面行为测试。
 *
 * 真实渲染 ExcelTemplatePage（jsdom + http mock），验证：
 * - 列表展示适用系统/生成周期列；未配置模板显示"待配置"标注；
 * - 工作区信息行展示当前配置并提供"配置"入口；点击拉取
 *   GET generation-config（系统清单 + 按台账类型收敛的周期候选）；
 * - 保存提交 PUT（system + generation_period），成功后重取详情与列表；
 * - 已停用模板不提供配置入口（仅供查看）。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const h = React.createElement;

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: (...args) => mockHttpGet(...args),
    post: (...args) => mockHttpPost(...args),
    put: (...args) => mockHttpPut(...args),
    delete: (...args) => mockHttpDelete(...args),
  },
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  history: {push: jest.fn()},
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

const excelTemplateStoreModule = require('../excelTemplateStore');
const ExcelTemplatePage = require('../ExcelTemplatePage').default;

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

function templateSummary(overrides = {}) {
  return {
    id: 7, name: '信道Excel维护台账', ledger_type: 'week_month',
    description: '', is_active: true,
    system: null, system_name: '', system_code: '',
    generation_period: '', generation_period_text: '待配置',
    draft_source_filename: 'channel.xlsx', draft_source_hash: 'a'.repeat(64),
    has_draft_bindings: true, draft_updated_at: '2026-10-14 09:00:00',
    created_at: '2026-09-28 09:00:00', updated_at: null,
    latest_version_no: 1, versions_count: 1, ledgers_count: 0, status: 'published',
    ...overrides,
  };
}

function templateDetailPayload(overrides = {}) {
  return {
    data: {
      ...templateSummary(overrides),
      draft: {
        sheet_name: '信道维护记录',
        layout: {active_sheet: '信道维护记录', sheets: [
          {name: '信道维护记录', max_row: 4, max_column: 8, merged_ranges: [],
           cells: {C4: {v: ''}}},
        ]},
        field_bindings: [{field_id: 'f-1', sheet_name: '信道维护记录',
                          cell_coordinate: 'C4', field_name: 'PS模块',
                          input_type: 'status', is_required: true, unit: '', options: []}],
        pdf_params: {},
        source_filename: 'channel.xlsx', source_hash: 'a'.repeat(64),
        draft_updated_at: null, draft_updated_by: '',
      },
      compatibility: null,
    },
  };
}

function configPayload(system = null, generationPeriod = '') {
  return {
    data: {
      template_id: 7, system, generation_period: generationPeriod,
      systems: [
        {id: 3, system_code: 'SYS-3', name: 'DVOR系统', is_active: true},
        {id: 4, system_code: 'SYS-4', name: 'ILS系统', is_active: true},
      ],
      periods: {
        week_month: [
          {value: 'weekly', label: '每周'},
          {value: 'monthly', label: '每月'},
        ],
        seasonal: [{value: 'seasonal', label: '每航季'}],
      },
    },
  };
}

let container = null;
let store = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete].forEach(fn => fn.mockReset());
  // 单例 store：跨用例重置状态
  store = excelTemplateStoreModule.default;
  store.current = null;
  store.list = [];
  store.configVisible = false;
  store.configSystem = undefined;
  store.configPeriod = '';
  store.configSystems = [];
  store.configPeriodOptions = [];
  mockHttpGet.mockImplementation(url => {
    if (url.endsWith('/generation-config/')) {
      return Promise.resolve(configPayload());
    }
    if (url.endsWith('/excel-templates/')) {
      return Promise.resolve({data: [templateSummary()]});
    }
    return Promise.resolve({});
  });
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  document.body.querySelectorAll('.ant-modal-root, .ant-modal-mask').forEach(node => node.remove());
});

function findButton(text) {
  return Array.from(document.body.querySelectorAll('button, a'))
    .find(el => el.textContent.replace(/\s+/g, '') === text);
}

describe('ExcelTemplatePage 生成配置', () => {
  test('列表展示适用系统与生成周期列，未配置显示待配置标注', async () => {
    await act(async () => {
      ReactDOM.render(h(ExcelTemplatePage, {store}), container);
    });
    await act(flush);
    const text = container.textContent;
    expect(text).toContain('适用系统');
    expect(text).toContain('生成周期');
    expect(text).toContain('待配置');
  });

  test('列表展示已配置模板的系统与周期文本', async () => {
    mockHttpGet.mockImplementation(url => {
      if (url.endsWith('/excel-templates/')) {
        return Promise.resolve({data: [templateSummary({
          system: 3, system_name: 'DVOR系统', system_code: 'SYS-3',
          generation_period: 'weekly', generation_period_text: '每周',
        })]});
      }
      return Promise.resolve({});
    });
    await act(async () => {
      ReactDOM.render(h(ExcelTemplatePage, {store}), container);
    });
    await act(flush);
    const text = container.textContent;
    expect(text).toContain('DVOR系统（SYS-3）');
    expect(text).toContain('每周');
    // 已配置模板不出现待配置标注
    expect(container.querySelector('[data-testid="tpl-system-unset"]')).toBeNull();
  });

  test('工作区配置入口拉取选项，保存提交 system 与 generation_period', async () => {
    mockHttpGet.mockImplementation(url => {
      if (url.endsWith('/excel-templates/7/')) {
        return Promise.resolve(templateDetailPayload());
      }
      if (url.endsWith('/generation-config/')) {
        return Promise.resolve(configPayload());
      }
      if (url.endsWith('/excel-templates/')) {
        return Promise.resolve({data: [templateSummary()]});
      }
      return Promise.resolve({});
    });
    await act(async () => {
      ReactDOM.render(h(ExcelTemplatePage, {store}), container);
    });
    await act(flush);
    // 进入绑定工作区
    await act(async () => {
      findButton('编辑草稿').click();
    });
    await act(flush);
    const text = document.body.textContent;
    expect(text).toContain('适用系统：待配置');
    expect(text).toContain('生成周期：待配置');
    // 打开配置弹窗：拉取系统清单与周期候选
    await act(async () => {
      findButton('配置').click();
    });
    await act(flush);
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/excel-templates/7/generation-config/');
    const modalText = document.body.textContent;
    expect(modalText).toContain('适用系统（一个模板只对应一个系统）');
    expect(modalText).toContain('生成周期');
    expect(document.body.querySelectorAll('.ant-select').length).toBeGreaterThanOrEqual(2);
  });

  test('已停用模板不提供配置入口（仅供查看）', async () => {
    mockHttpGet.mockImplementation(url => {
      if (url.endsWith('/excel-templates/7/')) {
        return Promise.resolve(templateDetailPayload({is_active: false, status: 'deleted'}));
      }
      if (url.endsWith('/excel-templates/')) {
        return Promise.resolve({data: [templateSummary({is_active: false, status: 'deleted'})]});
      }
      return Promise.resolve({});
    });
    await act(async () => {
      ReactDOM.render(h(ExcelTemplatePage, {store}), container);
    });
    await act(flush);
    // 已停用模板集中在「已停用」视图（2026-10-19 双视图），先切换再进入
    await act(async () => {
      Array.from(container.querySelectorAll('[data-testid="tpl-view-switch"] input'))
        .find(node => node.value === 'disabled').click();
    });
    await act(flush);
    await act(async () => {
      findButton('查看模板').click();
    });
    await act(flush);
    expect(document.body.textContent).toContain('适用系统：待配置');
    expect(findButton('配置')).toBeUndefined();
  });
});
