/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
jest.mock('libs', () => ({
  http: {get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn()},
  history: {push: jest.fn()},
  hasPermission: jest.fn(() => true),
}));

const {http} = require('libs');
const detailStore = require('../detail/store').default;

describe('detail store（手册详情数据）', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    detailStore.reset();
  });

  it('fetchDetail 成功与失败分流', async () => {
    http.get.mockResolvedValueOnce({id: 7, name: 'SMS手册', my_roles: []});
    await detailStore.fetchDetail(7);
    expect(detailStore.manual.name).toBe('SMS手册');
    expect(detailStore.error).toBe('');
    http.get.mockRejectedValueOnce(new Error('e'));
    await detailStore.fetchDetail(8);
    expect(detailStore.error).toContain('无权限');
  });

  it('fetchVersions / fetchLogs 记录分页', async () => {
    http.get.mockImplementation(url => {
      if (url.includes('/versions/')) {
        return Promise.resolve({items: [{id: 1, version_no: 1}], total: 21});
      }
      if (url.includes('/operation-logs/')) {
        return Promise.resolve({items: [{id: 1, action: 'publish'}], total: 31});
      }
      return Promise.reject(new Error('unexpected ' + url));
    });
    await detailStore.fetchVersions(7, 2);
    expect(detailStore.versions.length).toBe(1);
    expect(detailStore.versionsPage).toBe(2);
    expect(detailStore.versionsTotal).toBe(21);
    await detailStore.fetchLogs(7, 3);
    expect(detailStore.logsPage).toBe(3);
    expect(detailStore.logsTotal).toBe(31);
  });

  it('fetchDetail 迟到响应不覆盖新手册（seq 守卫）', async () => {
    let resolveOld;
    http.get.mockImplementation(url => {
      if (url.includes('manuals/5/')) {
        return new Promise(resolve => {resolveOld = resolve;});
      }
      return Promise.resolve({id: 6, name: 'B', my_roles: []});
    });
    detailStore.fetchDetail(5);
    await detailStore.fetchDetail(6);
    expect(detailStore.manual.name).toBe('B');
    resolveOld({id: 5, name: 'A', my_roles: []});
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(detailStore.id).toBe(6);
    expect(detailStore.manual.name).toBe('B');
  });

  it('fetchVersions 跨手册迟到响应丢弃（seq 守卫）', async () => {
    let resolveOldVersions;
    http.get.mockImplementation(url => {
      if (url.includes('manuals/5/versions/')) {
        return new Promise(resolve => {resolveOldVersions = resolve;});
      }
      if (url.includes('manuals/5/')) return Promise.resolve({id: 5, name: 'A'});
      if (url.includes('manuals/6/versions/')) {
        return Promise.resolve({items: [{id: 2, version_no: 1}], total: 1});
      }
      return Promise.resolve({id: 6, name: 'B', my_roles: []});
    });
    const detailOld = detailStore.fetchDetail(5);
    const versionsOld = detailStore.fetchVersions(5, 1);
    await detailStore.fetchDetail(6);
    await detailStore.fetchVersions(6, 1);
    resolveOldVersions({items: [{id: 1, version_no: 9}], total: 99});
    await detailOld;
    await versionsOld;
    expect(detailStore.versions[0].id).toBe(2);
    expect(detailStore.versionsTotal).toBe(1);
  });

  it('fetchOriginalsOverview 一次拉取聚合清单并缓存 files', async () => {
    http.get.mockResolvedValueOnce({files: [
      {file_id: 11, name: '第一章', first_original: {id: 5}, history: [{id: 5}]},
      {file_id: 12, name: '第二章', first_original: null, history: []},
    ]});
    await detailStore.fetchOriginalsOverview(7);
    expect(http.get).toHaveBeenCalledWith('/api/institution/manuals/7/originals-overview/');
    expect(detailStore.originalsOverview).toHaveLength(2);
    expect(detailStore.originalsOverview[0].file_id).toBe(11);
    expect(detailStore.originalsOverviewError).toBe('');
    expect(detailStore.isFetchingOriginalsOverview).toBe(false);
  });

  it('fetchOriginalsOverview 失败置错误态可重试（不以空列表冒充成功）', async () => {
    http.get.mockRejectedValueOnce(new Error('network'));
    await detailStore.fetchOriginalsOverview(7);
    expect(detailStore.originalsOverview).toEqual([]);
    expect(detailStore.originalsOverviewError).toContain('加载失败');
    expect(detailStore.isFetchingOriginalsOverview).toBe(false);
  });

  it('同手册刷新（OriginalsTab.refresh 先列表后详情）不孤儿化 loading', async () => {
    http.get.mockImplementation(url => {
      if (url.includes('/originals-overview/')) {
        return Promise.resolve({files: [{file_id: 1, name: '甲'}]});
      }
      return Promise.resolve({id: 7, name: 'X', my_roles: ['edit']});
    });
    await detailStore.fetchDetail(7);
    await Promise.all([
      detailStore.fetchOriginalsOverview(7),
      detailStore.fetchDetail(7),
    ]);
    expect(detailStore.isFetchingOriginalsOverview).toBe(false);
    expect(detailStore.isFetching).toBe(false);
    expect(detailStore.originalsOverview.length).toBe(1);
  });
});

