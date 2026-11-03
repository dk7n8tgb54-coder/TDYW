/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 草稿工作台 store 落盘确认核心与离开保护行为测试（自 draft.store.test.js
 * 拆分，文件行数门禁只减不增）：
 * - _confirmForcesave 复核轮：修订号推进后再次 forcesave 复核到
 *   no_changes 才认定成功——他处（如同账号其他页签 multipart）推进的
 *   修订号不冒充本次保存成功；轮询超时后最终复核 no_changes 仍可确认
 *   （回调内容幂等跳过、修订号不推进的情形），绝不冒充成功。
 * - editorDirty 闩锁与 confirmFileSave（离开保护，确认成功不撤销会话）。
 */
jest.mock('libs', () => ({
  http: {get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn()},
  history: {push: jest.fn()},
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: false, permissions: []},
}));

const {http} = require('libs');
const store = require('../draft/store').default;

function makeFile(id, overrides) {
  return Object.assign({
    id,
    manual_id: 5,
    name: `文件${id}`,
    sort_order: id,
    is_removed: false,
    draft: {id: 100 + id, revision: id, file_name: `文件${id}.docx`,
      file_size: 1024, file_hash: `hash-${id}`, base_version_id: null,
      last_saved_by_name: '张三',
      last_saved_at: '2026-10-01T10:00:00',
      created_at: '2026-10-01T10:00:00'},
    active_session: null,
  }, overrides);
}
describe('draft store（落盘确认核心：复核轮与他处推进防护）', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    store.reset();
    sessionStorage.clear();
    store.id = 5;
    store.files = [makeFile(7)];
    store.selectedFileId = 7;
    store.passwordVerified = true;
    store.pollIntervalMs = 1;
    store.confirmSettleMs = 0;
  });

  /** draft/ 轮询依次返回的修订号序列；耗尽后保持最后一个 */
  function mockPoll(revisions) {
    let i = 0;
    http.get.mockImplementation(url => {
      if (url.endsWith('/draft/')) {
        const value = revisions[Math.min(i, revisions.length - 1)];
        i += 1;
        return Promise.resolve({revision: value,
          last_saved_at: '2026-10-30T10:00:00', last_saved_by_name: '张三'});
      }
      return Promise.resolve([]);
    });
  }

  it('他处推进的修订号不冒充成功：复核轮继续直到 no_changes 才确认', async () => {
    store.saveSession(7, 'sess-7', '2099-01-01T00:00:00');
    store.editorConfigs[7] = {editor_available: true, document_key: 'k1'};
    // 轮次1：受理(r7) → 轮询到 r8（可能来自同账号其他页签的 multipart）
    // 轮次2：再次受理(r8) → 轮询到 r9（本次回调落盘）
    // 轮次3：复核 no_changes → 才认定确认成功
    const fsReplies = [
      {forcesave: 'requested', revision: 7},
      {forcesave: 'requested', revision: 8},
      {forcesave: 'no_changes', revision: 9},
    ];
    let n = 0;
    http.post.mockImplementation(url => {
      if (url.includes('forcesave')) {
        const reply = fsReplies[Math.min(n, fsReplies.length - 1)];
        n += 1;
        return Promise.resolve(reply);
      }
      return Promise.resolve({});
    });
    mockPoll([8, 9]);
    const result = await store._confirmForcesave(7, 'sess-7', store.finishSeq);
    expect(result.ok).toBe(true);
    expect(store.saveConfirmed[7]).toBeTruthy();
    expect(store.saveConfirmed[7].revision).toBe(9);
  });

  it('他处持续推进耗尽复核轮数：确认失败，绝不冒充成功', async () => {
    store.saveSession(7, 'sess-7', '2099-01-01T00:00:00');
    store.editorConfigs[7] = {editor_available: true, document_key: 'k1'};
    let n = 0;
    http.post.mockImplementation(url => {
      if (url.includes('forcesave')) {
        n += 1;
        return Promise.resolve({forcesave: 'requested', revision: 6 + n});
      }
      return Promise.resolve({});
    });
    mockPoll([8, 9, 10]);
    const result = await store._confirmForcesave(7, 'sess-7', store.finishSeq);
    expect(result.ok).toBe(false);
    expect(result.reason).toBe('timeout');
  });

  it('轮询超时后最终复核 no_changes：幂等跳过场景仍确认成功', async () => {
    store.saveSession(7, 'sess-7', '2099-01-01T00:00:00');
    store.editorConfigs[7] = {editor_available: true, document_key: 'k1'};
    store.pollMaxAttempts = 1;
    // 回调内容与当前草稿一致被幂等跳过：修订号不推进，但 DS 报告无
    // 更多待落盘修改——最终复核 no_changes 仍认定成功
    let n = 0;
    http.post.mockImplementation(url => {
      if (url.includes('forcesave')) {
        n += 1;
        return Promise.resolve(n === 1
          ? {forcesave: 'requested', revision: 7}
          : {forcesave: 'no_changes', revision: 7});
      }
      return Promise.resolve({});
    });
    mockPoll([7]); // 修订号始终不推进
    const result = await store._confirmForcesave(7, 'sess-7', store.finishSeq);
    expect(result.ok).toBe(true);
    expect(store.saveConfirmed[7]).toBeTruthy();
  });

  it('轮询超时且最终复核仍受理：确认失败', async () => {
    store.saveSession(7, 'sess-7', '2099-01-01T00:00:00');
    store.editorConfigs[7] = {editor_available: true, document_key: 'k1'};
    store.pollMaxAttempts = 1;
    http.post.mockResolvedValue({forcesave: 'requested', revision: 7});
    mockPoll([7]); // 修订号始终不推进
    const result = await store._confirmForcesave(7, 'sess-7', store.finishSeq);
    expect(result.ok).toBe(false);
    expect(result.reason).toBe('timeout');
  });
});

