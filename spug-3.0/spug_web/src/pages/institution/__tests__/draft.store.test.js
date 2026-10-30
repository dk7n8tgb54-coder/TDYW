/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 多文件草稿工作台 store 行为测试：
 * - 会话按 (manualId, fileId) 存取（sessionStorage 键
 *   institution_edit_session_<manualId>_<fileId>），清单恢复与孤儿键清理。
 * - 密码门对第一份有草稿的文件开会话；工作区用已验证密码开启其余文件。
 * - 会话类失败清该文件会话、密码类失败回密码门；错误一律上抛不重复弹错。
 * - 文件管理（新增/改名/排序/移除）后清单刷新；移除清本地会话与选中。
 * - 编辑配置按文件缓存：编辑中禁止重复取（轮换 document key 会使回调失效）。
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
    originals_count: 1,
    draft: {
      id: 100 + id,
      revision: id,
      file_name: `文件${id}.docx`,
      file_size: 1024,
      file_hash: `hash-${id}`,
      base_version_id: null,
      source_original_id: null,
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

describe('draft store（会话按 manualId+fileId 存取）', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    store.reset();
    sessionStorage.clear();
  });

  it('saveSession 写入按文件的 sessionStorage 键，sessionKeyOf 按文件读取', () => {
    setupStore(5, []);
    store.saveSession(7, 'sess-a', '2099-01-01T00:00:00');
    expect(store.sessionKeyOf(7)).toBe('sess-a');
    expect(store.sessionKeyOf(8)).toBe('');
    expect(store.sessionExpiresOf(8)).toBeNull();
    const raw = sessionStorage.getItem('institution_edit_session_5_7');
    expect(JSON.parse(raw)).toEqual(
      {sessionKey: 'sess-a', expiresAt: '2099-01-01T00:00:00'});
  });

  it('loadSessions 恢复清单内文件的未过期会话，清理孤儿键与旧单文件键', () => {
    setupStore(5, [makeFile(7), makeFile(8)]);
    sessionStorage.setItem('institution_edit_session_5_7',
      JSON.stringify({sessionKey: 'sess-a', expiresAt: '2099-01-01T00:00:00'}));
    // 清单外文件的键（已移除/他册）：清理
    sessionStorage.setItem('institution_edit_session_5_9',
      JSON.stringify({sessionKey: 'sess-x', expiresAt: '2099-01-01T00:00:00'}));
    // 旧单文件模式的无后缀键：清理
    sessionStorage.setItem('institution_edit_session_5',
      JSON.stringify({sessionKey: 'sess-old', expiresAt: '2099-01-01T00:00:00'}));
    store.loadSessions();
    expect(store.sessionKeyOf(7)).toBe('sess-a');
    expect(store.sessionKeyOf(8)).toBe('');
    expect(sessionStorage.getItem('institution_edit_session_5_9')).toBeNull();
    expect(sessionStorage.getItem('institution_edit_session_5')).toBeNull();
    expect(sessionStorage.getItem('institution_edit_session_5_7')).not.toBeNull();
  });

  it('loadSessions 清除已过期会话', () => {
    setupStore(5, [makeFile(7)]);
    sessionStorage.setItem('institution_edit_session_5_7',
      JSON.stringify({sessionKey: 'sess-old', expiresAt: '2000-01-01T00:00:00'}));
    store.loadSessions();
    expect(store.sessionKeyOf(7)).toBe('');
    expect(sessionStorage.getItem('institution_edit_session_5_7')).toBeNull();
  });

  it('clearSession 只清指定文件，不影响其他文件的会话', () => {
    setupStore(5, [makeFile(7), makeFile(8)]);
    store.saveSession(7, 'sess-a', '2099-01-01T00:00:00');
    store.saveSession(8, 'sess-b', '2099-01-01T00:00:00');
    store.clearSession(7);
    expect(store.sessionKeyOf(7)).toBe('');
    expect(store.sessionKeyOf(8)).toBe('sess-b');
    expect(sessionStorage.getItem('institution_edit_session_5_8')).not.toBeNull();
    expect(sessionStorage.getItem('institution_edit_session_5_7')).toBeNull();
  });

  it('hasAnySession 任一文件持会话即为真（未保存拦截依据）', () => {
    setupStore(5, [makeFile(7), makeFile(8)]);
    expect(store.hasAnySession).toBe(false);
    store.saveSession(8, 'sess-b', '2099-01-01T00:00:00');
    expect(store.hasAnySession).toBe(true);
  });
});