describe('detail store（文件清单与重置）', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    detailStore.reset();
  });

  it('fetchFiles 成功缓存清单并复位 loading', async () => {
    http.get.mockResolvedValueOnce([
      {id: 11, name: '第一章 总则', sort_order: 0, is_removed: false,
        originals_count: 2, draft: {revision: 3}, active_session: null},
    ]);
    await detailStore.fetchFiles(7);
    expect(detailStore.files.length).toBe(1);
    expect(detailStore.files[0].name).toBe('第一章 总则');
    expect(detailStore.isFetchingFiles).toBe(false);
  });

  it('fetchFiles 失败置空数组（拦截器已提示，不吞成功语义）', async () => {
    http.get.mockResolvedValueOnce([{id: 11, name: 'A'}]);
    await detailStore.fetchFiles(7);
    expect(detailStore.files.length).toBe(1);
    http.get.mockRejectedValueOnce(new Error('network'));
    await detailStore.fetchFiles(7);
    expect(detailStore.files).toEqual([]);
    expect(detailStore.isFetchingFiles).toBe(false);
  });

  it('reset 清理 files 与 isFetchingFiles', async () => {
    http.get.mockResolvedValueOnce([{id: 11, name: 'A'}]);
    await detailStore.fetchFiles(7);
    detailStore.reset();
    expect(detailStore.files).toEqual([]);
    expect(detailStore.isFetchingFiles).toBe(false);
    expect(detailStore.id).toBe(null);
  });

  it('fetchFiles 跨手册迟到响应丢弃（seq 守卫）', async () => {
    let resolveOldFiles;
    http.get.mockImplementation(url => {
      if (url.includes('manuals/5/files/')) {
        return new Promise(resolve => {resolveOldFiles = resolve;});
      }
      if (url.includes('manuals/6/files/')) {
        return Promise.resolve([{id: 2, name: 'B文件'}]);
      }
      return Promise.resolve({id: url.includes('manuals/5/') ? 5 : 6, name: 'X', my_roles: []});
    });
    await detailStore.fetchDetail(5);
    const oldFiles = detailStore.fetchFiles(5);
    await detailStore.fetchDetail(6);
    await detailStore.fetchFiles(6);
    resolveOldFiles([{id: 1, name: '旧文件'}]);
    await oldFiles;
    expect(detailStore.files.length).toBe(1);
    expect(detailStore.files[0].id).toBe(2);
  });

  it('reset 作废在途请求并复位 loading（卸载后旧响应不写入）', async () => {
    let resolveOverview;
    http.get.mockImplementation(url => {
      if (url.includes('/originals-overview/')) {
        return new Promise(resolve => {resolveOverview = resolve;});
      }
      return Promise.resolve({id: 7, name: 'X', my_roles: []});
    });
    await detailStore.fetchDetail(7);
    const overviewPending = detailStore.fetchOriginalsOverview(7);
    detailStore.reset();
    resolveOverview({files: [{file_id: 9, name: '旧'}]});
    await overviewPending;
    expect(detailStore.originalsOverview).toEqual([]);
    expect(detailStore.isFetchingOriginalsOverview).toBe(false);
    expect(detailStore.id).toBe(null);
  });
});

