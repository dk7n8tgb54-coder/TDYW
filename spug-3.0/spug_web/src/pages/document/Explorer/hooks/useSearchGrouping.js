/**
 * 搜索结果分组 Hook
 * 【任务4.2】从Explorer组件拆分出来的独立Hook
 * 职责：处理搜索结果按类型分组展示
 */
import React, { useMemo } from 'react';
import { FolderIcon, ImageIcon, VideoIcon, PdfIcon, ArchiveIcon, FileIcon } from '../../components/FileTypeIcon';

// 文件类型检测函数
const checkIsImage = (fileType) => {
  if (!fileType) return false;
  const type = fileType.toLowerCase();
  if (type.startsWith('image/')) return true;
  const imageExts = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'svg', 'webp', 'ico', 'tiff', 'tif'];
  return imageExts.includes(type);
};

const checkIsVideo = (fileType) => {
  if (!fileType) return false;
  const type = fileType.toLowerCase();
  if (type.startsWith('video/')) return true;
  const videoExts = ['mp4', 'avi', 'mov', 'wmv', 'flv', 'mkv', 'webm', 'm4v', 'mpg', 'mpeg', '3gp'];
  return videoExts.includes(type);
};

const checkIsDocument = (fileType) => {
  if (!fileType) return false;
  const type = fileType.toLowerCase();
  const docExts = ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'rtf', 'odt', 'ods', 'odp'];
  const docMimes = ['application/pdf', 'application/msword', 'application/vnd.openxmlformats-officedocument',
                    'application/vnd.ms-excel', 'application/vnd.ms-powerpoint', 'text/plain', 'text/rtf'];
  if (docExts.includes(type)) return true;
  return docMimes.some(mime => type.includes(mime));
};

const checkIsArchive = (fileType) => {
  if (!fileType) return false;
  const type = fileType.toLowerCase();
  const archiveExts = ['zip', 'rar', '7z', 'tar', 'gz', 'bz2', 'xz', 'tgz', 'bz', 'jar', 'war'];
  const archiveMimes = ['application/zip', 'application/x-rar', 'application/x-7z', 'application/x-tar',
                       'application/gzip', 'application/x-bzip', 'application/x-xz'];
  if (archiveExts.includes(type)) return true;
  return archiveMimes.some(mime => type.includes(mime));
};

// 分组配置
const GROUP_CONFIG = {
  folder: { title: <><FolderIcon size={14} /> 文件夹</>, order: 0 },
  image: { title: <><ImageIcon size={14} /> 图片</>, order: 1 },
  video: { title: <><VideoIcon size={14} /> 视频</>, order: 2 },
  document: { title: <><PdfIcon size={14} /> 文档</>, order: 3 },
  archive: { title: <><ArchiveIcon size={14} /> 压缩包</>, order: 4 },
  other: { title: <><FileIcon size={14} /> 其他</>, order: 5 },
};

/**
 * 获取文件所属分组
 * @param {Object} item - 文件项
 * @returns {string} 分组key
 */
const getItemGroup = (item) => {
  if (item.isFolder) return 'folder';
  if (checkIsImage(item.file_type)) return 'image';
  if (checkIsVideo(item.file_type)) return 'video';
  if (checkIsDocument(item.file_type)) return 'document';
  if (checkIsArchive(item.file_type)) return 'archive';
  return 'other';
};

/**
 * 搜索结果分组Hook
 * @param {Array} items - 搜索结果列表
 * @param {boolean} isSearching - 是否处于搜索模式
 * @returns {Array|null} 分组后的数据
 */
export const useSearchGrouping = (items, isSearching) => {
  return useMemo(() => {
    if (!isSearching || !items?.length) return null;

    const groups = {};
    
    // 初始化分组
    Object.keys(GROUP_CONFIG).forEach(key => {
      groups[key] = { key, ...GROUP_CONFIG[key], items: [] };
    });

    // 分类项目
    items.forEach(item => {
      const groupKey = getItemGroup(item);
      if (groups[groupKey]) {
        groups[groupKey].items.push(item);
      }
    });

    // 过滤空分组并按顺序返回
    return Object.values(groups)
      .filter(group => group.items.length > 0)
      .sort((a, b) => a.order - b.order);
  }, [items, isSearching]);
};

export default useSearchGrouping;
