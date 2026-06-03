# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
import os
from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone
from apps.account.models import User


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

# 为了向后兼容，保留类名
class TenantType:
    PUBLIC = 'PUBLIC'
    PRIVATE = 'PRIVATE'
    GLOBAL = 'GLOBAL'


# ==================== 私有空间模型（原有数据保留） ====================
class DocumentFolderPrivate(models.Model):
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

    # ========== 自定义管理器（【V3】双管理器）==========
    objects = SoftDeletedManager()      # 默认：不包含已删除
    all_objects = AllObjectsManager()   # 全量：包含已删除

    class Meta:
        db_table = 'tdyw_document_folder_private'
        verbose_name = '文档文件夹(私有)'
        verbose_name_plural = '文档文件夹(私有)'
        ordering = ['-created_at']

    def __str__(self):
        return self.name

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

    def get_full_path(self):
        """获取文件夹完整路径（用于显示）"""
        if self.parent and not self.parent.is_deleted:
            return f"{self.parent.get_full_path()}/{self.name}"
        return self.name


class DocumentFilePrivate(models.Model):
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
        ordering = ['-created_at']

    def __str__(self):
        return self.display_name or self.name

    def delete(self, *args, **kwargs):
        """
        【P0修复】重写删除方法：默认软删除，硬删除时确保物理文件删除成功

        Args:
            hard: 是否硬删除（默认False软删除）
        """
        import logging
        logger = logging.getLogger(__name__)

        hard = kwargs.pop('hard', False)

        if hard:
            # 【P0修复】硬删除：先删除物理文件，成功后再删除数据库记录
            physical_deleted = True
            if os.path.exists(self.file_path):
                try:
                    os.remove(self.file_path)
                    logger.info(f'[RecycleBin] 物理文件已删除: {self.file_path}')
                except Exception as e:
                    logger.error(f'[RecycleBin] 删除物理文件失败: {self.file_path}, error={e}')
                    physical_deleted = False

            # 删除缩略图
            if self.thumbnail_path and os.path.exists(self.thumbnail_path):
                try:
                    os.remove(self.thumbnail_path)
                    logger.info(f'[RecycleBin] 缩略图已删除: {self.thumbnail_path}')
                except Exception as e:
                    logger.warning(f'[RecycleBin] 删除缩略图失败: {self.thumbnail_path}, error={e}')

            # 【P0修复】只有物理文件删除成功才删除数据库记录
            if physical_deleted:
                super().delete(*args, **kwargs)
            else:
                # 标记为待清理状态，由定时任务重试
                self.is_pending_clean = True
                self.clean_retry_count = (self.clean_retry_count or 0) + 1
                self.last_clean_attempt = timezone.now()
                self.save(update_fields=['is_pending_clean', 'clean_retry_count', 'last_clean_attempt'])
                raise Exception(f'物理文件删除失败，已标记为待清理: {self.file_path}')
        else:
            # 软删除：标记删除状态
            self.is_deleted = True
            self.deleted_at = timezone.now()
            self.save(update_fields=['is_deleted', 'deleted_at'])

    def restore(self):
        """【V3】恢复软删除的文件"""
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=['is_deleted', 'deleted_at'])


# ==================== 公共共享空间模型（新建表） ====================
class DocumentFolderPublic(models.Model):
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

    # ========== 自定义管理器（【V3】双管理器）==========
    objects = SoftDeletedManager()      # 默认：不包含已删除
    all_objects = AllObjectsManager()   # 全量：包含已删除

    class Meta:
        db_table = 'tdyw_document_folder_public'
        verbose_name = '文档文件夹(公共)'
        verbose_name_plural = '文档文件夹(公共)'
        ordering = ['-created_at']
        # 公共表唯一索引: 同一父文件夹下不允许同名文件夹,避免同名冲突
        constraints = [
            models.UniqueConstraint(
                fields=['name', 'parent'],
                name='unique_folder_name_parent_public'
            )
        ]

    def __str__(self):
        return self.name

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

    def get_full_path(self):
        """获取文件夹完整路径（用于显示）"""
        if self.parent and not self.parent.is_deleted:
            return f"{self.parent.get_full_path()}/{self.name}"
        return self.name


class DocumentFilePublic(models.Model):
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
        ordering = ['-created_at']
        # 公共表唯一索引: 同一文件夹下不允许同名文件
        constraints = [
            models.UniqueConstraint(
                fields=['name', 'folder'],
                name='unique_file_name_folder_public'
            )
        ]

    def __str__(self):
        return self.display_name or self.name

    def delete(self, *args, **kwargs):
        """
        【P0修复】重写删除方法：默认软删除，硬删除时确保物理文件删除成功
        """
        import logging
        logger = logging.getLogger(__name__)

        hard = kwargs.pop('hard', False)

        if hard:
            # 【P0修复】硬删除：先删除物理文件，成功后再删除数据库记录
            physical_deleted = True
            if os.path.exists(self.file_path):
                try:
                    os.remove(self.file_path)
                    logger.info(f'[RecycleBin] 物理文件已删除: {self.file_path}')
                except Exception as e:
                    logger.error(f'[RecycleBin] 删除物理文件失败: {self.file_path}, error={e}')
                    physical_deleted = False

            # 删除缩略图
            if self.thumbnail_path and os.path.exists(self.thumbnail_path):
                try:
                    os.remove(self.thumbnail_path)
                    logger.info(f'[RecycleBin] 缩略图已删除: {self.thumbnail_path}')
                except Exception as e:
                    logger.warning(f'[RecycleBin] 删除缩略图失败: {self.thumbnail_path}, error={e}')

            # 【P0修复】只有物理文件删除成功才删除数据库记录
            if physical_deleted:
                super().delete(*args, **kwargs)
            else:
                # 标记为待清理状态，由定时任务重试
                self.is_pending_clean = True
                self.clean_retry_count = (self.clean_retry_count or 0) + 1
                self.last_clean_attempt = timezone.now()
                self.save(update_fields=['is_pending_clean', 'clean_retry_count', 'last_clean_attempt'])
                raise Exception(f'物理文件删除失败，已标记为待清理: {self.file_path}')
        else:
            self.is_deleted = True
            self.deleted_at = timezone.now()
            self.save(update_fields=['is_deleted', 'deleted_at'])
    
    def restore(self):
        """【V3】恢复软删除的文件"""
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=['is_deleted', 'deleted_at'])


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
        ordering = ['-created_at']
        # 索引优化：支持租户+用户查询、租户+状态查询、租户+文件哈希查询
        indexes = [
            models.Index(fields=['tenant_id', 'user'], name='idx_transfer_tenant_user'),
            models.Index(fields=['tenant_id', 'status'], name='idx_transfer_tenant_status'),
            models.Index(fields=['tenant_id', 'file_hash'], name='idx_transfer_tenant_hash'),
            models.Index(fields=['user', 'status'], name='idx_transfer_user_status'),
            models.Index(fields=['created_at'], name='idx_transfer_created'),
        ]

    def __str__(self):
        return f"{self.transfer_type} - {self.file_name} - {self.status}"

