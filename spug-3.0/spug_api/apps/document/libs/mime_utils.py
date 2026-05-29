# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
MIME 类型工具
提供文件 MIME 类型映射和查询
"""

# MIME 类型映射表
MIME_TYPES = {
    # 文档
    '.pdf': 'application/pdf',
    '.doc': 'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.xls': 'application/vnd.ms-excel',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.ppt': 'application/vnd.ms-powerpoint',
    '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    '.txt': 'text/plain',
    '.rtf': 'application/rtf',
    # 图片
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.gif': 'image/gif',
    '.bmp': 'image/bmp',
    '.svg': 'image/svg+xml',
    '.webp': 'image/webp',
    '.ico': 'image/x-icon',
    # 音频
    '.mp3': 'audio/mpeg',
    '.wav': 'audio/wav',
    '.ogg': 'audio/ogg',
    '.aac': 'audio/aac',
    '.flac': 'audio/flac',
    # 视频
    '.mp4': 'video/mp4',
    '.avi': 'video/x-msvideo',
    '.mkv': 'video/x-matroska',
    '.mov': 'video/quicktime',
    '.wmv': 'video/x-ms-wmv',
    '.flv': 'video/x-flv',
    '.webm': 'video/webm',
    # 压缩文件
    '.zip': 'application/zip',
    '.rar': 'application/x-rar-compressed',
    '.7z': 'application/x-7z-compressed',
    '.tar': 'application/x-tar',
    '.gz': 'application/gzip',
    # 代码
    '.js': 'text/javascript',
    '.json': 'application/json',
    '.xml': 'application/xml',
    '.html': 'text/html',
    '.css': 'text/css',
    '.py': 'text/x-python',
    '.java': 'text/x-java-source',
    '.c': 'text/x-c',
    '.cpp': 'text/x-c++',
    '.h': 'text/x-c',
    '.hpp': 'text/x-c++',
    # 扩展代码/文本类型
    '.ts': 'text/typescript',
    '.tsx': 'text/typescript',
    '.jsx': 'text/jsx',
    '.vue': 'text/x-vue',
    '.go': 'text/x-go',
    '.rs': 'text/x-rust',
    '.rb': 'text/x-ruby',
    '.php': 'text/x-php',
    '.sh': 'text/x-sh',
    '.bash': 'text/x-sh',
    '.zsh': 'text/x-sh',
    '.yaml': 'text/yaml',
    '.yml': 'text/yaml',
    '.toml': 'text/x-toml',
    '.sql': 'text/x-sql',
    '.md': 'text/markdown',
    '.csv': 'text/csv',
    '.log': 'text/plain',
    '.ini': 'text/plain',
    '.cfg': 'text/plain',
    '.conf': 'text/plain',
    '.env': 'text/plain',
    '.gitignore': 'text/plain',
    '.dockerfile': 'text/plain',
    '.tf': 'text/x-hcl',
    '.proto': 'text/x-proto',
    '.lua': 'text/x-lua',
    '.r': 'text/x-r',
    '.scala': 'text/x-scala',
    '.kt': 'text/x-kotlin',
    '.swift': 'text/x-swift',
    '.dart': 'text/x-dart',
    '.ps1': 'text/x-powershell',
    '.bat': 'text/x-bat',
    '.makefile': 'text/plain',
    # 工程文件
    '.dwg': 'application/octet-stream',
    '.dxf': 'application/octet-stream',
    '.stp': 'application/octet-stream',
    '.iges': 'application/octet-stream',
    '.igs': 'application/octet-stream',
}


def get_mime_type(file_name):
    """根据文件名获取 MIME 类型"""
    import os
    file_ext = os.path.splitext(file_name)[1].lower()
    return MIME_TYPES.get(file_ext, 'application/octet-stream')
