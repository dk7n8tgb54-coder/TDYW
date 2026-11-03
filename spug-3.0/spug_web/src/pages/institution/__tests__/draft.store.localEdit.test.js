/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 本机编辑 store 行为测试（编辑方式切换 + 基线修订号上传，jsdom）：
 * - 编辑方式生效口径（effectiveEditMode）：在线配置可用时取 editModes
 *   （缺省在线）；服务未配置/配置缓存清除/配置加载失败一律回落本机。
 * - switchEditMode（在线→本机）：先落盘确认（confirmFileSave，成功不
 *   撤销会话）→ 轮换闸门（确认返回与轮换之间编辑器实时脏态翻 true 则
 *   重走一次确认，2026-10-31 在途修改竞态防护）→ 重取编辑配置轮换
 *   document key（rotateEditorKey，旧编辑实例回调在服务端失效）→ 清
 *   配置缓存；确认失败不轮换不切换，轮换失败阻止切换（此刻旧 key 回调
 *   仍会被接受，切走即留下覆盖窗口）。
 * - switchEditMode（本机→在线）：重新取编辑配置（本机期间修订号可能
 *   已推进，旧配置不得复用渲染）。
 * - uploadLocalDraft：必须携带下载草稿时记录的基线修订号（绝不改用
 *   清单内最新修订号）；成功清基线并刷新清单；基线过期（服务端草稿
 *   已被推进）清基线要求重新下载，其他失败保留基线可重试；全程不清
 *   会话（会话类失败由 saveDraft 既有语义处理）。
 * - replaceLocalDraft（整份替换当前草稿，不要求先下载）：以确认弹窗
 *   快照的修订号为基线（同样绝不读取清单最新修订号，缺失即拒绝）；
 *   成功只更新草稿、清已消费基线并刷新清单（不发布/不建文件/不改历史
 *   版本）；冲突「草稿已被其他会话更新」不清会话，其余失败沿用既有
 *   会话/密码分类。
 */
jest.mock('libs', () => ({
  http: {
    get: jest.fn(),
    post: jest.fn(),
    put: jest.fn(),
    delete: jest.fn(),
  },
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
  }, overrides);
}

function setupStore(id, files) {
  store.reset();
  store.id = id;
  store.files = files;
  store.selectedFileId = files.length ? files[0].id : null;
}

/** 建立在线编辑中的 store 状态（会话+可用配置，不经过页面渲染） */
function setupOnlineEditing(fileId) {
  setupStore(5, [makeFile(fileId)]);
  store.passwordVerified = true;
  store.saveSession(fileId, 'sess-1', '2099-01-01T00:00:00');
  store.editorConfigs[fileId] = {
    editor_available: true, document_key: 'k1', revision: 1};
  store.onlineAvailable[fileId] = true;
  store.pollIntervalMs = 1;
  store.confirmSettleMs = 0;
}

async function flush() {
  await Promise.resolve();
  await new Promise(resolve => setTimeout(resolve, 0));
}

beforeEach(() => {
  jest.clearAllMocks();
  store.reset();
  sessionStorage.clear();
});

describe('draft store（编辑方式生效口径）', () => {
  it('在线配置可用时取 editModes，缺省在线', () => {
    setupStore(5, [makeFile(1)]);
    store.editorConfigs[1] = {editor_available: true, document_key: 'k1'};
    expect(store.effectiveEditMode(1)).toBe('online');
    store.editModes[1] = 'local';
    expect(store.effectiveEditMode(1)).toBe('local');
  });

  it('服务未配置（editor_available=false）恒为本机，不受 editModes 影响', () => {
    setupStore(5, [makeFile(1)]);
    store.editorConfigs[1] = {editor_available: false};
    store.editModes[1] = 'online';
    expect(store.effectiveEditMode(1)).toBe('local');
  });

  it('配置缓存被清除（主动切换本机后）与配置加载失败都回落本机', () => {
    setupStore(5, [makeFile(1)]);
    store.onlineAvailable[1] = true;
    expect(store.effectiveEditMode(1)).toBe('local');
    store.editorErrors[1] = '在线编辑配置加载失败，可使用本机编辑降级路径';
    expect(store.effectiveEditMode(1)).toBe('local');
  });
});

