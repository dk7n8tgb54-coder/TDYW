/**
 * 上传相关常量
 * 
 * 本文件定义了资料库模块上传功能的所有常量配置
 * 包括分片大小、并发控制、重试机制、文件限制等
 * 
 * @module constants/upload
 */

// ============================================================
// 辅助函数
// ============================================================

/**
 * MD5动态分片大小配置
 * 根据文件大小返回最优的分片大小
 * @param {number} fileSize - 文件大小(字节)
 * @returns {number} 推荐的分片大小(字节)
 */
const getMD5ChunkSize = (fileSize) => {
  // < 10MB: 1MB 分片，追求快速响应
  if (fileSize < 10 * 1024 * 1024) {
    return 1 * 1024 * 1024;
  }
  // 10MB - 100MB: 2MB 分片，平衡方案
  else if (fileSize < 100 * 1024 * 1024) {
    return 2 * 1024 * 1024;
  }
  // 100MB - 1GB: 4MB 分片，减少读取次数
  else if (fileSize < 1024 * 1024 * 1024) {
    return 4 * 1024 * 1024;
  }
  // > 1GB: 8MB 分片，最大效率
  else {
    return 8 * 1024 * 1024;
  }
};

/**
 * ID计数器 - 用于生成唯一上传ID
 * 配合 Date.now() 使用，避免高并发时ID冲突
 * @type {number}
 */
let uploadIdCounter = 0;

/**
 * 生成唯一上传ID
 * 使用 timestamp + counter + random 确保唯一性
 * @returns {string} 唯一ID
 */
function generateUploadId() {
  uploadIdCounter = (uploadIdCounter + 1) % 10000;
  return `${Date.now()}_${uploadIdCounter}_${Math.random().toString(36).substr(2, 9)}`;
}

/**
 * 获取MD5 Worker脚本路径
 * 根据运行环境动态获取路径，支持部署到子路径
 * @returns {string} Worker脚本路径
 */
function getMD5WorkerPath() {
  // 使用 PUBLIC_URL 环境变量（由构建工具注入），默认为根路径
  const basePath = process.env.PUBLIC_URL || '';
  return `${basePath}/md5-worker-spark.js`;
}

// ============================================================
// 【任务3.2】抽样MD5配置
// ============================================================

/**
 * 抽样MD5配置
 * 对于超大文件，只抽样计算部分数据的MD5，大幅提升速度
 */
const SAMPLING_CONFIG = {
  // 启用抽样的文件大小阈值：1GB（从500MB提高到1GB，提升数据完整性保护）
  THRESHOLD: 1024 * 1024 * 1024,
  // 每个抽样块的大小：2MB
  SAMPLE_SIZE: 2 * 1024 * 1024,
  // 抽样块数量（头、中、尾）
  SAMPLE_COUNT: 3,
};

/**
 * 【任务3.2】判断是否应该使用抽样MD5
 * @param {number} fileSize - 文件大小(字节)
 * @returns {boolean} 是否使用抽样
 */
function shouldUseSamplingMD5(fileSize) {
  // 【修复】确保 fileSize 是有效数字且大于0
  if (!fileSize || typeof fileSize !== 'number' || fileSize <= 0) {
    return false;
  }
  return fileSize >= SAMPLING_CONFIG.THRESHOLD;
}

/**
 * 【任务3.2】获取抽样MD5的块范围
 * 对于大文件，只计算头部、中部、尾部各2MB的数据
 * @param {number} fileSize - 文件大小(字节)
 * @returns {Array<{start: number, end: number}>} 抽样块范围数组
 */
