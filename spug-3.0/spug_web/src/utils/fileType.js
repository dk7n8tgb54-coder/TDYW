/**
 * 文件类型判断工具函数
 * @module utils/fileType
 * @description 提供文件类型判断和图标获取功能
 */

// 图片文件扩展名
const IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg', 'ico'];

// 视频文件扩展名
const VIDEO_EXTENSIONS = ['mp4', 'avi', 'mov', 'wmv', 'flv', 'mkv', 'webm'];

// 音频文件扩展名
const AUDIO_EXTENSIONS = ['mp3', 'wav', 'wma', 'aac', 'flac', 'ogg'];

// 文档文件扩展名
const DOCUMENT_EXTENSIONS = ['doc', 'docx', 'pdf', 'txt', 'xls', 'xlsx', 'ppt', 'pptx'];

// 压缩文件扩展名
const ARCHIVE_EXTENSIONS = ['zip', 'rar', '7z', 'tar', 'gz', 'bz2'];

// 代码文件扩展名
const CODE_EXTENSIONS = ['js', 'jsx', 'ts', 'tsx', 'py', 'java', 'cpp', 'c', 'h', 'html', 'css', 'json', 'xml'];

/**
 * 获取文件扩展名
 * @param {string} filename - 文件名
 * @returns {string} 小写的扩展名
 */
function getExtension(filename) {
  if (!filename) return '';
  const parts = filename.split('.');
  return parts.length > 1 ? parts.pop().toLowerCase() : '';
}

/**
 * 判断是否为图片文件
 * @param {string} filename - 文件名
 * @returns {boolean}
 */
export function isImage(filename) {
  return IMAGE_EXTENSIONS.includes(getExtension(filename));
}

/**
 * 判断是否为视频文件
 * @param {string} filename - 文件名
 * @returns {boolean}
 */
export function isVideo(filename) {
  return VIDEO_EXTENSIONS.includes(getExtension(filename));
}

/**
 * 判断是否为音频文件
 * @param {string} filename - 文件名
 * @returns {boolean}
 */
export function isAudio(filename) {
  return AUDIO_EXTENSIONS.includes(getExtension(filename));
}

/**
 * 判断是否为文档文件
 * @param {string} filename - 文件名
 * @returns {boolean}
 */
export function isDocument(filename) {
  return DOCUMENT_EXTENSIONS.includes(getExtension(filename));
}

/**
 * 判断是否为压缩文件
 * @param {string} filename - 文件名
 * @returns {boolean}
 */
export function isArchive(filename) {
  return ARCHIVE_EXTENSIONS.includes(getExtension(filename));
}

/**
 * 判断是否为代码文件
 * @param {string} filename - 文件名
 * @returns {boolean}
 */
export function isCode(filename) {
  return CODE_EXTENSIONS.includes(getExtension(filename));
}

/**
 * 获取文件类型
 * @param {string} filename - 文件名
 * @returns {string} 文件类型: 'image' | 'video' | 'audio' | 'document' | 'archive' | 'code' | 'other'
 */
export function getFileType(filename) {
  if (isImage(filename)) return 'image';
  if (isVideo(filename)) return 'video';
  if (isAudio(filename)) return 'audio';
  if (isDocument(filename)) return 'document';
  if (isArchive(filename)) return 'archive';
  if (isCode(filename)) return 'code';
  return 'other';
}

/**
 * 获取文件类型标签
 * @param {string} filename - 文件名
 * @returns {string} 文件类型标签
 */
export function getFileTypeLabel(filename) {
  const type = getFileType(filename);
  const labels = {
    image: '图片',
    video: '视频',
    audio: '音频',
    document: '文档',
    archive: '压缩包',
    code: '代码',
    other: '其他',
  };
  return labels[type] || '其他';
}

/**
 * 获取文件图标
 * @param {string} filename - 文件名
 * @returns {string} 图标类名或图标类型
 */
export function getFileIcon(filename) {
  const type = getFileType(filename);
  const icons = {
    image: 'picture',
    video: 'video-camera',
    audio: 'sound',
    document: 'file-text',
    archive: 'file-zip',
    code: 'code',
    other: 'file',
  };
  return icons[type] || 'file';
}

/**
 * 根据MIME类型判断文件类型
 * @param {string} mimeType - MIME类型
 * @returns {string} 文件类型
 */
export function getFileTypeFromMime(mimeType) {
  if (!mimeType) return 'other';

  const type = mimeType.toLowerCase();
  if (type.startsWith('image/')) return 'image';
  if (type.startsWith('video/')) return 'video';
  if (type.startsWith('audio/')) return 'audio';
  if (type.includes('pdf')) return 'document';
  if (type.includes('zip') || type.includes('compressed')) return 'archive';

  return 'other';
}