describe('draft store（切换到本机编辑：确认→闸门→轮换）', () => {
  it('在线切本机：确认链路成功后重取编辑配置轮换 key，清配置缓存，会话保留', async () => {
    setupOnlineEditing(1);
    store.pollMaxAttempts = 2;
    // 确认链：第一次 forcesave 受理 → 轮询修订号推进 → 第二次复核 no_changes；
    // order 记录统一调用顺序（断言轮换发生在确认之后）
    const order = [];
    let forcesaveCalls = 0;
    http.post.mockImplementation(() => {
      order.push('forcesave');
      forcesaveCalls += 1;
      return Promise.resolve(forcesaveCalls === 1
        ? {forcesave: 'requested', revision: 1}
        : {forcesave: 'no_changes'});
    });
    http.get.mockImplementation(url => {
      if (url.includes('editor-config')) {
        order.push('rotate-config');
        return Promise.resolve({
          editor_available: true, document_key: 'k2', revision: 2});
      }
      if (url.endsWith('/draft/')) return Promise.resolve({revision: 2});
      if (url.includes('/files/')) return Promise.resolve([makeFile(1)]);
      return Promise.resolve({id: 5, name: '测试手册'});
    });
    const res = await store.switchEditMode(1, 'local');
    expect(res.ok).toBe(true);
    // 轮换恰一次，且发生在最后一次 forcesave（确认链）之后
    expect(order.filter(t => t === 'rotate-config')).toHaveLength(1);
    expect(order.indexOf('rotate-config'))
      .toBeGreaterThan(order.lastIndexOf('forcesave'));
    // 旧配置缓存清除（编辑器随渲染分支卸载；旧 token 不得被再次渲染使用）
    expect(store.editorConfigs[1]).toBeUndefined();
    expect(store.editModes[1]).toBe('local');
    expect(store.effectiveEditMode(1)).toBe('local');
    // 会话保留：本机上传（multipart draft/save）依赖有效会话
    expect(store.sessionKeyOf(1)).toBe('sess-1');
    expect(http.delete).not.toHaveBeenCalled();
    // 确认成功不清除在线能力标记（本机面板提供切回在线入口）
    expect(store.onlineAvailable[1]).toBe(true);
  });

  it('确认返回与轮换之间编辑器报脏：重走确认后才轮换（在途修改不随 key 轮换丢失）', async () => {
    // 2026-10-31 dev 保存丢失回归（轮换闸门）：确认链最后一次复核命令
    // 处理之后、轮换发生之前的敲入，其 documentState(true) 事件在确认
    // 收尾同拍到达——旧实现确认成功即轮换，该在途修改随旧 key 的收尾
    // 回调被 409 丢弃。修复后：确认返回与轮换之间编辑器翻脏必须重走
    // 一次确认，干净后才允许轮换。
    setupOnlineEditing(1);
    store.pollMaxAttempts = 2;
    const order = [];
    let forcesaveCalls = 0;
    http.post.mockImplementation(() => {
      order.push('forcesave');
      forcesaveCalls += 1;
      // 链1（确认）：no_changes（首次+沉降复核）；收尾同拍编辑器翻脏
      // 链2（闸门重走确认）：DS 看到在途修改改报受理 → 落盘 → 干净确认
      if (forcesaveCalls <= 2) return Promise.resolve({forcesave: 'no_changes'});
      if (forcesaveCalls === 3) {
        return Promise.resolve({forcesave: 'requested', revision: 1});
      }
      return Promise.resolve({forcesave: 'no_changes'});
    });
    http.get.mockImplementation(url => {
      if (url.includes('editor-config')) {
        order.push('rotate-config');
        return Promise.resolve({
          editor_available: true, document_key: 'k2', revision: 2});
      }
      if (url.endsWith('/draft/')) {
        // 回调落盘，DS 随即上报"所有更改已保存"
        store.setEditorDirty(1, false);
        return Promise.resolve({revision: 2});
      }
      if (url.includes('/files/')) return Promise.resolve([makeFile(1)]);
      return Promise.resolve({id: 5, name: '测试手册'});
    });
    // 模拟"确认收尾同拍到达的 documentState(true) 事件"：markSaveConfirmed
    // 清除闩锁的同拍，实时脏态被翻 true（这正是闩锁读不到、必须读实时
    // 脏态的窗口）
    const realMark = store.markSaveConfirmed;
    const markSpy = jest.spyOn(store, 'markSaveConfirmed')
      .mockImplementation((fid, draftData) => {
        realMark.call(store, fid, draftData);
        store.setEditorDirty(fid, true);
        markSpy.mockRestore();
      });
    const res = await store.switchEditMode(1, 'local');
    expect(res.ok).toBe(true);
    // 轮换恰一次，且发生在最后一条 forcesave（二次确认链）之后
    expect(order.filter(t => t === 'rotate-config')).toHaveLength(1);
    expect(order.indexOf('rotate-config'))
      .toBeGreaterThan(order.lastIndexOf('forcesave'));
    // 5 次 forcesave：链1 no_changes×2 + 链2 受理 → no_changes → 复核
    expect(forcesaveCalls).toBe(5);
    // 切换完成：配置缓存清除、方式为本机、会话保留
    expect(store.editorConfigs[1]).toBeUndefined();
    expect(store.effectiveEditMode(1)).toBe('local');
    expect(store.sessionKeyOf(1)).toBe('sess-1');
    expect(http.delete).not.toHaveBeenCalled();
  });
});

