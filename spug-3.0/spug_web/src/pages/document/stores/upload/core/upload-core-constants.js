/**
 * UploadCore 常量定义
 * 从原 index.js 中提取的核心常量
 * 
 * 注意：此文件从 stores/constants/upload.js 重新导出核心常量
 * 避免循环导入问题
 */

// 从主常量文件导入
import { UPLOAD_CONSTANTS as ORIGINAL_UPLOAD_CONSTANTS } from '../../constants/upload';

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

// ============================================================
// 状态枚举（统一来源，避免在多处重复定义状态字符串）
// ============================================================

/**
 * 上传任务的所有可能状态
 * 任何新增/删除状态都必须同步更新以下位置：
 *   - index.js 的 uploadingItems / completedItems / errorItems / cancelledItems
 *   - TransferList.js 的 activeItems / pausedItems
 *   - UploadStateMachine.js 的 STATES 静态常量
 */
export const UPLOAD_STATUS = Object.freeze({
  WAITING: 'waiting',
  CALCULATING: 'calculating',
  UPLOADING: 'uploading',
  DOWNLOADING: 'downloading',
  PAUSED: 'paused',
  MERGING: 'merging',
  COMPLETED: 'completed',
  ERROR: 'error',
  CANCELLED: 'cancelled',
});

// 终态集合（状态机不会从这些状态继续转换）
export const TERMINAL_STATUSES = Object.freeze([
  UPLOAD_STATUS.COMPLETED,
  UPLOAD_STATUS.ERROR,
  UPLOAD_STATUS.CANCELLED,
]);

// 活跃状态集合（占用并发槽位）
// 注意：merging 仍在活跃列表中用于统计展示，但不再占用上传并发槽位
export const ACTIVE_STATUSES = Object.freeze([
  UPLOAD_STATUS.CALCULATING,
  UPLOAD_STATUS.UPLOADING,
  UPLOAD_STATUS.MERGING,
]);

// 等待/处理中状态集合（不占用并发槽位但仍在进行）
export const PENDING_STATUSES = Object.freeze([
  UPLOAD_STATUS.WAITING,
]);

// 【P0修复 2026-06-27】语义更精准的状态集合，替代各处硬编码数组

/**
 * 占用上传并发槽位的状态（仅 calculating + uploading）
 * 用于：UploadCoordinator.startWaiting / DebounceController.resumeAll / RecoveryCoordinator 的 countByStates
 * merging 不占槽位（后端合并、前端只轮询，不占前端网络/CPU 资源）
 */
export const SLOT_OCCUPYING_STATUSES = Object.freeze([
  UPLOAD_STATUS.CALCULATING,
  UPLOAD_STATUS.UPLOADING,
]);

/**
 * 可暂停的状态（waiting + calculating + uploading）
 * 用于：TransferItem canPause / VirtualTransferList pauseableCount / StateMachineManager.batchPause
 * merging 不可暂停（状态机无 PAUSE 转换，会让按钮失效）
 * paused 不可暂停（已暂停）
 */
export const PAUSEABLE_STATUSES = Object.freeze([
  UPLOAD_STATUS.WAITING,
  UPLOAD_STATUS.CALCULATING,
  UPLOAD_STATUS.UPLOADING,
]);

/**
 * 传输列表"进行中"页签应展示的状态
 * 用于：UploadCoreStore.uploadingItems / activeCount / TransferList isUploadingStatus / MiniBar 计数
 * 包含 paused（暂停只是临时态，仍在进行中列表展示）
 */
export const DISPLAY_UPLOADING_STATUSES = Object.freeze([
  UPLOAD_STATUS.WAITING,
  UPLOAD_STATUS.CALCULATING,
  UPLOAD_STATUS.UPLOADING,
  UPLOAD_STATUS.PAUSED,
  UPLOAD_STATUS.MERGING,
]);

// 状态映射：后端状态 -> 前端状态
export const BACKEND_STATUS_MAP = {
  'UPLOADING': 'uploading',
  'DOWNLOADING': 'downloading',
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
  'downloading': 'DOWNLOADING',
  'merging': 'MERGING',
  'paused': 'PAUSED',
  'completed': 'COMPLETED',
  'error': 'FAILED',
  'cancelled': 'CANCELED',
};

// 终态集合
export const FINAL_STATES = ['completed', 'error', 'cancelled'];

// ============================================================
// 错误分类枚举（2026-06-06 新增）
// 行业惯例：错误区分"可重试"与"不可重试"，UI 据此决定按钮
// ============================================================

/**
 * 错误码枚举
 * 任意位置产生错误时都应附带 errorCode，用于前端决定 UX
 */
