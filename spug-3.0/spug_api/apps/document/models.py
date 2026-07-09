# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
import os
import hashlib
import logging
from django.db import models, transaction
from django.core.validators import MinValueValidator
from django.utils import timezone
from apps.account.models import User
from .exceptions import DocumentPhysicalDeleteError
from .constants import DEFAULT_MAX_FOLDER_DEPTH

logger = logging.getLogger(__name__)


# ==================== 软删除管理器 ====================
class SoftDeletedManager(models.Manager):
    """默认管理器：只返回未删除的记录"""
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class AllObjectsManager(models.Manager):
    """全量管理器：返回所有记录（包括已删除）"""
    def get_queryset(self):
        return super().get_queryset()


# 定义租户类型枚举
TENANT_TYPE_CHOICES = (
    ('PUBLIC', '公共表'),
    ('PRIVATE', '私有表'),
    ('GLOBAL', '全局表（无租户）'),
)


class TenantType:
    """为了向后兼容，保留类名"""
    PUBLIC = 'PUBLIC'
    PRIVATE = 'PRIVATE'
    GLOBAL = 'GLOBAL'


# ==================== 模型 Mixin（抽象 Public/Private 重复逻辑） ====================

class SoftDeleteFolderMixin(models.Model):
    """
    文件夹软删除 Mixin

    提供 delete(hard=False) 和 restore() 的通用实现。
    子类必须定义: is_deleted, deleted_at, deleted_by 字段。
    """
    class Meta:
        abstract = True

    def delete(self, hard=False, *args, **kwargs):
        """
        删除文件夹
        hard=True: 硬删除（彻底删除）
        hard=False: 软删除（移入回收站）
        """
        if hard:
            super().delete(*args, **kwargs)
        else:
            self.is_deleted = True
            self.deleted_at = timezone.now()
            self.save(update_fields=['is_deleted', 'deleted_at'])

    def restore(self):
        """恢复软删除的文件夹"""
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])


class FolderPathMixin:
    """
    文件夹路径 Mixin

    提供 get_full_path() 的迭代实现，带循环引用和深度保护。
    子类必须定义: name, parent (ForeignKey to self), is_deleted 字段。
    """

    def get_full_path(self):
        """获取文件夹完整路径（迭代实现，带深度保护）

        - visited 集合检测循环引用，发现时停止并记录警告
        - 超过 DEFAULT_MAX_FOLDER_DEPTH 深度时停止并记录警告
        """
        parts = []
        current = self
        visited = set()
        depth = 0

        while current and not current.is_deleted:
            if current.id in visited:
                logger.warning(
                    f'[FolderPathMixin] get_full_path 检测到循环引用: '
                    f'folder_id={current.id}, name={current.name}, '
                    f'starting_from={self.id}'
                )
                break
            if depth >= DEFAULT_MAX_FOLDER_DEPTH:
                logger.warning(
                    f'[FolderPathMixin] get_full_path 超过最大深度 {DEFAULT_MAX_FOLDER_DEPTH}: '
                    f'folder_id={current.id}, name={current.name}, '
                    f'starting_from={self.id}'
                )
                break

            visited.add(current.id)
            parts.append(current.name)
            depth += 1
            current = current.parent

        return '/'.join(reversed(parts))


class UniqueKeyMixin(models.Model):
    """
    唯一标识键 Mixin

    提供 save() 中自动计算 unique_key 的通用 hook。
    子类必须: 1) 定义 unique_key 字段; 2) 实现 _compute_unique_key() 方法。
    """
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.unique_key = self._compute_unique_key()
        # 确保 unique_key 始终在 update_fields 中
        update_fields = kwargs.get('update_fields')
        if update_fields is not None and 'unique_key' not in update_fields:
            kwargs['update_fields'] = set(update_fields) | {'unique_key'}
        super().save(*args, **kwargs)


class SoftDeleteFileMixin(models.Model):
    """
    文件软删除 Mixin

    提供 restore() 的通用实现。
    子类必须定义: is_deleted, deleted_at 字段。
    """
    class Meta:
        abstract = True

    def restore(self):
        """恢复软删除的文件"""
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=['is_deleted', 'deleted_at'])