describe('draft store（切换到本机编辑：闸门静默路径与失败保护）', () => {
  it('确认返回时编辑器干净：无二次确认直接轮换（no_changes 链共两次 forcesave）', async () => {
    setupOnlineEditing(1);
    http.post.mockResolvedValue({forcesave: 'no_changes'});
    http.get.mockImplementation(url => {
      if (url.includes('editor-config')) {
        return Promise.resolve({
          editor_available: true, document_key: 'k2'});
      }
      if (url.includes('/files/')) return Promise.resolve([makeFile(1)]);
      return Promise.resolve({id: 5, name: '测试手册'});
    });
    const res = await store.switchEditMode(1, 'local');
    expect(res.ok).toBe(true);
    // 2 次 forcesave（首次 + 沉降复核），轮换恰一次，闸门未引入二次确认
    expect(http.post).toHaveBeenCalledTimes(2);
    expect(http.get.mock.calls.filter(([u]) =>
      u.includes('editor-config'))).toHaveLength(1);
    expect(store.effectiveEditMode(1)).toBe('local');
  });

  it('确认失败（未确认落盘）：不轮换、不切换、配置保留、语境标注 switch_local', async () => {
    setupOnlineEditing(1);
    store.pollMaxAttempts = 1;
    http.post.mockResolvedValue({forcesave: 'requested', revision: 1});
    http.get.mockImplementation(url => {
      if (url.includes('editor-config')) {
        return Promise.resolve({editor_available: true, document_key: 'k2'});
      }
      if (url.endsWith('/draft/')) return Promise.resolve({revision: 1});
      if (url.includes('/files/')) return Promise.resolve([makeFile(1)]);
      return Promise.resolve({id: 5, name: '测试手册'});
    });
    const res = await store.switchEditMode(1, 'local');
    expect(res.ok).toBe(false);
    expect(res.reason).toBe('confirm_failed');
    // 编辑配置未被再次取（轮换未发生，旧编辑实例回调仍被服务端接受——
    // 此刻绝不允许切走）
    expect(http.get.mock.calls.filter(([u]) =>
      u.includes('editor-config'))).toHaveLength(0);
    expect(store.editorConfigs[1]).not.toBeUndefined();
    expect(store.effectiveEditMode(1)).toBe('online');
    expect(store.sessionKeyOf(1)).toBe('sess-1');
    expect(store.finishingErrorKind).toBe('switch_local');
    expect(store.finishingError).toContain('已取消切换到本机编辑');
  });

  it('轮换失败（editor-config 请求失败）：阻止切换并呈现可重试语境', async () => {
    setupOnlineEditing(1);
    http.post.mockResolvedValue({forcesave: 'no_changes'});
    http.get.mockImplementation(url => {
      if (url.includes('editor-config')) {
        return Promise.reject('文档服务请求失败');
      }
      if (url.includes('/files/')) return Promise.resolve([makeFile(1)]);
      return Promise.resolve({id: 5, name: '测试手册'});
    });
    const res = await store.switchEditMode(1, 'local');
    expect(res.ok).toBe(false);
    expect(res.reason).toBe('rotate_failed');
    // 配置缓存与在线模式原样保留（编辑器与旧 key 行为不变，供重试）
    expect(store.editorConfigs[1]).not.toBeUndefined();
    expect(store.effectiveEditMode(1)).toBe('online');
    expect(store.finishingErrorKind).toBe('switch_local');
    expect(store.finishingError).toContain('保存回调尚未在服务端失效');
  });
});