describe('draft store（密码门与按文件开启会话）', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    store.reset();
    sessionStorage.clear();
  });

  it('verifyPassword 对第一份有草稿的文件开会话并记下已验证密码', async () => {
    setupStore(5, [makeFile(1, {draft: null}), makeFile(2)]);
    http.post.mockResolvedValue({
      session_key: 'sess-2', expires_at: '2099-01-01T00:00:00',
      revision: 2, file_name: '文件2.docx', base_version_id: null,
    });
    http.get.mockResolvedValue({editor_available: false});
    await store.verifyPassword('pw');
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/2/draft/session/', {password: 'pw'});
    expect(store.passwordVerified).toBe(true);
    expect(store.verifiedPassword).toBe('pw');
    expect(store.sessionKeyOf(2)).toBe('sess-2');
    expect(store.sessionKeyOf(1)).toBe('');
    expect(store.verifyError).toBe('');
    // 会话持久化到按文件的 sessionStorage 键
    expect(sessionStorage.getItem('institution_edit_session_5_2')).not.toBeNull();
  });

  it('verifyPassword 密码错误留在密码门：不建会话、记原因、不上抛丢失', async () => {
    setupStore(5, [makeFile(1)]);
    http.post.mockRejectedValue('编辑密码错误');
    await expect(store.verifyPassword('bad')).rejects.toBe('编辑密码错误');
    expect(store.passwordVerified).toBe(false);
    expect(store.verifiedPassword).toBe('');
    expect(store.sessionKeyOf(1)).toBe('');
    expect(store.verifyError).toContain('编辑密码错误');
  });

  it('verifyPassword 无待发布文件时直接给出原因不开会话', async () => {
    setupStore(5, []);
    await expect(store.verifyPassword('pw')).rejects.toContain('待发布文件');
    expect(http.post).not.toHaveBeenCalled();
    expect(store.verifyError).toContain('待发布文件');
  });

  it('startFileSession 用已验证密码开启指定文件会话', async () => {
    setupStore(5, [makeFile(7), makeFile(8)]);
    store.verifiedPassword = 'pw';
    store.passwordVerified = true;
    http.post.mockResolvedValue({
      session_key: 'sess-8', expires_at: '2099-01-01T00:00:00',
      revision: 8, file_name: '文件8.docx', base_version_id: null,
    });
    http.get.mockResolvedValue({editor_available: false});
    await store.startFileSession(8);
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/8/draft/session/', {password: 'pw'});
    expect(store.sessionKeyOf(8)).toBe('sess-8');
    expect(store.sessionKeyOf(7)).toBe('');
  });

  it('startFileSession 密码失效时清已验证密码并回密码门', async () => {
    setupStore(5, [makeFile(8)]);
    store.verifiedPassword = 'pw';
    store.passwordVerified = true;
    http.post.mockRejectedValue('密码错误次数过多，请约 5 分钟后重试');
    await expect(store.startFileSession(8)).rejects.toContain('密码');
    expect(store.passwordVerified).toBe(false);
    expect(store.verifiedPassword).toBe('');
    expect(store.sessionKeyOf(8)).toBe('');
  });

  it('startFileSession 无已验证密码（恢复会话直入）时回密码门且不请求', async () => {
    setupStore(5, [makeFile(8)]);
    store.passwordVerified = true;
    store.verifiedPassword = '';
    await expect(store.startFileSession(8)).rejects.toContain('密码验证');
    expect(http.post).not.toHaveBeenCalled();
    expect(store.passwordVerified).toBe(false);
  });

  it('exitFileSession 成功后清除该文件本地会话（服务端 revoke）', async () => {
    setupStore(5, [makeFile(7), makeFile(8)]);
    store.saveSession(7, 'sess-a', '2099-01-01T00:00:00');
    store.saveSession(8, 'sess-b', '2099-01-01T00:00:00');
    http.delete.mockResolvedValue({});
    await store.exitFileSession(8);
    expect(http.delete).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/8/draft/session/',
      {data: {session_key: 'sess-b'}});
    expect(store.sessionKeyOf(8)).toBe('');
    expect(store.sessionKeyOf(7)).toBe('sess-a');
  });

  it('exitFileSession 失败时保留本地会话供重试，错误向上抛（不弹假成功）', async () => {
    setupStore(5, [makeFile(8)]);
    store.saveSession(8, 'sess-b', '2099-01-01T00:00:00');
    http.delete.mockRejectedValue('网络错误');
    await expect(store.exitFileSession(8)).rejects.toBe('网络错误');
    expect(store.sessionKeyOf(8)).toBe('sess-b');
  });

  it('exitFileSession 无会话时直接返回不请求', async () => {
    setupStore(5, [makeFile(8)]);
    await store.exitFileSession(8);
    expect(http.delete).not.toHaveBeenCalled();
  });
});

