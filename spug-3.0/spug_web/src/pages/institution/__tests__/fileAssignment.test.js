/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 文件分工行为测试（详情页文件清单页签 + 分工弹窗，2026-11-03 固定快照版）：
 * - 负责人列：显示有效负责人（effective_owner_name），owner_assigned=false
 *   注明「（手册所有者，默认）」，仅 effective_owner_id 为空才「未分配」；
 *   有分工权限者点击姓名/「未分配」直接打开分工弹窗（操作列无「文件分工」链接）；
 * - 批量分工：勾选多份文件 → 批量弹窗明确已选数量与作用范围，经
 *   store.batchAssignFiles 提交（后端全成功或全失败）；冻结文件行勾选禁用；
 * - 编制状态列：服务端提交快照状态（pending/withdrawn/returned/legacy）映射
 *   文案，前端不推断（不再出现「未提交」）；
 * - 「只看我负责的文件」筛选按服务端 is_mine 过滤行；
 * - 「提交待发布核对」仅有效负责人行渲染（陈旧快照→「重新提交」），确认后经
 *   store.submitCompile 提交并刷新清单+菜单红点；
 * - 旧章节记录（遗留只读）仅在存在记录时过渡展示，无任何写入口。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';

window.matchMedia = window.matchMedia || function () {
  return {matches: false, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}};
};

jest.mock('libs', () => ({
  http: {get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn()},
  history: {push: jest.fn()},
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: false, permissions: []},
}));

jest.mock('antd', () => {
  const antd = jest.requireActual('antd');
  return {
    ...antd,
    message: Object.assign({}, antd.message, {
      success: jest.fn(), error: jest.fn(), warning: jest.fn(),
    }),
  };
});

jest.mock('../detail/store', () => {
  const {observable} = require('mobx');
  class DetailStore {
    @observable id = 7;
    @observable manual = {id: 7, name: '科室操作手册', status: 'active',
      my_roles: ['view', 'edit', 'publish'],
      // 2026-10-31 授权模型：分工业务门=所有者/制度管理员（默认夹具为所有者）
      is_owner: true, is_admin: false,
      current_version: {id: 9, version_no: 3}};
    @observable files = [];
    @observable isFetchingFiles = false;
    @observable currentFiles = null;
    @observable isFetchingCurrentFiles = false;
    @observable currentFilesError = '';
    @observable draftStatus = null;
    @observable isFetchingDraftStatus = false;
    @observable draftStatusError = '';
    @observable chapters = [];
    @observable isFetchingChapters = false;
    fetchFiles = jest.fn(function () { return Promise.resolve(); });
    fetchCurrentFiles = jest.fn(function () { return Promise.resolve(); });
    clearCurrentFiles = jest.fn(function () {});
    fetchDraftStatus = jest.fn(function () { return Promise.resolve(); });
    fetchChapters = jest.fn(function () { return Promise.resolve(); });
    fetchDetail = jest.fn(function () { return Promise.resolve(); });
    // 与真实 store 一致的成功路径：返回的最新文件行就地替换清单行
    assignFile = jest.fn(function (fileId, ownerId, note) {
      const idx = this.files.findIndex(f => f.id === fileId);
      if (idx >= 0) {
        const row = {...this.files[idx],
          assignment: {...this.files[idx].assignment,
            owner_id: ownerId, owner_name: ownerId ? '戊' : '',
            note: note || ''}};
        this.files.splice(idx, 1, row);
        return Promise.resolve(row);
      }
      return Promise.resolve(null);
    });
    batchAssignFiles = jest.fn(function (fileIds, ownerId, note) {
      fileIds.forEach(fileId => {
        const idx = this.files.findIndex(f => f.id === fileId);
        if (idx >= 0) {
          const row = {...this.files[idx],
            assignment: {...this.files[idx].assignment,
              owner_id: ownerId, owner_name: ownerId ? '戊' : '',
              note: note || ''}};
          this.files.splice(idx, 1, row);
        }
      });
      return Promise.resolve({count: fileIds.length, files: []});
    });
    submitCompile = jest.fn(function (fileId) {
      const idx = this.files.findIndex(f => f.id === fileId);
      const row = idx >= 0 ? this.files[idx] : null;
      return Promise.resolve(row);
    });
  }
  return new DetailStore();
});

