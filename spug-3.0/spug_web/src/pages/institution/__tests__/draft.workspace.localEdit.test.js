/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 草稿工作台「本机编辑」组件行为测试（jsdom + ReactDOM）：
 * - 编辑方式切换控件（Segmented）在在线编辑配置可用时渲染；用户可主动
 *   切换到本机方式：先确认落盘（forcesave 链路）→ 重取编辑配置轮换
 *   document key（旧编辑实例回调服务端失效）→ 清配置缓存呈现本机面板；
 *   会话全程保留。
 * - forcesave 未确认时切换被阻止：留在在线编辑、配置不轮换、呈现
 *   「重试切换」入口，绝不静默切换。
 * - 配置不可用（editor_available=false）：无切换控件、直接呈现本机面板，
 *   下载/上传入口可见（本机入口不依赖失败上报）。
 * - 编辑器加载失败（store.editorLoadFailed）：呈现显式「切换到本机编辑」
 *   入口，点击即走切换链路。
 * - 在线编辑期间下载草稿：先确认落盘，确认失败不下载（重试下载）；
 *   下载成功记录基线修订号。
 * - 本机上传：成功提示只在后端真实成功响应后；.doc 被客户端拒绝；
 *   基线过期失败不清会话不报成功，可重新下载后重试。
 * - 整份替换当前草稿（2026-10-31 二轮拆分，不要求先下载）：本机面板
 *   同时渲染日常「上传保存（需先下载草稿）」与次级「用本机文件替换当前
 *   草稿」两个入口；点击替换先 Modal.confirm（目标制度文件名 + 当前草稿
 *   修订号 rN + 整份替换/不发布/不影响历史版本影响说明），取消不打开
 *   文件选择器也不上传，确认后才打开；选文件后以**确认时快照的修订号**
 *   上传（确认后清单被推进也不改用最新修订号）；.doc 拒绝；冲突
 *   「草稿已被其他会话更新」不报成功、保留会话、刷新清单并提示重新确认；
 *   文案不得承诺"系统已校验所选文件基于下载草稿"。
 * mock 约定与 draft.workspace.test.js 相同（见该文件头注释）。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';
import { message } from 'antd';

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

jest.mock('../draft/OnlyOfficeEditor', () => function OnlyOfficeEditor() {
  return null;
});
jest.mock('../detail/PreviewModal', () => function PreviewModal() {
  return null;
});
jest.mock('../../../layout/useWorkTabUnsaved', () => () => {});
jest.mock('../utils', () => {
  const actual = jest.requireActual('../utils');
  return Object.assign({}, actual, {
    downloadFile: jest.fn(() => Promise.resolve()),
  });
});

import InstitutionDraftWorkspace from '../draft';
import {http} from 'libs';
import {downloadFile} from '../utils';
import store from '../draft/store';

function makeFile(id, overrides) {
  return Object.assign({
    id,
    manual_id: 5,
    name: `文件${id}`,
    sort_order: id,
    is_removed: false,
    created_at: '2026-10-01T10:00:00',
    draft: {
      id: 100 + id,
      revision: id,
      file_name: `文件${id}.docx`,
      file_size: 1024,
      file_hash: `hash-${id}`,
      base_version_id: null,
      last_saved_by_name: '张三',
      last_saved_at: '2026-10-01T10:00:00',
      created_at: '2026-10-01T10:00:00',
    },
    active_session: null,
    assignment: {owner_id: 9, owner_name: '我', note: '', is_mine: true},
  }, overrides);
}

function mockFetch(files, manual) {
  http.get.mockImplementation(url => {
    if (url.includes('editor-config')) {
      return Promise.resolve({editor_available: true, document_key: 'k2'});
    }
    if (url.includes('/files/')) return Promise.resolve(files);
    return Promise.resolve(manual || {id: 5, name: '测试手册', my_roles: ['edit'], is_owner: true, is_admin: false});
  });
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await new Promise(resolve => setTimeout(resolve, 0));
  });
}

/**
 * 有界等待：确认链（forcesave→轮询→复核）使用真实 setTimeout(1ms) 推进，
 * 单次 flush 不保证走完（用例渲染量大会挤占时序）；循环冲刷直到谓词成立
 * 或轮次耗尽，避免对宏任务轮次的隐式依赖。
 */