describe('draft store（草稿保存与清单刷新）', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    store.reset();
    sessionStorage.clear();
  });

  it('saveDraft 携带该文件会话与修订序号，成功后更新清单内条目', async () => {
    setupStore(5, [makeFile(7), makeFile(8)]);
    store.saveSession(8, 'sess-8', '2099-01-01T00:00:00');
    const file = new File(['x'], 'a.docx');
    http.post.mockResolvedValue({revision: 9, file_name: '文件8.docx'});
    const data = await store.saveDraft(8, file);
    const [url, formData] = http.post.mock.calls[0];
    expect(url).toBe('/api/institution/manuals/5/files/8/draft/save/');
    expect(formData.get('session_key')).toBe('sess-8');
    expect(formData.get('revision')).toBe('8');
    expect(formData.get('file')).toBe(file);
    expect(data.revision).toBe(9);
    // 清单内该文件条目的草稿更新为最新修订（MobX 转换后需经 store 读取）
    expect(store.files[1].draft.revision).toBe(9);
  });

  it('saveDraft 失败错误含"会话"时清除该文件会话且不影响其他文件', async () => {
    const files = [makeFile(7), makeFile(8)];
    setupStore(5, files);
    store.saveSession(7, 'sess-7', '2099-01-01T00:00:00');
    store.saveSession(8, 'sess-8', '2099-01-01T00:00:00');
    store.passwordVerified = true;
    store.verifiedPassword = 'pw';
    http.post.mockRejectedValue('编辑会话已过期，请重新验证密码');
    await expect(store.saveDraft(8, new File(['x'], 'a.docx')))
      .rejects.toBe('编辑会话已过期，请重新验证密码');
    expect(store.sessionKeyOf(8)).toBe('');
    expect(store.sessionKeyOf(7)).toBe('sess-7');
    // 会话类失败不回密码门（密码仍视为已验证，可重新开启会话）
    expect(store.passwordVerified).toBe(true);
    expect(store.verifiedPassword).toBe('pw');
    store.saveSession(8, 'sess-8', '2099-01-01T00:00:00');
    http.post.mockRejectedValue('编辑密码错误');
    await expect(store.saveDraft(8, new File(['x'], 'a.docx')))
      .rejects.toBe('编辑密码错误');
    // 密码类失败清已验证密码并回密码门
    expect(store.passwordVerified).toBe(false);
    expect(store.verifiedPassword).toBe('');
  });

  it('refreshFiles 更新清单并保持选中；选中文件消失时回落第一份', async () => {
    setupStore(5, [makeFile(7), makeFile(8)]);
    store.selectedFileId = 8;
    http.get.mockResolvedValue([makeFile(7), makeFile(8), makeFile(9)]);
    await store.refreshFiles();
    expect(store.files).toHaveLength(3);
    expect(store.selectedFileId).toBe(8);
    http.get.mockResolvedValue([makeFile(7)]);
    await store.refreshFiles();
    expect(store.selectedFileId).toBe(7);
  });

  it('refreshFiles 失败时向上抛出（成功提示须等真实结果）', async () => {
    setupStore(5, [makeFile(7)]);
    http.get.mockRejectedValue('服务器内部错误');
    await expect(store.refreshFiles()).rejects.toBe('服务器内部错误');
  });

  it('selectFile 只接受清单内文件', () => {
    setupStore(5, [makeFile(7), makeFile(8)]);
    store.selectFile(8);
    expect(store.selectedFileId).toBe(8);
    store.selectFile(99);
    expect(store.selectedFileId).toBe(8);
  });
});