import {http} from 'libs';
import FileListTab from '../detail/FileListTab';
import FileAssignmentModal from '../detail/FileAssignmentModal';
import store from '../detail/store';
import institutionBadge from '../../../layout/InstitutionBadgeStore';

// 提交待发布核对成功后的菜单红点刷新钩子单独 mock：本套件聚焦分工/提交流程，
// 红点 store 契约钉死在 layout/__tests__
jest.mock('../../../layout/InstitutionBadgeStore', () => ({
  __esModule: true,
  default: {fetch: jest.fn()},
}));

function makeFile(id, over = {}) {
  return Object.assign({
    id, manual_id: 7, name: `文件${id}`, sort_order: id, is_removed: false,
    revision_open: false, draft: null,
    active_session: null,
    assignment: {owner_id: null, owner_name: '', note: '', is_mine: false},
    submission: {state: 'none', submitted_at: null, submitted_by_name: '',
      submission_revision: null, draft_revision: null},
  }, over);
}

const SUBMITTED = {status: 'pending', state: 'submitted', frozen: true,
  submitted_at: '2026-10-20T10:00:00', submitted_by_name: '张三',
  submission_revision: 5, draft_revision: 5,
  snapshot: {file_name: '文件1_快照.docx'}};
const STALE = {status: 'pending', state: 'stale', frozen: false,
  submitted_at: '2026-10-19T10:00:00', submitted_by_name: '张三',
  submission_revision: 4, draft_revision: 6};

function renderTab() {
  const container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(React.createElement(FileListTab), container);
  });
  return container;
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await new Promise(resolve => setTimeout(resolve, 0));
  });
}

function findButton(root, text) {
  return Array.from(root.querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s+/g, '').includes(text));
}

/** 表头文本集合（断言某列是否存在用，避免与说明文案误匹配） */
function columnHeaderTexts(root) {
  return Array.from(root.querySelectorAll('th'))
    .map(th => th.textContent.replace(/\s+/g, ''));
}

/** 2026-10-30 双视图版：负责人/提交/批量分工属「修订草稿」视图，
 *  相关用例先切换视图（默认视图=当前生效版本快照清单） */
function switchView(root, label) {
  const items = Array.from(root.querySelectorAll('.ant-segmented-item'));
  const item = items.find(el => el.textContent.includes(label));
  if (!item) throw new Error('未找到视图切换项: ' + label);
  const input = item.querySelector('input');
  act(() => {
    input.click();
  });
}

let container = null;

beforeEach(() => {
  jest.clearAllMocks();
  const {hasPermission} = require('libs');
  hasPermission.mockImplementation(() => true);
  store.files = [];
  store.chapters = [];
  store.currentFiles = null;
  store.currentFilesError = '';
  store.draftStatus = null;
  store.draftStatusError = '';
  // 分工弹窗挂载即拉负责人候选（制度专用接口 /assignment-owners/，
  // 仅 id+name 最小字段；测试注入两个候选）
  http.get.mockResolvedValue([
    {id: 55, name: '戊'},
    {id: 9, name: '乙'},
  ]);
});

afterEach(() => {
  if (container) {
    ReactDOM.unmountComponentAtNode(container);
    container = null;
  }
  Array.from(document.body.querySelectorAll('.ant-modal, .ant-modal-wrap'))
    .forEach(el => el.remove());
  Array.from(document.body.children).forEach(el => {
    if (el.tagName === 'DIV') el.remove();
  });
});