describe('draft store（no_changes 沉降复核：在途修改重走确认循环）', () => {
  // 2026-10-31 dev 保存丢失回归：DS 对 forcesave 的 no_changes 应答只
  // 反映命令处理瞬间的缓冲状态，与命令几乎同拍敲入的修改可能经事件
  // 通道晚于命令注册——旧实现即时采信 no_changes 即确认成功，前端随即
  // 轮换 key 销毁编辑器，在途修改随收尾回调被 409 丢弃。修复后
  // no_changes 须经 _settleNoChanges 沉降复核（实时脏态 + 沉降窗 +
  // 再次 forcesave）干净才确认，no_changes=确认成功的规则本身不变。
  // 本组钉住在途修改的两条发现路径（编辑器脏事件 / 沉降窗内 DS 注册）。
  beforeEach(() => {
    jest.clearAllMocks();
    store.reset();
    sessionStorage.clear();
    store.id = 5;
    store.files = [makeFile(7)];
    store.selectedFileId = 7;
    store.passwordVerified = true;
    store.pollIntervalMs = 1;
    store.confirmSettleMs = 0;
  });

  it('与命令同拍敲入（应答处理前编辑器已报脏）：不采信 no_changes，重走确认循环落盘', async () => {
    store.saveSession(7, 'sess-7', '2099-01-01T00:00:00');
    store.editorConfigs[7] = {editor_available: true, document_key: 'k1'};
    let n = 0;
    http.post.mockImplementation(url => {
      if (url.includes('forcesave')) {
        n += 1;
        if (n === 1) {
          // 修改事件与命令同拍：应答处理前 documentState(true) 已到达
          store.setEditorDirty(7, true);
          return Promise.resolve({forcesave: 'no_changes', revision: 7});
        }
        // DS 重新受理在途修改（#2）；落盘后报告无更多待存修改（#3）
        return Promise.resolve(n === 2
          ? {forcesave: 'requested', revision: 7}
          : {forcesave: 'no_changes', revision: 8});
      }
      return Promise.resolve({});
    });
    http.get.mockImplementation(url => {
      if (url.endsWith('/draft/')) {
        // 回调落盘（r7→r8），DS 随即上报"所有更改已保存"（false 不清闩锁）
        store.setEditorDirty(7, false);
        return Promise.resolve({revision: 8,
          last_saved_at: '2026-10-30T10:00:00', last_saved_by_name: '张三'});
      }
      return Promise.resolve([]);
    });
    const result = await store._confirmForcesave(7, 'sess-7', store.finishSeq);
    expect(result.ok).toBe(true);
    expect(store.saveConfirmed[7].revision).toBe(8);
    // 4 次 forcesave：no_changes（误答）→ requested（在途重答）→
    // no_changes → 沉降复核 no_changes
    expect(n).toBe(4);
  });

  it('事件未到达但沉降窗内 DS 注册（复核改报受理）：继续循环不冒充成功', async () => {
    store.saveSession(7, 'sess-7', '2099-01-01T00:00:00');
    store.editorConfigs[7] = {editor_available: true, document_key: 'k1'};
    let n = 0;
    http.post.mockImplementation(url => {
      if (url.includes('forcesave')) {
        n += 1;
        // 1=no_changes；2=沉降复核发现修改注册改报受理；3=再次受理；
        // 4=落盘后 no_changes；5=沉降复核仍 no_changes
        if (n <= 3) {
          return Promise.resolve({
            forcesave: n === 1 ? 'no_changes' : 'requested', revision: 7});
        }
        return Promise.resolve({forcesave: 'no_changes', revision: 8});
      }
      return Promise.resolve({});
    });
    http.get.mockImplementation(url => {
      if (url.endsWith('/draft/')) {
        return Promise.resolve({revision: 8,
          last_saved_at: '2026-10-30T10:00:00', last_saved_by_name: '张三'});
      }
      return Promise.resolve([]);
    });
    const result = await store._confirmForcesave(7, 'sess-7', store.finishSeq);
    expect(result.ok).toBe(true);
    expect(store.saveConfirmed[7].revision).toBe(8);
    expect(n).toBe(5);
  });
});

