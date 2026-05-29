/**
 * UploadCore 常量定义
 * 从原 index.js 中提取的核心常量
 * 
 * 注意：此文件从 stores/constants/upload.js 重新导出核心常量
 * 避免循环导入问题
 */

// 从主常量文件导入
import { UPLOAD_CONSTANTS as ORIGINAL_UPLOAD_CONSTANTS, generateUploadId as originalGenerateUploadId } from '../../constants/upload';

// 重新导出 UPLOAD_CONSTANTS
export const UPLOAD_CONSTANTS = ORIGINAL_UPLOAD_CONSTANTS;

// 重新导出函数
export { 
  generateUploadId, 
  getMD5ChunkSize, 
  getMD5WorkerPath,
  // 【任务3.2】导出抽样MD5函数
  shouldUseSamplingMD5,
  getSamplingRanges,
  generateSamplingHash,
} from '../../constants/upload';

// 导出 API_ENDPOINTS
export { API_ENDPOINTS } from '../../constants/api';

// 并发控制（单独导出以便解构使用）
export const MAX_CONCURRENT_UPLOADS = ORIGINAL_UPLOAD_CONSTANTS.MAX_CONCURRENT_UPLOADS;

// 分片上传阈值
export const NORMAL_UPLOAD_THRESHOLD = ORIGINAL_UPLOAD_CONSTANTS.NORMAL_UPLOAD_THRESHOLD;

// 分片大小
export const CHUNK_SIZE = ORIGINAL_UPLOAD_CONSTANTS.CHUNK_SIZE;

// 批量警告阈值
export const BATCH_WARNING_THRESHOLD = ORIGINAL_UPLOAD_CONSTANTS.BATCH_WARNING_THRESHOLD;

// 最大显示数量
export const MAX_DISPLAY_COUNT = ORIGINAL_UPLOAD_CONSTANTS.MAX_DISPLAY_COUNT;

// 并发槽位等待间隔
export const CONCURRENT_SLOT_WAIT_INTERVAL = ORIGINAL_UPLOAD_CONSTANTS.CONCURRENT_CHECK_INTERVAL || 500;

// 清理配置
export const QUEUE_CLEANUP_INTERVAL = ORIGINAL_UPLOAD_CONSTANTS.QUEUE_CLEANUP_INTERVAL || 30000;
export const COMPLETED_ITEM_MAX_AGE = 5 * 60000;       // 5分钟
export const STATE_MACHINE_CLEANUP_INTERVAL = 60000;   // 1分钟

// 防抖延迟
export const DEBOUNCE_DELAY_BATCH = 300;    // 批量操作防抖 300ms
export const DEBOUNCE_DELAY_ITEM = 200;     // 单任务操作防抖 200ms

// 状态映射：后端状态 -> 前端状态
export const BACKEND_STATUS_MAP = {
  'UPLOADING': 'uploading',
  'PAUSED': 'paused',
  'MERGING': 'merging',
  'COMPLETED': 'completed',
  'FAILED': 'error',
  'CANCELED': 'cancelled',
  'PENDING': 'waiting',
};

// 前端状态 -> 后端状态
export const FRONTEND_STATUS_MAP = {
  'calculating': 'UPLOADING',
  'uploading': 'UPLOADING',
  'merging': 'MERGING',
  'paused': 'PAUSED',
  'completed': 'COMPLETED',
  'error': 'FAILED',
  'cancelled': 'CANCELED',
};

// 终态集合
export const FINAL_STATES = ['completed', 'error', 'cancelled'];

// 活跃状态集合（占用并发槽位）
export const ACTIVE_STATES = ['calculating', 'uploading', 'merging'];

// 可上传的来源状态
export const UPLOADABLE_FROM_STATES = ['paused', 'waiting', 'calculating'];

// 需要显示在活跃列表中的状态
export const DISPLAY_ACTIVE_STATUSES = ['uploading', 'calculating', 'merging', 'paused', 'waiting'];