describe('detail store（开始修订与批量分工）', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    detailStore.reset();
    detailStore.id = 7;
    detailStore.files = [
      {id: 11, name: '甲.docx', assignment: {owner_id: null}},
      {id: 12, name: '乙.docx', assignment: {owner_id: null}},
    ];
  });

  it('startRevision 直连修订开始端点；确认修复时携带 confirm_repair', async () => {
    http.post.mockResolvedValueOnce({started: true, needs_repair: false});
    await detailStore.startRevision(11);
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/7/files/11/revision/start/', {});
    http.post.mockResolvedValueOnce({started: true, repaired: true,
      needs_repair: false});
    await detailStore.startRevision(11, true);
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/7/files/11/revision/start/',
      {confirm_repair: true});
  });

  it('startRevision 的 needs_repair 结果原样返回给调用方（前端明确提示）', async () => {
    const needsRepair = {needs_repair: true, reason: 'draft_corrupt',
      message: '将从当前生效版本快照恢复',
      draft_recovery: {source: 'current_version', version_no: 3}};
    http.post.mockResolvedValueOnce(needsRepair);
    const data = await detailStore.startRevision(12);
    expect(data).toBe(needsRepair);
  });

  it('batchAssignFiles 提交后用返回行就地更新清单（不整页重取）', async () => {
    http.post.mockResolvedValueOnce({
      count: 2,
      files: [
        {id: 11, name: '甲.docx',
          assignment: {owner_id: 55, owner_name: '戊', is_mine: false}},
        {id: 12, name: '乙.docx',
          assignment: {owner_id: 55, owner_name: '戊', is_mine: false}},
      ],
    });
    await detailStore.batchAssignFiles([11, 12], 55, '共同编制');
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/7/files/batch-assignment/',
      {file_ids: [11, 12], owner_id: 55, note: '共同编制'});
    expect(detailStore.files[0].assignment.owner_id).toBe(55);
    expect(detailStore.files[1].assignment.owner_name).toBe('戊');
  });

  it('batchAssignFiles 失败向上抛（拦截器已提示，清单不动）', async () => {
    http.post.mockRejectedValueOnce(new Error('所选文件不存在或不属于当前制度'));
    await expect(detailStore.batchAssignFiles([11], 55, ''))
      .rejects.toThrow('所选文件不存在或不属于当前制度');
    expect(detailStore.files[0].assignment.owner_id).toBeNull();
  });
});

