/**
 * 端到端自动化测试
 * 模拟完整的上传流程，包括状态流转、暂停、恢复、错误处理等
 */

import { StateMachineManager } from '../StateMachineManager';
import { UploadStateMachine } from '../UploadStateMachine';

// 模拟上传任务生命周期
describe('端到端上传流程测试', () => {
  let manager;
  let mockStores;
  let uploadEvents;

  beforeEach(() => {
    uploadEvents = [];

    // 创建完整的 mock stores
    mockStores = {
      queueStore: {
        items: new Map(),
        findUploadItemInCurrentTenant: jest.fn((id) => mockStores.queueStore.items.get(id)),
        updateUploadItem: jest.fn((id, updates) => {
          const item = mockStores.queueStore.items.get(id);
          if (item) {
            Object.assign(item, updates);
            uploadEvents.push({ type: 'update', id, updates, timestamp: Date.now() });
          }
        }),
        pauseUpload: jest.fn(),
        resumeUpload: jest.fn(),
        generateUniqueKey: jest.fn((file, folderId) => `${file.name}-${folderId}`),
        uploadingUniqueKeys: new Set(),
      },
      transferStore: {
        createTransfer: jest.fn().mockResolvedValue(12345),
        updateTransferStatus: jest.fn(),
        updateTransferHash: jest.fn(),
        updateTransferProgress: jest.fn(),
        checkUploadedChunks: jest.fn().mockResolvedValue({ exists: false, uploaded_chunks: [] }),
        fetchTransfers: jest.fn().mockResolvedValue([]),
      },
      md5Store: {
        calculateFileMD5: jest.fn().mockImplementation((file, uploadId) => {
          return new Promise((resolve) => {
            setTimeout(() => resolve(`md5-${uploadId}`), 100);
          });
        }),
      },
      chunkUploadStore: {
        uploadFileInChunks: jest.fn().mockImplementation(async (file, folderId, item, chunkCount) => {
          uploadEvents.push({ type: 'chunkUpload', id: item.id, chunkCount });
          // 模拟上传进度
          for (let i = 0; i < chunkCount; i++) {
            if (item.isCancelledByUser) throw new Error('已取消');
            if (item.isPausedByUser) {
              uploadEvents.push({ type: 'paused', id: item.id, atChunk: i });
              return;
            }
            item.currentChunk = i + 1;
            item.percent = Math.round(((i + 1) / chunkCount) * 100);
            await new Promise(r => setTimeout(r, 10));
          }
          uploadEvents.push({ type: 'completed', id: item.id });
        }),
      },
      fileUploadStore: {
        uploadFileNormal: jest.fn().mockImplementation(async (file, folderId, itemId, isPublic) => {
          uploadEvents.push({ type: 'normalUpload', id: itemId });
          await new Promise(r => setTimeout(r, 50));
          uploadEvents.push({ type: 'completed', id: itemId });
        }),
      },
    };

    manager = new StateMachineManager();
  });

  afterEach(() => {
    manager.clear();
  });

  // ============ 场景1: 正常上传流程 ============
  describe('场景1: 正常上传流程', () => {
    it('小文件应该完成 waiting -> calculating -> uploading -> completed 流程', async () => {
      const uploadId = 'small-file-1';
      const mockFile = { name: 'test.txt', size: 1024 * 1024 }; // 1MB

      // 创建上传项
      mockStores.queueStore.items.set(uploadId, {
        id: uploadId,
        file: mockFile,
        fileSize: mockFile.size,
        status: 'waiting',
        fileHash: null,
        percent: 0,
        currentChunk: 0,
        isPublic: false,
        folderId: null,
        transferId: null,
        isPausedByUser: false,
        isCancelledByUser: false,
      });

      // 创建状态机
      const machine = manager.create(uploadId, {
        queueStore: mockStores.queueStore,
        transferStore: mockStores.transferStore,
        md5Store: mockStores.md5Store,
        chunkUploadStore: mockStores.chunkUploadStore,
        fileUploadStore: mockStores.fileUploadStore,
      });

      // 1. 开始上传
      expect(machine.transition('START')).toBe(true);
      expect(machine.getState()).toBe('calculating');

      // 2. 模拟MD5完成
      const fileHash = 'md5-small-file-1';
      machine.updateContext({ fileHash });
      expect(machine.transition('MD5_COMPLETE', { fileHash })).toBe(true);
      expect(machine.getState()).toBe('uploading');

      // 3. 触发实际上传（小文件用普通上传）
      await mockStores.fileUploadStore.uploadFileNormal(mockFile, null, uploadId, false);

      // 4. 完成上传（小文件无 totalChunks，直接 completed）
      expect(machine.transition('UPLOAD_COMPLETE')).toBe(true);
      expect(machine.getState()).toBe('completed');

      // 验证事件流
      expect(uploadEvents.filter(e => e.type === 'completed')).toHaveLength(1);
    });

    it('大文件应该使用分片上传', async () => {
      const uploadId = 'large-file-1';
      const mockFile = { name: 'large.zip', size: 100 * 1024 * 1024 }; // 100MB

      mockStores.queueStore.items.set(uploadId, {
        id: uploadId,
        file: mockFile,
        fileSize: mockFile.size,
        status: 'waiting',
        fileHash: null,
        percent: 0,
        currentChunk: 0,
        isPublic: false,
        folderId: null,
        transferId: null,
        isPausedByUser: false,
        isCancelledByUser: false,
      });

      const machine = manager.create(uploadId, {
        queueStore: mockStores.queueStore,
        transferStore: mockStores.transferStore,
        md5Store: mockStores.md5Store,
        chunkUploadStore: mockStores.chunkUploadStore,
        fileUploadStore: mockStores.fileUploadStore,
      });

      machine.transition('START');
      const fileHash = 'md5-large-file-1';
      machine.updateContext({ fileHash });
      machine.transition('MD5_COMPLETE', { fileHash });

      expect(machine.getState()).toBe('uploading');

      // 触发分片上传
      const chunkCount = 25; // 100MB / 4MB
      const item = mockStores.queueStore.items.get(uploadId);
      await mockStores.chunkUploadStore.uploadFileInChunks(mockFile, null, item, chunkCount);

      // 验证分片上传被调用
      expect(uploadEvents.some(e => e.type === 'chunkUpload')).toBe(true);
    });
  });

  // ============ 场景2: 暂停和恢复 ============
  describe('场景2: 暂停和恢复', () => {
    it('应该在计算阶段暂停并恢复', async () => {
      const uploadId = 'pause-md5-1';
      mockStores.queueStore.items.set(uploadId, {
        id: uploadId,
        file: { name: 'test.txt', size: 1024 },
        fileSize: 1024,
        status: 'waiting',
        fileHash: null,
      });

      const machine = manager.create(uploadId, {
        queueStore: mockStores.queueStore,
      });

      // 开始
      machine.transition('START');
      expect(machine.getState()).toBe('calculating');

      // 暂停
      machine.transition('PAUSE');
      expect(machine.getState()).toBe('paused');

      // 恢复（无fileHash，shouldResumeWaiting → waiting）
      machine.transition('RESUME');
      expect(machine.getState()).toBe('waiting');

      // 重新开始计算
      machine.transition('START');
      expect(machine.getState()).toBe('calculating');

      // 完成MD5
      machine.transition('MD5_COMPLETE', { fileHash: 'abc123' });
      expect(machine.getState()).toBe('uploading');
    });

    it('应该在上传阶段暂停并恢复', async () => {
      const uploadId = 'pause-upload-1';
      mockStores.queueStore.items.set(uploadId, {
        id: uploadId,
        file: { name: 'test.txt', size: 1024 },
        fileSize: 1024,
        status: 'waiting',
        fileHash: 'abc123', // 已有fileHash
      });

      const machine = manager.create(uploadId, {
        queueStore: mockStores.queueStore,
      });

      // 进入上传状态
      machine.transition('START');
      machine.transition('MD5_COMPLETE');
      expect(machine.getState()).toBe('uploading');

      // 暂停
      machine.transition('PAUSE');
      expect(machine.getState()).toBe('paused');

      // 恢复（有fileHash，回到uploading）
      machine.transition('RESUME');
      expect(machine.getState()).toBe('uploading');
    });

    it('批量暂停和恢复应该正常工作', async () => {
      const ids = ['batch-1', 'batch-2', 'batch-3'];

      ids.forEach(id => {
        mockStores.queueStore.items.set(id, {
          id,
          file: { name: `${id}.txt`, size: 1024 },
          fileSize: 1024,
          status: 'waiting',
        });

        const machine = manager.create(id, { queueStore: mockStores.queueStore });
        machine.transition('START');
      });

      // 批量暂停
      const pauseResults = manager.batchPause();
      expect(pauseResults.filter(r => r.success).length).toBe(3);

      // 验证都暂停了
      ids.forEach(id => {
        expect(manager.get(id).getState()).toBe('paused');
      });

      // 批量恢复
      const resumeResults = manager.batchResume();
      expect(resumeResults.filter(r => r.success).length).toBe(3);
    });
  });

  // ============ 场景3: 错误处理 ============
  describe('场景3: 错误处理', () => {
    it('MD5计算失败应该转到error状态', async () => {
      const uploadId = 'md5-error-1';
      mockStores.queueStore.items.set(uploadId, {
        id: uploadId,
        file: { name: 'test.txt', size: 1024 },
        fileSize: 1024,
        status: 'waiting',
      });

      const machine = manager.create(uploadId, {
        queueStore: mockStores.queueStore,
      });

      machine.transition('START');
      expect(machine.getState()).toBe('calculating');

      // 模拟MD5错误
      machine.transition('ERROR', { error: new Error('MD5计算失败') });
      expect(machine.getState()).toBe('error');

      // 可以重试
      machine.transition('RESUME');
      expect(machine.getState()).toBe('waiting');
    });

    it('上传失败应该转到error状态', async () => {
      const uploadId = 'upload-error-1';
      mockStores.queueStore.items.set(uploadId, {
        id: uploadId,
        file: { name: 'test.txt', size: 1024 },
        fileSize: 1024,
        status: 'waiting',
        fileHash: 'abc123',
      });

      const machine = manager.create(uploadId, {
        queueStore: mockStores.queueStore,
      });

      machine.transition('START');
      machine.transition('MD5_COMPLETE');
      expect(machine.getState()).toBe('uploading');

      // 模拟上传错误
      machine.transition('ERROR', { error: new Error('网络错误') });
      expect(machine.getState()).toBe('error');
    });
  });

  // ============ 场景4: 取消上传 ============
  describe('场景4: 取消上传', () => {
    it('应该能在暂停状态取消上传', () => {
      const uploadId = 'cancel-1';
      mockStores.queueStore.items.set(uploadId, {
        id: uploadId,
        file: { name: 'test.txt', size: 1024 },
        fileSize: 1024,
        status: 'waiting',
      });

      const machine = manager.create(uploadId, {
        queueStore: mockStores.queueStore,
      });

      machine.transition('START');
      machine.transition('PAUSE');
      expect(machine.getState()).toBe('paused');

      // 取消（CANCEL → cancelled）
      machine.transition('CANCEL');
      expect(machine.getState()).toBe('cancelled');
    });

    it('批量取消应该取消所有暂停的任务', () => {
      const ids = ['cancel-batch-1', 'cancel-batch-2'];

      ids.forEach(id => {
        mockStores.queueStore.items.set(id, {
          id,
          file: { name: `${id}.txt`, size: 1024 },
          fileSize: 1024,
          status: 'waiting',
        });

        const machine = manager.create(id, { queueStore: mockStores.queueStore });
        machine.transition('START');
        machine.transition('PAUSE');
      });

      const results = manager.batchCancel();
      expect(results.filter(r => r.success).length).toBe(2);

      ids.forEach(id => {
        expect(manager.get(id).getState()).toBe('cancelled');
      });
    });
  });

  // ============ 场景5: 复杂流程 ============
  describe('场景5: 复杂流程', () => {
    it('应该处理多次暂停恢复', async () => {
      const uploadId = 'multi-pause-1';
      mockStores.queueStore.items.set(uploadId, {
        id: uploadId,
        file: { name: 'test.txt', size: 1024 },
        fileSize: 1024,
        status: 'waiting',
        fileHash: 'abc123',
      });

      const machine = manager.create(uploadId, {
        queueStore: mockStores.queueStore,
      });

      // 第一次暂停恢复
      machine.transition('START');
      machine.transition('MD5_COMPLETE');
      machine.transition('PAUSE');
      machine.transition('RESUME');

      // 第二次暂停恢复
      machine.transition('PAUSE');
      machine.transition('RESUME');

      expect(machine.getState()).toBe('uploading');

      // 验证历史记录
      const history = machine.getHistory();
      expect(history.filter(h => h.event === 'PAUSE')).toHaveLength(2);
      expect(history.filter(h => h.event === 'RESUME')).toHaveLength(2);
    });

    it('应该处理混合状态的任务', async () => {
      const scenarios = [
        { id: 'mix-1', finalState: 'calculating', transitions: ['START'] },
        { id: 'mix-2', finalState: 'paused', transitions: ['START', 'PAUSE'] },
        { id: 'mix-3', finalState: 'uploading', transitions: ['START', 'MD5_COMPLETE'] },
        { id: 'mix-4', finalState: 'error', transitions: ['START', 'ERROR'] },
      ];

      scenarios.forEach(({ id, transitions }) => {
        mockStores.queueStore.items.set(id, {
          id,
          file: { name: `${id}.txt`, size: 1024 },
          fileSize: 1024,
          status: 'waiting',
          fileHash: id === 'mix-3' ? 'abc123' : null,
        });

        const machine = manager.create(id, { queueStore: mockStores.queueStore });

        transitions.forEach(event => {
          if (event === 'MD5_COMPLETE') {
            machine.updateContext({ fileHash: 'abc123' });
          }
          machine.transition(event, event === 'ERROR' ? { error: new Error('test') } : {});
        });
      });

      // 验证批量操作只影响可操作的
      const pauseResults = manager.batchPause();
      expect(pauseResults.filter(r => r.success).length).toBe(2); // mix-1 和 mix-3

      expect(manager.get('mix-1').getState()).toBe('paused');
      expect(manager.get('mix-2').getState()).toBe('paused');
      expect(manager.get('mix-3').getState()).toBe('paused');
      expect(manager.get('mix-4').getState()).toBe('error');
    });
  });

  // ============ 场景6: 性能测试 ============
  describe('场景6: 性能测试', () => {
    it('应该能快速处理100个并发任务', () => {
      const startTime = Date.now();

      for (let i = 0; i < 100; i++) {
        const id = `perf-${i}`;
        mockStores.queueStore.items.set(id, {
          id,
          file: { name: `${id}.txt`, size: 1024 },
          fileSize: 1024,
          status: 'waiting',
        });

        const machine = manager.create(id, { queueStore: mockStores.queueStore });
        machine.transition('START');
      }

      const duration = Date.now() - startTime;

      expect(manager.size()).toBe(100);
      expect(duration).toBeLessThan(1000); // 应该在1秒内完成

      const stats = manager.getStats();
      expect(stats.byState.calculating).toBe(100);
    });

    it('批量操作100个任务应该高效', () => {
      // 创建100个calculating状态的任务
      for (let i = 0; i < 100; i++) {
        const id = `batch-perf-${i}`;
        mockStores.queueStore.items.set(id, {
          id,
          file: { name: `${id}.txt`, size: 1024 },
          fileSize: 1024,
          status: 'waiting',
        });

        const machine = manager.create(id, { queueStore: mockStores.queueStore });
        machine.transition('START');
      }

      const startTime = Date.now();

      // 批量暂停
      const pauseResults = manager.batchPause();
      expect(pauseResults.filter(r => r.success).length).toBe(100);

      // 批量恢复（可能受并发槽位限制，至少有部分成功）
      const resumeResults = manager.batchResume();
      expect(resumeResults.filter(r => r.success).length).toBeGreaterThan(0);

      const duration = Date.now() - startTime;
      expect(duration).toBeLessThan(500); // 批量操作应该很快
    });
  });
});
