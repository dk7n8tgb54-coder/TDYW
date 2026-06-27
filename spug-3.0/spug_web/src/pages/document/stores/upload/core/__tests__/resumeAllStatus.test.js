import {
  fetchBackendStatusMap,
  shouldResumeBackendPaused,
} from '../controls/resumeAllStatus';

describe('resumeAllStatus', () => {
  it('能从后端传输列表中提取目标 transferId 的状态', async () => {
    const transferStore = {
      fetchTransfers: jest.fn(() => Promise.resolve([
        { id: 101, status: 'PAUSED' },
        { id: 102, status: 'UPLOADING' },
      ])),
    };

    const statusMap = await fetchBackendStatusMap({
      transferStore,
      transferIds: [101],
      isPublic: false,
    });

    expect(transferStore.fetchTransfers).toHaveBeenCalledWith(false);
    expect(statusMap.get(101)).toBe('PAUSED');
    expect(statusMap.has(102)).toBe(false);
  });

  it('仅后端确认为 PAUSED 时才需要先调用后端恢复', () => {
    const item = { transferId: 101 };
    expect(
      shouldResumeBackendPaused(item, new Map([[101, 'PAUSED']]))
    ).toBe(true);
    expect(
      shouldResumeBackendPaused(item, new Map([[101, 'UPLOADING']]))
    ).toBe(false);
    expect(
      shouldResumeBackendPaused({ transferId: null }, new Map([[101, 'PAUSED']]))
    ).toBe(false);
  });

  it('查询失败时返回空状态表，调用方可降级为本地 waiting 调度', async () => {
    const transferStore = {
      fetchTransfers: jest.fn(() => Promise.reject(new Error('network'))),
    };

    const statusMap = await fetchBackendStatusMap({
      transferStore,
      transferIds: [101],
    });

    expect(statusMap.size).toBe(0);
  });
});