class DocumentFileDeleteMixin(models.Model):
    """
    文件硬删除 Mixin

    提供物理文件+缩略图清理、is_pending_clean 兜底标记、
    DocumentPhysicalDeleteError 异常的通用实现。
    子类必须定义: file_path, thumbnail_path, is_pending_clean,
                  clean_retry_count, last_clean_attempt, is_deleted, deleted_at 字段。
    """
    class Meta:
        abstract = True

    def delete(self, *args, **kwargs):
        """
        重写删除方法：默认软删除，硬删除时确保物理文件删除成功

        Args:
            hard: 是否硬删除（默认False软删除）

        事务语义：
            - 硬删除成功：super().delete() 在调用方的事务内完成
            - 物理文件删除失败：先保存 is_pending_clean 标记，再抛出
              DocumentPhysicalDeleteError。
              ⚠️ 注意：此保存使用嵌套 transaction.atomic()（即 savepoint），
              如果调用方外层事务随后回滚，此标记也会被回滚。
              调用方若需要此标记可靠落库，不应在捕获异常后回滚外层事务，
              而应让外层事务正常提交。如需更强保障，需改用异步补偿
              （如 Celery 任务重试待清理文件）。
        """
        hard = kwargs.pop('hard', False)

        if hard:
            # 硬删除：先删除物理文件，成功后再删除数据库记录
            physical_deleted = True
            if os.path.exists(self.file_path):
                from apps.document.libs.document_utils import safe_delete_document_file, safe_delete_thumbnail
                file_deleted, file_error = safe_delete_document_file(self.file_path)
                if file_deleted:
                    logger.info(f'[Document] 物理文件已删除: {self.file_path}')
                else:
                    logger.error(f'[Document] 删除物理文件失败: {self.file_path}, error={file_error}')
                    physical_deleted = False

            # 删除缩略图
            if self.thumbnail_path and os.path.exists(self.thumbnail_path):
                from apps.document.libs.document_utils import safe_delete_thumbnail
                thumb_deleted, thumb_error = safe_delete_thumbnail(self.thumbnail_path)
                if thumb_deleted:
                    logger.info(f'[Document] 缩略图已删除: {self.thumbnail_path}')
                else:
                    logger.warning(f'[Document] 删除缩略图失败: {self.thumbnail_path}, error={thumb_error}')

            if physical_deleted:
                super().delete(*args, **kwargs)
            else:
                # 使用 savepoint 保存 is_pending_clean 标记；
                # 注意：若外层事务回滚，此标记也会回滚
                with transaction.atomic():
                    self.is_pending_clean = True
                    self.clean_retry_count = (self.clean_retry_count or 0) + 1
                    self.last_clean_attempt = timezone.now()
                    self.save(update_fields=['is_pending_clean', 'clean_retry_count', 'last_clean_attempt'])
                raise DocumentPhysicalDeleteError(self.file_path)
        else:
            # 软删除：标记删除状态
            self.is_deleted = True
            self.deleted_at = timezone.now()
            self.save(update_fields=['is_deleted', 'deleted_at'])


# ==================== 私有空间模型（原有数据保留） ====================

