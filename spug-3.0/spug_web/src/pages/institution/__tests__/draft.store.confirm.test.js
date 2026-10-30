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
      source_original_id: null, last_saved_by_name: '张三',
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
