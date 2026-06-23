/**
 * 7.1 状态机唯一入口 - 场景 1~7 状态流转
 * 覆盖《资料库并发上传与状态机修复方案.md》7.1 节核心流转场景。
 */
import { setupGatewayEnv, teardownGatewayEnv, flushMicrotasks } from './_gatewayEnv';

describe('7.1 场景1-7 状态流转', () => {
  let env;
  beforeEach(() => { env = setupGatewayEnv(); });
  afterEach(() => { teardownGatewayEnv(env.adapter, env.manager); });

  it('场景1 普通上传成功：waiting -> calculating -> uploading -> completed', () => {
    const { manager, itemRef, capturedUpdates } = env;
    itemRef.totalChunks = 1;
    const machine = manager.create('normal-success', { queueStore: env.mockQueueStore });

    expect(machine.transition('START')).toBe(true);
    expect(machine.getState()).toBe('calculating');

    expect(machine.transition('MD5_COMPLETE', { fileHash: 'abc123' })).toBe(true);
    expect(machine.getState()).toBe('uploading');

    expect(machine.transition('UPLOAD_COMPLETE')).toBe(true);
    expect(machine.getState()).toBe('completed');

    const completedUpdate = capturedUpdates.find(u => u.status === 'completed');
    expect(completedUpdate).toBeDefined();
    expect(completedUpdate.canAbort).toBe(false);
    expect(completedUpdate.percent).toBe(100);
  });

  it('场景2 分片上传成功：waiting -> calculating -> uploading -> merging -> completed', () => {
    const { manager, itemRef, capturedUpdates } = env;
    itemRef.totalChunks = 5;
    const machine = manager.create('chunked-success', { queueStore: env.mockQueueStore });

    expect(machine.transition('START')).toBe(true);
    expect(machine.transition('MD5_COMPLETE', { fileHash: 'abc123' })).toBe(true);
    expect(machine.transition('UPLOAD_COMPLETE')).toBe(true);
    expect(machine.getState()).toBe('merging');

    expect(machine.transition('MERGE_SUCCESS')).toBe(true);
    expect(machine.getState()).toBe('completed');

    expect(capturedUpdates.find(u => u.status === 'merging')).toBeDefined();
    expect(capturedUpdates.find(u => u.status === 'completed')).toBeDefined();
  });

  it('场景3 上传中暂停：uploading -> paused', () => {
    const { manager, itemRef, capturedUpdates } = env;
    itemRef.totalChunks = 1;
    const machine = manager.create('pause-during-upload', { queueStore: env.mockQueueStore });
    machine.transition('START');
    machine.transition('MD5_COMPLETE', { fileHash: 'abc123' });

    expect(machine.transition('PAUSE')).toBe(true);
    expect(machine.getState()).toBe('paused');

    const pausedUpdate = capturedUpdates.find(u => u.status === 'paused');
    expect(pausedUpdate).toBeDefined();
    expect(pausedUpdate.canAbort).toBe(false);
    expect(pausedUpdate.error).toBe('已暂停');
  });

  it('场景4a 暂停后恢复（有 fileHash）：paused -> uploading', () => {
    const { manager, itemRef } = env;
    itemRef.totalChunks = 5;
    itemRef.fileHash = 'abc123';
    const machine = manager.create('resume-with-hash', { queueStore: env.mockQueueStore });
    machine.transition('START');
    machine.transition('MD5_COMPLETE', { fileHash: 'abc123' });
    machine.transition('PAUSE');

    expect(machine.transition('RESUME')).toBe(true);
    expect(machine.getState()).toBe('uploading');
  });

  it('场景4b 暂停后恢复（无 fileHash 大文件）：paused -> waiting -> calculating', () => {
    const { manager, itemRef } = env;
    itemRef.totalChunks = 5;
    itemRef.fileSize = 100 * 1024 * 1024;
    itemRef.fileHash = null;
    const machine = manager.create('resume-recalc', { queueStore: env.mockQueueStore });
    machine.transition('START');
    machine.transition('PAUSE');

    // shouldResumeWaiting 守卫优先 → waiting
    expect(machine.transition('RESUME')).toBe(true);
    expect(machine.getState()).toBe('waiting');

    // waiting -> calculating（由调度器触发 START）
    expect(machine.transition('START')).toBe(true);
    expect(machine.getState()).toBe('calculating');
  });

  it('场景5 上传中取消：uploading -> cancelled', () => {
    const { manager, itemRef, capturedUpdates } = env;
    itemRef.totalChunks = 1;
    const machine = manager.create('cancel-during-upload', { queueStore: env.mockQueueStore });
    machine.transition('START');
    machine.transition('MD5_COMPLETE', { fileHash: 'abc123' });

    expect(machine.transition('CANCEL')).toBe(true);
    expect(machine.getState()).toBe('cancelled');

    const cancelledUpdate = capturedUpdates.find(u => u.status === 'cancelled');
    expect(cancelledUpdate).toBeDefined();
    expect(cancelledUpdate.canAbort).toBe(false);
  });

  it('场景6 合并中失败：merging -> error', () => {
    const { manager, itemRef, capturedUpdates } = env;
    itemRef.totalChunks = 5;
    const machine = manager.create('merge-fail', { queueStore: env.mockQueueStore });
    machine.transition('START');
    machine.transition('MD5_COMPLETE', { fileHash: 'abc123' });
    machine.transition('UPLOAD_COMPLETE');
    expect(machine.getState()).toBe('merging');

    expect(machine.transition('ERROR', { error: '合并失败' })).toBe(true);
    expect(machine.getState()).toBe('error');

    const errorUpdate = capturedUpdates.find(u => u.status === 'error');
    expect(errorUpdate).toBeDefined();
    expect(errorUpdate.canAbort).toBe(false);
  });

  it('场景7 失败后重试：error -> waiting -> calculating（异步 START）', async () => {
    const { manager, itemRef } = env;
    itemRef.totalChunks = 1;
    const machine = manager.create('retry-after-error', { queueStore: env.mockQueueStore });
    machine.transition('START');
    machine.transition('ERROR', { error: '模拟失败' });

    expect(machine.transition('RESUME')).toBe(true);
    expect(machine.getState()).toBe('waiting');

    await flushMicrotasks();
    expect(machine.getState()).toBe('calculating');
  });
});
