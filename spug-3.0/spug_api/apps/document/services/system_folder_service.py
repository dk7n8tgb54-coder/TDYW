# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""系统目录服务：行业规章范围判断与根目录保护

核心能力：
- get_system_root_folder_id(code)：取系统目录绑定的公共根目录 ID
- is_folder_in_scope(folder_id, code)：判断目录是否在系统根目录或其子孙内
- is_file_in_scope(file_obj, code)：判断文件是否属于系统根目录范围
- is_protected_system_root(folder_id)：判断目录是否为受保护的系统根目录

判断方式采用向上查父链（带循环引用与深度保护），不递归整棵子树。
"""
import logging
from django.db import models

from ..constants import DEFAULT_MAX_FOLDER_DEPTH

logger = logging.getLogger(__name__)

# 行业规章系统目录编码
INDUSTRY_RULES_CODE = 'industry_rules'

# 系统目录编码白名单（避免任意 code 被查询）
SYSTEM_FOLDER_CODES = {INDUSTRY_RULES_CODE}


def is_valid_system_folder_code(code):
    """判断 code 是否为受支持的系统目录编码"""
    return code in SYSTEM_FOLDER_CODES


def get_system_folder(code):
    """获取系统目录绑定记录（含关联的 folder）"""
    if not code or code not in SYSTEM_FOLDER_CODES:
        return None
    from ..models import DocumentSystemFolder
    return (
        DocumentSystemFolder.objects
        .select_related('folder')
        .filter(code=code)
        .first()
    )


def get_system_root_folder_id(code):
    """获取系统目录绑定的公共根目录 ID，不存在返回 None"""
    sf = get_system_folder(code)
    return sf.folder_id if sf else None


def get_system_root_folder(code):
    """获取系统目录绑定的公共根目录对象，不存在返回 None"""
    sf = get_system_folder(code)
    return sf.folder if sf else None


def is_folder_in_scope(folder_id, code, include_root=True):
    """判断 folder_id 是否在系统根目录或其子孙目录内

    Args:
        folder_id: 待校验的目录 ID
        code: 系统目录编码
        include_root: 是否允许 folder_id 即为根目录本身

    Returns:
        bool
    """
    if folder_id is None:
        return False
    root_id = get_system_root_folder_id(code)
    if root_id is None:
        return False
    if folder_id == root_id:
        return include_root
    return _is_descendant_of(folder_id, root_id)


def _is_descendant_of(folder_id, root_id):
    """判断 folder_id 是否为 root_id 的子孙（向上查父链）"""
    from ..models import DocumentFolderPublic
    visited = set()
    current_id = folder_id
    depth = 0
    while current_id is not None and depth < DEFAULT_MAX_FOLDER_DEPTH:
        if current_id in visited:
            logger.warning(
                f'[SystemFolder] 检测到循环引用: folder_id={current_id}, '
                f'starting_from={folder_id}, root_id={root_id}'
            )
            return False
        visited.add(current_id)
        # 只查 parent_id，避免整行加载（轻量）
        parent_id = (
            DocumentFolderPublic.objects
            .filter(pk=current_id)
            .values_list('parent_id', flat=True)
            .first()
        )
        if parent_id is None:
            return False
        if parent_id == root_id:
            return True
        current_id = parent_id
        depth += 1
    return False


def is_file_in_scope(file_obj, code):
    """判断文件是否属于系统根目录范围

    行业规章不允许 folder_id 为 null 的文件（不属于公共库根目录）。
    """
    if file_obj is None:
        return False
    folder_id = getattr(file_obj, 'folder_id', None)
    if folder_id is None:
        return False
    return is_folder_in_scope(folder_id, code, include_root=True)


def is_protected_system_root(folder_id):
    """判断目录是否为任一受保护的系统根目录"""
    if folder_id is None:
        return False
    from ..models import DocumentSystemFolder
    return DocumentSystemFolder.objects.filter(
        folder_id=folder_id, protected=True
    ).exists()


def get_descendant_folder_ids(code, include_root=True):
    """获取系统根目录及其所有子孙目录 ID（BFS，批量查询避免 N+1）

    用于 all=true 场景下限定文件夹列表范围。
    """
    root_id = get_system_root_folder_id(code)
    if root_id is None:
        return set()
    from ..models import DocumentFolderPublic
    result = set()
    if include_root:
        result.add(root_id)
    queue = [root_id]
    visited = {root_id}
    depth = 0
    while queue and depth < DEFAULT_MAX_FOLDER_DEPTH:
        depth += 1
        children = list(
            DocumentFolderPublic.objects
            .filter(parent_id__in=queue)
            .values_list('id', flat=True)
        )
        next_level = []
        for cid in children:
            if cid not in visited:
                visited.add(cid)
                result.add(cid)
                next_level.append(cid)
        queue = next_level
    return result


def get_all_system_scope_folder_ids(include_root=True):
    """Return folder ids owned by protected system-folder modules."""
    folder_ids = set()
    for code in SYSTEM_FOLDER_CODES:
        folder_ids.update(get_descendant_folder_ids(code, include_root=include_root))
    return folder_ids


def is_folder_in_any_system_scope(folder_id, include_root=True):
    """Check whether a folder belongs to any protected system-folder module."""
    if folder_id is None:
        return False
    return any(
        is_folder_in_scope(folder_id, code, include_root=include_root)
        for code in SYSTEM_FOLDER_CODES
    )


def is_file_in_any_system_scope(file_obj):
    """Check whether a file belongs to any protected system-folder module."""
    if file_obj is None:
        return False
    folder_id = getattr(file_obj, 'folder_id', None)
    if folder_id is None:
        return False
    return is_folder_in_any_system_scope(folder_id, include_root=True)


def exclude_system_folder_scope(queryset):
    """Hide protected system-folder modules from normal document-library queries."""
    folder_ids = get_all_system_scope_folder_ids(include_root=True)
    if not folder_ids:
        return queryset
    return queryset.exclude(id__in=folder_ids)


def exclude_system_file_scope(queryset):
    """Hide files under protected system-folder modules from normal document queries."""
    folder_ids = get_all_system_scope_folder_ids(include_root=True)
    if not folder_ids:
        return queryset
    return queryset.exclude(folder_id__in=folder_ids)


# ==================== 校验辅助（返回错误消息，供视图使用） ====================

SCOPE_ERROR_MSG = '无权访问行业规章目录外的资料'
PROTECTED_ROOT_MSG = '行业规章根目录不允许删除、重命名或移动'
UPLOAD_TARGET_MSG = '行业规章文件必须上传到行业规章目录内'
SCOPE_MUST_PUBLIC_MSG = '行业规章模式仅支持公共空间'


NORMAL_DOCUMENT_SCOPE_ERROR_MSG = '请从行业规章模块访问该目录'


def validate_system_folder_context(system_folder, is_public):
    """校验 system_folder 上下文基本约束

    Returns:
        (ok: bool, error_msg: str|None)
    """
    if system_folder and system_folder not in SYSTEM_FOLDER_CODES:
        return False, '未知的系统目录编码'
    if system_folder == INDUSTRY_RULES_CODE and not is_public:
        return False, SCOPE_MUST_PUBLIC_MSG
    return True, None


def ensure_folder_in_scope_or_error(folder_id, code, include_root=True):
    """校验目录在系统范围内，否则返回错误消息"""
    if not is_folder_in_scope(folder_id, code, include_root=include_root):
        return False, SCOPE_ERROR_MSG
    return True, None


def ensure_file_in_scope_or_error(file_obj, code):
    """校验文件在系统范围内，否则返回错误消息"""
    if not is_file_in_scope(file_obj, code):
        return False, SCOPE_ERROR_MSG
    return True, None
