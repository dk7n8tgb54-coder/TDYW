/**
 * 7.3 异步操作加版本号 - 旧异步回调不覆盖新状态
 *
 * 验证 operationVersion 机制在以下场景下的正确性：
 * 1. 上传中取消：旧上传成功回调晚到，不得变 completed
 * 2. 上传中暂停：旧分片成功回调晚到，不得进入 merging
 * 3. 暂停后恢复：旧版本回调不得影响新版本上传
 * 4. 失败后重试：上一轮 ERROR 回调晚到，不得覆盖新一轮状态
 * 5. 合并轮询旧 task 返回 success，不得覆盖新 task
 * 6. MD5 旧 worker 返回，不得写入新任务 fileHash
 * 7. CANCEL 后任何旧回调都不能改变 cancelled 状态
 * 8. 版本一致时，正常上传、合并、完成流程不受影响
 */
import { setupGatewayEnv, teardownGatewayEnv, flushMicrotasks } from './_gatewayEnv';

describe('7.3 异步操作加版本号', () => {
  let env;
  beforeEach(() => { env = setupGatewayEnv(); });
  afterEach(() => { teardownGatewayEnv(env.adapter, env.manager); });

  // ============ 辅助：将任务推进到 uploading ============
  function advanceToUploading(machine) {
    machine.transition('START');
    machine.transition('MD5_COMPLETE', { fileHash: 'abc123' });
    return machine.getState();
  }

  // ============ 场景 1：上传中取消，旧 UPLOAD_COMPLETE 不得变 completed ============
  describe('场景1 取消后旧上传成功回调', () => {
    it('1a START 递增版本号', () => {
      const { manager, mockQueueStore } = env;
      const machine = manager.create('opv-start', { queueStore: mockQueueStore });
      const v0 = mockQueueStore.getOperationVersion('opv-start');
      machine.transition('START');
      const v1 = mockQueueStore.getOperationVersion('opv-start');
      expect(v1).toBeGreaterThan(v0);
    });

    it('1b CANCEL 后旧 UPLOAD_COMPLETE 带过期版本被拒绝', () => {
      const { manager, mockQueueStore, itemRef } = env;
      itemRef.totalChunks = 1;
      const machine = manager.create('opv-cancel', { queueStore: mockQueueStore });
      advanceToUploading(machine);

      // 捕获当前版本（上传开始时的版本）
      const uploadVersion = mockQueueStore.getOperationVersion('opv-cancel');

      // 用户取消 → 版本递增
      machine.transition('CANCEL');
      expect(machine.getState()).toBe('cancelled');

      // 旧上传成功回调晚到，携带旧版本号 → 被拒绝
      const result = machine.transition('UPLOAD_COMPLETE', { operationVersion: uploadVersion });
      expect(result).toBe(false);
      expect(machine.getState()).toBe('cancelled');
    });

    it('1c CANCEL 后旧 UPLOAD_COMPLETE 无版本号也被终态拒绝', () => {
      const { manager, itemRef } = env;
      itemRef.totalChunks = 1;
      const machine = manager.create('opv-cancel2', { queueStore: env.mockQueueStore });
      advanceToUploading(machine);
      machine.transition('CANCEL');
      expect(machine.getState()).toBe('cancelled');

      // 无版本号的旧回调：cancelled 是终态，无匹配转换规则，transition 返回 false
      expect(machine.transition('UPLOAD_COMPLETE')).toBe(false);
      expect(machine.getState()).toBe('cancelled');
    });
  });

  // ============ 场景 2：上传中暂停，旧回调不得推进到 merging ============
  describe('场景2 暂停后旧回调', () => {
    it('2a PAUSE 递增版本号', () => {
      const { manager, mockQueueStore } = env;
      const machine = manager.create('opv-pause', { queueStore: mockQueueStore });
      advanceToUploading(machine);
      const vBefore = mockQueueStore.getOperationVersion('opv-pause');
      machine.transition('PAUSE');
      const vAfter = mockQueueStore.getOperationVersion('opv-pause');
      expect(vAfter).toBeGreaterThan(vBefore);
    });

    it('2b PAUSE 后旧 UPLOAD_COMPLETE 带过期版本被拒绝', () => {
      const { manager, mockQueueStore, itemRef } = env;
      itemRef.totalChunks = 1;
      const machine = manager.create('opv-pause2', { queueStore: mockQueueStore });
      advanceToUploading(machine);

      const uploadVersion = mockQueueStore.getOperationVersion('opv-pause2');

      machine.transition('PAUSE');
      expect(machine.getState()).toBe('paused');

      // 旧分片上传成功回调晚到 → 被拒绝，不进入 merging
      expect(machine.transition('UPLOAD_COMPLETE', { operationVersion: uploadVersion })).toBe(false);
      expect(machine.getState()).toBe('paused');
    });
  });

  // ============ 场景 3：暂停后恢复，旧版本回调不得影响新版本 ============
  describe('场景3 恢复后旧版本回调', () => {
    it('3a RESUME 递增版本号，旧版本回调被拒绝', () => {
      const { manager, mockQueueStore, itemRef } = env;
      itemRef.totalChunks = 1;
      const machine = manager.create('opv-resume', { queueStore: mockQueueStore });
      advanceToUploading(machine);

      const v1 = mockQueueStore.getOperationVersion('opv-resume');
      machine.transition('PAUSE');
      const v2 = mockQueueStore.getOperationVersion('opv-resume');

      // 恢复（paused → uploading，走 shouldResumeUpload 守卫）
      itemRef.fileHash = 'abc123';
      itemRef.currentChunk = 0;
      const chunkCount = Math.ceil(itemRef.fileSize / (32 * 1024 * 1024));
      // 确保未传完，走 resume → uploading
      machine.transition('RESUME');
      const v3 = mockQueueStore.getOperationVersion('opv-resume');

      expect(v2).toBeGreaterThan(v1);
      expect(v3).toBeGreaterThan(v2);

      // 旧版本（暂停前）的回调被拒绝
      expect(machine.transition('UPLOAD_COMPLETE', { operationVersion: v1 })).toBe(false);
      // 新版本的回调可以通过
      expect(machine.transition('UPLOAD_COMPLETE', { operationVersion: v3 })).toBe(true);
      expect(machine.getState()).toBe('completed');
    });
  });

  // ============ 场景 4：失败后重试，旧 ERROR 回调不得覆盖新状态 ============
  describe('场景4 重试后旧ERROR回调', () => {
    it('4a error → RESUME(重试) 递增版本，旧版本 ERROR 被拒绝', async () => {
      const { manager, mockQueueStore, itemRef } = env;
      itemRef.totalChunks = 1;
      const machine = manager.create('opv-retry', { queueStore: mockQueueStore });
      advanceToUploading(machine);

      const v1 = mockQueueStore.getOperationVersion('opv-retry');

      // 第一轮失败
      machine.transition('ERROR', { error: '第一轮失败', operationVersion: v1 });
      expect(machine.getState()).toBe('error');

      // 用户重试：error → RESUME → waiting → (microtask) START
      machine.transition('RESUME');
      await flushMicrotasks(); // 触发 onRetryAction 中的 scheduleStart

      // 此时状态应为 waiting 或 calculating（START 已在 microtask 中触发）
      const stateAfterRetry = machine.getState();
      expect(['waiting', 'calculating']).toContain(stateAfterRetry);

      const v2 = mockQueueStore.getOperationVersion('opv-retry');
      expect(v2).toBeGreaterThan(v1);

      // 旧版本的 ERROR 回调晚到 → 被拒绝
      expect(machine.transition('ERROR', { error: '晚到的旧错误', operationVersion: v1 })).toBe(false);
    });
  });

  // ============ 场景 5：合并轮询旧 task 不得覆盖新 task ============
  describe('场景5 合并轮询版本保护', () => {
    it('5a merging 状态下旧 MERGE_SUCCESS 带过期版本被拒绝', () => {
      const { manager, mockQueueStore, itemRef } = env;
      // 大文件：需要分片上传 → merging
      itemRef.totalChunks = 5;
      itemRef.fileSize = 100 * 1024 * 1024; // 100MB
      const machine = manager.create('opv-merge', { queueStore: mockQueueStore });
      advanceToUploading(machine);

      // 进入 merging
      const uploadVersion = mockQueueStore.getOperationVersion('opv-merge');
      machine.transition('UPLOAD_COMPLETE', { operationVersion: uploadVersion });
      expect(machine.getState()).toBe('merging');

      // 假设用户在此期间重试（虽然 merging 不允许 PAUSE/CANCEL，
      // 但如果状态机被外部重建，版本会递增）
      // 模拟：直接递增版本
      mockQueueStore.bumpOperationVersion('opv-merge');
      const newVersion = mockQueueStore.getOperationVersion('opv-merge');

      // 旧轮询的 MERGE_SUCCESS 带旧版本 → 被拒绝
      expect(machine.transition('MERGE_SUCCESS', { operationVersion: uploadVersion })).toBe(false);
      expect(machine.getState()).toBe('merging');

      // 新版本的 MERGE_SUCCESS 可以通过
      expect(machine.transition('MERGE_SUCCESS', { operationVersion: newVersion })).toBe(true);
      expect(machine.getState()).toBe('completed');
    });
  });

  // ============ 场景 6：MD5 旧 worker 返回不得写入新任务 ============
  describe('场景6 MD5版本保护', () => {
    it('6a calculating 状态下旧 MD5_COMPLETE 带过期版本被拒绝', () => {
      const { manager, mockQueueStore, itemRef } = env;
      // 设置大文件 + forceRecalculateMD5，使 RESUME 回到 calculating 而非 uploading
      itemRef.fileSize = 100 * 1024 * 1024; // 100MB
      itemRef.forceRecalculateMD5 = true;
      const machine = manager.create('opv-md5', { queueStore: mockQueueStore });
      machine.transition('START');
      expect(machine.getState()).toBe('calculating');

      const md5Version = mockQueueStore.getOperationVersion('opv-md5');

      // 模拟：用户在 MD5 计算期间暂停 → 版本递增
      machine.transition('PAUSE');
      const vAfterPause = mockQueueStore.getOperationVersion('opv-md5');
      expect(vAfterPause).toBeGreaterThan(md5Version);

      // 恢复到 calculating（forceRecalculateMD5 使 shouldRecalculateMD5 返回 true）
      machine.transition('RESUME');
      expect(machine.getState()).toBe('calculating');
      const newVersion = mockQueueStore.getOperationVersion('opv-md5');

      // 旧 MD5 worker 回调带旧版本 → 被拒绝
      expect(machine.transition('MD5_COMPLETE', { fileHash: 'old-hash', operationVersion: md5Version })).toBe(false);

      // 新版本的 MD5_COMPLETE 可以通过
      expect(machine.transition('MD5_COMPLETE', { fileHash: 'new-hash', operationVersion: newVersion })).toBe(true);
      expect(machine.getState()).toBe('uploading');
    });
  });

  // ============ 场景 7：CANCEL 后任何旧回调都不能改变 cancelled ============
  describe('场景7 CANCEL 终态保护', () => {
    it('7a cancelled 后所有带过期版本的事件均被拒绝', () => {
      const { manager, mockQueueStore, itemRef } = env;
      itemRef.totalChunks = 1;
      const machine = manager.create('opv-cancel-final', { queueStore: mockQueueStore });
      advanceToUploading(machine);

      const oldVersion = mockQueueStore.getOperationVersion('opv-cancel-final');
      machine.transition('CANCEL');

      // 所有旧回调均被拒绝
      expect(machine.transition('UPLOAD_COMPLETE', { operationVersion: oldVersion })).toBe(false);
      expect(machine.transition('ERROR', { error: '旧错误', operationVersion: oldVersion })).toBe(false);
      expect(machine.transition('MERGE_SUCCESS', { operationVersion: oldVersion })).toBe(false);
      expect(machine.transition('MD5_COMPLETE', { fileHash: 'x', operationVersion: oldVersion })).toBe(false);
      expect(machine.getState()).toBe('cancelled');
    });
  });

  // ============ 场景 8：版本一致时正常流程不受影响 ============
  describe('场景8 版本一致时正常流程', () => {
    it('8a 正常小文件上传流程不受影响', () => {
      const { manager, mockQueueStore, itemRef } = env;
      itemRef.totalChunks = 1; // 普通上传
      const machine = manager.create('opv-normal', { queueStore: mockQueueStore });

      machine.transition('START');
      const v1 = mockQueueStore.getOperationVersion('opv-normal');

      // MD5 完成（小文件跳过，但状态机仍走 MD5_COMPLETE）
      expect(machine.transition('MD5_COMPLETE', { fileHash: '', operationVersion: v1 })).toBe(true);
      expect(machine.getState()).toBe('uploading');

      const v2 = mockQueueStore.getOperationVersion('opv-normal');
      // MD5_COMPLETE 不递增版本（不在 VERSION_BUMP_EVENTS 中）
      expect(v2).toBe(v1);

      // 上传完成
      expect(machine.transition('UPLOAD_COMPLETE', { operationVersion: v2 })).toBe(true);
      expect(machine.getState()).toBe('completed');
    });

    it('8b 正常大文件上传+合并流程不受影响', () => {
      const { manager, mockQueueStore, itemRef } = env;
      itemRef.totalChunks = 5;
      itemRef.fileSize = 100 * 1024 * 1024;
      const machine = manager.create('opv-chunked', { queueStore: mockQueueStore });

      machine.transition('START');
      const v1 = mockQueueStore.getOperationVersion('opv-chunked');

      machine.transition('MD5_COMPLETE', { fileHash: 'hash123', operationVersion: v1 });
      expect(machine.getState()).toBe('uploading');

      // 分片上传完成 → merging
      machine.transition('UPLOAD_COMPLETE', { operationVersion: v1 });
      expect(machine.getState()).toBe('merging');

      // 合并完成 → completed
      machine.transition('MERGE_SUCCESS', { operationVersion: v1 });
      expect(machine.getState()).toBe('completed');
    });

    it('8c 无版本号的 transition 仍可正常执行（向后兼容）', () => {
      const { manager, itemRef } = env;
      itemRef.totalChunks = 1;
      const machine = manager.create('opv-noversion', { queueStore: env.mockQueueStore });

      // 不传 operationVersion 的调用应正常工作
      expect(machine.transition('START')).toBe(true);
      expect(machine.transition('MD5_COMPLETE', { fileHash: 'x' })).toBe(true);
      expect(machine.transition('UPLOAD_COMPLETE')).toBe(true);
      expect(machine.getState()).toBe('completed');
    });
  });

  // ============ 场景 9：staleCallbackRejected 指标统计 ============
  describe('指标统计', () => {
    it('9a 过期回调被拒绝时 staleCallbackRejected 递增', () => {
      const { manager, mockQueueStore, itemRef } = env;
      itemRef.totalChunks = 1;
      const machine = manager.create('opv-metrics', { queueStore: mockQueueStore });
      advanceToUploading(machine);

      const v1 = mockQueueStore.getOperationVersion('opv-metrics');
      machine.transition('CANCEL');

      const before = manager.getMetrics().staleCallbackRejected || 0;
      machine.transition('UPLOAD_COMPLETE', { operationVersion: v1 });
      const after = manager.getMetrics().staleCallbackRejected || 0;

      expect(after).toBeGreaterThan(before);
    });
  });
});
