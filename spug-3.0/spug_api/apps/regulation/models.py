# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""规章管理业务模型

设计原则：
- 规章台账（Regulation）记录业务语义：编号、名称、分类、发布单位、
  业务类型、发布/生效日期、状态。
- 分类树（RegulationCategory）支持多级分类，供左侧树形导航使用。
- 附件（RegulationAttachment）为规章管理模块独立附件表，
  不再外键关联资料库 DocumentFilePublic。物理文件存储在
  storage/documents/regulation/ 子目录下，数据库只存相对路径。
"""
from django.db import models

from libs import human_datetime
from apps.account.models import User


class RegulationCategory(models.Model):
    """规章管理分类树（左侧多级树）"""
    name = models.CharField(max_length=100, verbose_name='分类名称')
    parent = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.CASCADE,
        related_name='children', verbose_name='父分类',
    )
    sort_order = models.IntegerField(default=0, verbose_name='排序')
    code = models.CharField(max_length=50, blank=True, default='', verbose_name='分类编码')
    is_leaf = models.BooleanField(default=True, verbose_name='是否叶子节点')
    created_at = models.CharField(max_length=20, default=human_datetime, verbose_name='创建时间')
    created_by = models.ForeignKey(
        User, null=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='创建人',
    )

    class Meta:
        db_table = 'tdyw_regulation_category'
        verbose_name = '规章分类'
        verbose_name_plural = '规章分类'
        ordering = ['sort_order', 'id']
        indexes = [
            models.Index(fields=['parent', 'sort_order'], name='reg_cat_parent_sort_idx'),
        ]

    def __str__(self):
        return self.name


class Regulation(models.Model):
    """规章台账"""

    # 状态枚举
    STATUS_ACTIVE = 'active'      # 现行
    STATUS_RETIRED = 'retired'    # 已废止

    STATUS_CHOICES = (
        (STATUS_ACTIVE, '现行'),
        (STATUS_RETIRED, '已废止'),
    )

    title = models.CharField(max_length=255, verbose_name='规章名称')
    rule_no = models.CharField(max_length=100, db_index=True, verbose_name='规章编号')
    category = models.ForeignKey(
        RegulationCategory, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='regulations', verbose_name='所属分类',
    )
    issuing_authority = models.CharField(max_length=200, blank=True, default='', db_index=True, verbose_name='发文单位')
    biz_type = models.CharField(max_length=50, blank=True, default='', db_index=True, verbose_name='业务类型')
    publish_date = models.DateField(null=True, blank=True, verbose_name='发布日期')
    effective_date = models.DateField(null=True, blank=True, db_index=True, verbose_name='生效日期')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE, db_index=True, verbose_name='状态')

    updated_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name='+', verbose_name='更新人')
    updated_at = models.CharField(max_length=20, null=True, blank=True, verbose_name='更新时间')

    class Meta:
        db_table = 'tdyw_regulation'
        verbose_name = '规章'
        verbose_name_plural = '规章'
        ordering = ['-effective_date', '-id']
        indexes = [
            models.Index(fields=['rule_no'], name='reg_rule_no_idx'),
            models.Index(fields=['issuing_authority'], name='reg_issue_auth_idx'),
            models.Index(fields=['biz_type'], name='reg_biz_type_idx'),
            models.Index(fields=['status'], name='reg_status_idx'),
        ]

    def __str__(self):
        return f'{self.rule_no or ""} {self.title}'.strip()


class RegulationAttachment(models.Model):
    """规章附件（模块独立附件表，不关联资料库 DocumentFilePublic）

    物理文件存储路径：storage/documents/regulation/{regulation_id}/{yyyy}/{mm}/{safe_name_uuid.ext}
    数据库 file_path 字段只存相对路径：regulation/{regulation_id}/{yyyy}/{mm}/{safe_name_uuid.ext}
    """
    regulation = models.ForeignKey(
        Regulation, on_delete=models.CASCADE,
        related_name='attachments', verbose_name='所属规章',
    )

    original_name = models.CharField(max_length=255, verbose_name='原始文件名')
    stored_name = models.CharField(max_length=255, verbose_name='存储文件名')
    file_path = models.CharField(max_length=500, verbose_name='文件相对路径')
    file_size = models.BigIntegerField(default=0, verbose_name='文件大小')
    file_type = models.CharField(max_length=100, blank=True, default='', verbose_name='文件类型')
    file_hash = models.CharField(max_length=64, blank=True, default='', db_index=True, verbose_name='文件哈希')

    sort_order = models.IntegerField(default=0, verbose_name='排序')

    uploaded_by = models.ForeignKey(
        User, null=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='上传人',
    )
    uploaded_at = models.CharField(max_length=20, default=human_datetime, verbose_name='上传时间')

    is_deleted = models.BooleanField(default=False, db_index=True, verbose_name='是否删除')
    deleted_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='删除人',
    )
    deleted_at = models.CharField(max_length=20, null=True, blank=True, verbose_name='删除时间')

    class Meta:
        db_table = 'tdyw_regulation_attachment'
        verbose_name = '规章附件'
        verbose_name_plural = '规章附件'
        ordering = ['sort_order', '-id']
        indexes = [
            models.Index(fields=['regulation', 'is_deleted', 'sort_order'], name='reg_att_list_idx'),
        ]