describe('detail store（版本与发布状态）', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    detailStore.reset();
  });

  it('fetchVersions 失败置错误态并清空（不冒充成功），成功后复位', async () => {
    http.get.mockResolvedValueOnce({items: [{id: 1}], total: 1});
    await detailStore.fetchVersions(7, 1);
    expect(detailStore.versionsError).toBe('');
    http.get.mockRejectedValueOnce(new Error('network'));
    await detailStore.fetchVersions(7, 1);
    expect(detailStore.versionsError).toContain('版本清单加载失败');
    expect(detailStore.versions).toEqual([]);
    expect(detailStore.versionsTotal).toBe(0);
    expect(detailStore.isFetchingVersions).toBe(false);
    http.get.mockResolvedValueOnce({items: [{id: 2}], total: 1});
    await detailStore.fetchVersions(7, 1);
    expect(detailStore.versionsError).toBe('');
    expect(detailStore.versions.length).toBe(1);
  });

  it('fetchCurrentFiles 成功缓存完整快照，失败置错误态可重试', async () => {
    http.get.mockResolvedValueOnce({version_id: 9, version_no: 3, items: [{id: 21}]});
    await detailStore.fetchCurrentFiles(7, 9);
    expect(detailStore.currentFiles.version_no).toBe(3);
    expect(detailStore.currentFilesError).toBe('');
    expect(detailStore.isFetchingCurrentFiles).toBe(false);
    expect(http.get).toHaveBeenCalledWith('/api/institution/manuals/7/versions/9/files/');
    http.get.mockRejectedValueOnce(new Error('network'));
    await detailStore.fetchCurrentFiles(7, 9);
    expect(detailStore.currentFiles).toBe(null);
    expect(detailStore.currentFilesError).toContain('加载失败');
    expect(detailStore.isFetchingCurrentFiles).toBe(false);
  });

  it('clearCurrentFiles 清空当前生效文件区域', () => {
    detailStore.currentFiles = {version_no: 1, items: []};
    detailStore.currentFilesError = 'x';
    detailStore.clearCurrentFiles();
    expect(detailStore.currentFiles).toBe(null);
    expect(detailStore.currentFilesError).toBe('');
    expect(detailStore.isFetchingCurrentFiles).toBe(false);
  });

  it('fetchPublishPreview 缓存分组预检结果', async () => {
    http.get.mockResolvedValueOnce({
      current_version_no: 2, changed: [], added: [{file_id: 1}], blocked: [],
    });
    await detailStore.fetchPublishPreview(7);
    expect(detailStore.publishPreview.added.length).toBe(1);
    expect(detailStore.isFetchingPublishPreview).toBe(false);
    expect(http.get).toHaveBeenCalledWith('/api/institution/manuals/7/publish-preview/');
  });

  it('reset 清理版本错误态/当前生效文件/预检状态', async () => {
    http.get.mockResolvedValueOnce({version_no: 3, items: [{id: 21}]});
    await detailStore.fetchCurrentFiles(7, 9);
    await detailStore.fetchPublishPreview(7);
    detailStore.versionsError = '版本清单加载失败，请重试';
    detailStore.reset();
    expect(detailStore.currentFiles).toBe(null);
    expect(detailStore.currentFilesError).toBe('');
    expect(detailStore.versionsError).toBe('');
    expect(detailStore.publishPreview).toBe(null);
    expect(detailStore.isFetchingPublishPreview).toBe(false);
  });

  it('fetchCurrentFiles 跨手册迟到响应丢弃（seq 守卫）', async () => {
    let resolveOldFiles;
    http.get.mockImplementation(url => {
      if (url.includes('manuals/5/versions/')) {
        return new Promise(resolve => {resolveOldFiles = resolve;});
      }
      if (url.includes('manuals/6/versions/')) {
        return Promise.resolve({version_no: 4, items: [{id: 6}]});
      }
      return Promise.resolve({id: url.includes('manuals/5/') ? 5 : 6, name: 'X'});
    });
    await detailStore.fetchDetail(5);
    const oldFetch = detailStore.fetchCurrentFiles(5, 51);
    await detailStore.fetchDetail(6);
    await detailStore.fetchCurrentFiles(6, 61);
    resolveOldFiles({version_no: 1, items: [{id: 5}]});
    await oldFetch;
    expect(detailStore.currentFiles.items[0].id).toBe(6);
  });
});

function makeRecordsTab() {
  const mod = require('../detail/RecordsTab');
  const Comp = mod.default;
  // 取未连接 observer 的原始类构造实例，直接测 renderDetail 纯逻辑
  const inner = Comp.N || Comp;
  const target = (typeof inner === 'function' && inner.prototype && inner.prototype.renderDetail)
    ? inner : Comp;
  return new target();
}

