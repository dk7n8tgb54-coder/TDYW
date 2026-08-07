/**
 * 行为测试：离开页面时全局暂停上传任务 (pauseForPageLeave)
 * 通过 mock 依赖加载真实 UploadCoreStore，验证最终状态。
 */

const mockMessage = { info: jest.fn(), error: jest.fn(), success: jest.fn(), warning: jest.fn() };
jest.mock('antd', () => ({ message: mockMessage, Tag: 'span', Drawer: () => null, Badge: 'span', Tooltip: 'span' }));
jest.mock('libs/http', () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn(), delete: jest.fn(), put: jest.fn() } }));
jest.mock('libs/systemFolderContext', () => ({ PARTY_BUILDING_DOCUMENTS_CODE: 'pbd', appendSystemFolderParam: jest.fn(u=>u), withSystemFolderParams: jest.fn(p=>p), setSystemFolder: jest.fn(), shouldUseSystemFolder: jest.fn(()=>false), getActiveSystemFolderCode: jest.fn(()=>null) }));
jest.mock('../stores/navigation', () => ({ __esModule: true, default: { isPublic: false, currentFolderId: 1 } }));
jest.mock('../stores/upload/ui', () => ({ __esModule: true, default: { drawerVisible: false } }));
jest.mock('../stores', () => ({ __esModule: true, uploadCoreStore: {} }));

// Mock sub-stores
jest.mock('../stores/upload/core/queue', () => class Q { constructor(c){this.core=c;this.uploadQueue={};} get currentUploadQueue(){return this.uploadQueue[this.core?.getCurrentTenantId?.()||'']||[];} findUploadItem(id){for(const t of Object.keys(this.uploadQueue)){const q=this.uploadQueue[t]||[];const i=q.find(x=>x.id===id);if(i)return{item:i,tenantId:t};}return null;} findUploadItemInCurrentTenant(id){const q=this.uploadQueue[this.core?.getCurrentTenantId?.()||'']||[];return q.find(x=>x.id===id);} updateUploadItem(id,u){const f=this.findUploadItem(id);if(f)Object.assign(f.item,u);} bumpOperationVersion(id){const i=this.findUploadItemInCurrentTenant(id);if(i){i.operationVersion=(i.operationVersion||0)+1;return i.operationVersion;}return null;} getOperationVersion(id){const i=this.findUploadItemInCurrentTenant(id);return i?.operationVersion||0;} isCurrentOperation(id,v){const i=this.findUploadItemInCurrentTenant(id);return!!i&&i.operationVersion===v;} });
jest.mock('../stores/upload/core/fileUpload', () => class F {});
jest.mock('../stores/upload/core/chunkUpload', () => class C {});
jest.mock('../stores/upload/core/folderUpload', () => class Fo {});
jest.mock('../stores/upload/core/md5', () => class M {});
jest.mock('../stores/upload/core/transfer', () => class T { constructor(){this.batchPauseTransfers=jest.fn(()=>Promise.resolve());this.batchResumeTransfers=jest.fn(()=>Promise.resolve());this.fetchTransfers=jest.fn(()=>Promise.resolve([]));} });
jest.mock('../stores/upload/core/StateMachineManager', () => ({ StateMachineManager: class SMM { constructor(){this.machines=new Map();this._l=[];} register(id,m){this.machines.set(id,m);} get(id){return this.machines.get(id);} remove(id){this.machines.delete(id);} addGlobalListener(f){this._l.push(f);} countByStates(){return 0;} batchPause(){} batchResume(){} } }));
jest.mock('../stores/upload/core/UploadStateMachine', () => ({ UploadStateMachine: class SM { constructor(id,ctx){this.uploadId=id;this.context=ctx;this._state='waiting';} getState(){return this._state;} canTransition(){return true;} transition(e){const i=this.context?.item;if(e==='PAUSE'){this._state='paused';if(i){if(i.abortController){try{i.abortController.abort();}catch(_){}i.abortController=null;}if(i.abortToken){try{i.abortToken.cancel();}catch(_){}i.abortToken=null;}i.status='paused';i.error='已暂停';i.canAbort=false;i.isPausedByUser=true;}return true;}if(e==='START'){this._state='calculating';if(i){i.status='calculating';i.error=null;}return true;}if(e==='RESUME'){this._state='uploading';if(i){i.status='uploading';i.error=null;i.isPausedByUser=false;}return true;}return false;} } }));
jest.mock('../stores/upload/core/guards', () => ({}));
jest.mock('../stores/upload/core/coordinators', () => ({ UploadCoordinator: class UC { constructor(c){this.core=c;} startWaiting(){if(this.core?.isPaused)return;const t=this.core?.getCurrentTenantId?.()||'';const q=this.core?.queueStore?.uploadQueue?.[t]||[];for(const i of q){if(i.status==='waiting'&&!i.isPausedByUser&&i.file){i.status='calculating';}}} processPending(){this.startWaiting();} ensureStateMachine(item){let m=this.core?.stateMachineManager?.get(item.id);if(m)return m;const{UploadStateMachine}=require('../stores/upload/core/UploadStateMachine');m=new UploadStateMachine(item.id,{queueStore:this.core.queueStore,item});this.core?.stateMachineManager?.register(item.id,m);return m;} }, RecoveryCoordinator: class RC { schedule(){} }, FileUploadCoordinator: class FC {}, ChunkUploadCoordinator: class CC {} }));
jest.mock('../stores/upload/core/lifecycle', () => ({ StateChangeHandler: class SCH { constructor(c){this.core=c;} handle(){} }, UploadLifecycle: class UL { constructor(){} init(){} }, NetworkLifecycle: class NL { constructor(){} init(){} } }));
jest.mock('../stores/upload/core/controls', () => ({ DebounceController: class DC { constructor(c){this.core=c;} pauseAll(){this.core.isPaused=true;} resumeAll(){this.core.isPaused=false;const t=this.core.getCurrentTenantId();const q=this.core.queueStore.uploadQueue[t]||[];for(const i of q){if(i.status==='paused'){let m=this.core.stateMachineManager.get(i.id);if(!m)m=this.core.uploadCoordinator?.ensureStateMachine?.(i);if(m)this.core.queueStore.updateUploadItem(i.id,{status:'waiting',error:null,canAbort:false,isPausedByUser:false});}}this.core.uploadCoordinator?.startWaiting();} wrapItemOperation(id,fn){return fn();} }, ItemOperationController: class IOC { constructor(c){this.core=c;} pauseItem(id){const m=this.core.stateMachineManager?.get(id);if(!m)return;if(m.canTransition('PAUSE'))m.transition('PAUSE');} resumeItem(id){const item=this.core.queueStore.findUploadItemInCurrentTenant(id);if(!item)return;let m=this.core.stateMachineManager?.get(id);if(!m){m=this.core.uploadCoordinator?.ensureStateMachine?.(item);if(item.status==='paused'||item.isPausedByUser)this.core.queueStore.updateUploadItem(id,{status:'waiting',error:null,canAbort:false,isPausedByUser:false});}if(m){const s=m.getState();m.transition(s==='waiting'?'START':'RESUME');}} cancelItem(){} removeItem(){} abortUpload(){} }, QueueOperationController: class QOC { removeAll(){} } }));
jest.mock('../stores/upload/core/sync', () => ({ StatusSynchronizer: class SS {} }));
jest.mock('../stores/upload/core/captureUploadTargetContext', () => ({ captureUploadTargetContext: jest.fn(() => ({})) }));

