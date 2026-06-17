/**
 * Guards - 状态转换守卫条件
 * 【任务4.1】从 UploadStateMachine 拆分出来，实现职责分离
 * 
 * 设计原则：
 * - 纯函数，无副作用
 * - 只依赖传入参数，不依赖外部状态
 * - 返回 boolean 类型结果
 */

/**
 * 检查是否可以启动上传
 * @param {Object} params - 参数
 * @param {Object} params.item - 上传项
 * @param {boolean} params.isCancelledByUser - 是否被用户取消
 * @returns {boolean}
 */
export function canStart({ item, isCancelledByUser }) {
  return item && !isCancelledByUser;
}

/**
 * 检查是否应该恢复到 waiting 状态
 * 条件：1) 没有File对象 或 2) 从waiting状态暂停过来的且没有fileHash
 * 
 * 【P2修复】添加边界条件检查，提高健壮性
 * 
 * @param {Object} params - 参数
 * @param {Object} params.item - 上传项
 * @param {Array} params.history - 状态历史
 * @returns {boolean}
 */
export function shouldResumeWaiting({ item, history }) {
  // 【边界检查】如果没有item，默认回到waiting
  if (!item) {
    console.warn('[shouldResumeWaiting] item is undefined, defaulting to waiting');
    return true;
  }
  
  // 如果没有File对象，必须回到waiting让用户重新选择
  if (!item.file) {
    return true;
  }

  // 【边界检查】确保history是数组
  const safeHistory = Array.isArray(history) ? history : [];
  
  // 仅使用历史记录判断，不依赖外部状态
  // 【修复】添加空数组保护，避免some方法在空数组上的意外行为
  const wasWaiting = safeHistory.length > 0 && 
    safeHistory.some(h => h && (h.from === 'waiting' || h.to === 'waiting'));
  
  const hasFileHash = !!item.fileHash;
  
  // 【修复】确保数值比较安全，避免undefined比较
  const currentChunk = typeof item.currentChunk === 'number' ? item.currentChunk : 0;
  const chunkCount = typeof item.chunkCount === 'number' ? item.chunkCount : 0;
  const isMerging = item.isMerging || (currentChunk >= chunkCount && chunkCount > 0);

  return wasWaiting && !hasFileHash && !isMerging;
}

/**
 * 检查是否应该重新计算MD5
 * 【优化】小于32MB的小文件跳过MD5计算，提升上传速度
 * @param {Object} params - 参数
 * @param {Object} params.item - 上传项
 * @returns {boolean}
 */
export function shouldRecalculateMD5({ item }) {
  // 如果没有File对象，不能计算MD5
  if (!item?.file) {
    return false;
  }
  
  // 【优化】小于32MB的小文件跳过MD5计算
  // 32MB = 32 * 1024 * 1024 = 33554432 bytes
  const SKIP_MD5_THRESHOLD = 32 * 1024 * 1024;
  if (item.fileSize < SKIP_MD5_THRESHOLD && !item.forceRecalculateMD5) {
    return false;
  }
  
  return !item?.fileHash || item.forceRecalculateMD5;
}

/**
 * 检查是否应该恢复上传
 * 【优化】小文件跳过MD5后，不需要fileHash也能上传
 * @param {Object} params - 参数
 * @param {Object} params.item - 上传项
 * @returns {boolean}
 */
export function shouldResumeUpload({ item }) {
  // 必须有File对象
  if (!item?.file) {
    return false;
  }
  
  // 【优化】小文件(<32MB)跳过MD5，不需要fileHash
  const SKIP_MD5_THRESHOLD = 32 * 1024 * 1024;
  if (item.fileSize < SKIP_MD5_THRESHOLD) {
    return true;
  }
  
  // 大文件必须有fileHash才能恢复上传（支持断点续传）
  return !!item?.fileHash;
}

/**
 * 判断是否为普通上传（小文件，不需要合并）
 * @param {Object} params - 参数
 * @param {Object} params.item - 上传项
 * @returns {boolean}
 */
export function isNormalUpload({ item }) {
  // 如果没有totalChunks或totalChunks为1，认为是普通上传
  return !item?.totalChunks || item.totalChunks <= 1;
}

/**
 * 判断是否为分片上传（大文件，需要合并）
 * @param {Object} params - 参数
 * @param {Object} params.item - 上传项
 * @returns {boolean}
 */
export function isChunkedUpload({ item }) {
  // 如果有totalChunks且大于1，认为是分片上传
  return item?.totalChunks > 1;
}

/**
 * Guard 工厂函数 - 创建组合 guard
 * @param {...Function} guards - guard 函数数组
 * @returns {Function} 组合后的 guard
 */
export function combineGuards(...guards) {
  return (params) => guards.every(guard => guard(params));
}

/**
 * Guard 工厂函数 - 创建否定 guard
 * @param {Function} guard - guard 函数
 * @returns {Function} 否定后的 guard
 */
export function not(guard) {
  return (params) => !guard(params);
}
