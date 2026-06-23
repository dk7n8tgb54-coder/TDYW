/**
 * 彩色文件类型 SVG 图标
 * 仿 Google Drive / 百度网盘风格，每种文件类型有专属颜色 + 类型标记
 * 替代 emoji 方案，解决跨平台渲染不一致问题
 */
import React from 'react';

// 图标尺寸预设
export const ICON_SIZES = {
  small: 16,
  default: 20,
  large: 32,
  xlarge: 48,
  xxlarge: 80,
};

/** 小尺寸阈值：低于此值隐藏角标文字，只留色块 */
const TEXT_THRESHOLD = 14;

/**
 * 文件底板 SVG（折角纸 + 角标色块）
 * @param {string} color - 角标颜色
 * @param {number} size - 图标尺寸
 */
const FileBase = ({ color, size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    {/* 纸张主体 */}
    <path d="M4 2C4 1.44772 4.44772 1 5 1H15L20 6V22C20 22.5523 19.5523 23 19 23H5C4.44772 23 4 22.5523 4 22V2Z" fill="#F5F5F5" stroke="#D9D9D9" strokeWidth="0.5"/>
    {/* 折角 */}
    <path d="M15 1L20 6H16C15.4477 6 15 5.55228 15 5V1Z" fill="#E8E8E8" stroke="#D9D9D9" strokeWidth="0.5"/>
    {/* 角标色块 */}
    <path d="M4 16H20V22C20 22.5523 19.5523 23 19 23H5C4.44772 23 4 22.5523 4 22V16Z" fill={color}/>
  </svg>
);

/**
 * 文件夹 SVG
 * @param {number} size - 图标尺寸
 * @param {boolean} open - 是否为打开的文件夹
 */
export const FolderIcon = ({ size = 20, open = false }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    {open ? (
      <>
        {/* 打开的文件夹后面 */}
        <path d="M2 6C2 5.44772 2.44772 5 3 5H9L11 7H21C21.5523 7 22 7.44772 22 8V18C22 18.5523 21.5523 19 21 19H3C2.44772 19 2 18.5523 2 18V6Z" fill="#FFC107"/>
        {/* 打开的文件夹前面 */}
        <path d="M2 9H22L20 20C19.912 20.4997 19.5523 21 19 21H3C2.44772 21 2 20.5523 2 20V9Z" fill="#FFCA28"/>
      </>
    ) : (
      <>
        {/* 关闭的文件夹后面 */}
        <path d="M2 6C2 5.44772 2.44772 5 3 5H9L11 7H21C21.5523 7 22 7.44772 22 8V18C22 18.5523 21.5523 19 21 19H3C2.44772 19 2 18.5523 2 18V6Z" fill="#FFA000"/>
        {/* 关闭的文件夹前面 */}
        <path d="M2 9H22V18C22 18.5523 21.5523 19 21 19H3C2.44772 19 2 18.5523 2 18V9Z" fill="#FFC107"/>
      </>
    )}
  </svg>
);

/** PDF 图标 — 红色角标 + "PDF"（小尺寸只显示色块） */
export const PdfIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M4 2C4 1.44772 4.44772 1 5 1H15L20 6V22C20 22.5523 19.5523 23 19 23H5C4.44772 23 4 22.5523 4 22V2Z" fill="#FFEBEE" stroke="#E53935" strokeWidth="0.5"/>
    <path d="M15 1L20 6H16C15.4477 6 15 5.55228 15 5V1Z" fill="#FFCDD2" stroke="#E53935" strokeWidth="0.5"/>
    <path d="M4 16H20V22C20 22.5523 19.5523 23 19 23H5C4.44772 23 4 22.5523 4 22V16Z" fill="#E53935"/>
    {size >= TEXT_THRESHOLD && <text x="12" y="20.5" textAnchor="middle" fill="white" fontSize="5" fontWeight="bold" fontFamily="Arial">PDF</text>}
  </svg>
);