describe('RecordsTab.renderDetail（时间线详情解析）', () => {
  it('解析修订/版本/变更说明等字段；空与坏 JSON 返回 "-"', () => {
    const tab = makeRecordsTab();
    expect(tab.renderDetail({detail: ''})).toBe('-');
    expect(tab.renderDetail({detail: 'not-json'})).toBe('-');
    expect(tab.renderDetail({detail: JSON.stringify({
      revision: 5, version_no: 2, change_note: '修订职责说明'})}))
      .toBe('修订 r5 · v2 · 修订职责说明');
    expect(tab.renderDetail({detail: JSON.stringify({
      file_name: '第一章.docx'})})).toBe('第一章.docx');
    expect(tab.renderDetail({detail: JSON.stringify({
      progress: 'submitted'})})).toBe('进度→submitted');
  });
});

describe('detail store（文件变更记录数据源）', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    detailStore.reset();
  });

  it('fetchFileVersionHistory 成功缓存完整载荷；失败置错误态可重试', async () => {
    http.get.mockResolvedValueOnce({file_id: 11, file_name: '管理规定.docx',
      items: [{version_no: 3, change_type: 'modified'}]});
    await detailStore.fetchFileVersionHistory(7, 11);
    expect(detailStore.fileVersion.file_name).toBe('管理规定.docx');
    expect(detailStore.fileVersion.items).toHaveLength(1);
    expect(detailStore.fileVersionError).toBe('');
    http.get.mockRejectedValueOnce(new Error('e'));
    await detailStore.fetchFileVersionHistory(7, 11);
    expect(detailStore.fileVersion).toBeNull();
    expect(detailStore.fileVersionError).toContain('加载失败');
    expect(detailStore.isFetchingFileVersion).toBe(false);
  });

  it('fetchFileLogs 携带 file_id 分页参数并记录分页', async () => {
    http.get.mockResolvedValueOnce({items: [{id: 1, action: 'save_draft'}], total: 9});
    await detailStore.fetchFileLogs(7, 11, 2);
    const [url, config] = http.get.mock.calls[0];
    expect(url).toBe('/api/institution/manuals/7/operation-logs/');
    expect(config.params).toMatchObject({page: 2, page_size: 15, file_id: 11});
    expect(detailStore.fileLogs).toHaveLength(1);
    expect(detailStore.fileLogsTotal).toBe(9);
    expect(detailStore.fileLogsPage).toBe(2);
    expect(detailStore.isFetchingFileLogs).toBe(false);
  });

  it('reset 清理文件变更记录状态', () => {
    detailStore.fileVersion = {items: []};
    detailStore.fileVersionError = 'x';
    detailStore.fileLogs = [{id: 1}];
    detailStore.fileLogsTotal = 1;
    detailStore.reset();
    expect(detailStore.fileVersion).toBeNull();
    expect(detailStore.fileVersionError).toBe('');
    expect(detailStore.fileLogs).toEqual([]);
    expect(detailStore.fileLogsTotal).toBe(0);
    expect(detailStore.fileLogsPage).toBe(1);
    expect(detailStore.isFetchingFileVersion).toBe(false);
    expect(detailStore.isFetchingFileLogs).toBe(false);
  });

  it('跨手册迟到响应丢弃（seq 守卫）', async () => {
    let resolveOld;
    http.get.mockImplementation(url => {
      if (url.includes('manuals/5/files/11/version-history/')) {
        return new Promise(resolve => {resolveOld = resolve;});
      }
      if (url.includes('/operation-logs/')) {
        return Promise.resolve({items: [], total: 0});
      }
      return Promise.resolve({id: url.includes('manuals/5/') ? 5 : 6, name: 'X'});
    });
    await detailStore.fetchDetail(5);
    const oldFetch = detailStore.fetchFileVersionHistory(5, 11);
    await detailStore.fetchDetail(6);
    resolveOld({file_id: 11, items: []});
    await oldFetch;
    expect(detailStore.fileVersion).toBeNull();
  });

  it('同手册快速切换文件：较早请求的迟到响应不覆盖当前文件发布记录', async () => {
    let resolveOld;
    http.get.mockImplementation(url => {
      if (url.includes('files/11/version-history/')) {
        return new Promise(resolve => {resolveOld = resolve;});
      }
      if (url.includes('files/12/version-history/')) {
        return Promise.resolve({file_id: 12, file_name: '乙.docx', items: []});
      }
      return Promise.resolve({items: [], total: 0});
    });
    const oldFetch = detailStore.fetchFileVersionHistory(7, 11);
    await detailStore.fetchFileVersionHistory(7, 12);
    expect(detailStore.fileVersion.file_id).toBe(12);
    // 较早请求（文件11）的迟到响应到达：不得覆盖文件12的记录
    resolveOld({file_id: 11, file_name: '甲.docx', items: []});
    await oldFetch;
    expect(detailStore.fileVersion.file_id).toBe(12);
    expect(detailStore.isFetchingFileVersion).toBe(false);
  });

  it('同文件快速翻页：较早请求的迟到响应不覆盖当前页操作记录', async () => {
    let resolveP1;
    http.get.mockImplementation((url, config) => {
      if (url.includes('/operation-logs/')) {
        if (config.params.file_id === 11 && config.params.page === 1) {
          return new Promise(resolve => {resolveP1 = resolve;});
        }
        return Promise.resolve({items: [{id: 2, action: 'file_rename'}], total: 30});
      }
      return Promise.reject(new Error('unexpected ' + url));
    });
    const p1 = detailStore.fetchFileLogs(7, 11, 1);
    await detailStore.fetchFileLogs(7, 11, 2);
    expect(detailStore.fileLogsPage).toBe(2);
    expect(detailStore.fileLogs[0].id).toBe(2);
    resolveP1({items: [{id: 1, action: 'save_draft'}], total: 30});
    await p1;
    expect(detailStore.fileLogsPage).toBe(2);
    expect(detailStore.fileLogs[0].id).toBe(2);
    expect(detailStore.isFetchingFileLogs).toBe(false);
  });
});