describe('draft store（文件管理）', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    store.reset();
    sessionStorage.clear();
  });

  it('createFile multipart 上传后刷新清单并透传 draft_error', async () => {
    setupStore(5, [makeFile(7)]);
    const created = {id: 9, name: '新文件', sort_order: 2, draft: null, active_session: null};
    http.post.mockResolvedValue(Object.assign({draft_error: '文件已创建，但可编辑草稿建立失败：转换失败'}, created));
    http.get.mockResolvedValue([makeFile(7), created]);
    const data = await store.createFile(new File(['x'], 'new.docx'));
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/create/', expect.any(FormData));
    const formData = http.post.mock.calls[0][1];
    expect(formData.get('file')).toBeInstanceOf(File);
    // draft_error 非空=文件已创建但草稿未就绪，透传给调用方警示（不算失败）
    expect(data.draft_error).toContain('草稿建立失败');
    expect(data.id).toBe(9);
    // 清单已刷新为含新文件的列表
    expect(store.files).toHaveLength(2);
  });

  it('moveFile 发送 1 起目标序位并重取清单保证全局有序', async () => {
    setupStore(5, [makeFile(7), makeFile(8), makeFile(9)]);
    http.post.mockResolvedValue({id: 9, name: '文件9', sort_order: 1});
    http.get.mockResolvedValue([makeFile(9), makeFile(7), makeFile(8)]);
    await store.moveFile(9, 1);
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/9/move/', {position: 1});
    expect(store.files.map(f => f.id)).toEqual([9, 7, 8]);
  });

  it('renameFile 提交新名称并刷新清单', async () => {
    setupStore(5, [makeFile(7)]);
    http.post.mockResolvedValue(Object.assign(makeFile(7), {name: '新名'}));
    http.get.mockResolvedValue([Object.assign(makeFile(7), {name: '新名'})]);
    await store.renameFile(7, '新名');
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/7/rename/', {name: '新名'});
    expect(store.files[0].name).toBe('新名');
  });

  it('removeFile 移除条目并清除该文件本地会话；选中文件回落第一份', async () => {
    const files = [makeFile(7), makeFile(8)];
    setupStore(5, files);
    store.selectedFileId = 8;
    store.saveSession(8, 'sess-8', '2099-01-01T00:00:00');
    http.post.mockResolvedValue({});
    await store.removeFile(8);
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/8/remove/', {});
    expect(store.files.map(f => f.id)).toEqual([7]);
    expect(store.selectedFileId).toBe(7);
    expect(store.sessionKeyOf(8)).toBe('');
    expect(sessionStorage.getItem('institution_edit_session_5_8')).toBeNull();
  });

  it('removeFile 失败时错误向上抛，清单不变（拦截器已提示）', async () => {
    setupStore(5, [makeFile(7)]);
    http.post.mockRejectedValue('最后一份文件不能移除');
    await expect(store.removeFile(7)).rejects.toBe('最后一份文件不能移除');
    expect(store.files).toHaveLength(1);
  });
});