async function flushUntil(predicate, maxRounds = 100) {
  for (let i = 0; i < maxRounds; i++) {
    await act(async () => {
      await Promise.resolve();
      await new Promise(resolve => setTimeout(resolve, 2));
    });
    if (predicate()) return;
  }
}

let pageInstance = null;

function renderPage() {
  const container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    pageInstance = ReactDOM.render(
      React.createElement(InstitutionDraftWorkspace, {match: {params: {id: '5'}}}),
      container);
  });
  return container;
}

function findButton(container, text) {
  return Array.from(container.querySelectorAll('button'))
    .find(b => b.textContent.includes(text));
}

function findSegmentedItem(container, label) {
  const items = Array.from(container.querySelectorAll('.ant-segmented-item'));
  const item = items.find(el => el.textContent.includes(label));
  if (!item) throw new Error('未找到编辑方式切换项: ' + label);
  return item.querySelector('input');
}

function findFileInputs(container) {
  return Array.from(container.querySelectorAll('input[type="file"]'));
}

function click(el) {
  el.dispatchEvent(new MouseEvent('click', {bubbles: true}));
}

/** 在线编辑中（会话 + 在线配置）的页面状态；轮询参数调小加速 */
function setupOnlineEditing(fileIds) {
  mockFetch(fileIds.map(id => makeFile(id)));
  const container = renderPage();
  return flush().then(() => {
    store.passwordVerified = true;
    store.saveSession(1, 'sess-1', '2099-01-01T00:00:00');
    store.editorConfigs[1] = {editor_available: true, document_key: 'k1'};
    store.pollIntervalMs = 1;
    return flush().then(() => container);
  });
}

/** forcesave 链路 mock：第一次受理且修订号推进、第二次复核 no_changes */
function mockConfirmChainOk() {
  let forcesaveCalls = 0;
  http.post.mockImplementation(() => {
    forcesaveCalls += 1;
    return Promise.resolve(forcesaveCalls === 1
      ? {forcesave: 'requested', revision: 1}
      : {forcesave: 'no_changes'});
  });
  http.get.mockImplementation(url => {
    if (url.includes('editor-config')) {
      return Promise.resolve({editor_available: true, document_key: 'k2'});
    }
    if (url.endsWith('/draft/')) return Promise.resolve({revision: 2});
    if (url.includes('/files/')) return Promise.resolve([makeFile(1)]);
    return Promise.resolve({id: 5, name: '测试手册'});
  });
}

/** forcesave 恒受理但修订号不推进（落盘始终未确认） */
function mockConfirmChainStuck() {
  http.post.mockResolvedValue({forcesave: 'requested', revision: 1});
  http.get.mockImplementation(url => {
    if (url.includes('editor-config')) {
      return Promise.resolve({editor_available: true, document_key: 'k2'});
    }
    if (url.endsWith('/draft/')) return Promise.resolve({revision: 1});
    if (url.includes('/files/')) return Promise.resolve([makeFile(1)]);
    return Promise.resolve({id: 5, name: '测试手册'});
  });
}

let errorSpy, successSpy, warningSpy;

beforeEach(() => {
  jest.clearAllMocks();
  store.reset();
  pageInstance = null;
  sessionStorage.clear();
  errorSpy = jest.spyOn(message, 'error').mockImplementation(() => {});
  successSpy = jest.spyOn(message, 'success').mockImplementation(() => {});
  warningSpy = jest.spyOn(message, 'warning').mockImplementation(() => {});
  store.pollIntervalMs = 1;
  store.pollMaxAttempts = 2;
  store.confirmSettleMs = 0;
});

afterEach(() => {
  errorSpy.mockRestore();
  successSpy.mockRestore();
  warningSpy.mockRestore();
  Array.from(document.body.children).forEach(el => {
    if (el.tagName === 'DIV') el.remove();
  });
});

