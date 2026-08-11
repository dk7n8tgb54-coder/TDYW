# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
文件命名工具模块（生产级）
提供文件名生成、清理、解析功能
符合资料库文件命名优化方案 V2 规范
"""

import os
import re
import unicodedata
import time
import uuid
import logging
from django.db import transaction

logger = logging.getLogger(__name__)


def clean_illegal_chars(filename, replace_space=True):
    """
    清理文件名中的非法字符

    规则：
    1. Unicode NFC 规范化
    2. 使用 os.path.basename 阻止路径穿越
    3. 替换系统非法字符 / \\ : * ? " < > | 为下划线
    4. 去除 NUL 和控制字符（\\x00-\\x1f, \\x7f）
    5. 可选替换空格为下划线（避免路径空格问题）
    6. 去除连续下划线（美观）
    7. 去除首尾下划线

    Args:
        filename: 原始文件名
        replace_space: 是否替换空格为下划线（默认True）

    Returns:
        清理后的文件名
    """
    if not filename:
        return "unnamed"

    # 第一步：Unicode NFC 规范化（统一组合/分解字符）
    clean_name = unicodedata.normalize('NFC', filename)

    # 第二步：阻止路径穿越 — 只取 basename
    clean_name = os.path.basename(clean_name)

    # 第三步：去除 NUL 和控制字符（\x00-\x1f, \x7f）
    clean_name = re.sub(r'[\x00-\x1f\x7f]', '', clean_name)

    # 第四步：替换系统非法字符（含正反斜杠）
    illegal_chars = r'[\\/:*?"<>|]'
    clean_name = re.sub(illegal_chars, "_", clean_name)

    # 第五步：替换空格（可选）
    if replace_space:
        clean_name = clean_name.replace(" ", "_")

    # 第六步：去除连续下划线
    clean_name = re.sub(r"_+", "_", clean_name)

    # 第七步：去除首尾下划线
    clean_name = clean_name.strip("_")

    # 兜底：如果清理后为空，返回unnamed
    if not clean_name:
        return "unnamed"

    return clean_name


def get_file_ext(filename):
    """
    智能提取文件扩展名（支持多扩展名、无扩展名）
    
    规则：
    1. 无扩展名：返回 (filename, "")
    2. 单扩展名：返回 (name, ".ext")
    3. 多扩展名（如.tar.gz）：返回 (name, ".tar.gz")
    
    Args:
        filename: 原始文件名
    
    Returns:
        (original_name_without_ext, ext_with_dot)
    """
    if not filename or "." not in filename:
        return filename or "unnamed", ""
    
    # 常见多扩展名后缀
    multi_ext_suffixes = ['.tar.gz', '.tar.bz2', '.tar.xz', '.md5', '.sha1', '.sha256']
    
    lower_filename = filename.lower()
    for suffix in multi_ext_suffixes:
        if lower_filename.endswith(suffix):
            original_name = filename[:-len(suffix)]
            return original_name, suffix
    
    # 单扩展名处理
    name_parts = filename.rsplit(".", 1)
    if len(name_parts) == 1:
        # 无扩展名
        return filename, ""
    else:
        original_name = name_parts[0]
        ext = f".{name_parts[1]}"
        return original_name, ext


def _truncate_utf8_safe(text, max_bytes):
    """
    按 UTF-8 字节安全截断字符串，不截断半个汉字

    Args:
        text: 原始字符串
        max_bytes: 最大 UTF-8 字节数

    Returns:
        截断后的字符串
    """
    if not text:
        return ""
    encoded = text.encode('utf-8')
    if len(encoded) <= max_bytes:
        return text
    # 截断到 max_bytes，然后回退到最后一个完整字符边界
    truncated = encoded[:max_bytes]
    # 尝试解码，如果失败则逐字节回退
    while truncated:
        try:
            return truncated.decode('utf-8')
        except UnicodeDecodeError:
            truncated = truncated[:-1]
    return ""


def generate_physical_name(ext="", original_name=""):
    """
    生成物理文件名（高并发安全 + 可识别性）

    方案：清理后的原始文件名(截断) + 毫秒级时间戳(13位) + 6位随机串
    - 保留原始文件名便于备份识别
    - 时间戳精确到毫秒，避免秒级冲突
    - 6位随机串（16^6=1677万种组合）
    - 长度按 UTF-8 字节安全截断，满足 model max_length=100 和 Linux 255 字节限制

    格式：{clean_name}_{timestamp}_{random_suffix}{ext}
    预留：timestamp(13) + underscore(1) + random(6) + underscore(1) + ext = 21 + len(ext)

    Args:
        ext: 扩展名（含点，如".mp4"）
        original_name: 原始文件名（用于生成可识别前缀）

    Returns:
        物理文件名
    """
    timestamp = int(time.time() * 1000)  # 13位毫秒时间戳
    random_suffix = uuid.uuid4().hex[:6]  # 6位随机

    # 如果有原始文件名，添加可识别前缀
    if original_name:
        # 提取原始文件名（不含扩展名）
        name_without_ext, _ = get_file_ext(original_name)
        # 清理非法字符（不替换空格，保留原始名可读性）
        clean_name = clean_illegal_chars(name_without_ext, replace_space=False)

        # 计算可用的最大字符长度
        # 格式: {clean_name}_{timestamp}_{random_suffix}{ext}
        # 预留部分: _{13}_{6}{ext} = 21 + len(ext) 字符
        suffix_part = f"_{timestamp}_{random_suffix}{ext}"
        suffix_len = len(suffix_part)

        # 模型 physical_name max_length=100
        max_total_chars = 100
        max_name_chars = max_total_chars - suffix_len

        # Linux 单文件名限制 255 字节（UTF-8）
        # 计算后缀部分的 UTF-8 字节数
        suffix_bytes = len(suffix_part.encode('utf-8'))
        max_total_bytes = 255
        max_name_bytes = max_total_bytes - suffix_bytes

        # 先按字符数截断（保守），再按 UTF-8 字节数截断
        if len(clean_name) > max_name_chars:
            clean_name = clean_name[:max_name_chars]

        clean_name = _truncate_utf8_safe(clean_name, max_name_bytes)

        # 兜底：如果清理后为空
        if not clean_name:
            clean_name = "unnamed"

        return f"{clean_name}_{timestamp}_{random_suffix}{ext}"

    # 无原始文件名，使用旧格式
    return f"{timestamp}_{random_suffix}{ext}"


def generate_unique_logical_name(FileModel, original_name, folder, user, max_original_length=50):
    """
    生成唯一逻辑名（name）- 数据库事务防竞态版本
    
    规则：
    1. 作用域：仅在「同一租户+同一文件夹」内保证唯一
    2. 序号逻辑：查询该文件夹下同名文件的最大序号，+1生成；无同名则不加序号
    3. 防竞态：用数据库事务，避免高并发生成重复序号
    4. 长度限制：原始名截断到50字符，序号占3位，总长度≤54字符
    
    Args:
        FileModel: 文件模型类
        original_name: 原始文件名（含扩展名）
        folder: 目标文件夹对象（None表示根目录）
        user: 当前用户（用于获取tenant_id）
        max_original_length: 原始文件名最大长度（默认50）
    
    Returns:
        唯一逻辑文件名
    """
    # 步骤1：提取原始名和扩展名
    name_without_ext, ext = get_file_ext(original_name)
    
    # 步骤2：清理非法字符
    clean_original = clean_illegal_chars(name_without_ext)
    
    # 步骤3：截断超长原始名
    if len(clean_original) > max_original_length:
        clean_original = clean_original[:max_original_length]
    
    # 步骤4：查询同一文件夹下的同名文件（事务防竞态）
    folder_id = folder.id if folder else None
    tenant_id = getattr(user, 'tenant_id', None)
    
    # 【P0修复】检查模型是否有 tenant_id 字段（公共空间模型没有该字段）
    has_tenant_id = hasattr(FileModel, 'tenant_id')
    
    with transaction.atomic():
        # 【P1修复】锁住父文件夹记录，序列化同文件夹下的并发命名
        # select_for_update 只能锁已存在的行，不能防止新行插入
        # 通过锁父文件夹实现粗粒度互斥：同文件夹的并发命名请求必须串行执行
        if folder:
            FolderModel = type(folder)
            FolderModel.objects.select_for_update().filter(id=folder.id).first()

        # 【P1修复】查询该文件夹下的同名文件
        # 修复：原代码 name__startswith=f"{clean_original}_" 无法匹配精确名 foo.txt
        # 需要同时查询精确名和带序号前缀的文件
        prefix_pattern = f"{clean_original}_"
        
        base_filter = {
            'folder_id': folder_id,
        }
        if has_tenant_id:
            base_filter['tenant_id'] = tenant_id
        
        exact_pattern = f"{clean_original}{ext}"
        
        # 先检查精确名是否已存在（独立查询，避免 startswith 漏匹配）
        exact_exists = FileModel.objects.filter(
            name=exact_pattern,
            **base_filter
        ).exists()
        
        if not exact_exists:
            # 无同名文件，直接用清理后的原始名
            return exact_pattern
        
        # 有同名文件，查询所有带前缀的文件以提取最大序号
        all_matching_files = list(
            FileModel.objects.filter(
                name__startswith=prefix_pattern,
                **base_filter
            ).values_list('name', flat=True)
        )
        
        # 有同名文件，提取最大序号（\d{3,} 匹配 3 位及以上，兼容序号溢出到 1000+）
        regex_pattern = rf"^{re.escape(clean_original)}_(\d{{3,}}){re.escape(ext)}$"
        max_counter = 0
        for existing_name in all_matching_files:
            match = re.match(regex_pattern, existing_name)
            if match:
                max_counter = max(max_counter, int(match.group(1)))
        
        # 生成新序号
        new_counter = max_counter + 1
        
        # 序号溢出检查（999个同名文件，极罕见）
        if new_counter > 999:
            return f"{clean_original}_{new_counter:04d}{ext}"
        
        return f"{clean_original}_{new_counter:03d}{ext}"


def parse_old_physical_name_to_display(old_physical_name):
    """
    从旧物理名提取display_name（兼容历史数据）
    
    旧名格式：{file_base}_{user_id}_{timestamp}_{random8}{ext}
    目标：提取file_base作为display_name
    
    Args:
        old_physical_name: 旧格式物理文件名
    
    Returns:
        解析后的显示名称
    """
    if not old_physical_name:
        return "unnamed"
    
    # 按最后3个下划线分割
    parts = old_physical_name.rsplit("_", 3)
    if len(parts) >= 4:
        # 取第一部分作为原始名
        file_base = parts[0]
        # 最后一部分包含扩展名
        last_part = parts[-1]
        if "." in last_part:
            # 提取扩展名
            ext = last_part.split(".")[-1]
            return f"{file_base}.{ext}"
        return file_base
    
    # 格式异常，返回原名称
    return old_physical_name


def get_file_display_name(file_obj):
    """
    获取文件的显示名称（兼容新旧数据）
    
    新数据：直接使用display_name
    旧数据：从physical_name或name解析
    
    Args:
        file_obj: 文件模型对象
    
    Returns:
        显示名称
    """
    # 新数据：直接使用display_name
    if file_obj.display_name:
        return file_obj.display_name
    
    # 尝试从physical_name解析（旧格式）
    if hasattr(file_obj, 'physical_name') and file_obj.physical_name:
        # 如果physical_name包含下划线，可能是旧格式
        if "_" in file_obj.physical_name:
            return parse_old_physical_name_to_display(file_obj.physical_name)
    
    # 兜底：使用name
    return file_obj.name


def generate_file_names(FileModel, original_name, folder, user):
    """
    生成文件的三层名称（生产级统一入口）
    
    Args:
        FileModel: 文件模型类
        original_name: 原始文件名（用户上传时的文件名）
        folder: 目标文件夹对象
        user: 当前用户
    
    Returns:
        dict: {
            'display_name': 显示名称（用户友好）,
            'logical_name': 逻辑名称（数据库唯一）,
            'physical_name': 物理名称（存储用）
        }
    """
    # 步骤1：提取扩展名
    _, ext = get_file_ext(original_name)
    
    # 步骤2：生成物理文件名（带原始文件名前缀，便于备份识别）
    physical_name = generate_physical_name(ext, original_name)
    
    # 步骤3：生成逻辑文件名（可读+唯一）
    logical_name = generate_unique_logical_name(
        FileModel, 
        original_name, 
        folder, 
        user
    )
    
    # 步骤4：display_name 使用原始文件名；若逻辑名已加序号则同步带序号
    # 这样"保留两者"后两个文件的 display_name 也可区分（如 foo.txt / foo_001.txt）
    exact_pattern = f"{clean_illegal_chars(get_file_ext(original_name)[0])}{ext}"
    display_name = logical_name if logical_name != exact_pattern else original_name
    
    return {
        'display_name': display_name,
        'logical_name': logical_name,
        'physical_name': physical_name,
        'ext': ext
    }