describe('draft store（切回在线编辑：重新取配置）', () => {
  it('本机切回在线：重新取编辑配置（旧配置已失效不得复用）', async () => {
    setupOnlineEditing(1);
    store.editModes[1] = 'local';
    delete store.editorConfigs[1]; // 模拟已切换为本机（缓存已清）
    http.get.mockImplementation(url => {
      if (url.includes('editor-config')) {
        return Promise.resolve({
          editor_available: true, document_key: 'k3', revision: 1});
      }
      if (url.includes('/files/')) return Promise.resolve([makeFile(1)]);
      return Promise.resolve({id: 5, name: '测试手册'});
    });
    const res = await store.switchEditMode(1, 'online');
    expect(res.ok).toBe(true);
    await flush();
    expect(store.editorConfigs[1]).not.toBeUndefined();
    expect(store.editorConfigs[1].document_key).toBe('k3');
    expect(store.effectiveEditMode(1)).toBe('online');
  });

  it('在线能力缺失时切回在线被拒绝（服务未配置文件恒为本机）', async () => {
    setupStore(5, [makeFile(1)]);
    store.saveSession(1, 'sess-1', '2099-01-01T00:00:00');
    store.editorConfigs[1] = {editor_available: false};
    const res = await store.switchEditMode(1, 'online');
    expect(res.ok).toBe(false);
    expect(res.reason).toBe('unavailable');
    expect(store.effectiveEditMode(1)).toBe('local');
  });
});

