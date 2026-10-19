/**
 * 运行处置记录——详情附件可见性行为测试（2026-10-18）。
 * 真实渲染 RecordDetail（ReactDOM + jsdom），mock libs.http；components 的
 * AttachmentManager 以"迷你管理器"模拟公共组件契约：挂载/recordId 变化时
 * 调用 listRequest（store 适配器，走真实 http mock）取列表并回传
 * onCountChange(全量长度)；提供模拟上传（POST 上传端点成功后才回写数量）
 * 与删除（走调用方真实 deleteRequest prop）按钮。验证：
 * - 附件区块位于进展时间线之前，单页无页签；
 * - 顶部快捷入口与附件区块标题共用同一数量口径（附件（N）/附件（0）/
 *   附件加载中/附件加载失败），加载中禁用；
 * - 默认收起，标题点击展开/收起；顶部入口点击展开并定位附件区块；
 * - 上传/删除真实成功后数量同步、失败数量不变；
 * - 失败后点击入口重试：重发列表请求并恢复数量；
 * - 切换记录：展开状态重置，旧记录迟到响应不污染新记录数量；
 * - 定位目标 attachments（2026-10-18 前的查看附件类入口）自动展开并定位。
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

// 定位函数以 spy 观察（区块锚点 ID 保持真实实现导出）
jest.mock('../detailSections', () => ({
  ...jest.requireActual('../detailSections'),
  scrollToSection: jest.fn(() => true),
}));

// 迷你 AttachmentManager：模拟公共组件的 listRequest/onCountChange/
// deleteRequest 契约（真实组件行为见公共组件自身），供本套件驱动真实
// store 数据流
jest.mock('components', () => {
  const React = require('react');
  const {useEffect, useRef, useState} = React;
  const {http} = require('libs');
  const AttachmentManager = (props) => {
    const itemsRef = useRef([]);
    const [, bump] = useState(0);
    useEffect(() => {
      let mounted = true;
      if (props.listRequest) {
        props.listRequest().then(rows => {
          if (!mounted) return;
          itemsRef.current = rows || [];
          if (props.onCountChange) props.onCountChange(itemsRef.current.length);
          bump(n => n + 1);
        }).catch(() => {});
      }
      return () => { mounted = false; };
    }, [props.recordId, props.listRequest]);
    const reportCount = () => {
      if (props.onCountChange) props.onCountChange(itemsRef.current.length);
      bump(n => n + 1);
    };
    // 模拟上传：POST 上传端点真实成功后才回写数量（与真实管理器一致）
    const mockUpload = () => {
      http.post(props.uploadUrl, {}).then(() => {
        itemsRef.current = [...itemsRef.current, {id: 999, file_name: '新附件'}];
        reportCount();
      }).catch(() => {});
    };
    // 模拟删除：走调用方传入的真实 deleteRequest，成功后才回写数量
    const mockDelete = () => {
      const att = itemsRef.current[0];
      if (!att) return;
      props.deleteRequest(att).then(() => {
        itemsRef.current = itemsRef.current.filter(x => x.id !== att.id);
        reportCount();
      }).catch(() => {});
    };
    return React.createElement('div', {
      'data-object-type': props.objectType,
      'data-readonly': props.readOnly ? 'true' : 'false',
    },
    React.createElement('button', {type: 'button', onClick: mockUpload}, 'mock上传'),
    React.createElement('button', {type: 'button', onClick: mockDelete}, 'mock删除'));
  };
  // 详情顶部动作按钮（RecordDetailActions）与时间线更正入口所需的
  // 权限按钮壳（isSuper=true 直通）
  const AuthButton = (props) => React.createElement(
    'button',
    {onClick: props.onClick, 'data-auth': props.auth || '', type: 'button'},
    props.children);
  return {AttachmentManager, AuthButton};
});

const {scrollToSection, PROGRESS_SECTION_ID, ATTACHMENT_SECTION_ID,
  ATTACHMENT_PANEL_ID} = require('../detailSections');

if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

const FAULT_DETAIL = {
  id: 11, record_no: 'JL20261011-0001', record_type: 'fault',
  system: 3, system_name: 'DVOR系统', system_location: '机房A',
  occurred_at: '2026-10-11 08:00:00', title: '发射机故障',
  description: '告警灯亮', registrar_name: '张三', status: 'handling',
  affects_system_operation: true, impact_status: 'fault',
  source_type: 'manual', progress_count: 0, created_by_name: 'op_user',
};

let container = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  mockHttpGet.mockReset();
  mockHttpPost.mockReset();
  mockHttpPost.mockResolvedValue({data: {}});
  mockHttpPut.mockReset();
  mockHttpDelete.mockReset();
  mockHttpDelete.mockResolvedValue({});
  scrollToSection.mockClear();
  const store = require('../store').default;
  store.detailVisible = false;
  store.detailId = null;
  store.detail = {};
  store.detailError = false;
  store.records = [];
  store.pendingSection = 'basic';
  store.attachments = [];
  store.attachmentsTotal = 0;
  store.attachmentsError = false;
  store.attachmentsExpanded = false;
  store.isAttachmentsFetching = false;
  store.attachmentRetrySeq = 0;
  store.systemRecordsSystemId = null;
});

afterEach(() => {
  try {
    ReactDOM.unmountComponentAtNode(container);
  } catch (e) {
    // ignore
  }
  document.body.removeChild(container);
  document.querySelectorAll('.ant-modal, .ant-message').forEach(
    node => node.parentNode && node.parentNode.removeChild(node));
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

function findButton(label) {
  return Array.from(document.querySelectorAll('button'))
    .find(btn => (btn.textContent || '').replace(/\s/g, '') === label);
}

function attachmentHeader() {
  return document.querySelector(`#${ATTACHMENT_SECTION_ID} > button`);
}

function attachmentPanel() {
  return document.getElementById(ATTACHMENT_PANEL_ID);
}

function click(btn) {
  return act(async () => {
    btn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    await flush();
  });
}

// 渲染详情：attachments 为数组（列表响应）/'pending'（挂起）/'error'（拒绝）；
// 传入 impl 时使用调用方自建的 http mock 实现（切换记录竞态用例）
async function renderDetail(detail, attachments = [], section = 'basic',
    impl = null) {
  if (impl) {
    mockHttpGet.mockImplementation(impl);
  } else {
    mockHttpGet.mockImplementation((url) => {
      if (url.endsWith('/progress/')) return Promise.resolve({data: [], total: 0});
      if (url.endsWith('/attachments/')) {
        if (attachments === 'pending') return new Promise(() => {});
        if (attachments === 'error') return Promise.reject(new Error('boom'));
        return Promise.resolve(attachments);
      }
      return Promise.resolve(detail);
    });
  }
  const store = require('../store').default;
  const RecordDetail = require('../RecordDetail').default;
  await act(async () => {
    store.showDetail(detail.id, section);
    ReactDOM.render(React.createElement(RecordDetail), container);
  });
  await act(async () => {
    await flush();
  });
  return store;
}

// 附件列表请求次数（断言重试是否重发）
function attachmentGetCalls() {
  return mockHttpGet.mock.calls.filter(
    ([url]) => String(url).endsWith('/attachments/')).length;
}

describe('附件区块位置与数量展示（2026-10-18）', () => {
  it('附件区块位于进展时间线之前，单页无页签', async () => {
    await renderDetail(FAULT_DETAIL, [{id: 1}, {id: 2}]);
    expect(document.querySelector('.ant-tabs-tab')).toBeNull();
    const att = document.getElementById(ATTACHMENT_SECTION_ID);
    const progress = document.getElementById(PROGRESS_SECTION_ID);
    expect(att).toBeTruthy();
    expect(progress).toBeTruthy();
    // DOCUMENT_POSITION_FOLLOWING：进展区块位于附件区块之后
    expect(
      att.compareDocumentPosition(progress) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

  it('多条附件：顶部入口与区块标题同显"附件（2）"', async () => {
    await renderDetail(FAULT_DETAIL, [{id: 1}, {id: 2}]);
    expect(findButton('附件（2）')).toBeTruthy();
    expect(attachmentHeader().textContent).toContain('附件（2）');
    // 顶部快捷入口与附件区块标题共用同一数量（恰好两处）
    expect(Array.from(document.querySelectorAll('button'))
      .filter(btn => btn.textContent.includes('附件（2）'))).toHaveLength(2);
  });

  it('无附件：同显"附件（0）"，不显示加载中或失败', async () => {
    await renderDetail(FAULT_DETAIL, []);
    expect(findButton('附件（0）')).toBeTruthy();
    expect(attachmentHeader().textContent).toContain('附件（0）');
    expect(document.body.textContent).not.toContain('附件加载');
  });

  it('加载中：同显"附件加载中"且顶部入口禁用，不显示为 0', async () => {
    await renderDetail(FAULT_DETAIL, 'pending');
    expect(findButton('附件加载中')).toBeTruthy();
    expect(findButton('附件加载中').disabled).toBe(true);
    expect(attachmentHeader().textContent).toContain('附件加载中');
  });

  it('加载失败：区块标题提供重试并恢复数量', async () => {
    const store = await renderDetail(FAULT_DETAIL, 'error');
    expect(findButton('附件加载失败，重试')).toBeTruthy();
    expect(attachmentHeader().textContent).toContain('附件加载失败');
    expect(attachmentGetCalls()).toBe(1);
    // 恢复为成功响应后点击区块标题：展开并重发列表请求
    mockHttpGet.mockImplementation((url) => {
      if (url.endsWith('/progress/')) return Promise.resolve({data: [], total: 0});
      if (url.endsWith('/attachments/')) {
        return Promise.resolve([{id: 1, file_name: '现场照片.png'}]);
      }
      return Promise.resolve(FAULT_DETAIL);
    });
    await click(attachmentHeader());
    expect(store.attachmentsExpanded).toBe(true);
    expect(attachmentGetCalls()).toBe(2);
    // 重试成功后数量恢复，失败文案消失
    const text = document.body.textContent;
    expect(text).toContain('附件（1）');
    expect(text).not.toContain('附件加载失败');
  });

  it('顶部入口点击：展开附件区并在弹窗内定位', async () => {
    const store = await renderDetail(FAULT_DETAIL, [{id: 1}]);
    await click(findButton('附件（1）'));
    expect(store.attachmentsExpanded).toBe(true);
    expect(attachmentPanel().style.display).toBe('block');
    expect(scrollToSection).toHaveBeenCalledWith(ATTACHMENT_SECTION_ID);
  });

  it('默认收起：标题点击展开/再点收起，aria 状态同步', async () => {
    await renderDetail(FAULT_DETAIL, [{id: 1}]);
    expect(attachmentPanel().style.display).toBe('none');
    expect(attachmentHeader().getAttribute('aria-expanded')).toBe('false');
    await click(attachmentHeader());
    expect(attachmentPanel().style.display).toBe('block');
    expect(attachmentHeader().getAttribute('aria-expanded')).toBe('true');
    await click(attachmentHeader());
    expect(attachmentPanel().style.display).toBe('none');
    expect(attachmentHeader().getAttribute('aria-expanded')).toBe('false');
  });

  it('定位目标 attachments：自动展开并定位后复位（内容就绪后执行）', async () => {
    const store = await renderDetail(FAULT_DETAIL, [{id: 1}], 'attachments');
    expect(store.attachmentsExpanded).toBe(true);
    expect(store.pendingSection).toBe('basic');
    expect(scrollToSection).toHaveBeenCalledWith(ATTACHMENT_SECTION_ID);
    expect(attachmentPanel().style.display).toBe('block');
  });
});

describe('附件数量同步与记录切换（2026-10-18）', () => {
  it('上传真实成功后标题与列表同步，失败不更新', async () => {
    await renderDetail(FAULT_DETAIL, [{id: 1}, {id: 2}]);
    mockHttpGet.mockClear();
    await click(findButton('mock上传'));
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/11/attachments/', {});
    expect(attachmentHeader().textContent).toContain('附件（3）');
    expect(mockHttpGet.mock.calls.filter(([url]) =>
      url === '/api/equipment-lifecycle/records/')).toHaveLength(1);
    // 上传失败：数量不变
    mockHttpPost.mockRejectedValueOnce(new Error('boom'));
    await click(findButton('mock上传'));
    expect(attachmentHeader().textContent).toContain('附件（3）');
    expect(mockHttpGet.mock.calls.filter(([url]) =>
      url === '/api/equipment-lifecycle/records/')).toHaveLength(1);
  });

  it('删除真实成功后数量同步减一，失败不变', async () => {
    await renderDetail(FAULT_DETAIL, [{id: 1}, {id: 2}]);
    await click(findButton('mock删除'));
    expect(mockHttpDelete).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/11/attachments/1/');
    expect(attachmentHeader().textContent).toContain('附件（1）');
    // 删除失败：数量不变
    mockHttpDelete.mockRejectedValueOnce(new Error('boom'));
    await click(findButton('mock删除'));
    expect(attachmentHeader().textContent).toContain('附件（1）');
  });

  it('切换记录：展开状态重置为收起，迟到旧响应不污染新记录数量', async () => {
    let resolveOld;
    const impl = (url) => {
      if (url.endsWith('/progress/')) return Promise.resolve({data: [], total: 0});
      if (url.includes('/records/11/attachments/')) {
        return new Promise((resolve) => { resolveOld = resolve; });
      }
      if (url.includes('/records/12/attachments/')) {
        return Promise.resolve([{id: 5, file_name: '新记录附件'}]);
      }
      return Promise.resolve(
        url.includes('/records/11/') ? FAULT_DETAIL
          : {...FAULT_DETAIL, id: 12, record_no: 'JL20261011-0002'});
    };
    // 记录 11 的附件列表挂起（迟到响应场景），先展开附件区
    const store = await renderDetail(FAULT_DETAIL, 'pending', 'basic', impl);
    await click(attachmentHeader());
    expect(store.attachmentsExpanded).toBe(true);
    // 切换到记录 12：展开状态重置；新记录列表到达后数量为新记录的
    await act(async () => {
      store.showDetail(12);
      await flush();
    });
    expect(store.attachmentsExpanded).toBe(false);
    expect(attachmentPanel().style.display).toBe('none');
    expect(attachmentHeader().textContent).toContain('附件（1）');
    // 旧记录 11 的迟到列表响应：仅失效拒绝，不覆盖新记录数量与状态
    await act(async () => {
      resolveOld([{id: 1}, {id: 2}]);
      await flush();
    });
    expect(attachmentHeader().textContent).toContain('附件（1）');
    expect(store.attachmentsError).toBe(false);
  });
});
