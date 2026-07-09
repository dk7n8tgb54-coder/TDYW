# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
行业规章业务模型

设计原则：
- 规章台账（IndustryRule）记录业务语义：编号、名称、类别、发布单位、
  适用范围、发布/生效/废止日期、状态、版本、摘要。
- 附件（IndustryRuleAttachment）引用资料库 DocumentFilePublic，
  不复制文件存储逻辑，文件仍由资料库统一管理（受 system_folder=industry_rules 范围保护）。
- 一条规章可关联多个附件，其中可标记一个为主附件。
"""
import logging
from django.db import models

from apps.account.models import User

logger = logging.getLogger(__name__)


class IndustryRule(models.Model):
    """行业规章台账"""

    # 状态枚举
    STATUS_DRAFT = 'draft'        # 草稿
    STATUS_UPCOMING = 'upcoming'  # 即将生效
    STATUS_ACTIVE = 'active'      # 现行
    STATUS_RETIRED = 'retired'    # 已废止

    STATUS_CHOICES = (
        (STATUS_DRAFT, '草稿'),
        (STATUS_UPCOMING, '即将生效'),
        (STATUS_ACTIVE, '现行'),
        (STATUS_RETIRED, '已废止'),
    )

    title = models.CharField(max_length=255, verbose_name='规章名称')
    rule_no = models.CharField(max_length=100, blank=True, default='', db_index=True, verbose_name='规章编号')
    category = models.CharField(max_length=50, blank=True, default='', db_index=True, verbose_name='规章类别')
    issuing_authority = models.CharField(max_length=200, blank=True, default='', db_index=True, verbose_name='发布单位')
    applicable_scope = models.CharField(max_length=255, blank=True, default='', verbose_name='适用范围')
    publish_date = models.DateField(null=True, blank=True, verbose_name='发布日期')
    effective_date = models.DateField(null=True, blank=True, db_index=True, verbose_name='生效日期')
    repeal_date = models.DateField(null=True, blank=True, verbose_name='废止日期')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True, verbose_name='状态')
    version = models.CharField(max_length=50, blank=True, default='', verbose_name='版本')
    summary = models.TextField(blank=True, default='', verbose_name='摘要')

    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name='created_industry_rules', verbose_name='创建人')
    updated_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name='updated_industry_rules', verbose_name='更新人')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'tdyw_industry_rule'
        verbose_name = '行业规章'
        verbose_name_plural = '行业规章'
        ordering = ['-effective_date', '-created_at']

    def __str__(self):
        return f'{self.rule_no or ""} {self.title}'.strip()


class IndustryRuleAttachment(models.Model):
    """行业规章附件（关联资料库 DocumentFilePublic）"""

    rule = models.ForeignKey(IndustryRule, on_delete=models.CASCADE, related_name='attachments', verbose_name='所属规章')
    document_file = models.ForeignKey(
        'document.DocumentFilePublic', on_delete=models.CASCADE,
        related_name='industry_rule_attachments', verbose_name='关联文件',
    )
    is_primary = models.BooleanField(default=False, verbose_name='是否主附件')
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name='industry_rule_attachments', verbose_name='关联人')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='关联时间')

    class Meta:
        db_table = 'tdyw_industry_rule_attachment'
        verbose_name = '行业规章附件'
        verbose_name_plural = '行业规章附件'
        unique_together = (('rule', 'document_file'),)
        ordering = ['-is_primary', '-created_at']