/** Word 图标 — 蓝色角标 + "W"（小尺寸只显示色块） */
export const WordIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M4 2C4 1.44772 4.44772 1 5 1H15L20 6V22C20 22.5523 19.5523 23 19 23H5C4.44772 23 4 22.5523 4 22V2Z" fill="#E3F2FD" stroke="#1565C0" strokeWidth="0.5"/>
    <path d="M15 1L20 6H16C15.4477 6 15 5.55228 15 5V1Z" fill="#BBDEFB" stroke="#1565C0" strokeWidth="0.5"/>
    <path d="M4 16H20V22C20 22.5523 19.5523 23 19 23H5C4.44772 23 4 22.5523 4 22V16Z" fill="#1565C0"/>
    {size >= TEXT_THRESHOLD && <text x="12" y="20.5" textAnchor="middle" fill="white" fontSize="6" fontWeight="bold" fontFamily="Arial">W</text>}
  </svg>
);

/** Excel 图标 — 绿色角标 + "X"（小尺寸只显示色块） */
export const ExcelIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M4 2C4 1.44772 4.44772 1 5 1H15L20 6V22C20 22.5523 19.5523 23 19 23H5C4.44772 23 4 22.5523 4 22V2Z" fill="#E8F5E9" stroke="#2E7D32" strokeWidth="0.5"/>
    <path d="M15 1L20 6H16C15.4477 6 15 5.55228 15 5V1Z" fill="#C8E6C9" stroke="#2E7D32" strokeWidth="0.5"/>
    <path d="M4 16H20V22C20 22.5523 19.5523 23 19 23H5C4.44772 23 4 22.5523 4 22V16Z" fill="#2E7D32"/>
    {size >= TEXT_THRESHOLD && <text x="12" y="20.5" textAnchor="middle" fill="white" fontSize="6" fontWeight="bold" fontFamily="Arial">X</text>}
  </svg>
);

/** PPT 图标 — 橙色角标 + "P"（小尺寸只显示色块） */
export const PptIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M4 2C4 1.44772 4.44772 1 5 1H15L20 6V22C20 22.5523 19.5523 23 19 23H5C4.44772 23 4 22.5523 4 22V2Z" fill="#FFF3E0" stroke="#E65100" strokeWidth="0.5"/>
    <path d="M15 1L20 6H16C15.4477 6 15 5.55228 15 5V1Z" fill="#FFE0B2" stroke="#E65100" strokeWidth="0.5"/>
    <path d="M4 16H20V22C20 22.5523 19.5523 23 19 23H5C4.44772 23 4 22.5523 4 22V16Z" fill="#E65100"/>
    {size >= TEXT_THRESHOLD && <text x="12" y="20.5" textAnchor="middle" fill="white" fontSize="6" fontWeight="bold" fontFamily="Arial">P</text>}
  </svg>
);

/** 图片图标 — 紫色角标 + 山景 */
export const ImageIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M4 2C4 1.44772 4.44772 1 5 1H15L20 6V22C20 22.5523 19.5523 23 19 23H5C4.44772 23 4 22.5523 4 22V2Z" fill="#F3E5F5" stroke="#7B1FA2" strokeWidth="0.5"/>
    <path d="M15 1L20 6H16C15.4477 6 15 5.55228 15 5V1Z" fill="#E1BEE7" stroke="#7B1FA2" strokeWidth="0.5"/>
    <path d="M4 16H20V22C20 22.5523 19.5523 23 19 23H5C4.44772 23 4 22.5523 4 22V16Z" fill="#7B1FA2"/>
    {/* 山景图标 */}
    <path d="M7 14L10 10L12.5 12.5L15 9L18 14H7Z" fill="#CE93D8" opacity="0.6"/>
    <circle cx="8.5" cy="9.5" r="1.5" fill="#CE93D8" opacity="0.6"/>
  </svg>
);

