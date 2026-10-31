/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 初始来源页签交互行为测试（jsdom + ReactDOM，2026-10-29 改版）：
 * - 进页签一次拉取 originals-overview 聚合清单（每文件一行），不再渲染
 *   逐文件选择下拉、不为每一行单独发请求。
 * - 「新增制度文件」批量上传：每个所选文件各建一份制度文件（逐个走
 *   files/create），不得把多个文件追加到同一项；draft_error 只警示不算失败。
 * - 「为已有文件更换来源」是按行受控操作：选择文件后必须确认目标文件
 *   与对草稿的影响，确认后才上传为该文件的新原稿记录。
 * - 隐藏 file input 必须 ref 程序触发（死按钮回归防护）。
 * - 「从原始上传文件重建草稿」：未发布过版本的制度主行直接可见（普通
 *   确认、携带 original_id）；已发布过版本的制度收进"高级恢复操作"，
 *   弹窗带风险提示、confirm=true 与编辑密码；原稿已按保留策略清理的
 *   记录不渲染 预览/下载/重建 入口（仅存来源元数据）。
 * - 展开历史区分「最初原稿」与「后续来源」，已清理记录展示清理时间。
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

jest.mock('../detail/PreviewModal', () => function PreviewModal() {
  return null;
});

const mockOverviewRow = {
  file_id: 11, name: '第一章 总则', sort_order: 0, is_removed: false,
  originals_count: 1,
  first_original: {id: 5, file_name: '手册.docx', ext: '.docx', file_size: 1024,
    uploaded_by_name: '张三', uploaded_at: '2026-01-05T10:00:00',
    is_cleaned: false, cleaned_at: null},
  has_usable_original: true,
  first_published_version_no: null, first_published_at: null,
  history: [{id: 5, file_name: '手册.docx', ext: '.docx', file_size: 1024,
    uploaded_by_name: '张三', uploaded_at: '2026-01-05T10:00:00',
    is_cleaned: false, cleaned_at: null}],
  draft: {has_draft: true, revision: 3, source_original_id: 5},
};

jest.mock('../detail/store', () => {
  const {observable} = require('mobx');
  class DetailStore {
    @observable id = 7;
    @observable manual = {id: 7, name: '科室操作手册', my_roles: ['edit'],
      // 2026-10-31 授权模型：上传/更换来源业务门=所有者/管理员；
      // 重建按文件负责人独占判定（配合 store.files 的 assignment）
      is_owner: true, is_admin: false};
    @observable originalsOverview = [];
    @observable isFetchingOriginalsOverview = false;
    @observable originalsOverviewError = '';
    @observable files = [];
    fetchOriginalsOverview = jest.fn(function () {
      this.originalsOverview = [JSON.parse(JSON.stringify(mockOverviewRow))];
      return Promise.resolve();
    });
    fetchDetail = jest.fn(function () {
      this.manual = Object.assign({}, this.manual);
      return Promise.resolve();
    });
  }
  return new DetailStore();
});

import OriginalsTab from '../detail/OriginalsTab';
import {http} from 'libs';
import store from '../detail/store';

function renderTab() {
  const container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(React.createElement(OriginalsTab), container);
  });
  return container;
}

function flush() {
  return act(async () => {
    await new Promise(resolve => setTimeout(resolve, 0));
  });
}

function findButton(container, text) {
  // antd 对两字中文按钮在非 link 型会插空格（"重 试"），归一化后匹配
  return Array.from(container.querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s+/g, '').includes(text));
}

function pickFiles(container, names) {
  const input = container.querySelector('input[type="file"]');
  Object.defineProperty(input, 'files', {
    value: names.map(n => new File(['PK\x03\x04'], n))});
  return act(async () => {
    input.dispatchEvent(new Event('change', {bubbles: true}));
  });
}

