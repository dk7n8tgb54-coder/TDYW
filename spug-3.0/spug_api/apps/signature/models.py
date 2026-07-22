# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""账号签名 - 数据模型

第一阶段：`AccountSignature`（账号当前签名绑定）。
第二阶段：`SignatureUsage`（不可变的实际签署使用快照），用于固化签署时的签名版本、
文件哈希、业务快照哈希、签署人和证据事件，保证历史业务记录不随当前签名变化。
"""
from django.db import models

from django.utils import timezone
from libs import ModelMixin


# ==================== 状态常量 ====================
# 禁止散落魔法字符串，所有状态判断使用以下常量
STATUS_ACTIVE = 'active'
STATUS_DISABLED = 'disabled'
STATUS_CHOICES = (
    (STATUS_ACTIVE, '生效'),
    (STATUS_DISABLED, '已停用'),
)
# 账号列表轻量状态值（前端展示用）
LIST_STATUS_NONE = 'none'
LIST_STATUS_ACTIVE = 'active'
LIST_STATUS_DISABLED = 'disabled'


class AccountSignature(models.Model, ModelMixin):
    """账号当前签名绑定

    每个账号最多一条记录（user_id 唯一约束）。
    - 首次赋予版本为 1，替换时严格递增；
    - current_attachment_id 指向 EvidenceAttachment.id（逻辑外键，保持与项目附件模型低耦合）；
    - 停用只改变 status，不删除附件和物理文件；
    - 替换生成新附件记录和新物理文件，旧版本保留。
    """
    # ---- 租户与目标账号 ----
    tenant_id = models.CharField(max_length=50, default='', db_index=True, help_text='目标账号所属租户快照')
    user_id = models.BigIntegerField(unique=True, help_text='目标账号 ID，一账号一条绑定记录')

    # ---- 当前版本指针 ----
    current_attachment_id = models.BigIntegerField(null=True, blank=True, help_text='当前签名对应的 EvidenceAttachment.id')
    version = models.PositiveIntegerField(default=1, help_text='当前版本号，从 1 递增')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE, help_text='签名状态')

    # ---- 赋予/替换 快照 ----
    assigned_by_id = models.BigIntegerField(null=True, blank=True, help_text='最近一次赋予/替换的超级管理员 ID')
    assigned_by_name = models.CharField(max_length=100, default='', help_text='管理员姓名快照')
    assigned_at = models.DateTimeField(default=timezone.now, help_text='最近一次赋予/替换时间')

    # ---- 停用 快照 ----
    disabled_by_id = models.BigIntegerField(null=True, blank=True, help_text='停用操作人 ID')
    disabled_by_name = models.CharField(max_length=100, null=True, blank=True, help_text='停用操作人姓名快照')
    disabled_at = models.DateTimeField(null=True, blank=True, help_text='停用时间')

    # ---- 备注 ----
    remark = models.CharField(max_length=255, default='', blank=True, help_text='管理备注，不返回给普通业务页面')

    # ---- 时间 ----
    created_at = models.DateTimeField(auto_now_add=True, help_text='创建时间')
    updated_at = models.DateTimeField(auto_now=True, help_text='更新时间')

    def __repr__(self):
        return '<AccountSignature user_id=%r version=%r status=%r>' % (
            self.user_id, self.version, self.status)

    class Meta:
        db_table = 'tdyw_account_signatures'
        verbose_name = '账号签名'
        verbose_name_plural = '账号签名'
        ordering = ('-id',)
        indexes = [
            # 账号列表按租户+状态筛选签名
            models.Index(fields=['tenant_id', 'status'], name='sig_tenant_status_idx'),
            # 账号列表批量查询签名状态（user_id 已有唯一约束自带索引，此处不再重复）
        ]


class SignatureUsage(models.Model, ModelMixin):
    """不可变的实际签署使用快照

    每次账号在具体业务模块中完成一次正式签署，写入一条不可变记录，固化：
    - 签署人身份快照（signer_user_id / signer_username / signer_name）
    - 签名图片版本（signature_attachment_id / signature_version / signature_sha256）
    - 业务数据摘要（business_snapshot / business_snapshot_hash）
    - 请求幂等键（request_id / request_fingerprint）
    - 证据事件关联（evidence_event_id）
    - 服务器签署时间和 IP（signed_at / signer_ip）

    不可变规则：
    - 创建完成后不提供普通更新和删除服务；
    - 不提供 DELETE API；
    - 不允许替换附件、版本、签署人或哈希；
    - evidence_event_id 只在创建流程的最终步骤回填；
    - 撤回、作废、重签通过新事件或新记录表达，不修改本表。

    幂等：
    - (tenant_id, request_id) 唯一约束保证数据库级幂等；
    - 相同 (tenant_id, request_id) 重试时，若关键字段一致则返回已有记录，
      否则返回冲突。
    """
    # ---- 租户与业务对象 ----
    tenant_id = models.CharField(max_length=50, default='', db_index=True, help_text='签署业务所属租户')
    module = models.CharField(max_length=50, help_text='已批准接入的调用模块标识')
    object_type = models.CharField(max_length=50, help_text='已批准模块中的业务对象类型')
    object_id = models.CharField(max_length=50, help_text='业务对象 ID')
    scene_code = models.CharField(max_length=50, help_text='签署位置，如 operator/reviewer/approver')

    # ---- 签署人身份快照（姓名只展示，身份以账号 ID 为准）----
    signer_user_id = models.BigIntegerField(help_text='签署账号 ID')
    signer_username = models.CharField(max_length=100, default='', help_text='登录名快照')
    signer_name = models.CharField(max_length=100, default='', help_text='显示姓名快照')

    # ---- 签名图片版本固化 ----
    signature_attachment_id = models.BigIntegerField(help_text='签署时使用的 EvidenceAttachment.id')
    signature_version = models.PositiveIntegerField(help_text='签署时账号签名版本号')
    signature_sha256 = models.CharField(max_length=64, default='', help_text='签名文件 SHA256 快照')

    # ---- 业务数据摘要 ----
    business_snapshot = models.TextField(null=True, blank=True, help_text='业务快照 JSON 字符串（最小必要摘要）')
    business_snapshot_hash = models.CharField(max_length=64, default='', help_text='业务快照规范化 SHA256')

    # ---- 签署时间和来源 ----
    signed_at = models.DateTimeField(help_text='服务器签署时间')
    signer_ip = models.CharField(max_length=50, default='', help_text='请求来源 IP')

    # ---- 请求幂等 ----
    request_id = models.CharField(max_length=64, help_text='请求追踪 ID / 幂等键')
    request_fingerprint = models.CharField(
        max_length=64, default='', help_text='请求指纹 SHA256，覆盖 tenant/signer/module/object/scene/snapshot_hash')

    # ---- 证据事件关联 ----
    evidence_event_id = models.BigIntegerField(null=True, blank=True, help_text='对应 EvidenceEvent.id')

    def __repr__(self):
        return '<SignatureUsage id=%r tenant=%r module=%r object=%r/%r scene=%r signer=%r>' % (
            self.id, self.tenant_id, self.module, self.object_type, self.object_id,
            self.scene_code, self.signer_user_id)

    class Meta:
        db_table = 'tdyw_signature_usages'
        verbose_name = '签名使用记录'
        verbose_name_plural = '签名使用记录'
        ordering = ('-id',)
        indexes = [
            # 按业务对象查询签名
            models.Index(fields=['tenant_id', 'module', 'object_type', 'object_id'],
                         name='sig_usage_obj_idx'),
            # 按签署人追溯
            models.Index(fields=['tenant_id', 'signer_user_id', 'signed_at'],
                         name='sig_usage_signer_idx'),
            # 判断某版本是否已被业务使用（防止物理删除被引用的附件）
            models.Index(fields=['signature_attachment_id'], name='sig_usage_att_idx'),
        ]
        constraints = [
            # 数据库级幂等：相同 (tenant_id, request_id) 只能存在一条记录
            # request_id 作用域为租户内，与 tenant_id 组成唯一约束
            models.UniqueConstraint(
                fields=['tenant_id', 'request_id'],
                name='sig_usage_tenant_request_uniq',
            ),
        ]
