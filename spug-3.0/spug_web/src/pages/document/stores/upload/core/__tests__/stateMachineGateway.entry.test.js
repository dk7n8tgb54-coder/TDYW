/**
 * 7.1 状态机唯一入口 - entry 钩子写生命周期字段 + 一致性兜底
 * 验证 status/canAbort/isPausedByUser/isCancelledByUser 由状态机 entry 统一写入。
 */
import { setupGatewayEnv, teardownGatewayEnv } from './_gatewayEnv';

describe('7.1 生命周期字段由状态机 entry 写入', () => {
  let env;
  beforeEach(() => { env = setupGatewayEnv(); });
  afterEach(() => { teardownGatewayEnv(env.adapter, env.manager); });

  it('onUploadingEntry 写入 status/canAbort 并重置 isPausedByUser/isCancelledByUser', () => {
    const { manager, itemRef, capturedUpdates } = env;
    itemRef.totalChunks = 1;
    // 预置脏数据（isCancelledByUser 必须为 false，否则 canStart 守卫失败）
    itemRef.isPausedByUser = true;
    itemRef.isCancelledByUser = false;
    const machine = manager.create('uploading-entry', { queueStore: env.mockQueueStore });
    machine.transition('START');
    machine.transition('MD5_COMPLETE', { fileHash: 'abc123' });

    const uploadingUpdate = capturedUpdates.find(u => u.status === 'uploading');
    expect(uploadingUpdate).toBeDefined();
    expect(uploadingUpdate.canAbort).toBe(true);
    // 7.1 收敛：标志重置由状态机 entry 负责，业务模块不再写
    expect(uploadingUpdate.isPausedByUser).toBe(false);
    expect(uploadingUpdate.isCancelledByUser).toBe(false);
  });

  it('onCompletedEntry 写入 status/canAbort/percent，业务模块不写 completed', () => {
    const { manager, itemRef, capturedUpdates } = env;
    itemRef.totalChunks = 1;
    const machine = manager.create('completed-entry', { queueStore: env.mockQueueStore });
    machine.transition('START');
    machine.transition('MD5_COMPLETE', { fileHash: 'abc123' });
    machine.transition('UPLOAD_COMPLETE');

    const completedUpdate = capturedUpdates.find(u => u.status === 'completed');
    expect(completedUpdate).toBeDefined();
    expect(completedUpdate.percent).toBe(100);
    expect(completedUpdate.canAbort).toBe(false);
  });

  it('assertStatusConsistency 兜底：entry 写入后 item.status 与状态机一致', () => {
    const { manager, itemRef } = env;
    itemRef.totalChunks = 1;
    const machine = manager.create('consistency-fix', { queueStore: env.mockQueueStore });

    machine.transition('START');
    expect(machine.getState()).toBe('calculating');
    // onCalculatingEntry 已通过 STATUS_CHANGE 写入 status:'calculating'
    expect(itemRef.status).toBe('calculating');
  });
});
