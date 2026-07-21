/**
 * 上传工具函数集合
 * 所有函数从原代码中抽离，业务规则完全不变
 */

import { message } from 'antd';
import {
  PROGRESS_THROTTLE_DELAY,
  RETRY_DELAY_BASE,
  BATCH_UPLOAD_THRESHOLD,
  BATCH_UPLOAD_WARNING_TEMPLATE
} from '../stores/constants/upload';

// ============================================================
// 文件名长度限制常量
// ============================================================
export const MAX_FILE_NAME_LENGTH = 100; // 与后端数据库字段长度一致

// ============================================================
// 文件名合法性校验函数
// ============================================================
export function validateFileName(fileName) {
  // 校验文件名长度
  if (!fileName || fileName.length === 0) {
    return { valid: false, message: '文件名不能为空' };
  }
  if (fileName.length > MAX_FILE_NAME_LENGTH) {
    return { valid: false, message: `文件名过长（最大${MAX_FILE_NAME_LENGTH}字符），当前${fileName.length}字符` };
  }
  // 校验非法字符
  const forbiddenChars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|'];
  for (const char of forbiddenChars) {
    if (fileName.includes(char)) {
      return { valid: false, message: `文件名包含非法字符: ${char}` };
    }
  }
  // 校验路径遍历
  if (fileName.includes('..')) {
    return { valid: false, message: '文件名不能包含路径遍历符(..)' };
  }
  return { valid: true };
}

// ============================================================
// 进度节流更新函数
// 消除原代码中2处重复的进度节流逻辑
// ============================================================
export function createProgressUpdater(throttleDelay = PROGRESS_THROTTLE_DELAY) {
  let lastUpdateTime = 0;

  return (uploadId, uploadQueue, percent) => {
    const now = Date.now();
    if (now - lastUpdateTime >= throttleDelay || percent === 100) {
      lastUpdateTime = now;
      const item = uploadQueue.find(item => item.id === uploadId);
      if (item && item.percent !== percent) {
        item.percent = percent;
      }
    }
  };
}

// ============================================================
// 上传重试工具函数
// 消除原代码中2处重复的文件夹文件重试逻辑
// ============================================================
export async function retryUpload(uploadFn, maxRetry = 3, delayBase = 1000, maxDelay = 3000) {
  let retryCount = 0;
  let uploadSuccess = false;

  while (retryCount < maxRetry && !uploadSuccess) {
    try {
      await uploadFn();
      uploadSuccess = true;
    } catch (error) {
      retryCount++;
      if (retryCount < maxRetry) {
        const retryDelay = Math.min(delayBase * Math.pow(2, retryCount), maxDelay);
        await new Promise(resolve => setTimeout(resolve, retryDelay));
      } else {
        throw error;
      }
    }
  }
}

// ============================================================
// 错误日志标准化
// 统一的日志格式，便于内网问题排查
// ============================================================
export function logUploadError(type, fileInfo, error) {
  const timestamp = new Date().toISOString();
  const fileId = fileInfo?.id || 'unknown';
  const fileName = fileInfo?.name || 'unknown';
  const errorMessage = error?.message || error || 'unknown';

  console.error(`[传输错误] 时间:${timestamp} | 文件ID:${fileId} | 文件名:${fileName} | 类型:${type} | 错误:${errorMessage}`);
}

// ============================================================
// 批量上传提示函数
// 统一的批量文件上传提示逻辑
// ============================================================
export function showBatchUploadWarning(count) {
  // 【P1-14修复】统一使用 ES6 import 替代 require
  if (count > BATCH_UPLOAD_THRESHOLD) {
    message.warning(BATCH_UPLOAD_WARNING_TEMPLATE.replace('{count}', count));
  }
}

// ============================================================
// 重试延迟计算函数
// 基于重试次数计算指数退避延迟
// ============================================================
export function calculateRetryDelay(retryCount, maxDelay = 5000) {
  return Math.min(RETRY_DELAY_BASE * Math.pow(2, retryCount), maxDelay);
}