function clickButton(button) {
  return act(async () => {
    button.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
}

function confirmOk() {
  return act(async () => {
    const okButton = document.querySelector('.ant-modal-confirm .ant-btn-primary');
    okButton.click();
    await Promise.resolve();
    await Promise.resolve();
    await new Promise(resolve => setTimeout(resolve, 0));
  });
}

function confirmText() {
  return document.querySelector('.ant-modal-confirm').textContent;
}

afterEach(() => {
  Array.from(document.body.children).forEach(el => {
    if (el.tagName === 'DIV') el.remove();
  });
  jest.clearAllMocks();
});

beforeEach(() => {
  // 预览端点默认可解析（用例内可覆盖）；避免未打桩时点击预览直接 TypeError
  http.get.mockResolvedValue({preview_url: 'http://preview/example', file_name: 'x.docx'});
  // store 是模块级单例：每个用例前复位基础状态，防止前一用例的错误态/
  // enableVersions 改写泄漏到后续用例
  store.manual = {id: 7, name: '科室操作手册', my_roles: ['edit'],
    is_owner: true, is_admin: false};
  // 负责人独占重建（2026-10-31）：默认当前账号是 file 11 的负责人
  store.files = [{id: 11, name: '第一章 总则',
    assignment: {owner_id: 9, owner_name: '我', note: '', is_mine: true}}];
  store.originalsOverview = [];
  store.originalsOverviewError = '';
  store.fetchDetail = jest.fn(function () {
    this.manual = Object.assign({}, this.manual);
    return Promise.resolve();
  });
});

describe('初始来源聚合清单', () => {
  it('进页签一次拉取 originals-overview 聚合清单，不渲染文件下拉', async () => {
    const container = renderTab();
    await flush();
    expect(store.fetchOriginalsOverview).toHaveBeenCalledTimes(1);
    expect(store.fetchOriginalsOverview).toHaveBeenCalledWith(7);
    // 不再有逐文件选择的下拉框
    expect(container.querySelectorAll('.ant-select').length).toBe(0);
    // 每份制度文件一行：文件名与最初原稿上传人/时间直接可见
    expect(container.textContent).toContain('第一章 总则');
    expect(container.textContent).toContain('张三');
    expect(container.textContent).toContain('2026-01-05 10:00:00');
    // 单次聚合请求即覆盖清单，不逐行拉原稿
    expect(http.get).not.toHaveBeenCalled();
  });

  it('加载失败置错误态并可重试（不以空列表冒充成功）', async () => {
    store.fetchOriginalsOverview.mockImplementationOnce(function () {
      this.originalsOverview = [];
      this.originalsOverviewError = '初始来源加载失败，请重试';
      return Promise.resolve();
    });
    const container = renderTab();
    await flush();
    expect(container.textContent).toContain('初始来源加载失败');
    const retry = findButton(container, '重试');
    expect(retry).not.toBeUndefined();
    await clickButton(retry);
    expect(store.fetchOriginalsOverview).toHaveBeenCalledTimes(2);
  });

  it('0 文件手册渲染空态引导，上传按钮可用', async () => {
    store.fetchOriginalsOverview.mockImplementationOnce(function () {
      this.originalsOverview = [];
      return Promise.resolve();
    });
    const container = renderTab();
    await flush();
    expect(container.textContent).toContain('该制度还没有制度文件');
    const button = findButton(container, '上传文件');
    expect(button).not.toBeUndefined();
    expect(button.disabled).toBe(false);
  });

  it('点击新增按钮触发隐藏 file input（死按钮回归防护），input 可多选', async () => {
    const container = renderTab();
    await flush();
    const button = findButton(container, '新增制度文件');
    expect(button).not.toBeUndefined();
    const clickSpy = jest.spyOn(HTMLInputElement.prototype, 'click')
      .mockImplementation(() => {});
    await clickButton(button);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    clickSpy.mockRestore();
    const input = container.querySelector('input[type="file"]');
    expect(input.hasAttribute('multiple')).toBe(true);
  });
});

describe('新增制度文件（批量，每份各建一项）', () => {
  it('多选上传：每个所选文件各建一份制度文件（顺序走 files/create）', async () => {
    const container = renderTab();
    await flush();
    http.post.mockResolvedValueOnce({id: 21, name: '甲.docx',
      draft: {revision: 1}, draft_error: ''});
    http.post.mockResolvedValueOnce({id: 22, name: '乙.docx',
      draft: {revision: 1}, draft_error: ''});
    await pickFiles(container, ['甲.docx', '乙.docx']);
    // 两次 files/create（每份各建一个制度文件），无 originals/upload 调用
    expect(http.post.mock.calls.length).toBe(2);
    expect(http.post.mock.calls[0][0]).toBe('/api/institution/manuals/7/files/create/');
    expect(http.post.mock.calls[1][0]).toBe('/api/institution/manuals/7/files/create/');
    await flush();
    expect(store.fetchOriginalsOverview).toHaveBeenCalledTimes(2);
    expect(store.fetchDetail).toHaveBeenCalledWith(7);
  });

  it('draft_error 非空只警示不算失败（文件条目已建），刷新照常', async () => {
    const {message} = require('antd');
    const warningSpy = jest.spyOn(message, 'warning').mockImplementation(() => {});
    try {
      const container = renderTab();
      await flush();
      http.post.mockResolvedValue({id: 100, name: 'broken.doc',
        draft: null, draft_error: '文件已创建，但可编辑草稿建立失败：转换失败'});
      await pickFiles(container, ['broken.doc']);
      expect(http.post).toHaveBeenCalledWith(
        '/api/institution/manuals/7/files/create/', expect.any(FormData));
      await flush();
      expect(warningSpy).toHaveBeenCalledWith(expect.stringContaining('草稿建立失败'));
      expect(store.fetchOriginalsOverview).toHaveBeenCalledTimes(2);
    } finally {
      warningSpy.mockRestore();
    }
  });

  it('批量新增单个失败不中断剩余文件（拦截器弹错，成功数如实汇总）', async () => {
    const container = renderTab();
    await flush();
    http.post.mockRejectedValueOnce('网络错误');
    http.post.mockResolvedValueOnce({id: 22, name: '乙.docx',
      draft: {revision: 1}, draft_error: ''});
    await pickFiles(container, ['a.docx', 'b.docx']);
    expect(http.post.mock.calls.length).toBe(2);
    await flush();
    expect(store.fetchDetail).toHaveBeenCalledWith(7);
  });
});

describe('为已有文件更换来源（按行受控操作）', () => {
  it('点击更换来源触发文件选择；确认弹窗明确目标文件与草稿影响后上传', async () => {
    const container = renderTab();
    await flush();
    const clickSpy = jest.spyOn(HTMLInputElement.prototype, 'click')
      .mockImplementation(() => {});
    await clickButton(findButton(container, '更换来源'));
    // 程序触发隐藏 input（同一 input，按 pendingReplace 分支语义）
    expect(clickSpy).toHaveBeenCalledTimes(1);
    clickSpy.mockRestore();
    // 选择文件后弹出受控确认：目标文件 + 草稿影响
    http.post.mockResolvedValue({id: 6, file_name: '新版来源.docx'});
    await pickFiles(container, ['新版来源.docx']);
    await flush();
    const text = confirmText();
    expect(text).toContain('目标制度文件');
    expect(text).toContain('第一章 总则');
    expect(text).toContain('不会改动当前草稿');
    expect(text).toContain('r3');
    await confirmOk();
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/7/files/11/originals/upload/',
      expect.any(FormData));
    await flush();
    expect(store.fetchOriginalsOverview).toHaveBeenCalledTimes(2);
    expect(store.fetchDetail).toHaveBeenCalledWith(7);
  });

  it('多份文件一起更换来源：逐个上传为该文件的新来源记录', async () => {
    const container = renderTab();
    await flush();
    const clickSpy = jest.spyOn(HTMLInputElement.prototype, 'click')
      .mockImplementation(() => {});
    await clickButton(findButton(container, '更换来源'));
    clickSpy.mockRestore();
    http.post.mockResolvedValue({id: 7});
    await pickFiles(container, ['a.docx', 'b.docx']);
    await flush();
    await confirmOk();
    expect(http.post.mock.calls.length).toBe(2);
    expect(http.post.mock.calls[0][0]).toBe(
      '/api/institution/manuals/7/files/11/originals/upload/');
    expect(http.post.mock.calls[1][0]).toBe(
      '/api/institution/manuals/7/files/11/originals/upload/');
  });

  it('非所有者/管理员：上传与更换来源禁用（页面码有 upload 但业务门收窄）', async () => {
    store.manual = {...store.manual, is_owner: false, is_admin: false};
    const container = renderTab();
    await flush();
    const uploadBtn = findButton(container, '新增制度文件');
    expect(uploadBtn).not.toBeUndefined();
    expect(uploadBtn.disabled).toBe(true);
    const replaceBtn = findButton(container, '更换来源');
    expect(replaceBtn).not.toBeUndefined();
    expect(replaceBtn.disabled).toBe(true);
    expect(container.textContent).toContain('仅限手册所有者或制度管理员');
  });
});

describe('原稿预览/下载与已清理状态', () => {
  it('最初原稿可用时主行提供预览/下载', async () => {
    const container = renderTab();
    await flush();
    expect(findButton(container, '预览')).not.toBeUndefined();
    expect(findButton(container, '下载')).not.toBeUndefined();
    expect(http.get).not.toHaveBeenCalled();
    await clickButton(findButton(container, '预览'));
    expect(http.get).toHaveBeenCalledWith(
      '/api/institution/manuals/7/originals/5/preview-url/');
  });

  it('原稿已按保留策略清理：不渲染预览/下载/重建，展示已清理标记', async () => {
    store.fetchOriginalsOverview.mockImplementationOnce(function () {
      const row = JSON.parse(JSON.stringify(mockOverviewRow));
      row.first_original.is_cleaned = true;
      row.first_original.cleaned_at = '2026-03-01T08:00:00';
      row.has_usable_original = false;
      row.history = [row.first_original];
      this.originalsOverview = [row];
      return Promise.resolve();
    });
    const container = renderTab();
    await flush();
    expect(container.textContent).toContain('已清理');
    expect(findButton(container, '预览')).toBeUndefined();
    expect(findButton(container, '下载')).toBeUndefined();
    expect(findButton(container, '重建草稿')).toBeUndefined();
  });
});

describe('从原始上传文件重建草稿', () => {
  it('非文件负责人（持编制授权）：不渲染重建入口（负责人独占，2026-10-31）', async () => {
    store.files = [{id: 11, name: '第一章 总则',
      assignment: {owner_id: 8, owner_name: '别人', note: '', is_mine: false}}];
    const container = renderTab();
    await flush();
    expect(findButton(container, '重建草稿')).toBeUndefined();
    // 已发布过版本时同样不出现"高级恢复操作"（无可重建文件的账号）
    store.manual = {...store.manual, has_versions: true};
    const container2 = renderTab();
    await flush();
    expect(findButton(container2, '高级恢复操作')).toBeUndefined();
  });

  it('未发布过版本的制度：主行重建按钮直接可见，确认后携带 original_id', async () => {
    const container = renderTab();
    await flush();
    http.post.mockResolvedValue({revision: 1});
    const rebuild = findButton(container, '重建草稿');
    expect(rebuild).not.toBeUndefined();
    await clickButton(rebuild);
    // Modal.confirm 经 setTimeout(0) 异步渲染，先冲刷再定位 OK 按钮
    await flush();
    expect(confirmText()).toContain('创建草稿');
    await confirmOk();
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/7/files/11/draft/create/', {original_id: 5});
    expect(store.fetchOriginalsOverview).toHaveBeenCalledTimes(2);
    expect(store.fetchDetail).toHaveBeenCalledWith(7);
  });

  describe('已发布过版本（高级恢复路径）', () => {
    function enableVersions() {
      store.manual = Object.assign({}, store.manual,
        {has_versions: true, has_password: true});
      store.fetchDetail = jest.fn(function () {
        this.manual = Object.assign({}, this.manual,
          {has_versions: true, has_password: true});
        return Promise.resolve();
      });
    }

    it('默认不显示重建按钮，收进"高级恢复操作"展开项', async () => {
      enableVersions();
      const container = renderTab();
      await flush();
      expect(findButton(container, '重建草稿')).toBeUndefined();
      const toggle = findButton(container, '高级恢复操作');
      expect(toggle).not.toBeUndefined();
      await clickButton(toggle);
      await flush();
      expect(findButton(container, '重建草稿')).not.toBeUndefined();
      expect(container.textContent).toContain('高级恢复操作：');
    });

    it('重建弹窗必须展示风险提示；密码为空不发请求、不显示成功', async () => {
      enableVersions();
      const {message} = require('antd');
      const successSpy = jest.spyOn(message, 'success').mockImplementation(() => {});
      const warningSpy = jest.spyOn(message, 'warning').mockImplementation(() => {});
      try {
        const container = renderTab();
        await flush();
        await clickButton(findButton(container, '高级恢复操作'));
        await flush();
        await clickButton(findButton(container, '重建草稿'));
        await flush();
        const text = confirmText();
        expect(text).toContain('当前草稿内容将被丢弃');
        expect(text).toContain('不可撤销');
        // 密码为空直接确认：拦截在弹窗层，不发请求
        const okButton = document.querySelector('.ant-modal-confirm .ant-btn-primary');
        await act(async () => {
          okButton.click();
          await Promise.resolve();
          await new Promise(resolve => setTimeout(resolve, 0));
        });
        expect(http.post).not.toHaveBeenCalled();
        expect(successSpy).not.toHaveBeenCalled();
        expect(warningSpy).toHaveBeenCalledWith('请输入编辑密码确认');
      } finally {
        successSpy.mockRestore();
        warningSpy.mockRestore();
      }
    });

    it('输入编辑密码并确认后携带 confirm=true 与 password 重建', async () => {
      enableVersions();
      const container = renderTab();
      await flush();
      await clickButton(findButton(container, '高级恢复操作'));
      await flush();
      await clickButton(findButton(container, '重建草稿'));
      await flush();
      const pwInput = document.querySelector(
        '.ant-modal-confirm input[type="password"]');
      expect(pwInput).not.toBeNull();
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, 'value').set;
      await act(async () => {
        setter.call(pwInput, 'edit-pass-9');
        pwInput.dispatchEvent(new Event('input', {bubbles: true}));
      });
      http.post.mockResolvedValue({revision: 4});
      await confirmOk();
      expect(http.post).toHaveBeenCalledWith(
        '/api/institution/manuals/7/files/11/draft/create/',
        {original_id: 5, confirm: true, password: 'edit-pass-9'});
    });
  });
});