describe('文件清单页签（文件分工展示）', () => {
  it('负责人列：已分配显示账号名，未分配明确显示「未分配」（草稿视图）', async () => {
    store.files = [
      makeFile(1, {assignment: {owner_id: 9, owner_name: '乙', note: '',
        is_mine: false}}),
      makeFile(2),
    ];
    container = renderTab();
    switchView(container, '修订草稿');
    const text = container.textContent;
    expect(text).toContain('负责人');
    expect(text).toContain('乙');
    expect(text).toContain('未分配');
  });

  it('操作列不再渲染「文件分工」链接（入口在负责人列）', async () => {
    store.files = [makeFile(1)];
    container = renderTab();
    switchView(container, '修订草稿');
    expect(findButton(container, '文件分工')).toBeUndefined();
  });

  it('负责人列点击「未分配」打开分工弹窗，确认后经 store.assignFile 提交', async () => {
    store.files = [makeFile(1, {assignment: {owner_id: 55, owner_name: '戊',
      note: '', is_mine: false}})];
    container = renderTab();
    switchView(container, '修订草稿');
    const ownerLinks = Array.from(
      container.querySelectorAll('.ant-table-tbody a'));
    expect(ownerLinks.length).toBe(1); // 负责人「戊」是行内唯一链接
    act(() => {
      ownerLinks[0].dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    const modal = document.querySelector('.ant-modal');
    expect(modal).not.toBeNull();
    expect(modal.textContent).toContain('文件1');
    // 分工说明以文本输入补充（owner 预填自行数据）
    const textarea = modal.querySelector('textarea');
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, 'value').set;
      setter.call(textarea, '负责正文与附则');
      textarea.dispatchEvent(new Event('input', {bubbles: true}));
    });
    await act(async () => {
      modal.querySelector('.ant-btn-primary').click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    expect(store.assignFile).toHaveBeenCalledWith(1, 55, '负责正文与附则');
    // 成功后行内数据经 updateFileRow 就地刷新（清单不整页重取）
    expect(store.files[0].assignment.note).toBe('负责正文与附则');
    expect(document.querySelector('.ant-modal')).toBeNull();
  });

  it('编制状态列：服务端提交快照状态只映射不推断，不再显示「未提交」', async () => {
    // 非所有者且无发布权：stale 提交的负责人行才落到「提交已失效」
    store.manual = {...store.manual, is_owner: false, my_roles: ['view', 'edit']};
    store.files = [
      makeFile(1, {draft: {revision: 5}, revision_open: false,
        submission: SUBMITTED,
        assignment: {owner_id: 9, owner_name: '乙', note: '', is_mine: true}}),
      makeFile(2, {draft: {revision: 6}, revision_open: true,
        submission: STALE,
        assignment: {owner_id: 9, owner_name: '乙', note: '', is_mine: true}}),
      makeFile(3, {draft: {revision: 1}, revision_open: false}),
    ];
    container = renderTab();
    switchView(container, '修订草稿');
    const text = container.textContent;
    // 2026-11-02：编制提交列合并为「编制状态」列（草稿修订列已删除）
    expect(columnHeaderTexts(container)).toContain('编制状态');
    expect(columnHeaderTexts(container)).not.toContain('编制提交');
    expect(columnHeaderTexts(container)).not.toContain('草稿修订');
    expect(text).toContain('待发布人核对');
    expect(text).toContain('提交已失效（需重新提交）');
    expect(text).toContain('无需提交');
    expect(text).not.toContain('未提交');
  });
});

describe('文件清单页签（分工过滤与提交待发布核对接入）', () => {
  it('只看我负责的文件：按服务端 is_mine 过滤行', async () => {
    store.files = [
      makeFile(1, {assignment: {owner_id: 9, owner_name: '乙', note: '',
        is_mine: true}}),
      makeFile(2, {assignment: {owner_id: 8, owner_name: '丙', note: '',
        is_mine: false}}),
    ];
    container = renderTab();
    switchView(container, '修订草稿');
    expect(container.textContent).toContain('文件2');
    const checkbox = container.querySelector('input[type="checkbox"]');
    act(() => {
      checkbox.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    const text = container.textContent;
    expect(text).toContain('文件1');
    expect(text).not.toContain('文件2');
    expect(text).toContain('只看我负责的文件（1）');
  });

  it('提交待发布核对接入仅有效负责人行；有效快照显示不可点击「待发布人核对」，待提交行经 store.submitCompile', async () => {
    // 非所有者夹具：提交入口唯一依据=该文件有效负责人身份
    store.manual = {...store.manual, is_owner: false};
    store.files = [
      makeFile(1, {draft: {revision: 5}, submission: SUBMITTED,
        assignment: {owner_id: 9, owner_name: '乙', note: '', is_mine: true,
          is_effective_owner: true, effective_owner_id: 9,
          effective_owner_name: '乙'}}),
      makeFile(2, {draft: {revision: 2}, revision_open: true,
        assignment: {owner_id: 9, owner_name: '乙', note: '', is_mine: true,
          is_effective_owner: true, effective_owner_id: 9,
          effective_owner_name: '乙'}}),
      makeFile(3, {draft: {revision: 2},
        assignment: {owner_id: 8, owner_name: '丙', note: '', is_mine: false,
          is_effective_owner: false, effective_owner_id: 8,
          effective_owner_name: '丙'}}),
    ];
    container = renderTab();
    switchView(container, '修订草稿');
    // 有效快照行：显示灰色不可点击「待发布人核对」，不再提供重复提交入口
    const pendingBtn = Array.from(container.querySelectorAll('button'))
      .find(b => b.textContent.replace(/\s+/g, '') === '待发布人核对');
    expect(pendingBtn).not.toBeUndefined();
    expect(pendingBtn.disabled).toBe(true);
    // 只有待提交的有效负责人行（文件2）渲染「提交待发布核对」
    const submitBtns = Array.from(container.querySelectorAll('button'))
      .filter(b => b.textContent.replace(/\s+/g, '') === '提交待发布核对');
    expect(submitBtns.length).toBe(1);
    store.submitCompile.mockResolvedValue(makeFile(2, {submission: SUBMITTED}));
    await act(async () => {
      submitBtns[0].dispatchEvent(new MouseEvent('click', {bubbles: true}));
      // Modal.confirm 异步渲染：等待两轮宏任务后再查询
      await new Promise(resolve => setTimeout(resolve, 0));
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    const confirm = document.querySelector('.ant-modal-confirm');
    expect(confirm).not.toBeNull();
    expect(confirm.textContent).toContain('提交待发布核对：文件2');
    expect(confirm.textContent).toContain('当前草稿修订号 r2');
    // 确认窗说明固定不可变快照 + 冻结语义（不再声称"不保存提交时刻副本"）
    expect(confirm.textContent).toContain('固定不可变内容快照');
    expect(confirm.textContent).not.toContain('系统不保存提交时刻的文件副本');
    await act(async () => {
      confirm.querySelector('.ant-btn-primary').click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    expect(store.submitCompile).toHaveBeenCalledWith(2);
    // 提交真实成功后立即刷新清单与菜单红点（待核对提交数）
    expect(store.fetchFiles).toHaveBeenCalledWith(7);
    expect(institutionBadge.fetch).toHaveBeenCalled();
  });
});

describe('文件清单页签（批量分工）', () => {
  beforeEach(() => {
    // 批量分工是所有者/超管的业务门：显式恢复所有者夹具（前组用例
    // 收窄过 is_owner，mock store 跨用例共享）
    store.manual = {...store.manual, is_owner: true};
  });

  function checkRow(container, rowIndex) {
    const checkboxes = Array.from(
      container.querySelectorAll('.ant-table-tbody input[type="checkbox"]'));
    act(() => {
      checkboxes[rowIndex].dispatchEvent(
        new MouseEvent('click', {bubbles: true}));
    });
  }

  it('勾选多份文件 → 批量弹窗明确数量与范围 → 经 store.batchAssignFiles 提交', async () => {
    store.files = [makeFile(1), makeFile(2)];
    container = renderTab();
    switchView(container, '修订草稿');
    checkRow(container, 0);
    checkRow(container, 1);
    expect(container.textContent).toContain('已选 2 份文件');
    act(() => {
      findButton(container, '批量指定负责人')
        .dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    const modal = document.querySelector('.ant-modal');
    expect(modal.textContent).toContain('批量文件分工（2 份文件）');
    expect(modal.textContent).toContain('文件1');
    expect(modal.textContent).toContain('文件2');
    await act(async () => {
      modal.querySelector('.ant-btn-primary').click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    expect(store.batchAssignFiles).toHaveBeenCalledWith([1, 2], null, '');
    expect(document.querySelector('.ant-modal')).toBeNull();
  });

  it('勾选后切筛选/清除选择清空勾选（不得误操作旧选择）', async () => {
    store.files = [makeFile(1), makeFile(2)];
    container = renderTab();
    switchView(container, '修订草稿');
    checkRow(container, 0);
    expect(container.textContent).toContain('已选 1 份文件');
    // 「只看我负责的文件」切换清空勾选（筛选后不可见的文件不保留选择）
    const onlyMine = Array.from(
      container.querySelectorAll('input[type="checkbox"]'))
      .find(c => c.closest('label') &&
        c.closest('label').textContent.includes('只看我负责的文件'));
    act(() => {
      onlyMine.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(container.textContent).not.toContain('已选 1 份文件');
    // 切回筛选后再勾选，点「清除选择」同样清空
    act(() => {
      onlyMine.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    checkRow(container, 0);
    expect(container.textContent).toContain('已选 1 份文件');
    act(() => {
      findButton(container, '清除选择')
        .dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    expect(container.textContent).not.toContain('已选 1 份文件');
  });
});

describe('文件清单页签（旧章节过渡与仅查看口径）', () => {
  it('旧章节记录存在时只读过渡展示，无任何写入口', async () => {
    store.files = [makeFile(1)];
    store.chapters = [
      {id: 3, title: '第一章 总则', owner_name: '乙', note: '旧记录',
        progress: 'in_progress', progress_display: '编制中',
        submitted_at: null, updated_at: '2026-10-01T10:00:00'},
    ];
    container = renderTab();
    const text = container.textContent;
    expect(text).toContain('第一章 总则');
    expect(text).toContain('编制中');
    expect(text).toContain('人工核对');
    // 无新增/删除/编辑入口（写接口已在后端关闭，前端不渲染维护按钮）
    expect(findButton(container, '添加章节分工')).toBeUndefined();
    expect(findButton(container, '删除')).toBeUndefined();
  });

  it('无旧章节记录时不渲染过渡面板', async () => {
    store.files = [makeFile(1)];
    container = renderTab();
    expect(container.textContent).not.toContain('人工核对');
  });

  it('仅查看角色的生效视图不渲染负责人列，仍无编制提交列与分工入口', async () => {
    const {hasPermission} = require('libs');
    hasPermission.mockImplementation(
      code => code === 'institution.manual.view' ||
        code === 'institution.manual.download');
    store.manual = Object.assign({}, store.manual, {my_roles: ['view'],
      // 纯仅查看账号：无所有者/管理员身份（工作区不可见，生效视图说明
      // 不出现工作区措辞）
      is_owner: false, is_admin: false});
    store.files = [makeFile(1, {assignment: {owner_id: 9, owner_name: '乙',
      note: '', is_mine: false}})];
    store.currentFiles = {version_id: 9, version_no: 3, items: [
      {id: 101, manual_file_id: 1, file_name: '文件1', sort_order: 0,
        file_size: 10, file_hash: 'h', change_type: 'unchanged'},
    ], removed_items: []};
    container = renderTab();
    const text = container.textContent;
    // 行来自生效快照
    expect(text).toContain('文件1');
    // 生效视图不渲染负责人列（2026-10-31 起：负责人属修订分工，只在
    // 修订草稿视图展示；表头断言以 th 文本为准，避免与说明文案误匹配）
    expect(columnHeaderTexts(container)).not.toContain('负责人');
    expect(text).not.toContain('编制提交');
    // 无任何分工点击入口
    expect(container.querySelector('.ant-table-tbody a')).toBeNull();
    expect(findButton(container, '提交待发布核对')).toBeUndefined();
  });

  it('无 draft_edit 页面权限：所有者打开分工也必然被拒，入口只读（保存必被拒不出现可点击入口）', async () => {
    // 后端写接口=@auth draft_edit +（所有者/管理员）；前端入口必须
    // 同时校验两层，缺 draft_edit 时点击后保存必然"权限拒绝"。
    // 注意 2026-10-31 起工作区可见性含所有者（is_owner），
    // 草稿视图可达，但分工入口仍必须只读
    const {hasPermission} = require('libs');
    hasPermission.mockImplementation(
      code => code === 'institution.manual.view' ||
        code === 'institution.manual.download' ||
        code === 'institution.manual.edit');
    store.manual = Object.assign({}, store.manual, {my_roles: ['view'],
      is_owner: true, is_admin: false});
    store.files = [makeFile(1, {assignment: {owner_id: 9, owner_name: '乙',
      note: '', is_mine: false}})];
    container = renderTab();
    switchView(container, '修订草稿');
    const text = container.textContent;
    expect(text).toContain('乙');
    // 负责人列只读：无链接入口
    expect(container.querySelector('.ant-table-tbody a')).toBeNull();
    // 无批量分工入口与勾选列
    expect(findButton(container, '批量指定负责人')).toBeUndefined();
    expect(findButton(container, '清空负责人')).toBeUndefined();
    expect(container.querySelector('.ant-table-selection-column')).toBeNull();
  });

  it('有 draft_edit + 编制角色（非所有者/管理员）：负责人列只读（2026-10-31 分工收窄为所有者/管理员）', async () => {
    const {hasPermission} = require('libs');
    hasPermission.mockImplementation(
      code => code === 'institution.manual.view' ||
        code === 'institution.manual.download' ||
        code === 'institution.manual.draft_edit');
    // 二轮权限模型改造：编制授权不再经开关获得发布版可见性，补 view 角色
    // 保持「可见两个视图的非负责人」用例口径（本用例主题=负责人列只读）
    store.manual = Object.assign({}, store.manual, {my_roles: ['view', 'edit'],
      is_owner: false, is_admin: false});
    store.files = [makeFile(1, {assignment: {owner_id: 9, owner_name: '乙',
      note: '', is_mine: false}})];
    container = renderTab();
    switchView(container, '修订草稿');
    expect(container.textContent).toContain('乙');
    // 负责人列只读，无勾选列与批量入口
    expect(container.querySelector('.ant-table-tbody a')).toBeNull();
    expect(container.querySelector('.ant-table-selection-column')).toBeNull();
  });

  it('制度管理员（is_admin）持 draft_edit：负责人列可点击（与所有者同口径）', async () => {
    const {hasPermission} = require('libs');
    hasPermission.mockImplementation(
      code => code === 'institution.manual.view' ||
        code === 'institution.manual.download' ||
        code === 'institution.manual.draft_edit');
    store.manual = Object.assign({}, store.manual, {my_roles: ['view'],
      is_owner: false, is_admin: true});
    store.files = [makeFile(1, {assignment: {owner_id: 9, owner_name: '乙',
      note: '', is_mine: false}})];
    container = renderTab();
    switchView(container, '修订草稿');
    const ownerLinks = Array.from(
      container.querySelectorAll('.ant-table-tbody a'));
    expect(ownerLinks.length).toBe(1);
  });
});

describe('FileAssignmentModal（文件分工弹窗）', () => {
  // antd Modal 经 portal 渲染到 document.body，断言须查 document 而非局部容器
  function renderModal(props) {
    const container = document.createElement('div');
    document.body.appendChild(container);
    act(() => {
      ReactDOM.render(
        <FileAssignmentModal manualId={7} {...props} onClose={() => {}}/>,
        container);
    });
    return container;
  }

  it('已有分工回填负责人与说明；确认提交携带显式 owner_id', async () => {
    const onSubmit = jest.fn(() => Promise.resolve());
    const file = makeFile(1, {name: '甲.docx',
      assignment: {owner_id: 55, owner_name: '戊', note: '旧说明',
        is_mine: false}});
    renderModal({file, onSubmit});
    await flush();
    const modal = document.querySelector('.ant-modal');
    expect(modal).not.toBeNull();
    expect(modal.textContent).toContain('甲.docx');
    // Select 预填值经 rc-select 展示（选项加载完成后显示昵称）
    expect(modal.textContent).toContain('戊');
    const textarea = modal.querySelector('textarea');
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, 'value').set;
      setter.call(textarea, '新说明');
      textarea.dispatchEvent(new Event('input', {bubbles: true}));
    });
    await act(async () => {
      modal.querySelector('.ant-btn-primary').click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    expect(onSubmit).toHaveBeenCalledWith(55, '新说明');
  });

  it('未指定负责人时提交 owner_id=null（清空即未分配）', async () => {
    const onSubmit = jest.fn(() => Promise.resolve());
    renderModal({file: makeFile(2), onSubmit});
    const modal = document.querySelector('.ant-modal');
    expect(modal).not.toBeNull();
    await act(async () => {
      modal.querySelector('.ant-btn-primary').click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    expect(onSubmit).toHaveBeenCalledWith(null, '');
  });

  it('批量模式：标题携带已选数量，明确作用范围且不预填现有负责人', async () => {
    const onSubmit = jest.fn(() => Promise.resolve());
    const files = [
      makeFile(1, {name: '甲.docx',
        assignment: {owner_id: 55, owner_name: '戊', note: '', is_mine: false}}),
      makeFile(2, {name: '乙.docx'}),
    ];
    renderModal({files, onSubmit});
    await flush();
    const modal = document.querySelector('.ant-modal');
    expect(modal.textContent).toContain('批量文件分工（2 份文件）');
    expect(modal.textContent).toContain('甲.docx');
    expect(modal.textContent).toContain('乙.docx');
    expect(modal.textContent).toContain('整体生效');
    // 不预填任何现有负责人（多份文件现状可能不同）：无 rc-select 选中项
    expect(modal.querySelector('.ant-select-selection-item')).toBeNull();
    await act(async () => {
      modal.querySelector('.ant-btn-primary').click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    expect(onSubmit).toHaveBeenCalledWith(null, '');
  });

  it('候选走制度专用接口且抑制拦截器弹错（错误只在弹窗内展示一次）', async () => {
    renderModal({file: makeFile(2), onSubmit: jest.fn()});
    await flush();
    expect(http.get).toHaveBeenCalledWith(
      '/api/institution/manuals/7/assignment-owners/',
      {skipErrorNotification: true});
  });

  it('候选加载失败：弹窗内展示明确错误与重试，重试成功后候选可选', async () => {
    http.get.mockRejectedValue('权限拒绝');
    renderModal({file: makeFile(2), onSubmit: jest.fn()});
    await flush();
    let modal = document.querySelector('.ant-modal');
    expect(modal.textContent).toContain('负责人候选加载失败');
    expect(modal.textContent).toContain('权限拒绝');
    expect(modal.textContent).toContain('重试');
    // 重试成功：错误消失，候选注入（下拉出现选项数据源）
    http.get.mockResolvedValue([{id: 55, name: '戊'}]);
    const retryBtn = Array.from(modal.querySelectorAll('button'))
      .find(b => b.textContent.replace(/\s+/g, '') === '重试');
    expect(retryBtn).not.toBeUndefined();
    await act(async () => {
      retryBtn.click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    modal = document.querySelector('.ant-modal');
    expect(modal.textContent).not.toContain('负责人候选加载失败');
    expect(http.get).toHaveBeenCalledTimes(2);
  });
});