describe('草稿工作台（编辑方式切换：在线 → 本机）', () => {
  it('在线编辑中主动切换：确认落盘 → 轮换 document key → 本机面板，会话保留', async () => {
    const container = await setupOnlineEditing([1]);
    // 切换控件可见（在线配置可用）
    expect(container.querySelector('.ant-segmented')).not.toBeNull();
    mockConfirmChainOk();
    await act(async () => {
      findSegmentedItem(container, '本机编辑').click();
      await flush();
    });
    // 确认链在先（forcesave），轮换在后（editor-config 重取一次）
    const configCalls = http.get.mock.calls.filter(([u]) =>
      u.includes('editor-config'));
    expect(configCalls).toHaveLength(1);
    expect(http.post.mock.calls.length).toBeGreaterThanOrEqual(2);
    // 编辑器随本机分支卸载（配置缓存清除），方式与面板就位
    expect(store.editorConfigs[1]).toBeUndefined();
    expect(store.effectiveEditMode(1)).toBe('local');
    expect(container.textContent).toContain('已切换为本机编辑');
    expect(container.textContent).toContain('尚未下载草稿');
    expect(container.textContent).toContain('下载草稿');
    expect(container.textContent).toContain('上传保存（需先下载草稿）');
    // 本机面板保留切回在线入口；会话保留（本机上传依赖有效会话）
    expect(container.querySelector('.ant-segmented')).not.toBeNull();
    expect(store.sessionKeyOf(1)).toBe('sess-1');
    expect(http.delete).not.toHaveBeenCalled();
    expect(successSpy).toHaveBeenCalledWith(
      expect.stringContaining('已切换为本机编辑'));
  });

  it('forcesave 未确认时切换被阻止：留在在线编辑并呈现「重试切换」', async () => {
    const container = await setupOnlineEditing([1]);
    mockConfirmChainStuck();
    await act(async () => {
      findSegmentedItem(container, '本机编辑').click();
      await flushUntil(() => !!store.finishingError &&
        store.finishingErrorKind === 'switch_local');
    });
    // 未确认落盘绝不切换：配置未轮换、编辑器分支保留
    expect(store.effectiveEditMode(1)).toBe('online');
    expect(store.editorConfigs[1]).not.toBeUndefined();
    expect(http.get.mock.calls.filter(([u]) =>
      u.includes('editor-config'))).toHaveLength(0);
    expect(store.sessionKeyOf(1)).toBe('sess-1');
    // 语境与重试入口
    expect(container.textContent).toContain('切换未完成，会话已保留');
    expect(container.textContent).toContain('已取消切换到本机编辑');
    expect(findButton(container, '重试切换')).not.toBeUndefined();
    // 确认成功路径的「不保存并退出」危险出口仍在
    expect(findButton(container, '不保存并退出')).not.toBeUndefined();
  });

  it('编辑器加载失败：呈现显式「切换到本机编辑」入口并可完成切换', async () => {
    const container = await setupOnlineEditing([1]);
    store.markEditorLoadFailed(1);
    await flush();
    expect(container.textContent).toContain('在线编辑器加载失败');
    mockConfirmChainOk();
    await act(async () => {
      click(findButton(container, '切换到本机编辑'));
      await flush();
    });
    expect(store.effectiveEditMode(1)).toBe('local');
    expect(store.editorConfigs[1]).toBeUndefined();
    expect(container.textContent).toContain('上传保存（需先下载草稿）');
  });
});

describe('草稿工作台（配置不可用：本机方式直接可用）', () => {
  it('editor_available=false：无切换控件、本机面板与上传入口直接呈现', async () => {
    mockFetch([makeFile(1)]);
    http.get.mockImplementation(url => {
      if (url.includes('editor-config')) {
        return Promise.resolve({editor_available: false});
      }
      if (url.includes('/files/')) return Promise.resolve([makeFile(1)]);
      return Promise.resolve({id: 5, name: '测试手册', my_roles: ['edit'], is_owner: true, is_admin: false});
    });
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    store.saveSession(1, 'sess-1', '2099-01-01T00:00:00');
    store.editorConfigs[1] = {editor_available: false};
    await flush();
    expect(store.effectiveEditMode(1)).toBe('local');
    expect(container.querySelector('.ant-segmented')).toBeNull();
    expect(container.textContent).toContain('在线编辑服务未配置');
    expect(container.textContent).toContain('本机 Word/WPS 编辑');
    expect(findButton(container, '下载草稿')).not.toBeUndefined();
    expect(findButton(container, '上传保存')).not.toBeUndefined();
  });
});

