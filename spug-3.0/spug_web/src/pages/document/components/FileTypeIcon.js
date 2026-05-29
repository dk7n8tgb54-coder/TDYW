/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 * 
 * 文件类型图标组件 - Emoji风格
 * 使用Emoji图标替代Ant Design图标
 */
import React from 'react';

// 文件类型图标映射 - Emoji风格
const FILE_ICONS = {
  // 图片
  'image': { emoji: '🖼️', label: '图片文件', color: '#52c41a', bgColor: '#f6ffed' },
  
  // 视频
  'video': { emoji: '🎬', label: '视频文件', color: '#722ed1', bgColor: '#f9f0ff' },
  
  // 音频
  'audio': { emoji: '🎵', label: '音频文件', color: '#eb2f96', bgColor: '#fff0f6' },
  
  // 文档
  'pdf': { emoji: '📄', label: 'PDF文档', color: '#ff4d4f', bgColor: '#fff2f0' },
  'word': { emoji: '📝', label: 'Word文档', color: '#1890ff', bgColor: '#e6f7ff' },
  'excel': { emoji: '📊', label: 'Excel表格', color: '#52c41a', bgColor: '#f6ffed' },
  'ppt': { emoji: '📽️', label: 'PPT演示', color: '#fa8c16', bgColor: '#fff7e6' },
  'text': { emoji: '📃', label: '文本文件', color: '#8c8c8c', bgColor: '#f5f5f5' },
  
  // 压缩包
  'zip': { emoji: '📦', label: '压缩文件', color: '#faad14', bgColor: '#fffbe6' },
  
  // 文件夹
  'folder': { emoji: '📁', label: '文件夹', color: '#faad14', bgColor: '#fffbe6' },
  
  // 代码文件
  'code': { emoji: '💻', label: '代码文件', color: '#13c2c2', bgColor: '#e6fffb' },
  
  // 默认
  'default': { emoji: '📎', label: '文件', color: '#8c8c8c', bgColor: '#f5f5f5' },
};

// 代码文件扩展名
const CODE_EXTENSIONS = ['js', 'jsx', 'ts', 'tsx', 'py', 'java', 'cpp', 'c', 'h', 'go', 'rs', 'php', 'rb', 'swift', 'kt', 'html', 'css', 'json', 'xml', 'yaml', 'yml', 'sql', 'sh', 'bash'];

/**
 * 获取文件类型配置
 * @param {string} fileName - 文件名
 * @param {string} mimeType - MIME类型
 * @param {boolean} isFolder - 是否文件夹
 */
const getFileTypeConfig = (fileName, mimeType, isFolder) => {
  if (isFolder) return FILE_ICONS['folder'];
  
  const ext = fileName?.split('.').pop()?.toLowerCase() || '';
  
  // 根据扩展名判断
  if (['pdf'].includes(ext)) return FILE_ICONS['pdf'];
  if (['doc', 'docx'].includes(ext)) return FILE_ICONS['word'];
  if (['xls', 'xlsx', 'csv'].includes(ext)) return FILE_ICONS['excel'];
  if (['ppt', 'pptx'].includes(ext)) return FILE_ICONS['ppt'];
  if (['txt', 'md', 'log'].includes(ext)) return FILE_ICONS['text'];
  if (['zip', 'rar', '7z', 'tar', 'gz', 'bz2'].includes(ext)) return FILE_ICONS['zip'];
  if (CODE_EXTENSIONS.includes(ext)) return FILE_ICONS['code'];
  // 视频文件扩展名
  if (['mp4', 'avi', 'mov', 'wmv', 'flv', 'mkv', 'webm', 'm4v', 'mpg', 'mpeg', '3gp'].includes(ext)) return FILE_ICONS['video'];
  // 音频文件扩展名
  if (['mp3', 'wav', 'flac', 'aac', 'ogg', 'wma', 'm4a'].includes(ext)) return FILE_ICONS['audio'];
  // 图片文件扩展名
  if (['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg', 'ico', 'tiff', 'tif'].includes(ext)) return FILE_ICONS['image'];
  
  // 根据 MIME 类型判断
  if (mimeType) {
    if (mimeType.startsWith('image/')) return FILE_ICONS['image'];
    if (mimeType.startsWith('video/')) return FILE_ICONS['video'];
    if (mimeType.startsWith('audio/')) return FILE_ICONS['audio'];
    if (mimeType.includes('pdf')) return FILE_ICONS['pdf'];
    if (mimeType.includes('word') || mimeType.includes('document')) return FILE_ICONS['word'];
    if (mimeType.includes('excel') || mimeType.includes('spreadsheet')) return FILE_ICONS['excel'];
    if (mimeType.includes('powerpoint') || mimeType.includes('presentation')) return FILE_ICONS['ppt'];
    if (mimeType.startsWith('text/')) return FILE_ICONS['text'];
    if (mimeType.includes('javascript') || mimeType.includes('json') || mimeType.includes('xml') || mimeType.includes('html')) return FILE_ICONS['code'];
  }
  
  return FILE_ICONS['default'];
};

/**
 * 文件类型图标组件 - Emoji风格
 * @param {Object} props
 * @param {string} props.fileName - 文件名
 * @param {string} props.mimeType - MIME类型
 * @param {boolean} props.isFolder - 是否文件夹
 * @param {number} props.size - 图标大小（默认40px）
 * @param {Object} props.style - 额外样式
 */
const FileTypeIcon = ({ fileName, mimeType, isFolder, size = 40, style = {} }) => {
  const config = getFileTypeConfig(fileName, mimeType, isFolder);
  
  return (
    <div
      style={{
        width: size,
        height: size,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: config.bgColor,
        borderRadius: 8,
        flexShrink: 0,
        transition: 'transform 0.2s',
        fontSize: size * 0.5,
        lineHeight: 1,
        ...style,
      }}
      title={config.label}
    >
      <span 
        role="img" 
        aria-label={config.label}
        style={{ 
          filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.1))',
        }}
      >
        {config.emoji}
      </span>
    </div>
  );
};

export default FileTypeIcon;
