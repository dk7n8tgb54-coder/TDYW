/**
 * error 终态防回写回归测试（2026-08-16 修复）
 *
 * 背景：notifyListeners 经 queueMicrotask 异步派发（UploadStateMachine.js），
 * 同一同步块内连发两次状态流转时，晚到的监听回调携带过期 toState，而守卫读取的
 * 是实时 item.status。曾因 FINAL_STATES 不含 error，过期非终态事件把后端 FAILED
 * 回写成 UPLOADING（真实链路复现：调用序列 ["UPLOADING","FAILED"]）。
 *
 * 契约（stable_contract）：
 * 1. error 终态项不被过期非终态事件回写后端（仅同步 FAILED）
 * 2. cancelled 终态项同样拦截（对照组）
 * 3. error 终态项不接收过期 paused 事件（StateChangeHandler paused 守卫）
 *
 * 链路全部使用真实实现：UploadStateMachine → StateChangeHandler → StatusSynchronizer，
 * 仅 mock queueStore / transferStore（数据与传输层）。
 */
import UploadStateMachine from '../UploadStateMachine';
import { StateChangeHandler } from '../lifecycle/StateChangeHandler';
import StatusSynchronizer from '../sync/StatusSynchronizer';

function buildRealChain() {
  const item = {
    id: 'upload-1',
    status: 'waiting',
    transferId: 101,
    file: { name: 'a.txt' },
    fileSize: 100,
    isPausedByUser: false,
    isCancelledByUser: false,
  };
  const updateTransferStatus = jest.fn().mockResolvedValue({ success: true });
  const queueStore = {
    findUploadItemInCurrentTenant: jest.fn(() => item),
    updateUploadItem: jest.fn((id, data) => { if (id === item.id) Object.assign(item, data); }),
    bumpOperationVersion: jest.fn(),
    getOperationVersion: jest.fn(() => 1),
    isCurrentOperation: jest.fn(() => true),
  };
  const transferStore = { updateTransferStatus, fetchTransfers: jest.fn().mockResolvedValue([]) };
  const statusSynchronizer = new StatusSynchronizer({ queueStore, transferStore });
  const stateChangeHandler = new StateChangeHandler({ queueStore, transferStore, statusSynchronizer });
  const sm = new UploadStateMachine('upload-1', { queueStore });
  sm.addListener((from, to, event, payload, uploadId) => stateChangeHandler.handle(from, to, event, payload, uploadId));
  return { sm, item, updateTransferStatus, stateChangeHandler };
}

const flush = () => new Promise((r) => setTimeout(r, 0));

describe('error 终态防回写（真实链路）', () => {
  it('快速失败（START 后同步连发 ERROR）→ 仅同步 FAILED，无 UPLOADING 回写', async () => {
    const { sm, item, updateTransferStatus } = buildRealChain();

    expect(sm.transition('START', {})).toBe(true);                    // waiting → calculating，L1(calc) 入队
    expect(item.status).toBe('calculating');
    expect(sm.transition('ERROR', { error: '模拟快速失败' })).toBe(true); // calculating → error，L2(error) 入队
    expect(item.status).toBe('error');

    await flush(); // 微任务派发 L1/L2，mock HTTP 立即 resolve

    expect(updateTransferStatus.mock.calls.map((c) => c[1])).toEqual(['FAILED']);
    expect(item.status).toBe('error');
  });

  it('对照组：同样连发但落到 cancelled → 仅同步 CANCELED', async () => {
    const { sm, item, updateTransferStatus } = buildRealChain();

    expect(sm.transition('START', {})).toBe(true);
    expect(sm.transition('CANCEL', {})).toBe(true); // calculating → cancelled
    expect(item.status).toBe('cancelled');

    await flush();

    expect(updateTransferStatus.mock.calls.map((c) => c[1])).toEqual(['CANCELED']);
  });

  it('error 终态项不接收过期 paused 事件（无 PAUSED 回写）', async () => {
    const { item, updateTransferStatus, stateChangeHandler } = buildRealChain();

    // 模拟过期事件：item 已是 error，但晚到的监听回调仍携带 toState='paused'
    item.status = 'error';
    stateChangeHandler.handle('uploading', 'paused', 'PAUSE', {}, 'upload-1');

    await flush();

    expect(updateTransferStatus).not.toHaveBeenCalled();
  });
});