describe('draft store（编辑配置按文件缓存）', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    store.reset();
    sessionStorage.clear();
  });

  it('fetchEditorConfig 按文件取配置（URL 携带该文件会话）', async () => {
    setupStore(5, [makeFile(7), makeFile(8)]);
    store.saveSession(7, 'sess-7', '2099-01-01T00:00:00');
    http.get.mockResolvedValue({
      editor_available: true, editor_type: 'onlyoffice',
      document_key: 'oo-7-r7-abcd1234', token: 'jwt-token',
      file_id: 7, revision: 7,
    });
    await store.fetchEditorConfig(7);
    expect(http.get).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/7/draft/editor-config/?session_key=sess-7');
    expect(store.editorConfigs[7].editor_available).toBe(true);
    expect(store.editorLoadingId).toBeNull();
  });

  it('已有缓存的文件重复调用不重新取（编辑中禁止轮换 document key）', async () => {
    setupStore(5, [makeFile(7)]);
    store.saveSession(7, 'sess-7', '2099-01-01T00:00:00');
    http.get.mockResolvedValue({editor_available: true, document_key: 'k1'});
    await store.fetchEditorConfig(7);
    await store.fetchEditorConfig(7);
    expect(http.get).toHaveBeenCalledTimes(1);
  });

  it('fetchEditorConfig 会话类失败时清除该文件会话，不记编辑器错误', async () => {
    setupStore(5, [makeFile(7)]);
    store.saveSession(7, 'sess-7', '2099-01-01T00:00:00');
    http.get.mockRejectedValue('编辑会话已过期，请重新验证密码');
    await store.fetchEditorConfig(7);
    expect(store.sessionKeyOf(7)).toBe('');
    expect(store.editorConfigs[7]).toBeUndefined();
    expect(store.editorErrors[7]).toBeUndefined();
  });

  it('fetchEditorConfig 其他失败保留会话并记为编辑器错误（拦截器已弹错不重复）', async () => {
    setupStore(5, [makeFile(7)]);
    store.saveSession(7, 'sess-7', '2099-01-01T00:00:00');
    http.get.mockRejectedValue('服务器内部错误');
    await store.fetchEditorConfig(7);
    expect(store.sessionKeyOf(7)).toBe('sess-7');
    expect(store.editorErrors[7]).toContain('本机编辑降级');
  });

  it('clearSession 同时清除该文件的编辑配置缓存与错误信息', async () => {
    setupStore(5, [makeFile(7)]);
    store.editorConfigs[7] = {editor_available: true};
    store.editorErrors[7] = 'x';
    store.saveSession(7, 'sess-7', '2099-01-01T00:00:00');
    store.clearSession(7);
    expect(store.editorConfigs[7]).toBeUndefined();
    expect(store.editorErrors[7]).toBeUndefined();
    expect(store.sessionKeyOf(7)).toBe('');
  });
});