describe('展开原稿历史（最初原稿 vs 后续来源）', () => {
  function overviewWithHistory() {
    return [{
      ...JSON.parse(JSON.stringify(mockOverviewRow)),
      originals_count: 3,
      first_original: {id: 5, file_name: '手册.docx', ext: '.docx', file_size: 1024,
        uploaded_by_name: '张三', uploaded_at: '2026-01-05T10:00:00',
        is_cleaned: false, cleaned_at: null},
      history: [
        {id: 9, file_name: '第三版来源.docx', ext: '.docx', file_size: 2048,
          uploaded_by_name: '李四', uploaded_at: '2026-02-10T09:00:00',
          is_cleaned: false, cleaned_at: null},
        {id: 6, file_name: '第二版来源.doc', ext: '.doc', file_size: 1536,
          uploaded_by_name: '王五', uploaded_at: '2026-01-20T09:00:00',
          is_cleaned: true, cleaned_at: '2026-03-01T08:00:00'},
        {id: 5, file_name: '手册.docx', ext: '.docx', file_size: 1024,
          uploaded_by_name: '张三', uploaded_at: '2026-01-05T10:00:00',
          is_cleaned: false, cleaned_at: null},
      ],
    }];
  }

  it('展开行展示完整历史：标记最初原稿/后续来源，已清理记录无预览/下载', async () => {
    store.fetchOriginalsOverview.mockImplementationOnce(function () {
      this.originalsOverview = overviewWithHistory();
      return Promise.resolve();
    });
    const container = renderTab();
    await flush();
    const expandIcon = container.querySelector('.ant-table-row-expand-icon');
    expect(expandIcon).not.toBeNull();
    await clickButton(expandIcon);
    await flush();
    const text = container.textContent;
    expect(text).toContain('最初原稿');
    expect(text).toContain('后续来源');
    expect(text).toContain('第三版来源.docx');
    expect(text).toContain('2026-03-01 08:00:00');
    // 预览按钮 = 主行最初原稿 1 个 + 历史行可用记录 2 个；
    // 已清理记录（第二版）不渲染预览/下载
    const previews = Array.from(container.querySelectorAll('button'))
      .filter(b => b.textContent === '预览');
    expect(previews.length).toBe(3);
  });

  it('历史行重建走该记录的 original_id（文件级 draft/create）', async () => {
    store.fetchOriginalsOverview.mockImplementationOnce(function () {
      this.originalsOverview = overviewWithHistory();
      return Promise.resolve();
    });
    const container = renderTab();
    await flush();
    await clickButton(container.querySelector('.ant-table-row-expand-icon'));
    await flush();
    // 主行重建按钮（基于最初原稿）+ 历史行 2 条可用记录各一个重建入口
    const rebuilds = Array.from(container.querySelectorAll('button'))
      .filter(b => b.textContent.includes('重建草稿'));
    expect(rebuilds.length).toBe(3);
    http.post.mockResolvedValue({revision: 2});
    await clickButton(rebuilds[1]);
    await flush();
    await confirmOk();
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/7/files/11/draft/create/', {original_id: 9});
  });
});
