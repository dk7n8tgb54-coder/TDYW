# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""规章附件物理文件存储工具

存储根目录复用资料库 volume：storage/documents/
规章附件独立子目录：storage/documents/regulation/{regulation_id}/{yyyy}/{mm}/{safe_name_uuid.ext}
数据库 file_path 只存相对路径：regulation/{regulation_id}/{yyyy}/{mm}/{safe_name_uuid.ext}

安全要求：
- 删除文件前必须校验最终路径仍位于 regulation/ 子目录内
- 规章模块只能读写 regulation/ 子目录下的文件
"""
import os
import re
import uuid
import hashlib
import logging
import datetime

from django.conf import settings

logger = logging.getLogger(__name__)

# 规章附件在 storage/documents 下的独立子目录名
REGULATION_SUBDIR = 'regulation'
MAX_STORED_BASENAME_LENGTH = 80
UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')

# 允许上传的文件扩展名白名单（小写，含点号）
ALLOWED_EXTENSIONS = frozenset({
    '.pdf', '.doc', '.docx', '.xls', '.xlsx',
    '.ppt', '.pptx', '.txt', '.md',
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp',
})

# 单文件大小上限（字节），默认 200MB
MAX_FILE_SIZE = getattr(settings, 'REGULATION_MAX_FILE_SIZE', 200 * 1024 * 1024)

# 可预览的文件扩展名（kkFileView 支持的类型 + 浏览器原生支持类型）
PREVIEWABLE_EXTENSIONS = frozenset({
    '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.pdf', '.txt', '.md',
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp',
})

# 浏览器原生可预览的文件类型（不需要 kkFileView，走 download inline 模式）
IMAGE_EXTENSIONS = frozenset({'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'})
PDF_EXTENSIONS = frozenset({'.pdf'})

# 预览令牌绑定的模块标识（与 evidence attachment_preview_token 的 module 字段一致）
PREVIEW_MODULE = 'regulation'
PREVIEW_OBJECT_TYPE = 'regulation'


def get_document_storage_base():
    """资料库存储根目录：storage/documents/（与资料库共用 volume）"""
    return os.path.join(settings.BASE_DIR, 'storage', 'documents')


def get_regulation_storage_base():
    """规章附件存储根目录：storage/documents/regulation/"""
    return os.path.join(get_document_storage_base(), REGULATION_SUBDIR)


def extract_extension(filename):
    """安全提取文件扩展名（小写，含点号），禁止路径穿越字符"""
    if not filename:
        return ''
    # 只取文件名部分，去掉任何路径分隔符
    basename = os.path.basename(filename)
    _, ext = os.path.splitext(basename)
    return ext.lower()


def _extract_original_extension(filename):
    """提取原始扩展名，保留大小写，仅用于生成可读物理文件名。"""
    if not filename:
        return ''
    basename = os.path.basename(str(filename).replace('\\', '/'))
    _, ext = os.path.splitext(basename)
    return ext


def _sanitize_filename_stem(original_name):
    """清洗原始文件名主体，保留可读性并避免路径/系统非法字符。"""
    if not original_name:
        return 'attachment'
    basename = os.path.basename(str(original_name).replace('\\', '/'))
    stem, _ = os.path.splitext(basename)
    stem = UNSAFE_FILENAME_CHARS.sub('_', stem)
    stem = re.sub(r'\s+', '_', stem).strip(' ._')
    stem = stem[:MAX_STORED_BASENAME_LENGTH].rstrip(' ._')
    return stem or 'attachment'


def build_stored_name(original_name):
    """生成可读且唯一的存储文件名：原名主体 + 唯一后缀 + 原扩展名。"""
    ext = _extract_original_extension(original_name)
    stem = _sanitize_filename_stem(original_name)
    suffix = uuid.uuid4().hex[:12]
    return f'{stem}_{suffix}{ext}'


def build_relative_path(regulation_id, stored_name):
    """生成相对路径：regulation/{regulation_id}/{yyyy}/{mm}/{stored_name}"""
    now = datetime.datetime.now()
    return os.path.join(
        REGULATION_SUBDIR,
        str(regulation_id),
        now.strftime('%Y'),
        now.strftime('%m'),
        stored_name,
    )


def resolve_absolute_path(relative_path):
    """将相对路径转为绝对路径，并校验位于 regulation/ 子目录内

    Raises:
        ValueError: 路径穿越或不在 regulation 子目录内
    """
    if not relative_path:
        raise ValueError('文件路径为空')
    # 规范化相对路径，防止 ../ 穿越
    normalized = os.path.normpath(relative_path)
    if normalized.startswith('..') or os.path.isabs(normalized):
        raise ValueError('非法文件路径')
    abs_path = os.path.join(get_document_storage_base(), normalized)
    reg_base = get_regulation_storage_base()
    if not _is_safe_path(reg_base, abs_path):
        raise ValueError('文件路径不在规章附件存储区域内')
    return abs_path


def _is_safe_path(base_path, target_path):
    """验证目标路径是否在基础路径内，防止路径穿越攻击"""
    base_path = os.path.normpath(base_path)
    target_path = os.path.normpath(target_path)
    try:
        common_prefix = os.path.commonpath([base_path, target_path])
        return common_prefix == base_path
    except ValueError:
        return False


def compute_md5(file_obj):
    """计算上传文件的 MD5 哈希（分块读取，避免内存溢出）"""
    md5 = hashlib.md5()
    for chunk in file_obj.chunks():
        md5.update(chunk)
    return md5.hexdigest()


def save_upload_file(file_obj, abs_path):
    """将上传文件写入磁盘（分块写入 + 同步计算 MD5）

    Returns:
        str: 文件 MD5 哈希
    """
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    md5 = hashlib.md5()
    with open(abs_path, 'wb') as f:
        for chunk in file_obj.chunks():
            f.write(chunk)
            md5.update(chunk)
    return md5.hexdigest()


def safe_delete_attachment_file(abs_path):
    """安全删除规章附件物理文件

    校验最终路径仍位于 regulation/ 子目录内后才删除。
    物理文件清理失败不抛异常，仅记录日志。

    Returns:
        tuple: (是否成功, 错误消息或 None)
    """
    if not abs_path or not os.path.exists(abs_path):
        return True, None

    reg_base = get_regulation_storage_base()
    if not _is_safe_path(reg_base, abs_path):
        logger.error(f'[Regulation] Refused to delete file outside regulation subdir: {abs_path}')
        return False, '文件路径不在规章附件存储区域内，拒绝删除'

    try:
        os.remove(abs_path)
        return True, None
    except OSError as e:
        logger.error(f'[Regulation] Failed to delete attachment file: {abs_path}, error={e}')
        return False, str(e)