describe('draft store（进入页面与迟到响应）', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    store.reset();
    sessionStorage.clear();
  });

  it('fetchAll 恢复本地会话并为持会话文件取配置，默认选中第一份', async () => {
    sessionStorage.setItem('institution_edit_session_5_8',
      JSON.stringify({sessionKey: 'sess-8', expiresAt: '2099-01-01T00:00:00'}));
    http.get.mockImplementation(url => {
      if (url.includes('editor-config')) {
        return Promise.resolve({editor_available: false});
      }
      if (url.includes('/files/')) {
        return Promise.resolve([makeFile(7), makeFile(8)]);
      }
      return Promise.resolve({id: 5, name: '手册', my_roles: ['edit']});
    });
    await store.fetchAll(5);
    expect(store.manual.name).toBe('手册');
    expect(store.selectedFileId).toBe(7);
    expect(store.sessionKeyOf(8)).toBe('sess-8');
    // 仅为持会话的文件取编辑配置
    const configCalls = http.get.mock.calls.filter(([url]) => url.includes('editor-config'));
    expect(configCalls).toHaveLength(1);
    expect(configCalls[0][0]).toContain('/files/8/');
  });

  it('fetchAll 切换手册时清空上一本手册的内存会话（文件 id 可能撞号）', async () => {
    setupStore(5, [makeFile(7)]);
    store.saveSession(7, 'sess-old-manual', '2099-01-01T00:00:00');
    http.get.mockImplementation(url => {
      if (url.includes('editor-config')) return Promise.resolve({editor_available: false});
      if (url.includes('/files/')) return Promise.resolve([makeFile(7)]);
      return Promise.resolve({id: 6, name: '另一册'});
    });
    await store.fetchAll(6);
    expect(store.id).toBe(6);
    // 手册 6 的文件 7 不应继承手册 5 文件 7 的会话
    expect(store.sessionKeyOf(7)).toBe('');
    expect(store.hasAnySession).toBe(false);
  });

  it('fetchAll 失败时清空残留手册数据，错误页不被旧数据短路', async () => {
    setupStore(5, [makeFile(7)]);
    http.get.mockRejectedValue('x');
    await store.fetchAll(6);
    expect(store.manual).toBeNull();
    expect(store.files).toHaveLength(0);
    expect(store.error).toContain('无权限');
  });

  it('fetchAll 迟到响应不覆盖新手册状态（seq 守卫）', async () => {
    store.reset();
    const pending = [];
    http.get.mockImplementation(url => {
      if (url.includes('manuals/5')) {
        return new Promise(resolve => pending.push(resolve));
      }
      if (url.includes('editor-config')) return Promise.resolve({editor_available: false});
      if (url.includes('/files/')) return Promise.resolve([makeFile(2)]);
      return Promise.resolve({id: 6, name: 'B'});
    });
    store.fetchAll(5);
    await store.fetchAll(6);
    expect(store.id).toBe(6);
    expect(store.manual.name).toBe('B');
    pending.forEach(resolve => resolve({id: 5, name: 'A'}));
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(store.id).toBe(6);
    expect(store.manual.name).toBe('B');
  });
});

describe('draft store（保存并结束编辑：落盘确认后才撤销会话）', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    store.reset();
    sessionStorage.clear();
    store.id = 5;
    store.files = [makeFile(7), makeFile(8)];
    store.selectedFileId = 7;
    store.passwordVerified = true;
    store.pollIntervalMs = 1;
  });

  it('降级路径（无在线编辑器）：直接撤销会话，不发 forcesave', async () => {
    store.saveSession(7, 'sess-7', '2099-01-01T00:00:00');
    store.editorConfigs[7] = {editor_available: false};
    http.delete.mockResolvedValue({});
    const ok = await store.finishEditing(7);
    expect(ok).toBe(true);
    expect(http.post).not.toHaveBeenCalled();
    expect(http.delete).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/7/draft/session/',
      {data: {session_key: 'sess-7'}});
    expect(store.sessionKeyOf(7)).toBe('');
    expect(store.finishingError).toBe('');
  });

  it('在线路径成功：受理 → 轮询到修订号推进 → 复核 no_changes 才撤销会话', async () => {
    store.saveSession(7, 'sess-7', '2099-01-01T00:00:00');
    store.editorConfigs[7] = {editor_available: true, document_key: 'k1'};
    const fsCalls = () => http.post.mock.calls.filter(
      ([url]) => url.includes('forcesave'));
    http.post.mockImplementation(url => {
      if (url.includes('forcesave')) {
        // 第一次受理；修订号推进后的复核轮 DS 报告无更多待存修改
        return fsCalls().length === 1
          ? Promise.resolve({forcesave: 'requested', revision: 7})
          : Promise.resolve({forcesave: 'no_changes', revision: 8});
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
    http.delete.mockResolvedValue({});
    const ok = await store.finishEditing(7);
    expect(ok).toBe(true);
    expect(fsCalls()).toHaveLength(2);
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/7/draft/forcesave/',
      {session_key: 'sess-7'});
    expect(http.delete).toHaveBeenCalled();
    expect(store.sessionKeyOf(7)).toBe('');
    // 确认成功曾写入服务端确认记录；结束编辑撤销会话（clearSession）
    // 后随之清除——无会话文件的保存状态回落到服务端草稿数据展示
    expect(store.saveConfirmed[7]).toBeUndefined();
    expect(store.editorDirty[7]).toBeUndefined();
  });

  it('在线路径 no_changes：DS 无修改时无需轮询直接结束', async () => {
    store.saveSession(7, 'sess-7', '2099-01-01T00:00:00');
    store.editorConfigs[7] = {editor_available: true, document_key: 'k1'};
    http.post.mockResolvedValue({forcesave: 'no_changes', revision: 7});
    http.delete.mockResolvedValue({});
    const ok = await store.finishEditing(7);
    expect(ok).toBe(true);
    // 只有一次 forcesave POST；无 draft/ 轮询 GET（成功收尾的 refreshFiles 除外）
    expect(http.post).toHaveBeenCalledTimes(1);
    const pollGets = http.get.mock.calls.filter(([url]) => url.endsWith('/draft/'));
    expect(pollGets).toHaveLength(0);
    expect(store.sessionKeyOf(7)).toBe('');
    // no_changes 同样是服务端确认（DS 无待落盘修改）；撤销会话后确认
    // 记录随 clearSession 清除，保存状态回落到服务端草稿数据展示
    expect(store.saveConfirmed[7]).toBeUndefined();
  });
});

