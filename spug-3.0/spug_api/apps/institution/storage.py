# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""制度手册物理文件存储工具

存储根目录：storage/institution/（独立于资料库与规章附件）
- drafts/manual_{id}/...     当前草稿工作文件（新增文件直接落此目录）
- versions/manual_{id}/...   发布版本快照（不可变）
- submissions/manual_{id}/... 提交待发布核对快照（不可变，2026-11-03）
- originals/manual_{id}/...  已下线原稿体系的历史遗留目录：本模块不再写入，
  仅由独立的幂等清理命令 `purge_institution_originals`
  （original_cleanup.py）在限定目录内清理；整本手册删除时一并移除。

数据库 file_path 只存相对路径（相对 storage/institution/）。

安全要求：
- 删除文件前必须校验最终路径仍位于 institution/ 子目录内
- 本模块只能读写 institution/ 子目录下的文件
"""
import os
import re
import uuid
import hashlib
import logging
import datetime
import shutil

from django.conf import settings

logger = logging.getLogger(__name__)

INSTITUTION_SUBDIR = 'institution'
UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')

# 文件名主体字节上限（ext4/overlayfs 单文件名 255 字节，中文 UTF-8 占 3 字节），
# 预留 1(下划线)+12(唯一后缀)+5(扩展名) 并留余量，取 230。
MAX_STORED_BASENAME_BYTES = 230

# 允许上传的手册文件扩展名白名单（小写，含点号）
ALLOWED_EXTENSIONS = frozenset({'.doc', '.docx'})

# 可在线编辑的工作副本扩展名（.doc 需先转换为 .docx）
EDITABLE_EXTENSIONS = frozenset({'.docx'})

# 单文件大小上限（字节），默认 100MB
MAX_FILE_SIZE = getattr(settings, 'INSTITUTION_MAX_FILE_SIZE', 100 * 1024 * 1024)

# 预览令牌绑定的模块标识（与 evidence attachment_preview_token 的 module 字段一致）
PREVIEW_MODULE = 'institution'

# 已下线原稿体系的存储子目录（只读兼容：不再写入，仅供原稿清理命令
# 与整本手册删除定位；普通文件读写一律不得使用该目录）
LEGACY_ORIGINALS_SUBDIR = 'originals'

FILE_KIND_DRAFT = 'draft'
FILE_KIND_VERSION = 'version'
FILE_KIND_VERSION_FILE = 'vfile'  # 版本文件快照（ManualVersionFile）
FILE_KIND_SUBMISSION = 'submission'  # 提交待发布核对快照（ManualSubmission）

_KIND_TO_SUBDIR = {
    FILE_KIND_DRAFT: 'drafts',
    FILE_KIND_VERSION: 'versions',
    # 提交快照独立目录：与草稿替换、版本保留清理隔离，生命周期由提交
    # 状态机（撤回/退回/发布消费）管理
    FILE_KIND_SUBMISSION: 'submissions',
}


def get_institution_storage_base():
    """制度存储根目录：storage/institution/"""
    return os.path.join(settings.BASE_DIR, 'storage', INSTITUTION_SUBDIR)


def extract_extension(filename):
    """安全提取文件扩展名（小写，含点号）"""
    if not filename:
        return ''
    basename = os.path.basename(str(filename).replace('\\', '/'))
    _, ext = os.path.splitext(basename)
    return ext.lower()


def _truncate_bytes(text, max_bytes):
    """按 UTF-8 字节数截断文本，避免多字节字符被切半产生乱码"""
    encoded = text.encode('utf-8')
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode('utf-8', errors='ignore')


def _sanitize_filename_stem(original_name):
    """清洗原始文件名主体，保留可读性并避免路径/系统非法字符"""
    if not original_name:
        return 'manual_file'
    basename = os.path.basename(str(original_name).replace('\\', '/'))
    stem, _ = os.path.splitext(basename)
    stem = UNSAFE_FILENAME_CHARS.sub('_', stem)
    stem = re.sub(r'\s+', '_', stem).strip(' ._')
    stem = _truncate_bytes(stem, MAX_STORED_BASENAME_BYTES).rstrip(' ._')
    return stem or 'manual_file'


def build_stored_name(original_name):
    """生成可读且唯一的存储文件名：原名主体 + 唯一后缀 + 原扩展名"""
    ext = extract_extension(original_name)
    stem = _sanitize_filename_stem(original_name)
    suffix = uuid.uuid4().hex[:12]
    return f'{stem}_{suffix}{ext}'


def display_name(raw_name, fallback_stem='manual_file'):
    """界面展示/下载用的文件名：仅取 basename、替换文件系统非法字符，
    保留主体可读性（空/纯符号回退 fallback_stem）。

    存储名（build_stored_name，带唯一后缀防碰撞）与显示名（本函数）
    必须分离：ManualDraft/ManualVersion.original_name 存显示名，
    file_path 存存储名，序列化 file_name 取显示名。
    """
    basename = os.path.basename(str(raw_name or '').replace('\\', '/')).strip()
    basename = UNSAFE_FILENAME_CHARS.sub('_', basename).strip(' .')
    return basename or fallback_stem


def stored_filename(relative_path):
    """kkFileView fullfilename 用的物理存储文件名（basename，含唯一后缀）

    kkFileView 以 fullfilename 作为回源下载文件名与转换缓存键（缓存目录
    直接以该名存放源文件与转换产物，同名即命中同一条目）：必须传与物理
    文件唯一对应的存储名（build_stored_name 生成），显示名绝不能作为
    fullfilename，否则同显示名的两份不同文件会串用转换缓存（预览串版）。
    """
    return os.path.basename(str(relative_path or '').replace('\\', '/'))


def build_relative_path(file_kind, manual_id, stored_name):
    """生成相对路径：{subdir}/manual_{id}/{yyyy}{mm}/{stored_name}

    相对路径相对 institution 存储根目录（不含 institution/ 前缀，
    resolve_absolute_path 负责拼接根目录并做防穿越校验）。
    """
    subdir = _KIND_TO_SUBDIR.get(file_kind)
    if not subdir:
        raise ValueError(f'未知文件类别: {file_kind}')
    now = datetime.datetime.now()
    return os.path.join(
        subdir, f'manual_{manual_id}', now.strftime('%Y%m'), stored_name,
    )


def resolve_absolute_path(relative_path):
    """将相对路径转为绝对路径，并校验位于 institution/ 子目录内

    Raises:
        ValueError: 路径穿越或不在 institution 子目录内
    """
    if not relative_path:
        raise ValueError('文件路径为空')
    normalized = os.path.normpath(relative_path)
    if normalized.startswith('..') or os.path.isabs(normalized):
        raise ValueError('非法文件路径')
    abs_path = os.path.join(get_institution_storage_base(), normalized)
    if not _is_safe_path(get_institution_storage_base(), abs_path):
        raise ValueError('文件路径不在制度存储区域内')
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


def save_stream_to_path(stream, abs_path):
    """把可分块读取的流写入目标路径（分块写入 + 同步计算 SHA256）

    返回 (file_size, sha256_hex)
    """
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    size = 0
    sha256 = hashlib.sha256()
    with open(abs_path, 'wb') as f:
        while True:
            chunk = stream.read(1024 * 512)
            if not chunk:
                break
            f.write(chunk)
            size += len(chunk)
            sha256.update(chunk)
    return size, sha256.hexdigest()


def save_upload_file(file_obj, abs_path):
    """将 Django UploadedFile 写入磁盘（分块写入 + 同步计算 SHA256）

    Returns:
        str: 文件 SHA256 哈希
    """
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    sha256 = hashlib.sha256()
    with open(abs_path, 'wb') as f:
        for chunk in file_obj.chunks():
            f.write(chunk)
            sha256.update(chunk)
    return sha256.hexdigest()


def compute_file_hash(abs_path):
    """计算既有文件 SHA256（分块读取，避免内存溢出）"""
    sha256 = hashlib.sha256()
    with open(abs_path, 'rb') as f:
        while True:
            chunk = f.read(1024 * 512)
            if not chunk:
                break
            sha256.update(chunk)
    return sha256.hexdigest()


def safe_delete_file(abs_path):
    """安全删除制度文件

    校验最终路径仍位于 institution/ 子目录内后才删除。
    物理文件清理失败不抛异常，仅记录日志。

    Returns:
        tuple: (是否成功, 错误消息或 None)
    """
    if not abs_path or not os.path.exists(abs_path):
        return True, None

    base = get_institution_storage_base()
    if not _is_safe_path(base, abs_path):
        logger.error(f'[Institution] Refused to delete file outside institution subdir: {abs_path}')
        return False, '文件路径不在制度存储区域内，拒绝删除'

    try:
        os.remove(abs_path)
        return True, None
    except OSError as e:
        logger.error(f'[Institution] Failed to delete file: {abs_path}, error={e}')
        return False, str(e)


def safe_delete_manual_dir(manual_id):
    """删除整本手册的文件树（manual 删除时的兜底清理，含年月子目录）

    同时清理已下线原稿体系的历史遗留目录（originals/），整本手册删除
    时不允许留下孤儿目录；这不是原稿清理入口，常规清理走独立命令。

    Returns:
        tuple: (是否成功, 错误消息或 None)
    """
    base = get_institution_storage_base()
    removed = True
    err = None
    subdirs = list(_KIND_TO_SUBDIR.values()) + [LEGACY_ORIGINALS_SUBDIR]
    for subdir in subdirs:
        dir_path = os.path.join(base, subdir, f'manual_{manual_id}')
        if not _is_safe_path(base, dir_path) or not os.path.isdir(dir_path):
            continue
        try:
            shutil.rmtree(dir_path)
        except OSError as e:
            removed = False
            err = str(e)
            logger.error(f'[Institution] Failed to cleanup manual dir: {dir_path}, error={e}')
    return removed, err