describe('detail store（文件变更记录状态清理）', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    detailStore.reset();
  });

  it('clearFileRecords 清空按文件记录（切换文件防残留）', () => {
    detailStore.fileVersion = {file_id: 11, items: []};
    detailStore.fileVersionError = 'x';
    detailStore.fileLogs = [{id: 1}];
    detailStore.fileLogsTotal = 1;
    detailStore.fileLogsPage = 2;
    detailStore.clearFileRecords();
    expect(detailStore.fileVersion).toBeNull();
    expect(detailStore.fileVersionError).toBe('');
    expect(detailStore.fileLogs).toEqual([]);
    expect(detailStore.fileLogsTotal).toBe(0);
    expect(detailStore.fileLogsPage).toBe(1);
  });
});

describe('detail store（草稿状态总览 draft-status）', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    detailStore.reset();
  });

  it('fetchDraftStatus 成功缓存服务端状态；失败清空旧状态并置错误态', async () => {
    http.get.mockResolvedValueOnce({
      has_current_version: true, current_version_no: 2,
      items: [{file_id: 11, status: 'modified'}],
      removed_items: [], summary: {modified: 1, consistent: false},
    });
    await detailStore.fetchDraftStatus(7);
    expect(http.get).toHaveBeenCalledWith('/api/institution/manuals/7/draft-status/');
    expect(detailStore.draftStatus.summary.modified).toBe(1);
    expect(detailStore.draftStatusError).toBe('');
    expect(detailStore.isFetchingDraftStatus).toBe(false);
    // 失败：旧状态清空 + 错误态（不得沿用旧数据冒充"无变化"）
    http.get.mockRejectedValueOnce(new Error('network'));
    await detailStore.fetchDraftStatus(7);
    expect(detailStore.draftStatus).toBeNull();
    expect(detailStore.draftStatusError).toContain('加载失败');
  });

  it('reset 清理草稿状态', () => {
    detailStore.draftStatus = {summary: {}};
    detailStore.draftStatusError = 'x';
    detailStore.reset();
    expect(detailStore.draftStatus).toBeNull();
    expect(detailStore.draftStatusError).toBe('');
    expect(detailStore.isFetchingDraftStatus).toBe(false);
  });
});

