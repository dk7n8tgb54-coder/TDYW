# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.

"""
证据闭环 - 统一证据底座模型

第一阶段已让全局操作审计具备哈希链能力（apps.logs）。
本阶段建立跨业务模块共用的证据事件表与附件证据表，
为运行日志、检查单、无线电执照、设备管理、干扰管理提供统一的证据写入入口。

设计原则：
- 业务数据可更正，不可悄悄覆盖：每次关键动作写一条证据事件，保留快照
- 姓名只展示，身份以账号 ID 为准：固化提交时的姓名/部门快照
- 附件必须可校验：上传即计算 SHA256，导出时重新校验
- 内网环境优先：不接入公网，仅做内部哈希存证；第三方时间戳/CA 预留字段

哈希链策略（方案 3.2.1 第一期）：
- 按"业务对象"(tenant_id + module + object_type + object_id) 形成链
- prev_hash = 同一业务对象链上一条的 event_hash
- 便于单条业务记录导出完整证据包
"""
from django.db import models
from libs.tenant_base_model import TenantModelMixin, TenantModelManager, make_tenant_id


# ==================== 证据事件类型 ====================
# submit/approve/reject/close/correct/delete/export/void
EVENT_TYPE_CHOICES = (
    ('submit', '提交'),
    ('approve', '审批通过'),
    ('reject', '驳回'),
    ('close', '关闭/归档'),
    ('correct', '更正'),
    ('delete', '删除'),
    ('export', '导出'),
    ('void', '作废'),
    ('other', '其他'),
)


class EvidenceEvent(models.Model, TenantModelMixin):
    """证据事件表（跨业务模块共用）

    每次关键动作（提交/复核/关闭/更正/作废/删除/导出）写一条记录，
    保存业务对象快照、附件哈希清单、操作人身份快照，
    并通过 prev_hash/event_hash 构成按业务对象的哈希链。
    """
    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    # ---- 业务对象定位 ----
    module = models.CharField(max_length=50, help_text='业务模块：runlog/checksheet/radio_license/device/interference')
    object_type = models.CharField(max_length=50, help_text='对象类型（业务自定义，如 runlog/checksheet_submission）')
    object_id = models.CharField(max_length=50, help_text='对象 ID')
    event_type = models.CharField(max_length=20, choices=EVENT_TYPE_CHOICES, help_text='事件类型')
    event_title = models.CharField(max_length=200, default='', help_text='事件标题/描述')

    # ---- 操作人身份快照（姓名只展示，身份以账号 ID 为准）----
    actor_user_id = models.IntegerField(null=True, blank=True, help_text='操作人账号 ID')
    actor_username = models.CharField(max_length=100, default='', help_text='登录账号快照')
    actor_name = models.CharField(max_length=100, default='', help_text='姓名快照')
    actor_department = models.CharField(max_length=100, default='', help_text='部门快照')
    actor_ip = models.CharField(max_length=50, default='', help_text='操作 IP')
    actor_device = models.CharField(max_length=255, default='', null=True, blank=True, help_text='设备信息，可为空')

    # ---- 业务对象快照 ----
    object_snapshot = models.TextField(null=True, blank=True, help_text='业务对象快照 JSON')
    before_snapshot = models.TextField(null=True, blank=True, help_text='修改前快照 JSON，可为空')
    after_snapshot = models.TextField(null=True, blank=True, help_text='修改后快照 JSON，可为空')
    attachment_hashes = models.TextField(null=True, blank=True, help_text='附件哈希清单 JSON')
    remark = models.CharField(max_length=500, default='', help_text='说明')

    # ---- 哈希链 ----
    prev_hash = models.CharField(max_length=64, default='', help_text='同一业务对象链上一条 event_hash；链首为空串')
    event_hash = models.CharField(max_length=64, default='', db_index=True, help_text='本条证据事件哈希(SHA256)')

    # ---- 关联 ----
    audit_log_id = models.IntegerField(null=True, blank=True, help_text='对应全局审计日志 ID，可为空')

    # ---- 预留：第三方时间戳/CA/电子签章（内网环境不实际接入）----
    external_ts_provider = models.CharField(max_length=50, default='', help_text='外部时间戳服务商标识，内网环境留空')
    external_ts_token = models.CharField(max_length=255, default='', help_text='外部时间戳凭证，内网环境留空')

    # ---- 时间 ----
    created_at = models.DateTimeField(auto_now_add=True, help_text='服务器时间')

    def __repr__(self):
        return '<EvidenceEvent %s/%s/%s %s>' % (
            self.module, self.object_type, self.object_id, self.event_type)

    def to_view(self):
        return self.to_dict()

    class Meta:
        db_table = 'tdyw_evidence_events'
        verbose_name = '证据事件'
        verbose_name_plural = '证据事件'
        ordering = ('-created_at', '-id')
        indexes = [
            # 业务对象主索引：按业务对象 + 时间倒序（证据包导出主路径）
            models.Index(fields=['tenant_id', 'module', 'object_type', 'object_id', '-id'],
                         name='ev_obj_chain_idx'),
            # 操作人筛选
            models.Index(fields=['tenant_id', 'actor_user_id'], name='ev_obj_actor_idx'),
            # 事件类型筛选
            models.Index(fields=['tenant_id', 'event_type'], name='ev_obj_type_idx'),
            # event_hash 校验
            models.Index(fields=['event_hash'], name='ev_event_hash_idx'),
        ]


