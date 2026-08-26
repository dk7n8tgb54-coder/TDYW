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


# 定义租户类型枚举
TENANT_TYPE_CHOICES = (
    ('PUBLIC', '公共表'),
    ('GLOBAL', '全局表（无租户）'),
)


class TenantType:
    """为了向后兼容，保留类名"""
    PUBLIC = 'PUBLIC'
    GLOBAL = 'GLOBAL'


# ==================== 模型 Mixin（抽象 Public/Private 重复逻辑） ====================

class FolderDeleteMixin(models.Model):
    """
    文件夹删除 Mixin

    物理删除（回收站已移除，不再支持软删除）。
    """
    class Meta:
        abstract = True

    def delete(self, *args, **kwargs):
        """物理删除文件夹"""
        super().delete(*args, **kwargs)


class FolderPathMixin:
    """
    文件夹路径 Mixin

    提供 get_full_path() 的迭代实现，带循环引用和深度保护。
    子类必须定义: name, parent (ForeignKey to self) 字段。
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

        while current:
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


class DocumentFileDeleteMixin(models.Model):
    """
    文件物理删除 Mixin

    提供物理文件+缩略图清理、is_pending_clean 兜底标记、
    DocumentPhysicalDeleteError 异常的通用实现。
    子类必须定义: file_path, thumbnail_path, is_pending_clean,
                  clean_retry_count, last_clean_attempt 字段。
    """
    class Meta:
        abstract = True

    def delete(self, *args, **kwargs):
        """
        物理删除：先删除物理文件，成功后再删除数据库记录

        事务语义：
            - 物理文件删除成功：super().delete() 在调用方的事务内完成
            - 物理文件删除失败：先保存 is_pending_clean 标记，再抛出
              DocumentPhysicalDeleteError。
              ⚠️ 注意：此保存使用嵌套 transaction.atomic()（即 savepoint），
              如果调用方外层事务随后回滚，此标记也会被回滚。
              调用方若需要此标记可靠落库，不应在捕获异常后回滚外层事务，
              而应让外层事务正常提交。如需更强保障，需改用异步补偿
              （如 Celery 任务重试待清理文件）。
        """
        # 删除物理文件，成功后再删除数据库记录
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


# ==================== 公共共享空间模型 ====================

class DocumentFolderPublic(FolderDeleteMixin, FolderPathMixin, UniqueKeyMixin):
    """公共共享空间文件夹模型 - 支持全平台共享"""
    TENANT_TYPE = 'PUBLIC'
    name = models.CharField(max_length=200, verbose_name='文件夹名称')
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, verbose_name='父文件夹')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name='创建人')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    # ========== 唯一性保障字段 ==========
    unique_key = models.CharField(
        max_length=32, null=True, blank=True, unique=True,
        editable=False, db_index=True,
        help_text='唯一标识键（MD5哈希）',
        verbose_name='唯一标识键'
    )

    class Meta:
        db_table = 'tdyw_document_folder_public'
        verbose_name = '文档文件夹(公共)'
        verbose_name_plural = '文档文件夹(公共)'
        indexes = [
            models.Index(
                fields=['parent_id', '-created_at', '-id'],
                name='doc_pub_folder_list_idx',
            ),
            # 名称排序索引（默认列表排序：文件夹按名称升序）
            models.Index(
                fields=['parent_id', 'name', 'id'],
                name='doc_pub_folder_name_idx',
            ),
        ]

    def __str__(self):
        return self.name

    def _compute_unique_key(self):
        """计算唯一标识键：同名+同父目录（公共空间不区分用户，MD5哈希）"""
        raw = f'{self.name}:{self.parent_id or "ROOT"}'
        return hashlib.md5(raw.encode('utf-8')).hexdigest()


class DocumentFilePublic(DocumentFileDeleteMixin):
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

    # ========== 软删除字段（已移除）==========
    # is_deleted / deleted_at 已于 2026-07-30 移除（回收站功能已废弃）

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

    class Meta:
        db_table = 'tdyw_document_file_public'
        verbose_name = '文档文件(公共)'
        verbose_name_plural = '文档文件(公共)'
        constraints = [
            models.UniqueConstraint(
                fields=['name', 'folder'],
                name='unique_file_name_folder_public'
            )
        ]
        indexes = [
            models.Index(
                fields=['folder_id', '-created_at', '-id'],
                name='doc_pub_file_list_idx',
            ),
            # 名称排序索引（默认列表排序：文件按显示名称升序）
            models.Index(
                fields=['folder_id', 'display_name', 'id'],
                name='doc_pub_file_name_idx',
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
        ('COPY', '复制'),
    )

    TRANSFER_STATUS_CHOICES = (
        ('PENDING', '等待中'),
        ('UPLOADING', '上传中'),
        ('DOWNLOADING', '下载中'),
        ('PAUSED', '已暂停'),
        ('MERGING', '合并中'),
        ('COPYING', '复制中'),
        ('COMPLETED', '已完成'),
        ('FAILED', '失败'),
        ('CANCELED', '已取消'),
    )

    id = models.BigAutoField(primary_key=True)
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
    file_size = models.BigIntegerField(default=1, validators=[MinValueValidator(1)], verbose_name='文件大小(字节)')
    file_path = models.CharField(max_length=500, verbose_name='文件存储路径')
    file_hash = models.CharField(max_length=100, blank=True, default='', verbose_name='文件哈希(MD5)', db_index=True)
    # 目标文件夹（上传时使用）
    folder_id = models.IntegerField(null=True, blank=True, verbose_name='目标文件夹ID')
    is_public = models.BooleanField(default=True, verbose_name='是否公共空间')
    system_folder = models.CharField(
        max_length=64,
        blank=True,
        default='',
        db_index=True,
        help_text='系统目录编码；普通文档为空，党建文档为 party_building_documents',
        verbose_name='系统目录编码'
    )
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
    error_message = models.TextField(blank=True, default='', verbose_name='错误信息')
    # Celery任务ID（用于追踪分片合并任务）
    celery_task_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name='Celery任务ID',
        help_text='分片合并任务的Celery任务ID',
        db_index=True
    )
    # 复制任务专用字段
    source_file_id = models.BigIntegerField(
        null=True, blank=True, verbose_name='源文件记录ID',
        help_text='异步复制任务中源文件的数据库记录ID'
    )
    source_file_path = models.CharField(
        max_length=500, blank=True, default='', verbose_name='源文件物理路径',
        help_text='异步复制任务中源文件的物理路径'
    )
    conflict_action = models.CharField(
        max_length=10, blank=True, default='',
        verbose_name='冲突处理动作',
        help_text='复制冲突处理：keep/replace/skip'
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
            models.Index(fields=['user', 'is_public', 'system_folder'], name='idx_transfer_user_scope'),
            models.Index(fields=['created_at'], name='idx_transfer_created'),
            models.Index(fields=['status', 'updated_at'], name='transfer_status_updated_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(transfer_type__in=['UPLOAD', 'DOWNLOAD', 'COPY']),
                name='doc_transfer_type_valid',
            ),
            models.CheckConstraint(
                check=models.Q(status__in=[
                    'PENDING', 'UPLOADING', 'DOWNLOADING', 'PAUSED',
                    'MERGING', 'COPYING', 'COMPLETED', 'FAILED', 'CANCELED',
                ]),
                name='doc_transfer_status_valid',
            ),
            models.CheckConstraint(
                check=(
                    models.Q(file_size__gte=1) &
                    models.Q(total_chunks__gte=0) &
                    models.Q(uploaded_chunks__gte=0) &
                    models.Q(transferred_size__gte=0) &
                    models.Q(speed__gte=0)
                ),
                name='doc_transfer_counts_nonnegative',
            ),
            models.CheckConstraint(
                check=models.Q(progress__gte=0, progress__lte=100),
                name='doc_transfer_progress_range',
            ),
            models.CheckConstraint(
                check=(
                    models.Q(total_chunks=0) |
                    models.Q(uploaded_chunks__lte=models.F('total_chunks'))
                ),
                name='doc_transfer_chunks_order',
            ),
        ]

    def __str__(self):
        return f"{self.transfer_type} - {self.file_name} - {self.status}"


# ==================== 系统目录绑定模型 ====================

class DocumentSystemFolder(models.Model):
    """系统目录绑定模型

    用于绑定公共空间中的受保护业务根目录（如"党建文档"），
    使前端可以按业务入口呈现独立模块，后端可据此做范围校验和根目录保护。

    - 不靠目录名称判断，避免用户改名或重名歧义
    - folder 外键 on_delete=PROTECT，防止系统目录被数据库级误删
    - 初始化命令可幂等执行，便于部署和修复
    """
    code = models.CharField(
        max_length=64, unique=True, db_index=True,
        help_text='系统目录编码，党建文档固定为 party_building_documents',
        verbose_name='系统目录编码'
    )
    name = models.CharField(max_length=100, verbose_name='显示名称')
    folder = models.ForeignKey(
        DocumentFolderPublic, on_delete=models.PROTECT,
        related_name='system_bindings',
        unique=True,
        verbose_name='绑定的公共目录',
        help_text='绑定的 DocumentFolderPublic 根目录（唯一，同一目录不可绑定多个系统模块）'
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