describe('draft store（no_changes 沉降复核：确认判据与实时脏态）', () => {
  // 沉降复核的干净判据（复核仍 no_changes 且编辑器不报脏）、复核请求
  // 失败的归因，以及 editorLiveState 与 editorDirty 闩锁的状态语义。
  beforeEach(() => {
    jest.clearAllMocks();
    store.reset();
    sessionStorage.clear();
    store.id = 5;
    store.files = [makeFile(7)];
    store.selectedFileId = 7;
    store.passwordVerified = true;
    store.pollIntervalMs = 1;
    store.confirmSettleMs = 0;
  });

  it('no_changes 沉降复核仍 no_changes 且编辑器不报脏：两次 forcesave 即确认', async () => {
    store.saveSession(7, 'sess-7', '2099-01-01T00:00:00');
    store.editorConfigs[7] = {editor_available: true, document_key: 'k1'};
    let n = 0;
    http.post.mockImplementation(url => {
      if (url.includes('forcesave')) {
        n += 1;
        return Promise.resolve({forcesave: 'no_changes', revision: 7});
      }
      return Promise.resolve({});
    });
    const result = await store._confirmForcesave(7, 'sess-7', store.finishSeq);
    expect(result.ok).toBe(true);
    expect(n).toBe(2);
    expect(store.saveConfirmed[7]).toBeTruthy();
    expect(store.editorDirty[7]).toBe(false);
  });

  it('沉降复核 forcesave 失败：按 forcesave_failed 处理，绝不冒充成功', async () => {
    store.saveSession(7, 'sess-7', '2099-01-01T00:00:00');
    store.editorConfigs[7] = {editor_available: true, document_key: 'k1'};
    let n = 0;
    http.post.mockImplementation(url => {
      if (url.includes('forcesave')) {
        n += 1;
        return n === 1
          ? Promise.resolve({forcesave: 'no_changes', revision: 7})
          : Promise.reject('文档服务保存请求失败');
      }
      return Promise.resolve({});
    });
    const result = await store._confirmForcesave(7, 'sess-7', store.finishSeq);
    expect(result.ok).toBe(false);
    expect(result.reason).toBe('forcesave_failed');
    expect(store.saveConfirmed[7]).toBeUndefined();
  });

  it('editorLiveState 实时脏态：true/false 都记录、不受 markSaveConfirmed 影响、ready 复位、清会话清除', () => {
    store.setEditorDirty(7, true);
    expect(store.editorLiveState[7]).toBe(true);
    store.setEditorDirty(7, false);
    expect(store.editorLiveState[7]).toBe(false); // 原始上报忠实记录
    expect(store.editorDirty[7]).toBe(true);      // 闩锁不受 false 影响
    store.markEditorReady(7);
    expect(store.editorLiveState[7]).toBe(false); // 新实例就绪复位
    store.setEditorDirty(7, true);
    store.markSaveConfirmed(7, {revision: 9});
    expect(store.editorLiveState[7]).toBe(true);  // 确认收尾不触碰实时脏态
    expect(store.editorDirty[7]).toBe(false);     // 闩锁按既有语义清除
    store.clearSession(7);
    expect(store.editorLiveState[7]).toBeUndefined();
  });
});

