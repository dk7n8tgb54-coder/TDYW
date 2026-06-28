# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.

from django.db import models
from django.utils import timezone
from libs.mixins import ModelMixin


class AuditLog(models.Model, ModelMixin):
    """操作审计日志模型"""
    ACTION_CHOICES = [
        ('create', '创建'),
        ('update', '更新'),
        ('delete', '删除'),
        ('login', '登录'),
        ('logout', '登出'),
        ('export', '导出'),
        ('import', '导入'),
        ('approve', '审批'),
        ('other', '其他'),
    ]

    user_id = models.IntegerField()
    username = models.CharField(max_length=100)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    target_type = models.CharField(max_length=50)
    target_id = models.CharField(max_length=50, null=True)
    target_name = models.CharField(max_length=255, null=True)
    detail = models.TextField(null=True)
    ip = models.CharField(max_length=50)
    is_success = models.BooleanField(default=True)
    tenant_id = models.CharField(max_length=50, null=True, default='default')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')

    # ==== 证据闭环：哈希链相关字段（第一阶段） ====
    # request_hash：基于 detail（脱敏后存库内容）的 SHA256，证明详情未被静默篡改
    request_hash = models.CharField(
        max_length=64, default='', db_index=True,
        help_text='请求详情哈希(SHA256)，基于存库 detail 计算')
    # response_hash：响应体内容的 SHA256，流式响应/文件下载无内容时留空
    response_hash = models.CharField(
        max_length=64, default='',
        help_text='响应体哈希(SHA256)，无响应内容时留空')
    # prev_hash：同租户上一条审计日志的 log_hash，构成按租户的哈希链
    prev_hash = models.CharField(
        max_length=64, default='',
        help_text='同租户上一条日志 log_hash，构成哈希链；链首为空串')
    # log_hash：本条日志哈希，覆盖全部关键字段 + prev_hash，防篡改
    log_hash = models.CharField(
        max_length=64, default='', db_index=True,
        help_text='日志哈希(SHA256)，覆盖全部关键字段+prev_hash；旧数据为空')
    # request_id：单次请求唯一标识(uuid4)，便于关联同一请求产生的多条记录
    request_id = models.CharField(
        max_length=64, null=True, blank=True, db_index=True,
        help_text='请求唯一标识(uuid4)，关联同请求多条记录')
    # user_agent：客户端 User-Agent，用于辅助识别操作终端
    user_agent = models.CharField(
        max_length=500, null=True, blank=True,
        help_text='客户端 User-Agent')

    class Meta:
        db_table = 'audit_logs'
        ordering = ('-id',)
        # 审计日志会持续增长，按常用筛选字段建立索引避免列表查询随数据量线性变慢。
        # - tenant_id + (-id)：租户隔离下的分页主路径（默认按 -id 排序）
        # - tenant_id + (-created_at) + (-id)：时间范围筛选 + 时间倒序分页
        #   （views.py 中 start_time/end_time 筛选 + 长期时间倒序展示的主路径）
        # - tenant_id + created_at：兼容已有时间范围筛选（保留，避免破坏旧迁移）
        # - action / target_type / username：单项精确筛选
        # 注意：request_hash / log_hash / request_id 已在字段上设 db_index=True，
        #       Django 会自动建索引，此处不再重复声明，避免重复索引（写入/磁盘成本）。
        indexes = [
            models.Index(fields=['tenant_id', '-id'], name='audit_tenant_id_idx'),
            models.Index(fields=['tenant_id', 'created_at'], name='audit_tenant_time_idx'),
            models.Index(fields=['tenant_id', '-created_at', '-id'], name='audit_tenant_ctime_id_idx'),
            models.Index(fields=['action'], name='audit_action_idx'),
            models.Index(fields=['target_type'], name='audit_target_type_idx'),
            models.Index(fields=['username'], name='audit_username_idx'),
        ]
