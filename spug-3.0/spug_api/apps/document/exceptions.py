# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
资料库模块自定义异常

所有资料库相关的业务异常统一在此定义，避免使用裸 Exception，
使调用方可以精确捕获特定异常类型。
"""


class DocumentError(Exception):
    """资料库模块基础异常"""
    pass


class DocumentPhysicalDeleteError(DocumentError):
    """
    物理文件删除失败异常

    当硬删除（hard delete）时物理文件无法删除（如文件被占用、权限不足），
    模型会先将 is_pending_clean 标记落库，再抛出此异常。

    调用方应：
    1. 精确捕获此异常，而非 except Exception
    2. 知道 is_pending_clean 已落库（由定时任务 retry_clean_pending_files 重试）
    3. 向前端返回"已加入待清理队列"，而非直接视为普通失败

    注意：is_pending_clean 的保存使用独立 savepoint，
    不会被外层 transaction.atomic() 回滚。
    """

    def __init__(self, file_path, message=None):
        self.file_path = file_path
        self.message = message or f'物理文件删除失败，已标记为待清理: {file_path}'
        super().__init__(self.message)


class DocumentPermissionError(DocumentError):
    """文档权限不足异常"""
    pass


class DocumentConflictError(DocumentError):
    """文档冲突异常（如同名文件夹已存在）"""
    pass