describe('detail store（生命周期统一刷新 refreshAfterLifecycle）', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    detailStore.reset();
  });

  function mockLifecycleResponses() {
    http.get.mockImplementation(url => {
      if (url.endsWith('/operation-logs/')) {
        return Promise.resolve({items: [], total: 0});
      }
      if (url.includes('/versions/')) {
        return Promise.resolve({items: [], total: 0});
      }
      return Promise.resolve({id: 7, name: '手册', my_roles: ['view', 'edit', 'publish'],
        current_version: {id: 9, version_no: 2}});
    });
  }

  it('发布/回退/废止后统一刷新：详情/版本/日志/草稿状态/当前生效文件', async () => {
    mockLifecycleResponses();
    await detailStore.refreshAfterLifecycle(7);
    const urls = http.get.mock.calls.map(args => args[0]);
    expect(urls.some(u => u.includes('/manuals/7/versions/'))).toBe(true);
    expect(urls.some(u => u.includes('/operation-logs/'))).toBe(true);
    // 工作区可见者（publish 角色）拉取整套草稿状态与当前生效快照
    expect(urls).toContain('/api/institution/manuals/7/draft-status/');
    expect(urls).toContain('/api/institution/manuals/7/versions/9/files/');
  });

  it('仅查看角色：统一刷新不请求 draft-status（后端亦拒绝）', async () => {
    http.get.mockImplementation(url => {
      if (url.endsWith('/operation-logs/')) {
        return Promise.resolve({items: [], total: 0});
      }
      if (url.includes('/versions/')) {
        return Promise.resolve({items: [], total: 0});
      }
      return Promise.resolve({id: 7, name: '手册', my_roles: ['view'],
        current_version: {id: 9, version_no: 2}});
    });
    const {hasPermission} = require('libs');
    hasPermission.mockImplementation(code =>
      code === 'institution.manual.view');
    await detailStore.refreshAfterLifecycle(7);
    const urls = http.get.mock.calls.map(args => args[0]);
    expect(urls).not.toContain('/api/institution/manuals/7/draft-status/');
    // 仍刷新版本与日志
    expect(urls.some(u => u.includes('/manuals/7/versions/'))).toBe(true);
    expect(urls.some(u => u.includes('/operation-logs/'))).toBe(true);
  });

  it('无生效版本（废止后）：统一刷新清空当前生效文件区，不请求快照', async () => {
    http.get.mockImplementation(url => {
      if (url.endsWith('/operation-logs/')) {
        return Promise.resolve({items: [], total: 0});
      }
      if (url.includes('/versions/')) {
        return Promise.resolve({items: [], total: 0});
      }
      return Promise.resolve({id: 7, name: '手册', my_roles: ['view', 'publish'],
        current_version: null});
    });
    await detailStore.refreshAfterLifecycle(7);
    const urls = http.get.mock.calls.map(args => args[0]);
    expect(urls.every(u => !u.includes('/versions/9/files/'))).toBe(true);
    expect(detailStore.currentFiles).toBeNull();
  });
});