class DocumentFolderPrivate(SoftDeleteFolderMixin, FolderPathMixin, UniqueKeyMixin):
    """私有空间文件夹模型"""
    TENANT_TYPE = 'PRIVATE'
    name = models.CharField(max_length=200, verbose_name='文件夹名称')
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, verbose_name='父文件夹')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name='创建人')
    tenant_id = models.CharField(max_length=50, default='', help_text='租户标识')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    # ========== 【V3】软删除字段 ==========
    is_deleted = models.BooleanField(
        default=False,
        help_text='是否已删除（软删除）',
        verbose_name='删除标记'
    )
    deleted_at = models.DateTimeField(
        null=True, blank=True,
        help_text='删除时间',
        verbose_name='删除时间'
    )
    deleted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='deleted_folders_private',
        help_text='删除人',
        verbose_name='删除人'
    )

    # ========== 唯一性保障字段 ==========
    # MariaDB 不支持部分唯一索引（WHERE 条件），因此使用 unique_key 方案：
    # - 未删除记录：unique_key = MD5("tenant_id:created_by_id:name:parent_id")
    # - 已删除记录：unique_key = NULL（不参与唯一约束）
    # 利用 MySQL 中 NULL 不参与唯一索引的特性，实现软删除后同名文件夹可创建
    unique_key = models.CharField(
        max_length=32, null=True, blank=True, unique=True,
        editable=False, db_index=True,
        help_text='唯一标识键（MD5哈希，仅未删除记录参与唯一约束）',
        verbose_name='唯一标识键'
    )

    # ========== 自定义管理器（【V3】双管理器）==========
    objects = SoftDeletedManager()      # 默认：不包含已删除
    all_objects = AllObjectsManager()   # 全量：包含已删除

    class Meta:
        db_table = 'tdyw_document_folder_private'
        verbose_name = '文档文件夹(私有)'
        verbose_name_plural = '文档文件夹(私有)'
        # 列表查询路径：filter(tenant_id=?, parent_id=?, is_deleted=False).order_by('-created_at')
        # 组合索引覆盖 过滤 + 排序，避免数据量增长后 Using filesort。
        # 字段顺序说明：parent_id 放最前，左前缀 [parent_id] 可服务 CASCADE
        # 删除父记录时的 WHERE parent_id=? 查询，避免额外维护单列外键索引。
        indexes = [
            models.Index(
                fields=['parent_id', 'tenant_id', 'is_deleted', '-created_at', '-id'],
                name='doc_pri_folder_list_idx',
            ),
        ]

    def __str__(self):
        return self.name

    def _compute_unique_key(self):
        """计算唯一标识键：同租户+同用户+同名+同父目录（MD5哈希）"""
        if self.is_deleted:
            return None
        raw = f'{self.tenant_id or ""}:{self.created_by_id or 0}:{self.name}:{self.parent_id or "ROOT"}'
        return hashlib.md5(raw.encode('utf-8')).hexdigest()


class DocumentFilePrivate(SoftDeleteFileMixin, DocumentFileDeleteMixin):
    """私有空间文件模型 - 生产级映射保障版本"""
    TENANT_TYPE = 'PRIVATE'

    # ========== 物理标识字段（只写一次，终身只读）==========
    physical_name = models.CharField(
        max_length=100,  # 【修复】从32增加到100，支持新命名格式（原始名20+时间戳13+随机6+扩展名）
        null=True,
        blank=True,
        editable=False,  # 【V3】后台不可编辑，防止误修改
        help_text='物理文件名（存储用），生成后终身不可修改',
        verbose_name='物理文件名'
    )

    file_path = models.CharField(
        max_length=500,
        editable=False,  # 【V3】路径不可编辑
        help_text='完整存储路径，生成后不可修改',
        verbose_name='文件存储路径'
    )

    # ========== 业务标识字段（可修改）==========
    name = models.CharField(
        max_length=100,  # 【修复】从64增加到100，与physical_name保持一致
        help_text='逻辑文件名（API交互用）',
        verbose_name='逻辑文件名'
    )

    display_name = models.CharField(
        max_length=128,
        help_text='显示名称（用户看到的文件名）',
        verbose_name='显示名称'
    )

    # ========== 关系字段 ==========
    folder = models.ForeignKey(
        DocumentFolderPrivate,
        on_delete=models.SET_NULL,  # 【修复】原为 CASCADE，防止文件夹删除时级联删除已软删除的文件
        null=True,
        blank=True,
        verbose_name='所属文件夹',
        help_text='NULL表示文件在根目录',
        related_name='files'
    )

    # ========== 文件信息字段 ==========
    file_size = models.BigIntegerField(default=0, verbose_name='文件大小(字节)')
    file_type = models.CharField(max_length=100, verbose_name='文件类型')
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name='上传人'
    )
    tenant_id = models.CharField(max_length=50, default='', help_text='租户标识')

    # ========== 软删除字段（【V3】新增）==========
    is_deleted = models.BooleanField(
        default=False,
        help_text='是否已删除（软删除，默认查询已过滤）',
        verbose_name='删除标记'
    )
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='删除时间',
        verbose_name='删除时间'
    )

    # 【P0修复】新增待清理字段（用于物理文件删除失败时的兜底处理）
    is_pending_clean = models.BooleanField(
        default=False,
        help_text='标记为待清理（物理文件删除失败时设置）',
        verbose_name='待清理标记'
    )
    clean_retry_count = models.IntegerField(
        default=0,
        help_text='清理重试次数',
        verbose_name='清理重试次数'
    )
    last_clean_attempt = models.DateTimeField(
        null=True,
        blank=True,
        help_text='上次清理尝试时间',
        verbose_name='上次清理尝试时间'
    )

    # 【新增】缩略图字段
    thumbnail_path = models.CharField(
        max_length=500,
        null=True,
        blank=True,
        editable=False,
        help_text='缩略图存储路径',
        verbose_name='缩略图路径'
    )

    # ========== 时间戳字段 ==========
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='上传时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    # ========== 自定义管理器（【V3】双管理器）==========
    objects = SoftDeletedManager()      # 默认：不包含已删除
    all_objects = AllObjectsManager()   # 全量：包含已删除

    class Meta:
        db_table = 'tdyw_document_file_private'
        verbose_name = '文档文件(私有)'
        verbose_name_plural = '文档文件(私有)'
        # 列表查询路径：filter(tenant_id=?, folder_id=?, is_deleted=False).order_by('-created_at')
        # （is_deleted=False 由 SoftDeletedManager 自动添加）
        # 字段顺序说明：folder_id 放最前，左前缀 [folder_id] 可服务 CASCADE
        # 删除父文件夹时的 WHERE folder_id=? 查询。
        indexes = [
            models.Index(
                fields=['folder_id', 'tenant_id', 'is_deleted', '-created_at', '-id'],
                name='doc_pri_file_list_idx',
            ),
        ]

    def __str__(self):
        return self.display_name or self.name