describe('draft store（保存并结束编辑：失败保护与 quiet forcesave）', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    store.reset();
    sessionStorage.clear();
    store.id = 5;
    store.files = [makeFile(7), makeFile(8)];
    store.selectedFileId = 7;
    store.passwordVerified = true;
    store.pollIntervalMs = 1;
  });

  it('在线路径超时未确认：返回 false、保留会话、finishingError 指向该文件', async () => {
    store.saveSession(7, 'sess-7', '2099-01-01T00:00:00');
    store.editorConfigs[7] = {editor_available: true, document_key: 'k1'};
    store.pollMaxAttempts = 2;
    http.post.mockResolvedValue({forcesave: 'requested', revision: 7});
    http.get.mockImplementation(url => {
      if (url.endsWith('/draft/')) return Promise.resolve({revision: 7});
      return Promise.resolve([]);
    });
    const ok = await store.finishEditing(7);
    expect(ok).toBe(false);
    expect(http.delete).not.toHaveBeenCalled();
    expect(store.sessionKeyOf(7)).toBe('sess-7');
    expect(store.finishingErrorFileId).toBe(7);
    expect(store.finishingError).toContain('未确认');
  });

  it('forcesave 业务失败：保留会话与编辑器，错误上抛路径呈现重试状态', async () => {
    store.saveSession(7, 'sess-7', '2099-01-01T00:00:00');
    store.editorConfigs[7] = {editor_available: true, document_key: 'k1'};
    http.post.mockRejectedValue('文档服务无法受理保存请求');
    const ok = await store.finishEditing(7);
    expect(ok).toBe(false);
    expect(store.sessionKeyOf(7)).toBe('sess-7');
    expect(store.finishingErrorFileId).toBe(7);
    expect(store.finishingError).toContain('请重试');
  });

  it('无会话文件 finishEditing 直接失败且不请求', async () => {
    const ok = await store.finishEditing(7);
    expect(ok).toBe(false);
    expect(http.post).not.toHaveBeenCalled();
    expect(http.delete).not.toHaveBeenCalled();
    expect(store.finishingError).toContain('没有进行中的编辑会话');
  });

  it('reset 使进行中的轮询失效（_pollSaveConfirmed 返回 null 不误撤销）', async () => {
    const seq = store.finishSeq;
    let releasePoll;
    http.get.mockImplementation(() => new Promise(
      resolve => { releasePoll = resolve; }));
    const polling = store._pollSaveConfirmed(7, 6, seq);
    store.reset(); // 离开页面：finishSeq 递增
    if (releasePoll) releasePoll({revision: 9});
    expect(await polling).toBeNull();
    expect(http.delete).not.toHaveBeenCalled();
  });

  it('requestForcesaveQuiet 有会话且在线时静默请求 forcesave，失败不抛', async () => {
    store.saveSession(7, 'sess-7', '2099-01-01T00:00:00');
    store.editorConfigs[7] = {editor_available: true, document_key: 'k1'};
    http.post.mockResolvedValue({forcesave: 'requested', revision: 7});
    await store.requestForcesaveQuiet(7);
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/7/draft/forcesave/',
      {session_key: 'sess-7'}, {skipErrorNotification: true});
    http.post.mockRejectedValue('网络错误');
    await expect(store.requestForcesaveQuiet(7)).resolves.toBeUndefined();
  });

  it('requestForcesaveQuiet 无会话或无在线配置时不请求', async () => {
    await store.requestForcesaveQuiet(7);
    store.saveSession(7, 'sess-7', '2099-01-01T00:00:00');
    store.editorConfigs[7] = {editor_available: false};
    await store.requestForcesaveQuiet(7);
    expect(http.post).not.toHaveBeenCalled();
  });
});