describe('draft store（本机上传：基线修订号保护）', () => {
  it('无基线（未下载草稿）时拒绝上传，不发请求', async () => {
    setupStore(5, [makeFile(1)]);
    store.saveSession(1, 'sess-1', '2099-01-01T00:00:00');
    await expect(store.uploadLocalDraft(1, new File(['x'], 'a.docx')))
      .rejects.toContain('请先下载草稿');
    expect(http.post).not.toHaveBeenCalled();
  });

  it('上传携带下载时记录的基线修订号，绝不改用清单内最新修订号', async () => {
    setupStore(5, [makeFile(1)]);
    store.saveSession(1, 'sess-1', '2099-01-01T00:00:00');
    // 清单内草稿修订号已被推进到 9，但本次本机编辑基线是下载时的 4：
    // 上传必须提交 4（服务端草稿若已推进到 9，后端按修订号冲突拒绝）
    store.localBaselines[1] = 4;
    http.post.mockResolvedValue({revision: 5, file_name: '文件1.docx'});
    const file = new File(['x'], 'a.docx');
    await store.uploadLocalDraft(1, file);
    const [url, formData] = http.post.mock.calls[0];
    expect(url).toBe('/api/institution/manuals/5/files/1/draft/save/');
    expect(formData.get('session_key')).toBe('sess-1');
    expect(formData.get('revision')).toBe('4');
    expect(formData.get('file')).toBe(file);
  });

  it('上传成功：清除已消费基线并刷新清单（修订状态随之刷新）', async () => {
    setupStore(5, [makeFile(1)]);
    store.saveSession(1, 'sess-1', '2099-01-01T00:00:00');
    store.localBaselines[1] = 4;
    http.post.mockResolvedValue({revision: 5, file_name: '文件1.docx'});
    http.get.mockResolvedValue([makeFile(1)]);
    const data = await store.uploadLocalDraft(1, new File(['x'], 'a.docx'));
    expect(data.revision).toBe(5);
    expect(store.localBaselines[1]).toBeUndefined();
    // 清单已重取（GET files/）
    expect(http.get.mock.calls.some(([u]) => u.includes('/files/'))).toBe(true);
  });

  it('基线过期（服务端草稿已被推进）：上传被拒、清基线、会话保留可重新下载', async () => {
    setupStore(5, [makeFile(1)]);
    store.saveSession(1, 'sess-1', '2099-01-01T00:00:00');
    store.localBaselines[1] = 4;
    http.post.mockRejectedValue('草稿已被其他会话更新，请刷新草稿后重试');
    await expect(store.uploadLocalDraft(1, new File(['x'], 'a.docx')))
      .rejects.toBeTruthy();
    expect(store.localBaselines[1]).toBeUndefined();
    // 会话保留：失败不清会话，重新下载取得新基线后可再次上传
    expect(store.sessionKeyOf(1)).toBe('sess-1');
  });

  it('其他失败（网络等）：基线保留可重试，会话不清', async () => {
    setupStore(5, [makeFile(1)]);
    store.saveSession(1, 'sess-1', '2099-01-01T00:00:00');
    store.localBaselines[1] = 4;
    http.post.mockRejectedValue('网络错误，请稍后重试');
    await expect(store.uploadLocalDraft(1, new File(['x'], 'a.docx')))
      .rejects.toBeTruthy();
    expect(store.localBaselines[1]).toBe(4);
    expect(store.sessionKeyOf(1)).toBe('sess-1');
  });
});

