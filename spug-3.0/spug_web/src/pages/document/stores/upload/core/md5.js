/**
 * MD5Store - MD5计算管理
 * 职责：使用Web Worker池计算文件MD5
 * 
 * 【动态分片优化】
 * 根据文件大小动态调整MD5计算分片大小：
 * - 小文件 (< 10MB): 1MB 分片，快速响应
 * - 中等文件 (10MB - 100MB): 2MB 分片，平衡方案  
 * - 大文件 (100MB - 1GB): 4MB 分片，减少读取次数
 * - 超大文件 (> 1GB): 8MB 分片，最大效率
 * 
 * 【任务3.2 - 抽样MD5优化】
 * 对于超大文件(>500MB)，使用抽样MD5替代全量计算：
 * - 只计算头部、中部、尾部各2MB的MD5
 * - 将抽样MD5与文件大小组合成唯一标识
 * - 大幅提升大文件MD5计算速度（从几十秒降到几秒）
 */
import { action } from 'mobx';
import { 
  UPLOAD_CONSTANTS, 
  getMD5ChunkSize, 
  getMD5WorkerPath,
  // 【任务3.2】导入抽样MD5函数
  shouldUseSamplingMD5,
  getSamplingRanges,
  generateSamplingHash,
} from './upload-core-constants';

export class MD5Store {
  md5WorkerPool = [];  // Worker池: [{worker, busy: false, useCount: 0}, ...]
  md5TaskQueue = [];   // MD5任务队列: [{file, uploadId, resolve, reject}, ...]
  isPoolInitialized = false;

  constructor(rootStore) {
    this.rootStore = rootStore;
  }

  /**
   * 初始化MD5 Worker池
   */
  @action
  initMD5WorkerPool() {
    if (this.isPoolInitialized) {
      return;
    }

    for (let i = 0; i < UPLOAD_CONSTANTS.MD5_WORKER_POOL_SIZE; i++) {
      // 【P1-13修复】使用动态路径获取Worker脚本路径
      const workerPath = getMD5WorkerPath();
      const worker = new Worker(workerPath);
      this.md5WorkerPool.push({
        worker,
        busy: false,
        useCount: 0
      });
    }

    this.isPoolInitialized = true;
  }

  /**
   * 从池中获取空闲Worker
   */
  getAvailableWorker() {
    for (let i = 0; i < this.md5WorkerPool.length; i++) {
      const workerItem = this.md5WorkerPool[i];
      if (!workerItem.busy) {
        // 检查是否需要重建Worker（防止内存泄漏）
        if (workerItem.useCount >= UPLOAD_CONSTANTS.MD5_WORKER_REUSE_COUNT) {
          workerItem.worker.terminate();
          // 【P1-13修复】使用动态路径获取Worker脚本路径
          workerItem.worker = new Worker(getMD5WorkerPath());
          workerItem.useCount = 0;
        }
        return workerItem;
      }
    }
    return null;
  }

  /**
   * 处理MD5任务队列
   */
  async processMD5TaskQueue() {
    const workerItem = this.getAvailableWorker();
    
    if (!workerItem || this.md5TaskQueue.length === 0) {
      return;
    }

    const task = this.md5TaskQueue.shift();
    workerItem.busy = true;
    workerItem.useCount++;

    try {
      const hash = await this.calculateFileMD5WithWorker(task.file, task.uploadId, workerItem.worker);
      task.resolve(hash);
    } catch (error) {
      console.error(`[MD5Store] ${task.uploadId}: 任务失败`, error);
      task.reject(error);
    } finally {
      workerItem.busy = false;
      // 处理下一个任务
      this.processMD5TaskQueue();
    }
  }

  /**
   * 计算文件MD5（入口）
   * 
   * 【任务3.2优化】对于超大文件使用抽样MD5
   * - 小/中文件：全量MD5计算
   * - 大文件(>500MB)：抽样MD5（头/中/尾各2MB）
   */
  async calculateFileMD5(file, uploadId) {
    // 【任务3.2】判断是否使用抽样MD5
    if (shouldUseSamplingMD5(file.size)) {
      return this.calculateSamplingMD5(file, uploadId);
    }
    
    if (!this.isPoolInitialized) {
      this.initMD5WorkerPool();
    }

    return new Promise((resolve, reject) => {
      const task = { file, uploadId, resolve, reject };
      this.md5TaskQueue.push(task);
      this.processMD5TaskQueue();
    });
  }

  /**
   * 【任务3.2新增】抽样MD5计算
   * 对于超大文件，只计算头部、中部、尾部各2MB的MD5
   * 大幅提升计算速度，同时保持较高的唯一性
   * 
   * @param {File} file - 文件对象
   * @param {string} uploadId - 上传任务ID
   * @returns {Promise<string>} 抽样MD5标识
   */
  async calculateSamplingMD5(file, uploadId) {
    if (!this.isPoolInitialized) {
      this.initMD5WorkerPool();
    }

    const ranges = getSamplingRanges(file.size);
    
    // 【修复】检查ranges是否为空（文件大小为0或无效）
    if (!ranges || ranges.length === 0) {
      console.warn(`[MD5Store] ${uploadId}: 无法计算抽样MD5，文件大小无效或为空`);
      throw new Error('文件大小无效，无法计算MD5');
    }
    
    const sampleHashes = [];
    
    // 更新进度显示
    this._updateMD5Progress(uploadId, 0);
    
    try {
      // 依次计算每个抽样块的MD5
      for (let i = 0; i < ranges.length; i++) {
        const range = ranges[i];
        const hash = await this._calculateSampleChunk(file, range, uploadId);
        sampleHashes.push(hash);
        
        // 更新进度
        const progress = Math.round(((i + 1) / ranges.length) * 100);
        this._updateMD5Progress(uploadId, progress);
      }
      
      // 生成最终的抽样MD5标识
      const samplingHash = generateSamplingHash(sampleHashes, file.size);
      
      return samplingHash;
    } catch (error) {
      console.error(`[MD5Store] ${uploadId}: 抽样MD5计算失败`, error);
      throw error;
    }
  }