class EvidenceAttachment(models.Model, TenantModelMixin):
    """附件证据表（抽象通用附件证据能力）

    各业务模块的附件表（如 RadioLicenseAttachment、运行日志附件）后续可：
    1. 直接复用本表（module + object_type + object_id 关联业务对象）
    2. 或在自身附件表增加 file_hash_sha256 字段并指向本表

    核心要求：
    - 上传即计算 SHA256
    - 原始文件名和磁盘文件名分开存
    - 删除附件优先做软删除
    - 证据包导出时重新计算 SHA256 并和入库值比对
    """
    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    # ---- 业务对象定位 ----
    module = models.CharField(max_length=50, help_text='业务模块')
    object_type = models.CharField(max_length=50, help_text='对象类型')
    object_id = models.CharField(max_length=50, help_text='对象 ID')

    # ---- 文件信息 ----
    file_name = models.CharField(max_length=255, help_text='原始文件名（用户上传时的名字）')
    file_path = models.CharField(max_length=500, help_text='磁盘存储路径（含重命名后的文件名）')
    file_size = models.BigIntegerField(default=0, help_text='文件大小(字节)')
    file_ext = models.CharField(max_length=20, default='', help_text='文件扩展名')
    file_hash_sha256 = models.CharField(max_length=64, default='', db_index=True, help_text='文件 SHA256')
    file_hash_md5 = models.CharField(max_length=32, default='', help_text='文件 MD5（兼容旧系统）')

    # ---- 上传人身份快照 ----
    uploaded_by_id = models.IntegerField(null=True, blank=True, help_text='上传人账号 ID')
    uploaded_by_name = models.CharField(max_length=100, default='', help_text='上传人姓名快照')

    # ---- 软删除 ----
    is_deleted = models.BooleanField(default=False, help_text='是否已删除（软删除）')
    deleted_by_id = models.IntegerField(null=True, blank=True, help_text='删除人账号 ID')
    deleted_by_name = models.CharField(max_length=100, default='', help_text='删除人姓名快照')
    deleted_at = models.DateTimeField(null=True, blank=True, help_text='删除时间')
    delete_reason = models.CharField(max_length=500, default='', help_text='删除原因')

    # ---- 时间 ----
    uploaded_at = models.DateTimeField(auto_now_add=True, help_text='上传时间')

    def __repr__(self):
        return '<EvidenceAttachment %s>' % self.file_name

    def to_view(self):
        return self.to_dict(excludes=('is_deleted',))

    class Meta:
        db_table = 'tdyw_evidence_attachments'
        verbose_name = '附件证据'
        verbose_name_plural = '附件证据'
        ordering = ('-uploaded_at', '-id')
        indexes = [
            # 业务对象主索引：按业务对象查附件
            models.Index(fields=['tenant_id', 'module', 'object_type', 'object_id'],
                         name='ev_att_obj_idx'),
            # 业务对象附件列表完整路径：tenant_id + 业务对象定位 + is_deleted + uploaded_at + id
            # 覆盖软删除筛选与时间倒序分页（AttachmentService.list / soft_delete_by_object）
            models.Index(
                fields=['tenant_id', 'module', 'object_type', 'object_id', 'is_deleted', 'uploaded_at', 'id'],
                name='ev_att_obj_del_time_idx',
            ),
            # SHA256 校验
            models.Index(fields=['file_hash_sha256'], name='ev_att_sha256_idx'),
            # 软删除筛选
            models.Index(fields=['tenant_id', 'is_deleted'], name='ev_att_del_idx'),
        ]