/** 视频图标 — 深蓝角标 + 播放三角 */
export const VideoIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M4 2C4 1.44772 4.44772 1 5 1H15L20 6V22C20 22.5523 19.5523 23 19 23H5C4.44772 23 4 22.5523 4 22V2Z" fill="#E8EAF6" stroke="#283593" strokeWidth="0.5"/>
    <path d="M15 1L20 6H16C15.4477 6 15 5.55228 15 5V1Z" fill="#C5CAE9" stroke="#283593" strokeWidth="0.5"/>
    <path d="M4 16H20V22C20 22.5523 19.5523 23 19 23H5C4.44772 23 4 22.5523 4 22V16Z" fill="#283593"/>
    {/* 播放三角 */}
    <path d="M10 9L16 12L10 15V9Z" fill="#7986CB" opacity="0.7"/>
  </svg>
);

/** 音频图标 — 粉色角标 + 音符 */
export const AudioIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M4 2C4 1.44772 4.44772 1 5 1H15L20 6V22C20 22.5523 19.5523 23 19 23H5C4.44772 23 4 22.5523 4 22V2Z" fill="#FCE4EC" stroke="#AD1457" strokeWidth="0.5"/>
    <path d="M15 1L20 6H16C15.4477 6 15 5.55228 15 5V1Z" fill="#F8BBD0" stroke="#AD1457" strokeWidth="0.5"/>
    <path d="M4 16H20V22C20 22.5523 19.5523 23 19 23H5C4.44772 23 4 22.5523 4 22V16Z" fill="#AD1457"/>
    {/* 音符 */}
    <circle cx="9" cy="18" r="1.5" fill="#F8BBD0" opacity="0.8"/>
    <rect x="10.5" y="10" width="0.8" height="8" fill="#F8BBD0" opacity="0.8"/>
    <path d="M11.3 10L15 8.5V11L11.3 12.5V10Z" fill="#F8BBD0" opacity="0.8"/>
  </svg>
);

/** 压缩包图标 — 黄棕角标 + 拉链 */
export const ArchiveIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M4 2C4 1.44772 4.44772 1 5 1H15L20 6V22C20 22.5523 19.5523 23 19 23H5C4.44772 23 4 22.5523 4 22V2Z" fill="#FFF8E1" stroke="#F57F17" strokeWidth="0.5"/>
    <path d="M15 1L20 6H16C15.4477 6 15 5.55228 15 5V1Z" fill="#FFECB3" stroke="#F57F17" strokeWidth="0.5"/>
    <path d="M4 16H20V22C20 22.5523 19.5523 23 19 23H5C4.44772 23 4 22.5523 4 22V16Z" fill="#F57F17"/>
    {/* 拉链图标 */}
    <rect x="10" y="8" width="4" height="1.5" fill="#FFCA28" rx="0.3"/>
    <rect x="10" y="10.5" width="4" height="1.5" fill="#FFCA28" rx="0.3"/>
    <rect x="10" y="13" width="4" height="1.5" fill="#FFCA28" rx="0.3"/>
  </svg>
);

/** 文本图标 — 灰蓝角标 + 横线 */
export const TextIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M4 2C4 1.44772 4.44772 1 5 1H15L20 6V22C20 22.5523 19.5523 23 19 23H5C4.44772 23 4 22.5523 4 22V2Z" fill="#ECEFF1" stroke="#546E7A" strokeWidth="0.5"/>
    <path d="M15 1L20 6H16C15.4477 6 15 5.55228 15 5V1Z" fill="#CFD8DC" stroke="#546E7A" strokeWidth="0.5"/>
    <path d="M4 16H20V22C20 22.5523 19.5523 23 19 23H5C4.44772 23 4 22.5523 4 22V16Z" fill="#546E7A"/>
    {/* 文本横线 */}
    <rect x="7" y="8" width="10" height="1" fill="#90A4AE" rx="0.3"/>
    <rect x="7" y="10.5" width="8" height="1" fill="#90A4AE" rx="0.3"/>
    <rect x="7" y="13" width="6" height="1" fill="#90A4AE" rx="0.3"/>
  </svg>
);