function getSamplingRanges(fileSize) {
  // 【修复】确保 fileSize 是有效数字
  if (!fileSize || typeof fileSize !== 'number' || fileSize <= 0) {
    return [];
  }
  
  const { SAMPLE_SIZE } = SAMPLING_CONFIG;
  const ranges = [];
  
  // 【修复】确保至少有一个字节可读
  const actualSize = Math.max(fileSize, 1);
  
  // 头部抽样
  ranges.push({ start: 0, end: Math.min(SAMPLE_SIZE, actualSize) });
  
  if (actualSize > SAMPLE_SIZE * 2) {
    // 中部抽样
    const middleStart = Math.floor((actualSize - SAMPLE_SIZE) / 2);
    ranges.push({ start: middleStart, end: middleStart + SAMPLE_SIZE });
    
    // 尾部抽样
    ranges.push({ start: actualSize - SAMPLE_SIZE, end: actualSize });
  }
  
  return ranges;
}

/**
 * 【任务3.2】生成抽样MD5标识
 * 将抽样块的MD5组合成最终的文件标识
 * @param {Array<string>} sampleHashes - 各抽样块的MD5
 * @param {number} fileSize - 文件大小
 * @returns {string} 抽样MD5标识
 */
function generateSamplingHash(sampleHashes, fileSize) {
  // 【修复】数据库限制100字符，需要控制总长度
  // 格式: sv1_{size(6位base36)}_{hash1(16位)}_{hash2(16位)}_{hash3(16位)}
  // 总长度: 4+1+6+1+16+1+16+1+16 = 62字符，安全
  
  // 【修复】确保 sampleHashes 有效且至少有一个hash
  if (!sampleHashes || !Array.isArray(sampleHashes) || sampleHashes.length === 0) {
    throw new Error('无效的抽样哈希数组');
  }
  
  const [h1, h2, h3] = sampleHashes;
  
  // 【修复】确保 h1 存在且为有效字符串
  if (!h1 || typeof h1 !== 'string' || h1.length < 16) {
    throw new Error('无效的抽样哈希值');
  }
  
  // base36编码文件大小，限制6位（最大36^6≈2.1GB，足够标识）
  // 【修复】使用padStart确保6位，不足前面补0，与后端保持一致
  const sizeStr = (fileSize || 0).toString(36).substring(0, 6).padStart(6, '0');
  
  // 使用MD5前16位，平衡唯一性和长度
  const safeH2 = (h2 && typeof h2 === 'string') ? h2 : '0';
  const safeH3 = (h3 && typeof h3 === 'string') ? h3 : '0';
  
  return `sv1_${sizeStr}_${h1.substring(0, 16)}_${safeH2.substring(0, 16)}_${safeH3.substring(0, 16)}`;
}

// ============================================================
// 统一导出对象
// ============================================================

/**
 * 上传相关常量（统一导出对象）
 * 方便一次性导入所有常量
 * 
 * @example
 * import { UPLOAD_CONSTANTS } from './constants/upload';
 * const chunkSize = UPLOAD_CONSTANTS.CHUNK_SIZE;
 */