describe('草稿工作台（在线编辑期间下载草稿：确认→基线）', () => {
  it('下载先确认落盘，成功后记录基线修订号', async () => {
    const container = await setupOnlineEditing([1]);
    mockConfirmChainOk();
    await act(async () => {
      click(findButton(container, '下载草稿'));
      await flush();
    });
    // 确认链先于下载（forcesave 已发起）
    expect(http.post.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(downloadFile).toHaveBeenCalledTimes(1);
    expect(downloadFile.mock.calls[0][0]).toContain('/draft/download/');
    // 基线=确认落盘后服务端清单返回的草稿修订号
    expect(store.localBaselines[1]).toBe(1);
    expect(successSpy).toHaveBeenCalledWith(
      expect.stringContaining('本机编辑基线'));
  });

  it('确认失败不下载：呈现「重试下载」，不记录基线', async () => {
    const container = await setupOnlineEditing([1]);
    mockConfirmChainStuck();
    await act(async () => {
      click(findButton(container, '下载草稿'));
      await flushUntil(() => !!store.finishingError &&
        store.finishingErrorKind === 'download_draft');
    });
    expect(downloadFile).not.toHaveBeenCalled();
    expect(store.localBaselines[1]).toBeUndefined();
    expect(store.sessionKeyOf(1)).toBe('sess-1');
    expect(container.textContent).toContain('下载未完成，会话已保留');
    expect(findButton(container, '重试下载')).not.toBeUndefined();
  });
});

describe('草稿工作台（本机上传）', () => {
  function setupLocalMode() {
    mockFetch([makeFile(1)]);
    const container = renderPage();
    return flush().then(() => {
      store.passwordVerified = true;
      store.saveSession(1, 'sess-1', '2099-01-01T00:00:00');
      // 已主动切换为本机（配置缓存清除、基线=下载时的修订号）
      store.editModes[1] = 'local';
      store.onlineAvailable[1] = true;
      store.localBaselines[1] = 4;
      return flush().then(() => container);
    });
  }

  function triggerUpload(container, name) {
    const saveInput = findFileInputs(container)[1];
    Object.defineProperty(saveInput, 'files', {value: [new File(['x'], name)]});
    saveInput.dispatchEvent(new Event('change', {bubbles: true}));
  }

  it('上传携带基线修订号；成功提示在后端真实响应后，基线清除并刷新清单', async () => {
    const container = await setupLocalMode();
    http.post.mockResolvedValue({revision: 5, file_name: '文件1.docx'});
    await act(async () => {
      triggerUpload(container, 'a.docx');
      await flush();
    });
    expect(http.post).toHaveBeenCalledTimes(1);
    const [url, formData] = http.post.mock.calls[0];
    expect(url).toBe('/api/institution/manuals/5/files/1/draft/save/');
    expect(formData.get('session_key')).toBe('sess-1');
    // 基线修订号=下载时记录的 4（不是清单内可能已推进的修订号）
    expect(formData.get('revision')).toBe('4');
    expect(successSpy).toHaveBeenCalledWith(
      expect.stringContaining('草稿已上传保存（修订号 r5）'));
    expect(store.localBaselines[1]).toBeUndefined();
    // 成功后刷新清单（修订状态刷新）
    expect(http.get.mock.calls.some(([u]) => u.includes('/files/'))).toBe(true);
  });

  it('.doc 被客户端拒绝，不发请求', async () => {
    const container = await setupLocalMode();
    await act(async () => {
      triggerUpload(container, 'a.doc');
      await flush();
    });
    expect(errorSpy).toHaveBeenCalledWith('草稿工作文件必须是 .docx 格式');
    expect(http.post).not.toHaveBeenCalled();
  });

  it('基线过期上传被拒：不清会话、不报成功、基线清除须重新下载', async () => {
    const container = await setupLocalMode();
    http.post.mockRejectedValue('草稿已被其他会话更新，请刷新草稿后重试');
    await act(async () => {
      triggerUpload(container, 'a.docx');
      await flush();
    });
    expect(successSpy).not.toHaveBeenCalled();
    expect(store.sessionKeyOf(1)).toBe('sess-1');
    expect(store.localBaselines[1]).toBeUndefined();
    // 上传入口仍在（重新下载取得新基线后可重试）
    expect(findButton(container, '上传保存')).not.toBeUndefined();
  });

  it('未下载草稿（无基线）时上传被阻止并明确提示', async () => {
    const container = await setupLocalMode();
    store.localBaselines[1] = undefined;
    await act(async () => {
      triggerUpload(container, 'a.docx');
      await flush();
    });
    expect(warningSpy).toHaveBeenCalledWith('请先下载草稿到本机编辑后再上传保存');
    expect(http.post).not.toHaveBeenCalled();
    expect(successSpy).not.toHaveBeenCalled();
  });
});

describe('草稿工作台（整份替换当前草稿：先确认后选文件）', () => {
  /** 本机方式（会话 + 已主动切换，无下载基线要求） */
  function setupLocalMode() {
    mockFetch([makeFile(1)]);
    const container = renderPage();
    return flush().then(() => {
      store.passwordVerified = true;
      store.saveSession(1, 'sess-1', '2099-01-01T00:00:00');
      store.editModes[1] = 'local';
      store.onlineAvailable[1] = true;
      return flush().then(() => container);
    });
  }

  /** 第三个隐藏 input = 整份替换控件（前两个=新增文件/日常上传） */
  function replaceInputOf(container) {
    return findFileInputs(container)[2];
  }

  /** antd Modal 经 portal 渲染到 document.body：按钮/文案断言都查 document */
  function findModalButton(text) {
    const modal = document.querySelector('.ant-modal');
    if (!modal) return undefined;
    const normalized = text.replace(/\s+/g, '');
    return Array.from(modal.querySelectorAll('button')).find(b =>
      b.textContent.replace(/\s+/g, '').includes(normalized));
  }

  function pickForReplace(container, name) {
    const input = replaceInputOf(container);
    Object.defineProperty(input, 'files', {value: [new File(['x'], name)]});
    input.dispatchEvent(new Event('change', {bubbles: true}));
  }

  it('本机面板同时提供两个入口，且不承诺校验所选文件基于下载草稿', async () => {
    const container = await setupLocalMode();
    expect(findButton(container, '上传保存（需先下载草稿）')).not.toBeUndefined();
    expect(findButton(container, '用本机文件替换当前草稿')).not.toBeUndefined();
    // 两条路径语义在面板文案中明确区分
    expect(container.textContent).toContain(
      '系统不会校验所选文件是否基于已下载的草稿修改');
    expect(container.textContent).toContain('整份替换');
    expect(container.textContent).not.toContain('已验证基于');
    expect(container.textContent).not.toContain('已校验所选文件');
  });

  it('点击替换先弹确认（目标文件名与 rN）；取消不打开文件选择器也不上传', async () => {
    const container = await setupLocalMode();
    // 替换不要求先下载：无基线也可进入确认
    store.localBaselines[1] = undefined;
    await flush();
    const replaceInput = replaceInputOf(container);
    const clickSpy = jest.spyOn(replaceInput, 'click').mockImplementation(() => {});
    await act(async () => {
      click(findButton(container, '用本机文件替换当前草稿'));
      await flush();
    });
    const modal = document.querySelector('.ant-modal');
    expect(modal).not.toBeNull();
    // 确认窗必须展示目标制度文件名、当前草稿修订号与整份替换影响
    expect(modal.textContent).toContain('目标制度文件');
    expect(modal.textContent).toContain('文件1');
    expect(modal.textContent).toContain('r1');
    expect(modal.textContent).toContain('整份替换');
    expect(modal.textContent).toContain('不会发布');
    expect(modal.textContent).toContain('历史发布版本不受影响');
    expect(modal.textContent).toContain(
      '系统不会校验所选文件是否基于已下载的草稿修改');
    // 未确认前：不打开文件选择器、不上传
    expect(clickSpy).not.toHaveBeenCalled();
    expect(http.post).not.toHaveBeenCalled();
    await act(async () => {
      click(findModalButton('取消'));
      await flush();
    });
    expect(clickSpy).not.toHaveBeenCalled();
    expect(http.post).not.toHaveBeenCalled();
    expect(successSpy).not.toHaveBeenCalled();
    clickSpy.mockRestore();
  });

  it('确认后才打开文件选择器；选文件后以确认时修订号上传（清单推进也不改）', async () => {
    const container = await setupLocalMode();
    const replaceInput = replaceInputOf(container);
    const clickSpy = jest.spyOn(replaceInput, 'click').mockImplementation(() => {});
    await act(async () => {
      click(findButton(container, '用本机文件替换当前草稿'));
      await flush();
    });
    const okBtn = findModalButton('选择文件并替换');
    expect(okBtn).not.toBeUndefined();
    await act(async () => {
      okBtn.click();
      await flush();
    });
    // 确认后才打开文件选择器（恰好一次）
    expect(clickSpy).toHaveBeenCalledTimes(1);
    clickSpy.mockRestore();
    // 确认之后、选文件之前清单/服务端修订号被其他会话推进到 9：
    // 上传仍必须用确认时快照的 r1，绝不改用最新修订号
    store.files[0].draft.revision = 9;
    http.post.mockResolvedValue({revision: 10, file_name: '文件1.docx'});
    await act(async () => {
      pickForReplace(container, 'a.docx');
      await flush();
    });
    expect(http.post).toHaveBeenCalledTimes(1);
    const [url, formData] = http.post.mock.calls[0];
    expect(url).toBe('/api/institution/manuals/5/files/1/draft/save/');
    expect(formData.get('session_key')).toBe('sess-1');
    expect(formData.get('revision')).toBe('1');
    // 成功提示只在后端真实响应后
    expect(successSpy).toHaveBeenCalledWith(
      expect.stringContaining('已用本机文件替换草稿（修订号 r10）'));
    // 只更新草稿：不发布、不新增文件、不改历史发布版本
    expect(http.put).not.toHaveBeenCalled();
    expect(http.delete).not.toHaveBeenCalled();
  });

  it('.doc 被客户端拒绝替换，不发请求', async () => {
    const container = await setupLocalMode();
    const replaceInput = replaceInputOf(container);
    const clickSpy = jest.spyOn(replaceInput, 'click').mockImplementation(() => {});
    await act(async () => {
      click(findButton(container, '用本机文件替换当前草稿'));
      await flush();
    });
    await act(async () => {
      findModalButton('选择文件并替换').click();
      await flush();
    });
    clickSpy.mockRestore();
    await act(async () => {
      pickForReplace(container, 'a.doc');
      await flush();
    });
    expect(errorSpy).toHaveBeenCalledWith('草稿工作文件必须是 .docx 格式');
    expect(http.post).not.toHaveBeenCalled();
  });

  it('冲突（草稿已被其他会话更新）：不报成功、会话保留、刷新清单并提示重新确认', async () => {
    const container = await setupLocalMode();
    const replaceInput = replaceInputOf(container);
    const clickSpy = jest.spyOn(replaceInput, 'click').mockImplementation(() => {});
    await act(async () => {
      click(findButton(container, '用本机文件替换当前草稿'));
      await flush();
    });
    await act(async () => {
      findModalButton('选择文件并替换').click();
      await flush();
    });
    clickSpy.mockRestore();
    const filesCallsBefore = http.get.mock.calls.filter(
      ([u]) => u.includes('/files/')).length;
    http.post.mockRejectedValue('草稿已被其他会话更新，请刷新草稿后重试');
    await act(async () => {
      pickForReplace(container, 'a.docx');
      await flush();
    });
    // 绝不报成功；修订号冲突与会话无关：会话保留可重试
    expect(successSpy).not.toHaveBeenCalled();
    expect(store.sessionKeyOf(1)).toBe('sess-1');
    // 刷新清单并提示重新确认（错误本身由拦截器提示，不在此重复弹错）
    const filesCallsAfter = http.get.mock.calls.filter(
      ([u]) => u.includes('/files/')).length;
    expect(filesCallsAfter).toBeGreaterThan(filesCallsBefore);
    expect(warningSpy).toHaveBeenCalledWith(
      expect.stringContaining('重新点击「用本机文件替换当前草稿」'));
    expect(errorSpy).not.toHaveBeenCalled();
  });
});
