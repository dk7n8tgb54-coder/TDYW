import StatusSynchronizer from '../sync/StatusSynchronizer';

describe('StatusSynchronizer', () => {
  function createSynchronizer(itemOverrides = {}) {
    const item = {
      id: 'upload-1',
      status: 'completed',
      transferId: 101,
      ...itemOverrides,
    };
    const transferStore = {
      updateTransferStatus: jest.fn().mockResolvedValue({ success: true }),
    };
    const queueStore = {
      findUploadItemInCurrentTenant: jest.fn(() => item),
    };
    const synchronizer = new StatusSynchronizer({
      queueStore,
      transferStore,
    });
    return { synchronizer, item, transferStore, queueStore };
  }

  it('终态 completed 仍会同步到后端', async () => {
    const { synchronizer, transferStore } = createSynchronizer({ status: 'completed' });

    await synchronizer.syncStateToBackend('upload-1', 'completed', {});

    expect(transferStore.updateTransferStatus).toHaveBeenCalledWith(101, 'COMPLETED');
  });

  it('终态 cancelled 仍会同步到后端', async () => {
    const { synchronizer, transferStore } = createSynchronizer({ status: 'cancelled' });

    await synchronizer.syncStateToBackend('upload-1', 'cancelled', {});

    expect(transferStore.updateTransferStatus).toHaveBeenCalledWith(101, 'CANCELED');
  });

  it('已有终态时阻止非终态回退同步', async () => {
    const { synchronizer, transferStore } = createSynchronizer({ status: 'completed' });

    await synchronizer.syncStateToBackend('upload-1', 'uploading', {});

    expect(transferStore.updateTransferStatus).not.toHaveBeenCalled();
  });

  it('终态 error 仍会同步到后端', async () => {
    const { synchronizer, transferStore } = createSynchronizer({ status: 'error' });

    await synchronizer.syncStateToBackend('upload-1', 'error', {});

    expect(transferStore.updateTransferStatus).toHaveBeenCalledWith(101, 'FAILED');
  });

  it('已有 cancelled 终态时阻止 merging 回退同步', async () => {
    const { synchronizer, transferStore } = createSynchronizer({ status: 'cancelled' });

    await synchronizer.syncStateToBackend('upload-1', 'merging', {});

    expect(transferStore.updateTransferStatus).not.toHaveBeenCalled();
  });

  it('已有 error 终态时阻止 uploading 回退同步', async () => {
    const { synchronizer, transferStore } = createSynchronizer({ status: 'error' });

    await synchronizer.syncStateToBackend('upload-1', 'uploading', {});

    expect(transferStore.updateTransferStatus).not.toHaveBeenCalled();
  });

  it('waiting 状态不同步到后端（前端调度态，后端已是 PENDING）', async () => {
    const { synchronizer, transferStore } = createSynchronizer({ status: 'waiting' });

    await synchronizer.syncStateToBackend('upload-1', 'waiting', {});

    expect(transferStore.updateTransferStatus).not.toHaveBeenCalled();
  });

  it('相同状态不重复同步（去重）', async () => {
    const { synchronizer, transferStore } = createSynchronizer({ status: 'uploading' });

    await synchronizer.syncStateToBackend('upload-1', 'uploading', {});
    await synchronizer.syncStateToBackend('upload-1', 'uploading', {});

    expect(transferStore.updateTransferStatus).toHaveBeenCalledTimes(1);
  });

  it('paused 状态同步到后端为 PAUSED', async () => {
    const { synchronizer, transferStore } = createSynchronizer({ status: 'paused' });

    await synchronizer.syncStateToBackend('upload-1', 'paused', {});

    expect(transferStore.updateTransferStatus).toHaveBeenCalledWith(101, 'PAUSED');
  });

  it('merging 状态同步到后端为 MERGING', async () => {
    const { synchronizer, transferStore } = createSynchronizer({ status: 'merging' });

    await synchronizer.syncStateToBackend('upload-1', 'merging', {});

    expect(transferStore.updateTransferStatus).toHaveBeenCalledWith(101, 'MERGING');
  });

  // ============ 共用去重逻辑测试（StoreEventAdapter 与 StatusSynchronizer 共享 _lastSyncStatusMap）============

  describe('共用去重逻辑（shouldSync / markSynced）', () => {
    it('shouldSync 返回 true 当 transferId 首次同步某状态', () => {
      const { synchronizer } = createSynchronizer();
      expect(synchronizer.shouldSync(101, 'COMPLETED')).toBe(true);
    });

    it('shouldSync 返回 false 当 transferId 已同步过相同状态', () => {
      const { synchronizer } = createSynchronizer();
      synchronizer.markSynced(101, 'COMPLETED');
      expect(synchronizer.shouldSync(101, 'COMPLETED')).toBe(false);
    });

    it('shouldSync 返回 true 当 transferId 状态发生变化', () => {
      const { synchronizer } = createSynchronizer();
      synchronizer.markSynced(101, 'UPLOADING');
      expect(synchronizer.shouldSync(101, 'COMPLETED')).toBe(true);
    });

    it('markSynced + shouldSync 模拟 StoreEventAdapter 与 StatusSynchronizer 共用去重', async () => {
      const { synchronizer, transferStore } = createSynchronizer({ status: 'completed' });

      // 模拟权威链路先同步 completed
      await synchronizer.syncStateToBackend('upload-1', 'completed', {});
      expect(transferStore.updateTransferStatus).toHaveBeenCalledTimes(1);

      // 模拟 StoreEventAdapter 兼容路径尝试同步相同状态（应被去重拦截）
      const backendStatus = 'COMPLETED';
      if (!synchronizer.shouldSync(101, backendStatus)) {
        // 去重命中，不调用后端
      } else {
        synchronizer.markSynced(101, backendStatus);
        await transferStore.updateTransferStatus(101, backendStatus);
      }

      expect(transferStore.updateTransferStatus).toHaveBeenCalledTimes(1);
    });
  });
});