describe('detail store（逐本账号授权与所有者，2026-10-31 授权模型）', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    detailStore.reset();
  });

  it('fetchAuthorizations 成功缓存清单；失败清空并置错误态（不以空清单冒充成功）', async () => {
    http.get.mockResolvedValueOnce({
      items: [{account_id: 11, account_name: '张三', can_view: true,
        can_edit: true, can_publish: false}],
    });
    await detailStore.fetchAuthorizations(7);
    expect(http.get).toHaveBeenCalledWith(
      '/api/institution/manuals/7/authorizations/');
    expect(detailStore.authorizations.items).toHaveLength(1);
    expect(detailStore.authorizationsError).toBe('');
    expect(detailStore.isFetchingAuthorizations).toBe(false);
    http.get.mockRejectedValueOnce(new Error('network'));
    await detailStore.fetchAuthorizations(7);
    expect(detailStore.authorizations).toBeNull();
    expect(detailStore.authorizationsError).toContain('加载失败');
  });

  it('saveAuthorizations PUT 全量 items（二轮改造：不再携带 editor_can_view_published），缓存响应并透传 revoked_sessions', async () => {
    const payload = [{account_id: 11, can_view: true, can_edit: true,
      can_publish: false}];
    http.put.mockResolvedValueOnce({items: payload, revoked_sessions: 2});
    const data = await detailStore.saveAuthorizations(7, payload);
    expect(http.put).toHaveBeenCalledWith(
      '/api/institution/manuals/7/authorizations/', {items: payload});
    expect(detailStore.authorizations.items).toEqual(payload);
    expect(detailStore.authorizations.editor_can_view_published).toBeUndefined();
    expect(data.revoked_sessions).toBe(2);
    // 失败向上抛（拦截器已提示），本地已缓存状态不动
    http.put.mockRejectedValueOnce(new Error('denied'));
    await expect(detailStore.saveAuthorizations(7, [])).rejects.toBeTruthy();
  });

  it('fetchAccountOptions/fetchOwnerCandidates：skipErrorNotification，失败置错误态由卡片内重试', async () => {
    http.get.mockImplementation((url, config) => {
      if (url.includes('/account-options/')) {
        expect(config).toMatchObject({skipErrorNotification: true});
        return Promise.resolve([{id: 11, name: '张三'}]);
      }
      if (url.includes('/owner-candidates/')) {
        expect(config).toMatchObject({skipErrorNotification: true});
        return Promise.reject('手册不存在或无权限访问');
      }
      return Promise.reject(new Error('unexpected ' + url));
    });
    await detailStore.fetchAccountOptions(7);
    await detailStore.fetchOwnerCandidates(7);
    expect(detailStore.accountOptions).toHaveLength(1);
    expect(detailStore.accountOptionsError).toBe('');
    expect(detailStore.ownerCandidates).toEqual([]);
    expect(detailStore.ownerCandidatesError).toContain('无权限');
  });

  it('setManualOwner POST owner/ 携带 account_id；响应含详情则就地更新 manual', async () => {
    http.post.mockResolvedValueOnce({
      id: 7, name: '手册', owner_id: 13, owner_name: '王五',
      is_owner: false, is_admin: true,
    });
    await detailStore.setManualOwner(7, 13);
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/7/owner/', {account_id: 13});
    expect(detailStore.manual.owner_name).toBe('王五');
  });

  it('setManualOwner 响应无详情时回退 fetchDetail 刷新', async () => {
    http.post.mockResolvedValueOnce({});
    http.get.mockResolvedValueOnce({
      id: 7, name: '手册', owner_id: 14, owner_name: '赵六',
      is_owner: false, is_admin: true,
    });
    await detailStore.setManualOwner(7, 14);
    expect(http.get).toHaveBeenCalledWith('/api/institution/manuals/7/');
    expect(detailStore.manual.owner_name).toBe('赵六');
  });

  it('reset 清理授权/账号候选/所有者候选状态', () => {
    detailStore.authorizations = {items: []};
    detailStore.authorizationsError = 'x';
    detailStore.isFetchingAuthorizations = true;
    detailStore.accountOptions = [{id: 1, name: 'a'}];
    detailStore.accountOptionsError = 'y';
    detailStore.ownerCandidates = [{id: 2, name: 'b'}];
    detailStore.ownerCandidatesError = 'z';
    detailStore.reset();
    expect(detailStore.authorizations).toBeNull();
    expect(detailStore.authorizationsError).toBe('');
    expect(detailStore.isFetchingAuthorizations).toBe(false);
    expect(detailStore.accountOptions).toEqual([]);
    expect(detailStore.accountOptionsError).toBe('');
    expect(detailStore.ownerCandidates).toEqual([]);
    expect(detailStore.ownerCandidatesError).toBe('');
  });
});