const UploadCoreStore = require('../stores/upload/core/index').default;
const { PAUSEABLE_STATUSES, TERMINAL_STATUSES, UPLOAD_STATUS } = require('../stores/upload/core/upload-core-constants');

function mkAbortCtrl() { return { aborted: false, abort() { this.aborted = true; } }; }
function mkStore(items, tenantId) {
  const s = new UploadCoreStore({ navigationStore: { isPublic: false } });
  const tid = tenantId || s.getCurrentTenantId();
  s.queueStore.uploadQueue = {};
  s.queueStore.uploadQueue[tid] = (items || []).map(i => ({ operationVersion: 0, isPausedByUser: false, isCancelledByUser: false, canAbort: false, error: null, progress: 0, ...i }));
  return s;
}
function mkSM(store, item, state) {
  const { UploadStateMachine } = require('../stores/upload/core/UploadStateMachine');
  const m = new UploadStateMachine(item.id, { queueStore: store.queueStore, item });
  m._state = state;
  store.stateMachineManager.register(item.id, m);
  return m;
}
function queue(store) { return store.queueStore.uploadQueue[store.getCurrentTenantId()]; }

describe('pauseForPageLeave() - 离开页面全局暂停', () => {
  beforeEach(() => jest.clearAllMocks());

  test('同步设置 isPaused=true', () => {
    const s = mkStore([{ id: 'a', status: 'uploading', file: {}, folderId: 1 }]);
    expect(s.isPaused).toBe(false);
    s.pauseForPageLeave();
    expect(s.isPaused).toBe(true);
  });

  test('uploading/calculating/waiting 都变为 paused', () => {
    const s = mkStore([
      { id: '1', status: 'uploading', file: {}, folderId: 1, abortController: mkAbortCtrl() },
      { id: '2', status: 'calculating', file: {}, folderId: 1 },
      { id: '3', status: 'waiting', file: {}, folderId: 1 },
    ]);
    mkSM(s, queue(s)[0], 'uploading');
    mkSM(s, queue(s)[1], 'calculating');
    // item 3 has no state machine (lazy waiting)
    s.pauseForPageLeave();
    expect(queue(s)[0].status).toBe('paused');
    expect(queue(s)[1].status).toBe('paused');
    expect(queue(s)[2].status).toBe('paused');
  });

  test('AbortController 被中止', () => {
    const ac = mkAbortCtrl();
    const s = mkStore([{ id: 'x', status: 'uploading', file: {}, folderId: 1, abortController: ac }]);
    mkSM(s, queue(s)[0], 'uploading');
    s.pauseForPageLeave();
    expect(ac.aborted).toBe(true);
  });

  test('暂停后状态是 paused 而非 error', () => {
    const s = mkStore([
      { id: 'e1', status: 'uploading', file: {}, folderId: 1, abortController: mkAbortCtrl() },
      { id: 'e2', status: 'waiting', file: {}, folderId: 1 },
    ]);
    mkSM(s, queue(s)[0], 'uploading');
    s.pauseForPageLeave();
    expect(queue(s)[0].status).toBe('paused');
    expect(queue(s)[0].error).toBe('已暂停');
    expect(queue(s)[1].status).toBe('paused');
    expect(queue(s)[1].error).toBe('已暂停');
  });

  test('暂停后 processPending 不启动新任务', () => {
    const s = mkStore([{ id: 'p', status: 'waiting', file: {}, folderId: 1 }]);
    s.pauseForPageLeave();
    s.uploadCoordinator.processPending();
    expect(queue(s)[0].status).toBe('paused');
  });

  test('merging 任务不被暂停', () => {
    const s = mkStore([
      { id: 'm', status: 'merging', file: {}, folderId: 1, transferId: 't' },
      { id: 'u', status: 'uploading', file: {}, folderId: 1, abortController: mkAbortCtrl() },
    ]);
    mkSM(s, queue(s)[1], 'uploading');
    s.pauseForPageLeave();
    expect(queue(s)[0].status).toBe('merging');
    expect(queue(s)[1].status).toBe('paused');
  });

  test('终态任务不被修改', () => {
    const s = mkStore([
      { id: 'c', status: 'completed', file: {}, folderId: 1 },
      { id: 'e', status: 'error', file: {}, folderId: 1, error: '网络错误' },
      { id: 'x', status: 'cancelled', file: {}, folderId: 1 },
    ]);
    s.pauseForPageLeave();
    expect(queue(s)[0].status).toBe('completed');
    expect(queue(s)[1].status).toBe('error');
    expect(queue(s)[1].error).toBe('网络错误');
    expect(queue(s)[2].status).toBe('cancelled');
  });

  test('不弹通知', () => {
    const s = mkStore([{ id: 'n', status: 'uploading', file: {}, folderId: 1, abortController: mkAbortCtrl() }]);
    mkSM(s, queue(s)[0], 'uploading');
    s.pauseForPageLeave();
    expect(mockMessage.success).not.toHaveBeenCalled();
    expect(mockMessage.warning).not.toHaveBeenCalled();
    expect(mockMessage.error).not.toHaveBeenCalled();
  });

  test('无状态机 paused 任务单项 resumeItem 恢复成功', () => {
    const s = mkStore([{ id: 'r', status: 'waiting', file: { size: 1 }, folderId: 1 }]);
    s.pauseForPageLeave();
    expect(queue(s)[0].status).toBe('paused');
    expect(queue(s)[0].isPausedByUser).toBe(true);
    s.itemOperationController.resumeItem('r');
    expect(queue(s)[0].status).not.toBe('paused');
    expect(queue(s)[0].isPausedByUser).toBe(false);
  });

  test('resumeAll 恢复所有 paused 并清除 isPaused', () => {
    const s = mkStore([
      { id: 'ra1', status: 'uploading', file: {}, folderId: 1, abortController: mkAbortCtrl() },
      { id: 'ra2', status: 'waiting', file: {}, folderId: 1 },
    ]);
    mkSM(s, queue(s)[0], 'uploading');
    s.pauseForPageLeave();
    expect(s.isPaused).toBe(true);
    s.resumeAll();
    expect(s.isPaused).toBe(false);
    for (const i of queue(s)) expect(i.status).not.toBe('paused');
  });

  test('大文件保留分片信息', () => {
    const s = mkStore([{ id: 'bf', status: 'uploading', file: { size: 10485760 }, folderId: 1, chunkCount: 10, uploadedChunks: [0,1,2,3,4], currentChunk: 5, abortController: mkAbortCtrl() }]);
    mkSM(s, queue(s)[0], 'uploading');
    s.pauseForPageLeave();
    expect(queue(s)[0].chunkCount).toBe(10);
    expect(queue(s)[0].uploadedChunks).toEqual([0,1,2,3,4]);
  });

  test('党建任务保留 systemFolderCode', () => {
    const s = mkStore([{ id: 'pb', status: 'uploading', file: {}, folderId: 5, systemFolderCode: 'party_building_documents', abortController: mkAbortCtrl() }]);
    mkSM(s, queue(s)[0], 'uploading');
    s.pauseForPageLeave();
    expect(queue(s)[0].systemFolderCode).toBe('party_building_documents');
    expect(queue(s)[0].folderId).toBe(5);
  });

  test('多租户队列全部暂停', () => {
    const s = new UploadCoreStore({ navigationStore: { isPublic: false } });
    s.queueStore.uploadQueue = {
      'admin': [{ id: 't1', status: 'waiting', file: {}, folderId: 1, operationVersion: 0, isPausedByUser: false }],
      'public': [{ id: 't2', status: 'uploading', file: {}, folderId: 2, operationVersion: 0, isPausedByUser: false, abortController: mkAbortCtrl() }],
    };
    const ac = s.queueStore.uploadQueue['public'][0].abortController;
    mkSM(s, s.queueStore.uploadQueue['public'][0], 'uploading');
    s.pauseForPageLeave();
    expect(s.queueStore.uploadQueue['admin'][0].status).toBe('paused');
    expect(s.queueStore.uploadQueue['admin'][0].isPausedByUser).toBe(true);
    expect(s.queueStore.uploadQueue['public'][0].status).toBe('paused');
    expect(ac.aborted).toBe(true);
  });

  test('多次调用保持幂等', () => {
    const s = mkStore([{ id: 'i', status: 'uploading', file: {}, folderId: 1, abortController: mkAbortCtrl() }]);
    mkSM(s, queue(s)[0], 'uploading');
    s.pauseForPageLeave();
    const v1 = queue(s)[0].operationVersion;
    s.pauseForPageLeave(); // second call
    const v2 = queue(s)[0].operationVersion;
    // Already paused, no re-abort or double-bump
    expect(v2).toBe(v1);
    expect(queue(s)[0].status).toBe('paused');
  });

  test('无 transferId 的 waiting 任务不调用后端接口', () => {
    const s = mkStore([{ id: 'nt', status: 'waiting', file: {}, folderId: 1 }]);
    s.transferStore.batchPauseTransfers.mockClear();
    s.pauseForPageLeave();
    expect(s.transferStore.batchPauseTransfers).not.toHaveBeenCalled();
  });

  test('有 transferId 的任务调用后端批量暂停', () => {
    const s = mkStore([{ id: 'wt', status: 'uploading', file: {}, folderId: 1, transferId: 'tid-1', abortController: mkAbortCtrl() }]);
    mkSM(s, queue(s)[0], 'uploading');
    s.transferStore.batchPauseTransfers.mockClear();
    s.pauseForPageLeave();
    expect(s.transferStore.batchPauseTransfers).toHaveBeenCalledWith(['tid-1']);
  });

  test('operationVersion 递增使旧回调失效', () => {
    const s = mkStore([{ id: 'ov', status: 'waiting', file: {}, folderId: 1 }]);
    const oldVersion = queue(s)[0].operationVersion;
    s.pauseForPageLeave();
    expect(queue(s)[0].operationVersion).toBe(oldVersion + 1);
    // isCurrentOperation should return false for old version
    expect(s.queueStore.isCurrentOperation('ov', oldVersion)).toBe(false);
  });

  test('file/folderId/isPublic 不丢失', () => {
    const s = mkStore([{ id: 'keep', status: 'waiting', file: { name: 'test.txt' }, folderId: 42, isPublic: true, tenantId: 'pub' }]);
    s.pauseForPageLeave();
    const item = queue(s)[0];
    expect(item.file).toEqual({ name: 'test.txt' });
    expect(item.folderId).toBe(42);
    expect(item.isPublic).toBe(true);
    expect(item.tenantId).toBe('pub');
  });
});