export const ERROR_CODES = Object.freeze({
  NETWORK: 'NETWORK',             // 网络问题（超时/断网/DNS）—— 可重试
  SERVER: 'SERVER',               // 服务端 5xx —— 可重试
  CLIENT: 'CLIENT',               // 客户端 4xx（请求格式错）—— 不可重试
  PERMISSION: 'PERMISSION',       // 401/403 权限错误 —— 不可重试
  QUOTA: 'QUOTA',                 // 413/磁盘满/配额超限 —— 不可重试
  MD5_MISMATCH: 'MD5_MISMATCH',   // 文件校验失败（分片损坏/篡改）—— 可重试（重新传）
  CHUNK: 'CHUNK',                 // 分片上传失败 —— 可重试
  MERGE: 'MERGE',                 // 服务端合并失败 —— 可重试
  CANCELLED: 'CANCELLED',         // 用户主动取消（实际用 cancelled 状态，errorCode 作为冗余）
  UNKNOWN: 'UNKNOWN',             // 未知错误 —— 默认可重试
});

/**
 * 错误码 → 是否可重试
 * UI 根据此映射决定是否显示"重试"按钮
 */
export const RETRYABLE_ERROR_CODES = Object.freeze(new Set([
  ERROR_CODES.NETWORK,
  ERROR_CODES.SERVER,
  ERROR_CODES.MD5_MISMATCH,
  ERROR_CODES.CHUNK,
  ERROR_CODES.MERGE,
  ERROR_CODES.UNKNOWN,
]));

/**
 * 不可重试的错误码
 */
export const NON_RETRYABLE_ERROR_CODES = Object.freeze(new Set([
  ERROR_CODES.CLIENT,
  ERROR_CODES.PERMISSION,
  ERROR_CODES.QUOTA,
  ERROR_CODES.CANCELLED,
]));

/**
 * 错误码 → 用户友好的提示文案（可选；缺省时使用 item.error 原始文本）
 */
export const ERROR_CODE_MESSAGES = Object.freeze({
  [ERROR_CODES.NETWORK]: '网络连接失败，请检查网络后重试',
  [ERROR_CODES.SERVER]: '服务暂时不可用，请稍后重试',
  [ERROR_CODES.CLIENT]: '请求格式错误，请联系管理员',
  [ERROR_CODES.PERMISSION]: '没有上传权限，请联系管理员',
  [ERROR_CODES.QUOTA]: '存储空间已满，请清理后重试',
  [ERROR_CODES.MD5_MISMATCH]: '文件校验失败，请重新上传',
  [ERROR_CODES.CHUNK]: '分片上传失败，请重试',
  [ERROR_CODES.MERGE]: '服务端合并失败，请重试',
  [ERROR_CODES.CANCELLED]: '已取消',
  [ERROR_CODES.UNKNOWN]: '上传失败，请重试',
});

// 【已废弃】请使用 ACTIVE_STATUSES（frozen 版本），保留仅为向后兼容
export const ACTIVE_STATES = ['calculating', 'uploading', 'merging'];

// 可上传的来源状态
export const UPLOADABLE_FROM_STATES = ['paused', 'waiting', 'calculating'];

// 【已废弃】请使用 DISPLAY_UPLOADING_STATUSES（frozen 版本），保留仅为向后兼容
export const DISPLAY_ACTIVE_STATUSES = ['uploading', 'calculating', 'merging', 'paused', 'waiting'];

// ============================================================
// 上传压力等级配置（2026-07-02 新增）
// 前端根据后端 /api/document/upload_pressure/ 返回的 level
// 动态调整上传并发，避免多账号同时上传大文件时压垮后端
// ============================================================

/**
 * 压力等级枚举
 * normal   : 服务器正常，使用默认高并发
 * busy     : 服务器繁忙，降低并发
 * critical : 服务器压力高，最低速上传模式
 */
export const PRESSURE_LEVELS = Object.freeze({
  NORMAL: 'normal',
  BUSY: 'busy',
  CRITICAL: 'critical',
});

/**
 * 等级 -> 建议并发配置
 * 与后端 views/pressure.py 的 LEVEL_CONFIG 保持一致
 */
export const PRESSURE_LEVEL_CONFIG = Object.freeze({
  [PRESSURE_LEVELS.NORMAL]: {
    maxConcurrentUploads: UPLOAD_CONSTANTS.MAX_CONCURRENT_UPLOADS, // 3
    maxConcurrentChunks: UPLOAD_CONSTANTS.MAX_CONCURRENT_CHUNKS,   // 3
    message: '',
  },
  [PRESSURE_LEVELS.BUSY]: {
    maxConcurrentUploads: 2,
    maxConcurrentChunks: 2,
    message: '服务器繁忙，已降低上传并发',
  },
  [PRESSURE_LEVELS.CRITICAL]: {
    maxConcurrentUploads: 1,
    maxConcurrentChunks: 1,
    message: '服务器压力较高，已进入低速上传模式',
  },
});

/**
 * 压力恢复保守阈值
 * 连续 N 次轮询都为 normal 后才恢复高并发，避免并发频繁抖动
 */
export const PRESSURE_RECOVERY_THRESHOLD = 3;

/**
 * 压力轮询间隔（毫秒）
 * 上传过程中每 15 秒拉取一次服务器压力
 */
export const PRESSURE_POLL_INTERVAL = 15000;