describe('draft store（离开保护与脏标记闩锁）', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    store.reset();
    sessionStorage.clear();
    store.id = 5;
    store.files = [makeFile(7)];
    store.selectedFileId = 7;
    store.passwordVerified = true;
    store.pollIntervalMs = 1;
    store.confirmSettleMs = 0;
  });

  it('editorDirty 闩锁：仅 true 置位，DS 自身保存（false）不清除', async () => {
    store.setEditorDirty(7, true);
    expect(store.editorDirty[7]).toBe(true);
    store.setEditorDirty(7, false);
    expect(store.editorDirty[7]).toBe(true);
    // 服务端确认落盘成功才清除
    store.saveSession(7, 'sess-7', '2099-01-01T00:00:00');
    store.editorConfigs[7] = {editor_available: true, document_key: 'k1'};
    http.post.mockResolvedValue({forcesave: 'no_changes', revision: 7});
    await store._confirmForcesave(7, 'sess-7', store.finishSeq);
    expect(store.editorDirty[7]).toBe(false);
    // 再置位后清会话同样清除
    store.setEditorDirty(7, true);
    store.clearSession(7);
    expect(store.editorDirty[7]).toBeUndefined();
  });

  it('confirmFileSave（离开保护）：确认成功不撤销会话', async () => {
    store.saveSession(7, 'sess-7', '2099-01-01T00:00:00');
    store.editorConfigs[7] = {editor_available: true, document_key: 'k1'};
    http.post.mockResolvedValue({forcesave: 'no_changes', revision: 7});
    const ok = await store.confirmFileSave(7, '切换文件');
    expect(ok).toBe(true);
    expect(http.delete).not.toHaveBeenCalled();
    expect(store.sessionKeyOf(7)).toBe('sess-7');
    expect(store.finishingFileId).toBeNull();
    expect(store.finishingError).toBe('');
  });

  it('confirmFileSave 失败：保留会话并呈现被取消动作的语境', async () => {
    store.saveSession(7, 'sess-7', '2099-01-01T00:00:00');
    store.editorConfigs[7] = {editor_available: true, document_key: 'k1'};
    store.pollMaxAttempts = 1;
    http.post.mockResolvedValue({forcesave: 'requested', revision: 7});
    http.get.mockImplementation(url => {
      if (url.endsWith('/draft/')) {
        return Promise.resolve({revision: 7}); // 修订号始终不推进
      }
      return Promise.resolve([]);
    });
    const ok = await store.confirmFileSave(7, '返回详情');
    expect(ok).toBe(false);
    expect(store.sessionKeyOf(7)).toBe('sess-7');
    expect(store.finishingErrorFileId).toBe(7);
    expect(store.finishingError).toContain('已取消返回详情');
    expect(store.finishingError).toContain('尚未经服务端确认落盘');
  });

  it('confirmFileSave 降级路径（无在线编辑器）直接成功', async () => {
    store.saveSession(7, 'sess-7', '2099-01-01T00:00:00');
    store.editorConfigs[7] = {editor_available: false};
    const ok = await store.confirmFileSave(7, '切换文件');
    expect(ok).toBe(true);
    expect(http.post).not.toHaveBeenCalled();
    expect(store.sessionKeyOf(7)).toBe('sess-7');
  });

  it('reset 清空 editorDirty 与 saveConfirmed', () => {
    store.setEditorDirty(7, true);
    store.markSaveConfirmed(
      7, {revision: 9, last_saved_at: 'x', last_saved_by_name: 'y'});
    store.reset();
    expect(store.editorDirty).toEqual({});
    expect(store.saveConfirmed).toEqual({});
  });
});

describe('draft store（撤销会话区分保存意图：discard 参数）', () => {
  // 契约（2026-10-30 收尾回调防丢失）：DS 在编辑器销毁时补发的收尾
  // status-2 回调可能晚于会话撤销到达——后端撤销端点接受可选布尔
  // discard（缺省 true=拒绝收尾回调）。前端唯一携带 discard=false 的
  // 是「保存并结束编辑」成功路径的撤销（finishEditing）；「不保存并
  // 退出」（showDiscardExit → store.exitFileSession(fileId)）与其他
  // 一切撤销路径一律不携带，维持缺省的显式丢弃语义。
  beforeEach(() => {
    jest.clearAllMocks();
    store.reset();
    sessionStorage.clear();
    store.id = 5;
    store.files = [makeFile(7)];
    store.selectedFileId = 7;
    store.passwordVerified = true;
    store.pollIntervalMs = 1;
    store.confirmSettleMs = 0;
  });

  it('保存并结束编辑成功路径：撤销请求体显式携带 discard=false', async () => {
    store.saveSession(7, 'sess-7', '2099-01-01T00:00:00');
    store.editorConfigs[7] = {editor_available: true, document_key: 'k1'};
    http.post.mockResolvedValue({forcesave: 'no_changes', revision: 7});
    http.delete.mockResolvedValue({});
    const ok = await store.finishEditing(7);
    expect(ok).toBe(true);
    expect(http.delete).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/7/draft/session/',
      {data: {session_key: 'sess-7', discard: false}});
    expect(store.sessionKeyOf(7)).toBe('');
  });

  it('exitFileSession 缺省（「不保存并退出」等一切其他撤销路径）：请求体不含 discard', async () => {
    store.saveSession(7, 'sess-7', '2099-01-01T00:00:00');
    http.delete.mockResolvedValue({});
    // 与 showDiscardExit（draft/index.js）同形调用：无 options
    await store.exitFileSession(7);
    expect(http.delete).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/7/draft/session/',
      {data: {session_key: 'sess-7'}});
    expect(store.sessionKeyOf(7)).toBe('');
  });
});
