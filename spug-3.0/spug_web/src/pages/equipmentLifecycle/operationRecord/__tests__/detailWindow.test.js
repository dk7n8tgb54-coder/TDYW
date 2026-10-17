/**
 * 运行处置记录——详情窗口渲染契约测试（2026-10-15 自 components.test.js 拆分，
 * 满足单文件有效行数门禁）。
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http，验证：
 * - 详情窗口按类型与状态收敛顶部动作：设备故障处置中 → 确认恢复并结案/
 *   撤销故障登记；异常事件已记录 → 认定设备故障/添加跟进记录；一般记录 →
 *   删除；已关闭/已撤销记录无业务动作按钮；
 * - 进展页签标题随记录类型：一般记录=补充记录（N）/ 异常事件=跟进记录（N）/
 *   设备故障=处置记录（N），进展加载中不显示数量，认定设备故障后随详情
 *   刷新切换为处置记录；
 * - 进展条目指称随类型贯穿时间线标题/空态/概览（"进展概览"标题保留通用名），
 *   旧"统一进展"字样不再出现；本次工时输入与展示退役；
 * - 认定设备故障弹窗提交 identify-fault 端点（原记录原地变更）；
 * - 撤销登记弹窗提交 cancel 端点（原因必填，前端拦截空原因不发请求）；
 * - 2026-10-15 体验四轮：详情加载失败显式呈现失败态与重试入口、不渲染依赖
 *   详情的状态操作，重试保持当前记录与页签并在成功后恢复正常显示，旧记录
 *   的迟到详情响应不覆盖新详情渲染。
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

jest.mock('components', () => {
  const React = require('react');
  const Shell = (props) => React.createElement('div', null, props.children);
  Shell.Item = (props) => React.createElement('div', null, props.title || '', props.children);
  const AuthButton = (props) => React.createElement(
    'button',
    {
      onClick: props.onClick,
      'data-auth': props.auth || '',
      type: 'button',
    },
    props.children);
  const Breadcrumb = (props) => React.createElement('div', null, props.children);
  Breadcrumb.Item = Shell;
  const SearchForm = (props) => React.createElement('div', null, props.children);
  SearchForm.Item = Shell.Item;
  return {
    AuthDiv: Shell,
    AuthButton,
    AuthCard: Shell,
    AuthFragment: Shell,
    Breadcrumb,
    SearchForm,
    ExportButton: (props) => React.createElement('button', {
      type: 'button',
      'data-export-params': JSON.stringify(props.params || {}),
    }, props.children),
    TableCard: Shell,
    AttachmentManager: (props) => React.createElement(
      'div', {'data-object-type': props.objectType}, 'attachments'),
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

let container = null;

// 重试按钮：antd 对两字中文按钮自动插空格（"重 试"），匹配前去掉空白
function findRetryButton() {
  return Array.from(document.querySelectorAll('button'))
    .find(btn => (btn.textContent || '').replace(/\s/g, '') === '重试');
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  mockHttpGet.mockReset();
  mockHttpGet.mockResolvedValue({data: [], total: 0});
  mockHttpPost.mockReset();
  mockHttpPost.mockResolvedValue({data: {}});
  mockHttpPut.mockReset();
  mockHttpPut.mockResolvedValue({data: {}});
  mockHttpDelete.mockReset();
  mockHttpDelete.mockResolvedValue({});
  // store 为模块级单例：跨测试重置可见性/失败标记/筛选草稿，避免上个用例的
  // 详情弹窗/失败横幅/关键词草稿泄入下个用例
  const store = require('../store').default;
  store.detailVisible = false;
  store.formVisible = false;
  store.detailId = null;
  store.detail = {};
  store.detailError = false;
  store.fetchError = false;
  store.todoError = false;
  store.statsError = false;
  store.systemRecordsError = false;
  store.records = [];
  store.todoRecords = [];
  store.todoCounts = null;
  store.statistics = null;
  store.activeTab = 'basic';
  store.input_keyword = '';
  store.f_keyword = undefined;
  store.sf_input_keyword = '';
  store.sf_keyword = undefined;
});

afterEach(() => {
  try {
    ReactDOM.unmountComponentAtNode(container);
  } catch (e) {
    // ignore
  }
  document.body.removeChild(container);
  document.querySelectorAll('.ant-modal, .ant-select-dropdown, .ant-message').forEach(
    node => node.parentNode && node.parentNode.removeChild(node));
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

function textContent() {
  return document.body.textContent || '';
}

function findButton(label) {
  return Array.from(document.querySelectorAll('button'))
    .find(btn => (btn.textContent || '').trim() === label);
}

async function renderDetail(detail, progress = {data: [], total: 0}) {
  mockHttpGet.mockImplementation((url) => {
    if (url.endsWith('/progress/')) {
      return Promise.resolve(progress);
    }
    if (url.endsWith('/attachments/')) {
      return Promise.resolve({data: []});
    }
    return Promise.resolve(detail);
  });
  const store = require('../store').default;
  const RecordDetail = require('../RecordDetail').default;
  await act(async () => {
    store.showDetail(detail.id, 'basic');
  });
  await act(async () => {
    ReactDOM.render(React.createElement(RecordDetail), container);
  });
  await act(async () => {
    await flush();
  });
}

const FAULT_DETAIL = {
  id: 11, record_no: 'JL20261011-0001', record_type: 'fault',
  system: 3, system_name: 'DVOR系统', system_location: '机房A',
  occurred_at: '2026-10-11 08:00:00', title: '发射机故障',
  description: '告警灯亮', registrar_name: '张三', status: 'handling',
  affects_system_operation: true, impact_status: 'fault',
  reason_analysis: '', reason_unknown: false,
  source_type: 'manual', source_ledger: null, source_ledger_no: '',
  progress_count: 0, created_by_name: 'op_user',
  // 详情响应计算字段（口径=最新进展时间-发生时间，2026-10-14 起随详情返回）
  latest_progress_at: '2026-10-11 10:30:00', duration_seconds: 9000,
};

const ABNORMAL_DETAIL = {
  ...FAULT_DETAIL,
  id: 12, record_no: 'JL20261011-0002', record_type: 'abnormal',
  title: '信号波动', status: 'recorded', affects_system_operation: false,
  impact_status: '',
};

const ROUTINE_DETAIL = {
  ...FAULT_DETAIL,
  id: 13, record_no: 'JL20261011-0003', record_type: 'routine',
  title: 'UPS巡检', status: 'recorded',
};

const CANCELLED_DETAIL = {
  ...FAULT_DETAIL,
  id: 14, record_no: 'JL20261011-0004', status: 'cancelled',
  cancel_reason: '重复登记',
};

describe('详情窗口动作按类型与状态收敛', () => {
  it('设备故障处置中：确认恢复并结案 + 撤销故障登记，下一步指引突出', async () => {
    await renderDetail(FAULT_DETAIL);
    const text = textContent();
    expect(text).toContain('确认恢复并结案');
    expect(text).toContain('撤销故障登记');
    expect(text).toContain('处置结果');
    // 运行概况展示"发生至最近进展"（9000s=2.5h，2026-10-14 起由列表移至详情，
    // 原"持续时间"更名以避免暗示恢复耗时）
    expect(text).toContain('发生至最近进展');
    expect(text).toContain('2小时30分钟');
    // 下一步指引与主按钮一致
    expect(text).toContain('确认恢复后点击');
    // 2026-10-14 起"添加处置记录"入口在顶部动作区
    expect(findButton('添加处置记录')).toBeTruthy();
    // 异常事件专属动作不出现
    expect(text).not.toContain('认定设备故障');
    expect(text).not.toContain('完成跟进');
  });

  it('异常事件已记录：添加跟进记录 + 认定设备故障，下一步指引指向开始跟进', async () => {
    await renderDetail(ABNORMAL_DETAIL);
    const text = textContent();
    // 2026-10-14 起"开始跟进"由顶部"添加跟进记录"承载（首条跟进即开始跟进）
    expect(text).toContain('添加跟进记录');
    expect(text).toContain('认定设备故障');
    expect(text).toContain('开始跟进');
    expect(text).not.toContain('确认恢复并结案');
    expect(text).not.toContain('撤销故障登记');
    expect(text).not.toContain('删除');
  });

  it('一般记录：编辑 + 删除，无任何异常/故障动作', async () => {
    await renderDetail(ROUTINE_DETAIL);
    const text = textContent();
    expect(text).toContain('删除');
    expect(text).not.toContain('认定设备故障');
    expect(text).not.toContain('确认恢复并结案');
    expect(text).not.toContain('开始跟进');
  });

  it('已关闭故障：无业务动作按钮，处置结果展示真实"恢复耗时"', async () => {
    // 发生 08:00 → 恢复 12:00：恢复耗时 4 小时（与"发生至最近进展"口径区分）
    await renderDetail({
      ...FAULT_DETAIL,
      status: 'closed',
      recovered_at: '2026-10-11 12:00:00',
      recovered_by_name: '李四',
      recovery_close_note: '更换主控板后恢复正常',
      latest_progress_at: '2026-10-11 09:00:00',
      duration_seconds: 3600,
    });
    const text = textContent();
    expect(text).toContain('已关闭归档');
    expect(findButton('添加处置记录')).toBeUndefined();
    expect(text).not.toContain('确认恢复并结案');
    expect(text).toContain('恢复耗时');
    expect(text).toContain('4小时');
    // 发生至最近进展（1 小时）与恢复耗时（4 小时）并存且口径不同
    expect(text).toContain('1小时');
  });

  it('已撤销记录：只读横幅提示，无业务动作按钮', async () => {
    await renderDetail(CANCELLED_DETAIL);
    const text = textContent();
    expect(text).toContain('该登记已撤销，仅供历史追溯');
    expect(text).toContain('撤销原因');
    expect(text).not.toContain('确认恢复并结案');
    expect(text).not.toContain('撤销故障登记');
  });

  it('进展条目不再挂附件入口，记录级附件页签保留', async () => {
    mockHttpGet.mockImplementation((url) => {
      if (url.endsWith('/progress/')) return Promise.resolve({
        data: [{id: 77, handled_at: '2026-10-11 09:00', handler_name: '李四',
          content: '排查中', corrections: []}],
        total: 1,
      });
      if (url.endsWith('/attachments/')) return Promise.resolve(
        [{id: 901, file_name: '现场照片.png', file_size: 1024}]);
      return Promise.resolve(FAULT_DETAIL);
    });
    const store = require('../store').default;
    const RecordDetail = require('../RecordDetail').default;
    await act(async () => {
      store.showDetail(FAULT_DETAIL.id, 'progress');
    });
    await act(async () => {
      ReactDOM.render(React.createElement(RecordDetail), container);
    });
    await act(async () => {
      await flush();
    });
    const text = textContent();
    expect(text).toContain('排查中');
    // 时间线标题随记录类型；"统一进展"、本次工时与逐条附件入口不再出现
    expect(text).toContain('处置记录时间线');
    expect(text).toContain('按时间追加记录的处理过程');
    expect(text).not.toContain('统一进展');
    expect(text).not.toContain('工时');
    expect(text).not.toContain('添加附件');
    expect(document.body.innerHTML).not.toContain('el_operation_progress');
    // 记录级附件页签保留：挂载公共 AttachmentManager（mock 以 data-object-type 暴露对象类型）
    await act(async () => {
      store.setActiveTab('attachments');
      await flush();
    });
    expect(document.body.innerHTML).toContain('el_operation_record');
  });
});

describe('详情进展页签标题随记录类型', () => {
  function tabTitles() {
    return Array.from(document.querySelectorAll('.ant-tabs-tab'))
      .map(node => (node.textContent || '').trim());
  }

  it('设备故障显示"处置记录（N）"', async () => {
    await renderDetail(FAULT_DETAIL, {data: [], total: 3});
    expect(tabTitles()).toContain('处置记录（3）');
    expect(tabTitles()).not.toContain('统一进展（3）');
  });

  it('异常事件显示"跟进记录（N）"', async () => {
    await renderDetail(ABNORMAL_DETAIL, {data: [], total: 2});
    expect(tabTitles()).toContain('跟进记录（2）');
  });

  it('一般记录显示"补充记录（N）"', async () => {
    await renderDetail(ROUTINE_DETAIL, {data: [], total: 0});
    expect(tabTitles()).toContain('补充记录（0）');
  });

  it('进展加载中显示类型标题但不显示数量', async () => {
    mockHttpGet.mockImplementation((url) => {
      if (url.endsWith('/progress/')) return new Promise(() => {});
      if (url.endsWith('/attachments/')) return Promise.resolve({data: []});
      return Promise.resolve(FAULT_DETAIL);
    });
    const store = require('../store').default;
    const RecordDetail = require('../RecordDetail').default;
    await act(async () => {
      store.showDetail(FAULT_DETAIL.id, 'basic');
    });
    await act(async () => {
      ReactDOM.render(React.createElement(RecordDetail), container);
    });
    await act(async () => {
      await flush();
    });
    expect(tabTitles()).toContain('处置记录');
    expect(tabTitles().some(t => t.startsWith('处置记录（'))).toBe(false);
  });

  it('异常事件认定为设备故障后，页签标题更新为"处置记录"', async () => {
    let currentDetail = {...ABNORMAL_DETAIL};
    mockHttpGet.mockImplementation((url) => {
      if (url.endsWith('/progress/')) return Promise.resolve({data: [], total: 1});
      if (url.endsWith('/attachments/')) return Promise.resolve({data: []});
      return Promise.resolve(currentDetail);
    });
    mockHttpPost.mockImplementation((url) => {
      if (url.endsWith('/identify-fault/')) {
        // 原记录原地变更：成功后详情刷新返回 fault 类型
        currentDetail = {
          ...ABNORMAL_DETAIL, record_type: 'fault', status: 'handling',
          affects_system_operation: true, impact_status: 'fault',
        };
      }
      return Promise.resolve({data: {}});
    });
    const store = require('../store').default;
    const RecordDetail = require('../RecordDetail').default;
    await act(async () => {
      store.showDetail(ABNORMAL_DETAIL.id, 'basic');
    });
    await act(async () => {
      ReactDOM.render(React.createElement(RecordDetail), container);
    });
    await act(async () => {
      await flush();
    });
    expect(tabTitles()).toContain('跟进记录（1）');
    const button = findButton('认定设备故障');
    expect(button).toBeTruthy();
    await act(async () => {
      button.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    await act(async () => {
      const modal = Array.from(document.querySelectorAll('.ant-modal'))
        .find(m => m.textContent.includes('在本条记录上认定为设备故障'));
      expect(modal).toBeTruthy();
      const ok = modal.querySelector('.ant-modal-footer .ant-btn-primary');
      expect(ok).toBeTruthy();
      ok.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/12/identify-fault/',
      expect.objectContaining({affects_system_operation: false}));
    expect(tabTitles()).toContain('处置记录（1）');
  });
});

describe('进展概览与时间线条目指称随记录类型', () => {
  it('概览标题保留通用名，条目指称/时间线标题随类型，工时输入退役', async () => {
    mockHttpGet.mockImplementation((url) => {
      if (url.endsWith('/progress/')) return Promise.resolve({
        data: [{id: 5, handled_at: '2026-10-13 09:00', handler_name: '李四',
          content: '巡检正常', corrections: []}],
        total: 2,
      });
      if (url.endsWith('/attachments/')) return Promise.resolve({data: []});
      return Promise.resolve({...ROUTINE_DETAIL, progress_count: 2});
    });
    const store = require('../store').default;
    const RecordDetail = require('../RecordDetail').default;
    await act(async () => {
      store.showDetail(ROUTINE_DETAIL.id, 'basic');
    });
    await act(async () => {
      ReactDOM.render(React.createElement(RecordDetail), container);
    });
    await act(async () => {
      await flush();
    });
    // 基本信息进展概览：标题保留通用名，条目指称与跳转链接随类型
    let text = textContent();
    expect(text).toContain('进展概览');
    expect(text).toContain('补充记录 2 条');
    expect(text).toContain('查看全部补充记录');
    await act(async () => {
      store.setActiveTab('progress');
      await flush();
    });
    text = textContent();
    expect(text).toContain('补充记录时间线');
    // "原因结论请在…原因分析中维护"指引仅设备故障适用，一般记录不出现
    expect(text).not.toContain('原因分析"中维护');
    expect(text).not.toContain('统一进展');
    expect(text).not.toContain('工时');
  });
});

describe('认定设备故障（原记录原地变更）', () => {
  it('弹窗提交 identify-fault 端点并携带故障字段', async () => {
    await renderDetail(ABNORMAL_DETAIL);
    const button = findButton('认定设备故障');
    expect(button).toBeTruthy();
    await act(async () => {
      button.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    const text = textContent();
    expect(text).toContain('在本条记录上认定为设备故障');
    // 默认不影响系统运行：直接提交
    // 详情窗口标题区也含"认定设备故障"按钮文本：按弹窗描述文本精确定位
    await act(async () => {
      const modal = Array.from(document.querySelectorAll('.ant-modal'))
        .find(m => m.textContent.includes('在本条记录上认定为设备故障'));
      expect(modal).toBeTruthy();
      // antd 默认 locale 为 en_US：Modal footer 确认按钮为 OK（主按钮）
      const ok = modal.querySelector('.ant-modal-footer .ant-btn-primary');
      expect(ok).toBeTruthy();
      ok.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/12/identify-fault/',
      expect.objectContaining({affects_system_operation: false}));
  });
});

describe('撤销故障登记', () => {
  it('空原因前端拦截不发请求；填写原因后提交 cancel 端点', async () => {
    await renderDetail(FAULT_DETAIL);
    const button = findButton('撤销故障登记');
    await act(async () => {
      button.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    const modal = Array.from(document.querySelectorAll('.ant-modal'))
      .find(m => m.textContent.includes('撤销故障登记确认'));
    const ok = Array.from(modal.querySelectorAll('button'))
      .find(b => b.textContent.trim() === 'OK');
    // 空原因 → 前端拦截
    await act(async () => {
      ok.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(mockHttpPost).not.toHaveBeenCalled();
    // 填写原因后提交
    const textarea = modal.querySelector('textarea');
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, 'value').set;
      setter.call(textarea, '重复登记');
      textarea.dispatchEvent(new Event('input', {bubbles: true}));
      await flush();
    });
    await act(async () => {
      ok.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/11/cancel/', {cancel_reason: '重复登记'});
  });
});

describe('顶部添加进展入口（2026-10-14 自进展页签迁入）', () => {
  it('进展页签不再有内联表单；顶部按钮弹窗提交进展端点', async () => {
    await renderDetail(ROUTINE_DETAIL);
    const store = require('../store').default;
    // 页签只保留时间线，原内联表单（追加进展按钮）不再出现
    await act(async () => {
      store.setActiveTab('progress');
      await flush();
    });
    expect(textContent()).not.toContain('追加进展');
    // 顶部"添加补充记录"打开弹窗
    await act(async () => {
      findButton('添加补充记录').dispatchEvent(
        new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    // 详情窗口本身也是 Modal：按弹窗标题精确匹配"添加补充记录"弹窗，
    // 避免误中详情 Modal（其动作区文本也含"添加补充记录"）
    const modal = Array.from(document.querySelectorAll('.ant-modal'))
      .find(m => {
        const title = m.querySelector('.ant-modal-title');
        return title && title.textContent === '添加补充记录';
      });
    expect(modal).toBeTruthy();
    // 处理人：tags 输入后回车确认为标签（rc-select 读 event.which 与
    // event.target.value，须原生 setter + input 事件 + which=13 的 keydown）
    const handlerInput = modal.querySelector('.ant-select-selection-search-input');
    const inputSetter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, 'value').set;
    await act(async () => {
      inputSetter.call(handlerInput, '李四');
      handlerInput.dispatchEvent(new Event('input', {bubbles: true}));
      await flush();
    });
    const enterEvent = new KeyboardEvent('keydown', {bubbles: true});
    // React 合成事件 which 取自原生 keyCode（jsdom 构造器不收 keyCode，
    // 须实例上补定义）；rc-select 侧读 which
    Object.defineProperty(enterEvent, 'keyCode', {get: () => 13});
    Object.defineProperty(enterEvent, 'which', {get: () => 13});
    await act(async () => {
      handlerInput.dispatchEvent(enterEvent);
      await flush();
    });
    expect(modal.textContent).toContain('李四');
    // 处理内容后提交
    const textarea = modal.querySelector('textarea');
    const textSetter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype, 'value').set;
    await act(async () => {
      textSetter.call(textarea, '现场检查正常');
      textarea.dispatchEvent(new Event('input', {bubbles: true}));
      await flush();
    });
    await act(async () => {
      modal.querySelector('.ant-modal-footer .ant-btn-primary')
        .dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/13/progress/',
      expect.objectContaining({
        handled_at: expect.any(String),
        handler_name: '李四',
        content: '现场检查正常',
      }));
  });

  it('终态记录不提供添加入口（已关闭故障无"添加处置记录"按钮）', async () => {
    await renderDetail({...FAULT_DETAIL, status: 'closed'});
    expect(findButton('添加处置记录')).toBeUndefined();
    expect(textContent()).not.toContain('确认恢复并结案');
  });
});

describe('详情加载失败状态（2026-10-15）', () => {
  function mockDetailHttp(detailFactory) {
    mockHttpGet.mockImplementation((url) => {
      if (url.endsWith('/progress/')) return Promise.resolve({data: [], total: 0});
      if (url.endsWith('/attachments/')) return Promise.resolve({data: []});
      return detailFactory();
    });
  }

  async function renderDetailWindow() {
    const store = require('../store').default;
    const RecordDetail = require('../RecordDetail').default;
    await act(async () => {
      store.showDetail(FAULT_DETAIL.id, 'basic');
      ReactDOM.render(React.createElement(RecordDetail), container);
    });
    await act(async () => {
      await flush();
    });
    return store;
  }

  it('加载失败：显式失败态与重试入口，不渲染依赖详情的状态操作与区块', async () => {
    mockDetailHttp(() => Promise.reject(new Error('boom')));
    const store = await renderDetailWindow();
    expect(store.detailError).toBe(true);
    const text = textContent();
    expect(text).toContain('详情加载失败');
    expect(findRetryButton()).toBeTruthy();
    // 依赖完整详情的状态操作/区块不渲染（不基于列表行旧数据操作）
    expect(findButton('添加处置记录')).toBeUndefined();
    expect(text).not.toContain('确认恢复并结案');
    expect(text).not.toContain('撤销故障登记');
    expect(text).not.toContain('处置结果');
    expect(text).not.toContain('发生至最近进展');
  });

  it('重试成功恢复正常显示，并保持当前记录与目标页签', async () => {
    let fail = true;
    mockDetailHttp(() => fail
      ? Promise.reject(new Error('boom'))
      : Promise.resolve({...FAULT_DETAIL}));
    const store = await renderDetailWindow();
    expect(store.detailError).toBe(true);
    // 失败后切到进展页签再重试：重试保持当前记录与页签
    await act(async () => {
      store.setActiveTab('progress');
      await flush();
    });
    fail = false;
    mockHttpGet.mockClear();
    await act(async () => {
      findRetryButton().dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(store.detailError).toBe(false);
    expect(store.detailId).toBe(11);
    expect(store.activeTab).toBe('progress');
    // 重试重发当前记录的详情/进展请求
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/records/11/');
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/records/11/progress/');
    // 成功后恢复完整渲染（状态动作在位），失败文案消失；且停留在重试前
    // 的进展页签（重试保持目标页签，基本信息区块不在当前页签渲染）
    const text = textContent();
    expect(text).toContain('确认恢复并结案');
    expect(text).toContain('处置记录时间线');
    expect(text).not.toContain('详情加载失败');
  });

  it('快速切换记录：旧详情迟到响应不覆盖新详情渲染', async () => {
    let resolveA;
    mockHttpGet.mockImplementation((url) => {
      if (url.endsWith('/progress/') || url.endsWith('/attachments/')) {
        return Promise.resolve({data: [], total: 0});
      }
      if (url.endsWith('/records/11/')) {
        return new Promise((resolve) => { resolveA = resolve; });
      }
      return Promise.resolve({...ABNORMAL_DETAIL});
    });
    const store = require('../store').default;
    const RecordDetail = require('../RecordDetail').default;
    await act(async () => {
      store.showDetail(11, 'basic');
      ReactDOM.render(React.createElement(RecordDetail), container);
    });
    // 未等 11 返回即切换 12
    await act(async () => {
      store.showDetail(12, 'basic');
      await flush();
    });
    expect(store.detailId).toBe(12);
    expect(textContent()).toContain('JL20261011-0002');
    // 11 的迟到响应到达：不覆盖 12 的渲染
    await act(async () => {
      resolveA({...FAULT_DETAIL});
      await flush();
    });
    expect(store.detail.record_no).toBe('JL20261011-0002');
    expect(store.detailError).toBe(false);
    expect(textContent()).not.toContain('JL20261011-0001');
  });
});