describe('draft store（?file= 深链定向验证）', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    store.reset();
    sessionStorage.clear();
  });

  it('fetchAll 携带深链目标时选中指定文件', async () => {
    http.get.mockImplementation(url => {
      if (url.includes('editor-config')) return Promise.resolve({editor_available: false});
      if (url.includes('/files/')) return Promise.resolve([makeFile(7), makeFile(8)]);
      return Promise.resolve({id: 5, name: '手册'});
    });
    await store.fetchAll(5, 8);
    expect(store.selectedFileId).toBe(8);
    expect(store.deeplinkNotice).toBe('');
  });

  it('深链目标不存在：给出明确状态、不建会话、回落默认选中', async () => {
    http.get.mockImplementation(url => {
      if (url.includes('editor-config')) return Promise.resolve({editor_available: false});
      if (url.includes('/files/')) return Promise.resolve([makeFile(7)]);
      return Promise.resolve({id: 5, name: '手册'});
    });
    await store.fetchAll(5, 99);
    expect(store.selectedFileId).toBe(7);
    expect(store.deeplinkNotice).toContain('不存在或已移除');
    expect(store.hasAnySession).toBe(false);
  });

  it('深链目标无草稿：给出明确状态（验证目标同样拒绝）', async () => {
    http.get.mockImplementation(url => {
      if (url.includes('editor-config')) return Promise.resolve({editor_available: false});
      if (url.includes('/files/')) {
        return Promise.resolve([makeFile(7), makeFile(8, {draft: null})]);
      }
      return Promise.resolve({id: 5, name: '手册'});
    });
    await store.fetchAll(5, 8);
    expect(store.deeplinkNotice).toContain('还没有草稿');
    // 验证只针对深链目标：无草稿 → 拒绝，绝不静默改开文件 7 的会话
    await expect(store.verifyPassword('pw')).rejects.toContain('还没有草稿');
    expect(http.post).not.toHaveBeenCalled();
    expect(store.sessionKeyOf(7)).toBe('');
  });

  it('深链定向验证只为指定文件建立会话', async () => {
    store.id = 5;
    store.requestedFileId = 8;
    store.files = [makeFile(7), makeFile(8)];
    store.selectedFileId = 8;
    http.post.mockResolvedValue({
      session_key: 'sess-8', expires_at: '2099-01-01T00:00:00',
      revision: 8, file_name: '文件8.docx', base_version_id: null,
    });
    http.get.mockResolvedValue({editor_available: false});
    await store.verifyPassword('pw');
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/8/draft/session/', {password: 'pw'});
    expect(store.sessionKeyOf(8)).toBe('sess-8');
    expect(store.sessionKeyOf(7)).toBe('');
  });

  it('深链目标已不存在时验证拒绝且不请求', async () => {
    store.requestedFileId = 99;
    store.files = [makeFile(7)];
    await expect(store.verifyPassword('pw')).rejects.toBeTruthy();
    expect(http.post).not.toHaveBeenCalled();
  });
});