/** 代码图标 — 青色角标 + "</>"（小尺寸只显示色块） */
export const CodeIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M4 2C4 1.44772 4.44772 1 5 1H15L20 6V22C20 22.5523 19.5523 23 19 23H5C4.44772 23 4 22.5523 4 22V2Z" fill="#E0F2F1" stroke="#00695C" strokeWidth="0.5"/>
    <path d="M15 1L20 6H16C15.4477 6 15 5.55228 15 5V1Z" fill="#B2DFDB" stroke="#00695C" strokeWidth="0.5"/>
    <path d="M4 16H20V22C20 22.5523 19.5523 23 19 23H5C4.44772 23 4 22.5523 4 22V16Z" fill="#00695C"/>
    {size >= TEXT_THRESHOLD && <text x="12" y="20.5" textAnchor="middle" fill="#80CBC4" fontSize="5" fontWeight="bold" fontFamily="monospace">&lt;/&gt;</text>}
  </svg>
);

/** 通用文件图标 — 灰色角标（无特殊类型时使用） */
export const FileIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M4 2C4 1.44772 4.44772 1 5 1H15L20 6V22C20 22.5523 19.5523 23 19 23H5C4.44772 23 4 22.5523 4 22V2Z" fill="#F5F5F5" stroke="#BDBDBD" strokeWidth="0.5"/>
    <path d="M15 1L20 6H16C15.4477 6 15 5.55228 15 5V1Z" fill="#E0E0E0" stroke="#BDBDBD" strokeWidth="0.5"/>
    <path d="M4 16H20V22C20 22.5523 19.5523 23 19 23H5C4.44772 23 4 22.5523 4 22V16Z" fill="#9E9E9E"/>
  </svg>
);

// ============================================================
// 右键菜单专用图标（小型单色）
// ============================================================