# ==================== 公共共享空间模型（新建表） ====================

class DocumentFolderPublic(SoftDeleteFolderMixin, FolderPathMixin, UniqueKeyMixin):
    """公共共享空间文件夹模型 - 支持全平台共享"""
    TENANT_TYPE = 'PUBLIC'
    name = models.CharField(max_length=200, verbose_name='文件夹名称')
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, verbose_name='父文件夹')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name='创建人')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    # ========== 【V3】软删除字段 ==========
    is_deleted = models.BooleanField(
        default=False,
        help_text='是否已删除（软删除）',
        verbose_name='删除标记'
    )
    deleted_at = models.DateTimeField(
        null=True, blank=True,
        help_text='删除时间',
        verbose_name='删除时间'
    )
    deleted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='deleted_folders_public',
        help_text='删除人',
        verbose_name='删除人'
    )

    # ========== 唯一性保障字段 ==========
    # 与 DocumentFolderPrivate 同理，使用 unique_key 方案替代部分唯一索引
    # - 未删除记录：unique_key = MD5("name:parent_id")
    # - 已删除记录：unique_key = NULL
    unique_key = models.CharField(
        max_length=32, null=True, blank=True, unique=True,
        editable=False, db_index=True,
        help_text='唯一标识键（MD5哈希，仅未删除记录参与唯一约束）',
        verbose_name='唯一标识键'
    )

    # ========== 自定义管理器（【V3】双管理器）==========
    objects = SoftDeletedManager()      # 默认：不包含已删除
    all_objects = AllObjectsManager()   # 全量：包含已删除

    class Meta:
        db_table = 'tdyw_document_folder_public'
        verbose_name = '文档文件夹(公共)'
        verbose_name_plural = '文档文件夹(公共)'
        # 公共空间无租户隔离，列表查询路径：
        # filter(parent_id=?, is_deleted=False).order_by('-created_at')
        # parent_id 放最前，左前缀可服务 CASCADE 删除。
        indexes = [
            models.Index(
                fields=['parent_id', 'is_deleted', '-created_at', '-id'],
                name='doc_pub_folder_list_idx',
            ),
        ]

    def __str__(self):
        return self.name

    def _compute_unique_key(self):
        """计算唯一标识键：同名+同父目录（公共空间不区分用户，MD5哈希）"""
        if self.is_deleted:
            return None
        raw = f'{self.name}:{self.parent_id or "ROOT"}'
        return hashlib.md5(raw.encode('utf-8')).hexdigest()


