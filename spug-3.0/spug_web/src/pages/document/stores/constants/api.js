/**
 * API端点常量
 */

const BASE_URL = '/api/document';

/**
 * API端点
 */
export const API_ENDPOINTS = {
  // 文件管理
  FILE_LIST: `${BASE_URL}/file/`,
  FILE_UPLOAD: `${BASE_URL}/upload/`,
  FILE_DOWNLOAD: `${BASE_URL}/file/download/`,
  FILE_PREVIEW: `${BASE_URL}/file/preview/`,
  FILE_COPY: `${BASE_URL}/file/copy/`,
  FILE_MOVE: `${BASE_URL}/file/move/`,
  FILE_RENAME: `${BASE_URL}/file/rename/`,
  FILE_DELETE: `${BASE_URL}/file/`,

  // 文件夹管理
  FOLDER_LIST: `${BASE_URL}/folder/`,
  FOLDER_CREATE: `${BASE_URL}/folder/`,
  FOLDER_UPDATE: `${BASE_URL}/folder/`,
  FOLDER_DELETE: `${BASE_URL}/folder/`,
  FOLDER_TREE: `${BASE_URL}/folder/tree/`,
  FOLDER_COPY: `${BASE_URL}/folder/copy/`,
  FOLDER_MOVE: `${BASE_URL}/folder/move/`,

  // 分片上传
  CHUNK_UPLOAD: `${BASE_URL}/upload_chunk/`,
  MERGE_CHUNKS: `${BASE_URL}/merge_chunks/`,
  CHECK_UPLOADED_CHUNKS: `${BASE_URL}/check_uploaded_chunks/`,
  MERGE_STATUS: `${BASE_URL}/merge_status/`,
  DIRECT_MERGE: `${BASE_URL}/direct_merge/`,

  // 传输记录
  TRANSFER_LIST: `${BASE_URL}/transfers/`,
  TRANSFER_CREATE: `${BASE_URL}/transfers/create/`,
  TRANSFER_UPDATE: `${BASE_URL}/transfers/`,
  TRANSFER_CANCEL: (id) => `${BASE_URL}/transfers/${id}/cancel/`,
  TRANSFER_PAUSE: (id) => `${BASE_URL}/transfers/${id}/pause/`,
  TRANSFER_RESUME: (id) => `${BASE_URL}/transfers/${id}/resume/`,
  TRANSFER_DELETE: (id) => `${BASE_URL}/transfers/${id}/delete/`,
  TRANSFER_COMPLETE: (id) => `${BASE_URL}/transfers/${id}/complete/`,
  TRANSFER_FAIL: (id) => `${BASE_URL}/transfers/${id}/fail/`,
  TRANSFER_PROGRESS: (id) => `${BASE_URL}/transfers/${id}/progress/`,
  TRANSFER_STATUS: (id) => `${BASE_URL}/transfers/${id}/status/`,
  TRANSFER_UPDATE_HASH: (id) => `${BASE_URL}/transfers/${id}/update_hash/`,
  TRANSFERS_BATCH_PAUSE: `${BASE_URL}/transfers/batch/pause/`,
  TRANSFERS_BATCH_RESUME: `${BASE_URL}/transfers/batch/resume/`,
  TRANSFERS_BATCH_CANCEL: `${BASE_URL}/transfers/batch/cancel/`,
  TRANSFERS_BATCH_DELETE: `${BASE_URL}/transfers/batch/delete/`,

  // 回收站
  RECYCLE_BIN_LIST: `${BASE_URL}/recycle-bin/`,
  RECYCLE_BIN_RESTORE: `${BASE_URL}/recycle-bin/restore/`,
  RECYCLE_BIN_DELETE: `${BASE_URL}/recycle-bin/delete/`,
  RECYCLE_BIN_STATS: `${BASE_URL}/recycle-bin/stats/`,

  // 搜索
  SEARCH: `${BASE_URL}/search/`,

  // 磁盘
  DISK_INFO: `${BASE_URL}/disk/`,
};