const MenuSvg = ({ children, size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 20 20" fill="currentColor" style={{ flexShrink: 0 }}>
    {children}
  </svg>
);

export const MenuIcons = {
  open: () => <MenuSvg><path d="M2 4C2 3.45 2.45 3 3 3H8L10 5H17C17.55 5 18 5.45 18 6V15C18 15.55 17.55 16 17 16H3C2.45 16 2 15.55 2 15V4Z"/></MenuSvg>,
  download: () => <MenuSvg><path d="M10 3V13M10 13L6 9M10 13L14 9M4 16H16" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round"/></MenuSvg>,
  copy: () => <MenuSvg><rect x="6" y="6" width="10" height="10" rx="1" stroke="currentColor" strokeWidth="1.5" fill="none"/><rect x="3" y="3" width="10" height="10" rx="1" stroke="currentColor" strokeWidth="1.5" fill="none" opacity="0.5"/></MenuSvg>,
  cut: () => <MenuSvg><circle cx="7" cy="14" r="2" stroke="currentColor" strokeWidth="1.5" fill="none"/><circle cx="13" cy="14" r="2" stroke="currentColor" strokeWidth="1.5" fill="none"/><path d="M8.5 12L12 4M11.5 12L8 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></MenuSvg>,
  rename: () => <MenuSvg><path d="M13 3L17 7M3 17L7 13L15 5L11 1L3 9V13L7 17Z" stroke="currentColor" strokeWidth="1.2" fill="none" strokeLinejoin="round"/></MenuSvg>,
  delete: () => <MenuSvg><path d="M5 5H15M8 5V4H12V5M6 5V16C6 16.55 6.45 17 7 17H13C13.55 17 14 16.55 14 16V5M9 8V14M11 8V14" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round"/></MenuSvg>,
  preview: () => <MenuSvg><path d="M1 10C3 6 6.5 4 10 4C13.5 4 17 6 19 10C17 14 13.5 16 10 16C6.5 16 3 14 1 10Z" stroke="currentColor" strokeWidth="1.5" fill="none"/><circle cx="10" cy="10" r="3" stroke="currentColor" strokeWidth="1.5" fill="none"/></MenuSvg>,
  properties: () => <MenuSvg><circle cx="10" cy="10" r="8" stroke="currentColor" strokeWidth="1.5" fill="none"/><path d="M10 6V11M10 13V14" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></MenuSvg>,
  newFolder: () => <MenuSvg><path d="M2 5C2 4.45 2.45 4 3 4H7L9 6H17C17.55 6 18 6.45 18 7V15C18 15.55 17.55 16 17 16H3C2.45 16 2 15.55 2 15V5Z" stroke="currentColor" strokeWidth="1.5" fill="none"/><path d="M10 9V13M8 11H12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></MenuSvg>,
};

// ============================================================
// 根据文件名/MIME类型返回对应图标组件
// ============================================================

export const getFileTypeIcon = (fileName, fileType, size = 20) => {
  let ext = '';
  if (fileName) {
    const parts = fileName.split('.');
    if (parts.length > 1) ext = parts[parts.length - 1].toLowerCase();
  }
  const mimeType = fileType ? fileType.toLowerCase() : '';

  if (ext === 'pdf' || mimeType.includes('pdf')) return <PdfIcon size={size} />;
  if (ext === 'doc' || ext === 'docx' || mimeType.includes('word') || mimeType.includes('document')) return <WordIcon size={size} />;
  if (ext === 'xls' || ext === 'xlsx' || mimeType.includes('excel') || mimeType.includes('spreadsheet')) return <ExcelIcon size={size} />;
  if (ext === 'ppt' || ext === 'pptx' || mimeType.includes('powerpoint') || mimeType.includes('presentation')) return <PptIcon size={size} />;
  if (ext === 'jpg' || ext === 'jpeg' || ext === 'png' || ext === 'gif' || ext === 'bmp' || ext === 'svg' || ext === 'webp' || mimeType.includes('image')) return <ImageIcon size={size} />;
  if (mimeType.includes('video') || ['mp4', 'avi', 'mov', 'wmv', 'flv', 'mkv', 'webm'].includes(ext)) return <VideoIcon size={size} />;
  if (mimeType.includes('audio') || ['mp3', 'wav', 'ogg', 'flac', 'aac'].includes(ext)) return <AudioIcon size={size} />;
  if (ext === 'zip' || ext === 'rar' || ext === '7z' || ext === 'tar' || ext === 'gz' || mimeType.includes('zip')) return <ArchiveIcon size={size} />;
  if (ext === 'txt' || ext === 'log' || ext === 'md' || mimeType.includes('text') || mimeType.includes('plain')) return <TextIcon size={size} />;
  if (['js', 'ts', 'jsx', 'tsx', 'vue', 'py', 'java', 'go', 'cpp', 'c', 'h', 'html', 'css', 'json', 'xml'].includes(ext)) return <CodeIcon size={size} />;

  return <FileIcon size={size} />;
};

/**
 * React 组件形式的文件类型图标（兼容 <FileTypeIcon fileName={...} mimeType={...} /> 用法）
 * TransferItem 等组件使用此默认导出
 * @param {string} fileName - 文件名（用于提取扩展名）
 * @param {string} mimeType - MIME 类型
 * @param {boolean} isFolder - 是否为文件夹
 * @param {number} size - 图标尺寸
 */
const FileTypeIconComponent = ({ fileName, mimeType, isFolder, size }) => {
  if (isFolder) return <FolderIcon size={size} />;
  return getFileTypeIcon(fileName, mimeType, size);
};

export default FileTypeIconComponent;