class DocumentFilePublic(SoftDeleteFileMixin, DocumentFileDeleteMixin):
    """公共共享空间文件模型 - 生产级映射保障版本"""
    TENANT_TYPE = 'PUBLIC'

    # ========== 物理标识字段（只写一次，终身只读）==========
    physical_name = models.CharField(
        max_length=100,  # 【修复】从32增加到100，支持新命名格式
        null=True,
        blank=True,
        editable=False,  # 【V3】后台不可编辑
        help_text='物理文件名（存储用），生成后终身不可修改',
        verbose_name='物理文件名'
    )

    file_path = models.CharField(
        max_length=500,
        editable=False,  # 【V3】路径不可编辑
        help_text='完整存储路径，生成后不可修改',
        verbose_name='文件存储路径'
    )

    # ========== 业务标识字段（可修改）==========
    name = models.CharField(
        max_length=100,  # 【修复】从64增加到100
        help_text='逻辑文件名（API交互用）',
        verbose_name='逻辑文件名'
    )

    display_name = models.CharField(
        max_length=128,
        help_text='显示名称（用户看到的文件名）',
        verbose_name='显示名称'
    )

    # ========== 关系字段 ==========
    folder = models.ForeignKey(
        DocumentFolderPublic,
        on_delete=models.SET_NULL,  # 【修复】原为 CASCADE，防止文件夹删除时级联删除已软删除的文件
        null=True,
        blank=True,
        verbose_name='所属文件夹',
        help_text='NULL表示文件在根目录',
        related_name='files'
    )

    # ========== 文件信息字段 ==========
    file_size = models.BigIntegerField(default=0, verbose_name='文件大小(字节)')
    file_type = models.CharField(max_length=100, verbose_name='文件类型')
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name='上传人'
    )

    # ========== 软删除字段（【V3】新增）==========
    is_deleted = models.BooleanField(
        default=False,
        help_text='是否已删除（软删除，默认查询已过滤）',
        verbose_name='删除标记'
    )
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='删除时间',
        verbose_name='删除时间'
    )

    # 【P0修复】新增待清理字段（用于物理文件删除失败时的兜底处理）
    is_pending_clean = models.BooleanField(
        default=False,
        help_text='标记为待清理（物理文件删除失败时设置）',
        verbose_name='待清理标记'
    )
    clean_retry_count = models.IntegerField(
        default=0,
        help_text='清理重试次数',
        verbose_name='清理重试次数'
    )
    last_clean_attempt = models.DateTimeField(
        null=True,
        blank=True,
        help_text='上次清理尝试时间',
        verbose_name='上次清理尝试时间'
    )

    # 【新增】缩略图字段
    thumbnail_path = models.CharField(
        max_length=500,
        null=True,
        blank=True,
        editable=False,
        help_text='缩略图存储路径',
        verbose_name='缩略图路径'
    )

    # ========== 时间戳字段 ==========
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='上传时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    # ========== 自定义管理器（【V3】双管理器）==========
    objects = SoftDeletedManager()      # 默认：不包含已删除
    all_objects = AllObjectsManager()   # 全量：包含已删除

    class Meta:
        db_table = 'tdyw_document_file_public'
        verbose_name = '文档文件(公共)'
        verbose_name_plural = '文档文件(公共)'
        # 公共表唯一索引: 同一文件夹下不允许同名文件
        constraints = [
            models.UniqueConstraint(
                fields=['name', 'folder'],
                name='unique_file_name_folder_public'
            )
        ]
        # 列表查询路径：filter(folder_id=?, is_deleted=False).order_by('-created_at')
        # （is_deleted=False 由 SoftDeletedManager 自动添加）
        # folder_id 放最前，左前缀可服务 CASCADE 删除。
        indexes = [
            models.Index(
                fields=['folder_id', 'is_deleted', '-created_at', '-id'],
                name='doc_pub_file_list_idx',
            ),
        ]

    def __str__(self):
        return self.display_name or self.name