export const UPLOAD_CONSTANTS = {
  // 分片配置
  CHUNK_SIZE: 32 * 1024 * 1024,
  NORMAL_UPLOAD_THRESHOLD: 32 * 1024 * 1024,
  
  // 并发控制
  MAX_CONCURRENT_UPLOADS: 3,
  MAX_CONCURRENT_CHUNKS: 3,
  // 【Loop-200修复】MAX_DISPLAY_COUNT 仅影响传输列表渲染显示数量，不影响真实队列容量和任务调度
  // 真实队列无上限，调度受 MAX_CONCURRENT_UPLOADS 控制；此值仅用于 UI 层截断/虚拟列表
  MAX_DISPLAY_COUNT: 200,           // 传输列表最大显示任务数（仅显示用途，不参与调度）
  MAX_COMPLETED_TASKS: 100,         // 自动清理：保留最近100个已完成任务
  
  // 重试配置
  MAX_RETRIES: 3,
  RETRY_DELAY: 1000,
  MAX_CHUNK_RETRY: 3,
  MAX_RETRY_DELAY_CHUNK: 30000,
  MAX_FOLDER_FILE_RETRY: 3,
  RETRY_DELAY_BASE: 2000,
  MAX_RETRY_DELAY_FOLDER: 30000,
  
  // 文件限制（单个文件最大 100MB）
  MAX_FILE_SIZE: 100 * 1024 * 1024,
  
  // 超时配置
  UPLOAD_TIMEOUT: 900000,
  
  // 进度配置
  PROGRESS_UPDATE_INTERVAL: 200,
  PROGRESS_THROTTLE_DELAY: 500,  // 从200ms增加到500ms，减少全局刷新频率
  MD5_PROGRESS_RATIO: 2,
  
  // MD5配置
  MD5_CHUNK_SIZE: 2 * 1024 * 1024,  // 默认2MB，建议使用 getMD5ChunkSize(fileSize) 获取动态值
  MD5_WORKER_POOL_SIZE: 2,
  MD5_WORKER_REUSE_COUNT: 10,
  
  // MD5动态分片大小函数
  getMD5ChunkSize: (fileSize) => {
    if (fileSize < 10 * 1024 * 1024) return 1 * 1024 * 1024;
    else if (fileSize < 100 * 1024 * 1024) return 2 * 1024 * 1024;
    else if (fileSize < 1024 * 1024 * 1024) return 4 * 1024 * 1024;
    else return 8 * 1024 * 1024;
  },
  
  // ID生成函数引用
  generateUploadId: generateUploadId,
  
  // Worker路径获取函数
  getMD5WorkerPath: getMD5WorkerPath,
  
  // 【任务3.2】抽样MD5配置
  SAMPLING_MD5: SAMPLING_CONFIG,
  shouldUseSamplingMD5: shouldUseSamplingMD5,
  getSamplingRanges: getSamplingRanges,
  generateSamplingHash: generateSamplingHash,
  
  // 轮询配置
  CANCEL_CHECK_INTERVAL: 500,
  CONCURRENT_CHECK_INTERVAL: 500,
  QUEUE_CLEANUP_INTERVAL: 3600000,
  MERGE_POLLING_INTERVAL: 2000,
  MERGE_MAX_POLLING_TIME: 300,
  
  // 批量上传
  BATCH_WARNING_THRESHOLD: 10,
  BATCH_UPLOAD_THRESHOLD: 10,
  BATCH_UPLOAD_WARNING_TEMPLATE: '正在批量上传 {count} 个文件，请稍候...',
  
  // 磁盘使用
  DISK_USAGE_THRESHOLD: 90,
  DISK_USAGE_WARNING_TEMPLATE: '磁盘使用率已达 {percent}%，请清理空间后再上传',
  
  // 【新增】虚拟列表配置
  VIRTUAL_LIST: {
    ITEM_HEIGHT: 80,              // 列表项固定高度（像素）
    OVERSCAN_COUNT: 15,           // 【优化】预渲染数量，从5增加到15，减少快速滚动时的空白
    LIST_MAX_HEIGHT: 400,         // 列表最大高度
    LIST_MIN_HEIGHT: 100,         // 列表最小高度
    FALLBACK_THRESHOLD: 30,       // 低于此数量使用原生渲染
  },
};

// 命名导出函数
export { 
  generateUploadId, 
  getMD5ChunkSize, 
  getMD5WorkerPath,
  // 【任务3.2】导出抽样MD5函数
  shouldUseSamplingMD5,
  getSamplingRanges,
  generateSamplingHash,
};

// 单独导出常用常量（方便直接导入）
export const DISK_USAGE_THRESHOLD = UPLOAD_CONSTANTS.DISK_USAGE_THRESHOLD;
export const DISK_USAGE_WARNING_TEMPLATE = UPLOAD_CONSTANTS.DISK_USAGE_WARNING_TEMPLATE;
export const PROGRESS_THROTTLE_DELAY = UPLOAD_CONSTANTS.PROGRESS_THROTTLE_DELAY;
export const RETRY_DELAY_BASE = UPLOAD_CONSTANTS.RETRY_DELAY_BASE;
export const BATCH_UPLOAD_THRESHOLD = UPLOAD_CONSTANTS.BATCH_UPLOAD_THRESHOLD;
export const BATCH_UPLOAD_WARNING_TEMPLATE = UPLOAD_CONSTANTS.BATCH_UPLOAD_WARNING_TEMPLATE;