describe('draft store（整份替换当前草稿：确认时修订号契约）', () => {
  it('以确认时修订号为基线上传（不是清单最新修订号）：只更新草稿、清基线并刷新清单', async () => {
    setupStore(5, [makeFile(1)]);
    store.saveSession(1, 'sess-1', '2099-01-01T00:00:00');
    // 旧下载基线=2；清单内草稿修订号已被推进到 9；确认时快照=3
    store.localBaselines[1] = 2;
    store.files[0].draft.revision = 9;
    http.post.mockResolvedValue({revision: 4, file_name: '文件1.docx'});
    http.get.mockResolvedValue([makeFile(1)]);
    const file = new File(['x'], 'a.docx');
    const data = await store.replaceLocalDraft(1, file, 3);
    expect(data.revision).toBe(4);
    // 唯一请求=文件级 draft/save（multipart），修订号=确认时修订号 3
    expect(http.post).toHaveBeenCalledTimes(1);
    const [url, formData] = http.post.mock.calls[0];
    expect(url).toBe('/api/institution/manuals/5/files/1/draft/save/');
    expect(formData.get('session_key')).toBe('sess-1');
    expect(formData.get('revision')).toBe('3');
    expect(formData.get('file')).toBe(file);
    // 只更新草稿：不发布、不新增文件、不改历史发布版本
    //（无 PUT/DELETE，POST 仅 draft/save）
    expect(http.put).not.toHaveBeenCalled();
    expect(http.delete).not.toHaveBeenCalled();
    expect(http.post.mock.calls.every(([u]) => u.includes('/draft/save/'))).toBe(true);
    // 成功清该文件已消费的基线并刷新清单（修订状态随清单刷新）
    expect(store.localBaselines[1]).toBeUndefined();
    expect(http.get.mock.calls.some(([u]) => u.includes('/files/'))).toBe(true);
    // 替换不撤销会话
    expect(store.sessionKeyOf(1)).toBe('sess-1');
  });

  it('确认时修订号缺失：拒绝替换，绝不回落到清单最新修订号', async () => {
    setupStore(5, [makeFile(1)]);
    store.saveSession(1, 'sess-1', '2099-01-01T00:00:00');
    store.files[0].draft.revision = 9;
    await expect(store.replaceLocalDraft(1, new File(['x'], 'a.docx'), null))
      .rejects.toContain('缺少替换前的草稿修订号');
    expect(http.post).not.toHaveBeenCalled();
    expect(store.sessionKeyOf(1)).toBe('sess-1');
  });

  it('冲突（草稿已被其他会话更新）：抛错、不清会话、不回密码门', async () => {
    setupStore(5, [makeFile(1)]);
    store.saveSession(1, 'sess-1', '2099-01-01T00:00:00');
    store.verifiedPassword = 'pw1';
    store.passwordVerified = true;
    http.post.mockRejectedValue('草稿已被其他会话更新，请刷新草稿后重试');
    await expect(store.replaceLocalDraft(1, new File(['x'], 'a.docx'), 3))
      .rejects.toBeTruthy();
    // 修订号冲突与会话失效无关：会话与密码门状态原样保留，可刷新后重新确认
    expect(store.sessionKeyOf(1)).toBe('sess-1');
    expect(store.passwordVerified).toBe(true);
  });

  it('其它错误沿用既有分类：会话类清该文件会话，纯密码类回密码门', async () => {
    setupStore(5, [makeFile(1)]);
    store.saveSession(1, 'sess-1', '2099-01-01T00:00:00');
    store.verifiedPassword = 'pw1';
    store.passwordVerified = true;
    http.post.mockRejectedValue('编辑会话已过期，请重新验证密码');
    await expect(store.replaceLocalDraft(1, new File(['x'], 'a.docx'), 3))
      .rejects.toBeTruthy();
    // 含"会话"的错误只清该文件会话、不回密码门（可重新开启）
    expect(store.sessionKeyOf(1)).toBe('');
    expect(store.passwordVerified).toBe(true);

    setupStore(5, [makeFile(1)]);
    store.saveSession(1, 'sess-1', '2099-01-01T00:00:00');
    store.verifiedPassword = 'pw1';
    store.passwordVerified = true;
    http.post.mockRejectedValue('编辑密码错误');
    await expect(store.replaceLocalDraft(1, new File(['x'], 'a.docx'), 3))
      .rejects.toBeTruthy();
    // 纯密码类错误：清会话并清已验证密码，回密码门
    expect(store.sessionKeyOf(1)).toBe('');
    expect(store.verifiedPassword).toBe('');
    expect(store.passwordVerified).toBe(false);
  });
});

describe('draft store（基线记录与状态清理）', () => {
  it('recordLocalBaseline 记录修订号；null 忽略', () => {
    setupStore(5, [makeFile(1)]);
    store.recordLocalBaseline(1, 7);
    expect(store.localBaselines[1]).toBe(7);
    store.recordLocalBaseline(1, null);
    expect(store.localBaselines[1]).toBe(7);
  });

  it('clearSession 清除该文件的编辑方式/能力/失败标记/基线', () => {
    setupStore(5, [makeFile(1)]);
    store.saveSession(1, 'sess-1', '2099-01-01T00:00:00');
    store.editModes[1] = 'local';
    store.onlineAvailable[1] = true;
    store.editorLoadFailed[1] = true;
    store.localBaselines[1] = 3;
    store.clearSession(1);
    expect(store.editModes[1]).toBeUndefined();
    expect(store.onlineAvailable[1]).toBeUndefined();
    expect(store.editorLoadFailed[1]).toBeUndefined();
    expect(store.localBaselines[1]).toBeUndefined();
  });

  it('reset 清空全部本机编辑状态', () => {
    setupStore(5, [makeFile(1)]);
    store.editModes[1] = 'local';
    store.onlineAvailable[1] = true;
    store.editorLoadFailed[1] = true;
    store.localBaselines[1] = 3;
    store.finishingErrorKind = 'switch_local';
    store.reset();
    expect(store.editModes).toEqual({});
    expect(store.onlineAvailable).toEqual({});
    expect(store.editorLoadFailed).toEqual({});
    expect(store.localBaselines).toEqual({});
    expect(store.finishingErrorKind).toBe('');
  });
});
