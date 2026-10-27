/**
 * 干扰事件表单行为测试（2026-10-25 分类选项化改造）。
 *
 * 真实渲染 EventForm（ReactDOM + jsdom），mock libs.http 与
 * components.AttachmentManager，直接驱动真实 store 单例（MobX），验证：
 * - 三个分类下拉选项从接口加载（含自定义选项）
 * - 新建事件分类字段默认「未知/待查」，不再默认「其他」
 * - 编辑模式回填存量编码显示名称、提交保留历史值且不再携带分类状态
 * - 停用编码通过 *_text 回退显示
 * - 分类缺省与选项合并的纯函数行为
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: mockHttpPost,
    put: jest.fn(),
    delete: jest.fn(),
  },
  hasPermission: jest.fn(() => true),
}));

jest.mock('components', () => ({
  AttachmentManager: () => <div data-testid="attachment-manager">ATTACHMENTS</div>,
}));

const EventForm = require('../EventForm').default;
const {withCategoryDefaults, mergeCategoryOptions} = require('../EventForm');
const S = require('../store').default;

if (!window.matchMedia) {
  window.matchMedia = query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent: () => false,
  });
}

const CATEGORY_RECORDS = {
  records: [
    {id: 1, group: 'interference_kind', code: 'noise', name: '杂音', is_active: true},
    {id: 2, group: 'interference_kind', code: 'harmonic', name: '谐波干扰', is_active: true},
    {id: 3, group: 'interference_kind', code: 'unknown', name: '未知/待查', is_active: true},
    {id: 4, group: 'affected_system', code: 'communication', name: '通信', is_active: true},
    {id: 5, group: 'affected_system', code: 'unknown', name: '未知/待查', is_active: true},
    {id: 6, group: 'source_type', code: 'unknown', name: '未知/待查', is_active: true},
  ],
};

const EDIT_EVENT = {
  id: 9,
  datetime: '2026-10-01 09:00:00',
  scene_code: 'ground',
  interference_kind_code: 'noise',
  affected_system_code: 'other',
  source_type_code: 'legacy_env',
  interference_kind_text: '杂音',
  affected_system_text: '其他',
  source_type_text: '历史环境',
  ground_detail: {location: '3号机位', frequency: '118.6'},
};

let container = null;

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

function renderForm() {
  container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(<EventForm/>, container);
  });
}

function unmountForm() {
  if (container) {
    act(() => {
      ReactDOM.unmountComponentAtNode(container);
    });
    container.remove();
    container = null;
  }
}

function q(selector) {
  return Array.from(document.querySelectorAll(selector));
}

// 表单内 Select 顺序：发生场景、具体干扰类型、受影响系统、疑似干扰源
function categorySelect(index) {
  return q('.ant-modal .ant-select')[index];
}

function selectText(index) {
  const node = categorySelect(index);
  const item = node && node.querySelector('.ant-select-selection-item');
  return item ? item.textContent : '';
}

beforeEach(() => {
  jest.clearAllMocks();
  mockHttpGet.mockResolvedValue(CATEGORY_RECORDS);
  S.eventModalVisible = true;
  S.event = {};
  S.categoryOptions = {
    interference_kind_code: [],
    affected_system_code: [],
    source_type_code: [],
  };
});

afterEach(() => {
  unmountForm();
  document.querySelectorAll('.ant-modal-root, .ant-select-dropdown').forEach(n => n.remove());
  S.eventModalVisible = false;
  S.event = {};
});

describe('事件表单分类下拉', () => {
  it('三个分类下拉的选项来自接口且包含自定义选项', async () => {
    renderForm();
    await act(async () => { await flush(); });
    // 打开「具体干扰类型」下拉（索引 1），antd4 需对 selector 派发 mousedown
    const kindSelector = categorySelect(1).querySelector('.ant-select-selector');
    await act(async () => {
      kindSelector.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
      await flush();
    });
    const dropdown = document.querySelector('.ant-select-dropdown:not(.ant-select-dropdown-hidden)');
    expect(dropdown).toBeTruthy();
    const dropdownText = dropdown.textContent;
    expect(dropdownText).toContain('杂音');
    expect(dropdownText).toContain('谐波干扰');
    expect(mockHttpGet).toHaveBeenCalledWith('/api/interference/categories/');
  });

  it('新建事件分类字段默认「未知/待查」而非「其他」', async () => {
    renderForm();
    await act(async () => { await flush(); });
    expect(selectText(1)).toBe('未知/待查');
    expect(selectText(2)).toBe('未知/待查');
    expect(selectText(3)).toBe('未知/待查');
  });

  it('编辑模式回填存量编码显示名称且不再渲染分类状态字段', async () => {
    S.event = {...EDIT_EVENT};
    renderForm();
    await act(async () => { await flush(); });
    expect(selectText(1)).toBe('杂音');
    expect(selectText(2)).toBe('其他');
    // 存量编码 legacy_env 不在启用选项中，按 *_text 回退显示
    expect(selectText(3)).toBe('历史环境');
    // 分类状态字段已整体下线
    const labels = q('.ant-modal .ant-form-item-label label').map(x => x.textContent);
    expect(labels).not.toContain('分类状态');
  });

  it('编辑提交载荷保留历史分类值且不携带 classification_status', async () => {
    mockHttpPost.mockResolvedValue({});
    S.event = {...EDIT_EVENT};
    renderForm();
    await act(async () => { await flush(); });
    const saveButton = q('.ant-modal-footer .ant-btn-primary')[0];
    await act(async () => {
      saveButton.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    const [url, payload] = mockHttpPost.mock.calls[0];
    expect(url).toBe('/api/interference/events/');
    expect(payload.id).toBe(9);
    expect(payload.datetime).toBe('2026-10-01 09:00:00');
    expect(payload.affected_system_code).toBe('other');
    expect(payload.source_type_code).toBe('legacy_env');
    expect(payload.ground_detail.location).toBe('3号机位');
    expect(payload).not.toHaveProperty('classification_status');
  });
});

describe('分类缺省与选项合并（纯函数）', () => {
  it('新建时对未设置字段应用未知/待查缺省，显式值保留', () => {
    const merged = withCategoryDefaults({affected_system_code: 'other'}, false);
    expect(merged.interference_kind_code).toBe('unknown');
    expect(merged.affected_system_code).toBe('other');
    expect(merged.source_type_code).toBe('unknown');
  });

  it('编辑时不改写任何存量值', () => {
    const values = {interference_kind_code: '', affected_system_code: 'other'};
    expect(withCategoryDefaults(values, true)).toEqual(values);
  });

  it('合并选项时为不在列表中的存量编码追加文本回退项', () => {
    const base = {interference_kind_code: [{value: 'noise', label: '杂音'}]};
    const merged = mergeCategoryOptions(base, {
      interference_kind_code: 'legacy_kind',
      interference_kind_text: '历史类型',
    });
    expect(merged.interference_kind_code).toEqual([
      {value: 'noise', label: '杂音'},
      {value: 'legacy_kind', label: '历史类型'},
    ]);
  });

  it('存量编码已在选项中时不重复追加', () => {
    const base = {source_type_code: [{value: 'environment', label: '环境'}]};
    const merged = mergeCategoryOptions(base, {source_type_code: 'environment'});
    expect(merged.source_type_code).toHaveLength(1);
  });
});

describe('store.fetchCategories', () => {
  it('按分组映射选项、始终携带三个分组键并忽略未知分组', async () => {
    mockHttpGet.mockResolvedValue({records: [
      {group: 'source_type', code: 'unknown', name: '未知/待查'},
      {group: 'unknown_group', code: 'x', name: 'x'},
    ]});
    let options = null;
    await act(async () => {
      options = await S.fetchCategories();
    });
    expect(options.interference_kind_code).toEqual([]);
    expect(options.affected_system_code).toEqual([]);
    expect(options.source_type_code).toEqual([{value: 'unknown', label: '未知/待查'}]);
    expect(S.categoryOptions.source_type_code).toEqual([{value: 'unknown', label: '未知/待查'}]);
  });
});