  /**
   * 【任务3.2新增】计算单个抽样块的MD5
   * @param {File} file - 文件对象
   * @param {Object} range - 范围 {start, end}
   * @param {string} uploadId - 上传任务ID
   * @param {number} retryCount - 重试次数（内部使用）
   * @returns {Promise<string>} MD5哈希
   */
  _calculateSampleChunk(file, range, uploadId, retryCount = 0) {
    const MAX_RETRIES = 100; // 最多等待10秒（100 * 100ms）
    
    return new Promise((resolve, reject) => {
      const workerItem = this.getAvailableWorker();
      if (!workerItem) {
        // 【修复】限制重试次数，避免无限递归
        if (retryCount >= MAX_RETRIES) {
          reject(new Error('MD5 Worker 不可用，请稍后重试'));
          return;
        }
        // 如果没有可用Worker，等待后重试
        setTimeout(() => {
          this._calculateSampleChunk(file, range, uploadId, retryCount + 1)
            .then(resolve)
            .catch(reject);
        }, 100);
        return;
      }

      workerItem.busy = true;
      workerItem.useCount++;

      const blob = file.slice(range.start, range.end);
      const reader = new FileReader();
      
      reader.onload = (e) => {
        let isHandled = false;
        
        const messageHandler = (e) => {
          // 【修复】防止重复处理
          if (isHandled) return;
          
          if (e.data.error) {
            isHandled = true;
            workerItem.worker.removeEventListener('message', messageHandler);
            workerItem.busy = false;
            reject(new Error(e.data.error));
          } else if (e.data.isComplete && e.data.hash) {
            isHandled = true;
            workerItem.worker.removeEventListener('message', messageHandler);
            workerItem.busy = false;
            resolve(e.data.hash);
          }
          // 【修复】忽略非完成消息（如进度消息），等待完成消息
        };
        
        workerItem.worker.addEventListener('message', messageHandler);
        workerItem.worker.postMessage({
          fileId: uploadId,
          fileChunk: e.target.result,
          isComplete: true,
          fileSize: blob.size
        });
      };
      
      reader.onerror = (e) => {
        workerItem.busy = false;
        reject(new Error(`FileReader error: ${e.target.error}`));
      };
      
      reader.readAsArrayBuffer(blob);
    });
  }

  /**
   * 【任务3.2新增】更新MD5计算进度
   * @param {string} uploadId - 上传任务ID
   * @param {number} progress - 进度(0-100)
   */
  _updateMD5Progress(uploadId, progress) {
    const item = this.rootStore.queueStore?.findUploadItemInCurrentTenant(uploadId);
    if (item) {
      item.percent = progress;
    }
  }

  /**
   * 使用Worker计算MD5
   * 
   * 【动态分片优化】根据文件大小自动选择最优分片大小：
   * - 小文件使用小分片，提高响应速度
   * - 大文件使用大分片，减少读取次数，提升性能
   * 
   * @param {File} file - 要计算MD5的文件
   * @param {string} uploadId - 上传任务ID
   * @param {Worker} worker - Web Worker实例
   * @returns {Promise<string>} MD5哈希值
   */
  calculateFileMD5WithWorker(file, uploadId, worker) {
    return new Promise((resolve, reject) => {
      // 【动态分片】根据文件大小获取最优分片大小
      const chunkSize = getMD5ChunkSize(file.size);
      const chunks = Math.ceil(file.size / chunkSize);
      let currentChunk = 0;
      
      // 记录使用的分片大小（调试用，已移除）

      const loadNext = () => {
        const start = currentChunk * chunkSize;
        const end = Math.min(start + chunkSize, file.size);
        const blob = file.slice(start, end);

        const reader = new FileReader();
        reader.onload = (e) => {
          // 【修复】使用Worker期望的消息格式：fileId, fileChunk, isComplete, fileSize
          worker.postMessage({
            fileId: uploadId,
            fileChunk: e.target.result,
            isComplete: currentChunk === chunks - 1,
            fileSize: file.size
          });
        };
        reader.onerror = (e) => {
          reject(new Error(`FileReader error: ${e.target.error}`));
        };
        reader.readAsArrayBuffer(blob);
      };

      worker.onmessage = (e) => {
        // 【修复】Worker返回的消息格式：{ fileId, progress, isComplete, hash, error }
        if (e.data.error) {
          reject(new Error(e.data.error));
        } else if (e.data.isComplete && e.data.hash) {
          // MD5计算完成
          resolve(e.data.hash);
        } else {
          // 进度更新
          const progress = e.data.progress || Math.round(((currentChunk + 1) / chunks) * 100);
          const item = this.rootStore.queueStore?.findUploadItemInCurrentTenant(uploadId);
          if (item) {
            item.percent = progress;
          }
          currentChunk++;
          if (currentChunk < chunks) {
            loadNext();
          }
        }
      };

      worker.onerror = (error) => {
        reject(error);
      };

      loadNext();
    });
  }

  /**
   * 终止所有Worker
   */
  terminateAll() {
    this.md5WorkerPool.forEach(item => {
      if (item.worker) {
        item.worker.terminate();
      }
    });
    this.md5WorkerPool = [];
    this.md5TaskQueue = [];
    this.isPoolInitialized = false;
  }
}

export default MD5Store;