# ==================== 文件传输记录模型（支持多租户） ====================
class DocumentTransfer(models.Model):
    """文件传输记录模型 - 支持上传和下载的持久化记录"""
    TRANSFER_TYPE_CHOICES = (
        ('UPLOAD', '上传'),
        ('DOWNLOAD', '下载'),
    )

    TRANSFER_STATUS_CHOICES = (
        ('PENDING', '等待中'),
        ('UPLOADING', '上传中'),
        ('DOWNLOADING', '下载中'),
        ('PAUSED', '已暂停'),
        ('MERGING', '合并中'),
        ('COMPLETED', '已完成'),
        ('FAILED', '失败'),
        ('CANCELED', '已取消'),
    )

    id = models.AutoField(primary_key=True)
    # 租户隔离字段
    tenant_id = models.CharField(max_length=50, default='', help_text='租户标识', db_index=True)
    # 用户关联
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name='用户')
    # 传输类型：上传/下载
    transfer_type = models.CharField(max_length=20, choices=TRANSFER_TYPE_CHOICES, verbose_name='传输类型', db_index=True)
    # 传输状态
    status = models.CharField(max_length=20, choices=TRANSFER_STATUS_CHOICES, default='PENDING', verbose_name='状态', db_index=True)
    # 文件信息
    file_name = models.CharField(max_length=255, verbose_name='文件名')
    file_size = models.BigIntegerField(default=0, validators=[MinValueValidator(0)], verbose_name='文件大小(字节)')
    file_path = models.CharField(max_length=500, verbose_name='文件存储路径')
    file_hash = models.CharField(max_length=100, blank=True, null=True, verbose_name='文件哈希(MD5)', db_index=True)
    # 目标文件夹（上传时使用）
    folder_id = models.IntegerField(null=True, blank=True, verbose_name='目标文件夹ID')
    is_public = models.BooleanField(default=False, verbose_name='是否公共空间')
    # 分片信息（上传时使用）
    total_chunks = models.IntegerField(default=0, verbose_name='总分片数')
    uploaded_chunks = models.IntegerField(default=0, verbose_name='已上传分片数')
    # 进度信息
    progress = models.IntegerField(default=0, verbose_name='进度百分比')
    transferred_size = models.BigIntegerField(default=0, verbose_name='已传输大小(字节)')
    # 速度信息
    speed = models.FloatField(default=0, verbose_name='传输速度(字节/秒)')
    # 时间信息
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间', db_index=True)
    started_at = models.DateTimeField(null=True, blank=True, verbose_name='开始时间')
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='完成时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    # 错误信息
    error_message = models.TextField(blank=True, null=True, verbose_name='错误信息')
    # Celery任务ID（用于追踪分片合并任务）
    celery_task_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name='Celery任务ID',
        help_text='分片合并任务的Celery任务ID',
        db_index=True
    )

    class Meta:
        db_table = 'tdyw_document_transfer'
        verbose_name = '文件传输记录'
        verbose_name_plural = '文件传输记录'
        # 索引优化：支持租户+用户查询、租户+状态查询、租户+文件哈希查询
        indexes = [
            models.Index(fields=['tenant_id', 'user'], name='idx_transfer_tenant_user'),
            models.Index(fields=['tenant_id', 'status'], name='idx_transfer_tenant_status'),
            models.Index(fields=['tenant_id', 'file_hash'], name='idx_transfer_tenant_hash'),
            models.Index(fields=['user', 'status'], name='idx_transfer_user_status'),
            models.Index(fields=['created_at'], name='idx_transfer_created'),
            models.Index(fields=['status', 'updated_at'], name='transfer_status_updated_idx'),
        ]

    def __str__(self):
        return f"{self.transfer_type} - {self.file_name} - {self.status}"


# ==================== 系统目录绑定模型 ====================

class DocumentSystemFolder(models.Model):
    """系统目录绑定模型

    用于绑定公共空间中的受保护业务根目录（如"行业规章"），
    使前端可以按业务入口呈现独立模块，后端可据此做范围校验和根目录保护。

    - 不靠目录名称判断，避免用户改名或重名歧义
    - folder 外键 on_delete=PROTECT，防止系统目录被数据库级误删
    - 初始化命令可幂等执行，便于部署和修复
    """
    code = models.CharField(
        max_length=64, unique=True, db_index=True,
        help_text='系统目录编码，行业规章固定为 industry_rules',
        verbose_name='系统目录编码'
    )
    name = models.CharField(max_length=100, verbose_name='显示名称')
    folder = models.ForeignKey(
        DocumentFolderPublic, on_delete=models.PROTECT,
        related_name='system_bindings',
        verbose_name='绑定的公共目录',
        help_text='绑定的 DocumentFolderPublic 根目录'
    )
    is_public = models.BooleanField(default=True, verbose_name='是否公共空间')
    protected = models.BooleanField(default=True, verbose_name='是否保护根目录')
    description = models.CharField(max_length=255, blank=True, default='', verbose_name='说明')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'tdyw_document_system_folder'
        verbose_name = '文档系统目录绑定'
        verbose_name_plural = '文档系统目录绑定'

    def __str__(self):
        return f'{self.code} -> folder({self.folder_id})'
