# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.

"""
证据服务 - 业务模块写入证据事件的统一入口

提供 record_evidence_event() 用于记录 submit/approve/reject/close/
correct/delete/export/void 等证据事件。

本阶段（第二阶段）只提供服务函数，不接入任何业务模块的视图/信号。
后续阶段各业务模块在关键动作处调用本服务写入证据事件。

设计要点：
- 在事务内查询同一业务对象链上一条的 event_hash 作为 prev_hash
- 显式生成 created_at，保证 event_hash 输入与落库值一致
- object_snapshot/attachment_hashes 接受 dict 或 JSON 字符串
- actor 身份快照：actor_user_id 为准，姓名/部门为快照
- 任何异常都不阻断业务主流程，仅记录错误日志并返回 None
"""
import json
import logging

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

from apps.evidence.models import EvidenceEvent
from apps.evidence.hash import compute_event_hash_from_values

logger = logging.getLogger(__name__)


# 合法事件类型集合（供调用方校验，避免拼写错误）
VALID_EVENT_TYPES = {
    'submit', 'approve', 'reject', 'close',
    'correct', 'delete', 'export', 'void', 'other',
}


def _serialize_snapshot(value):
    """将快照字段规范化为 JSON 字符串存库。

    - None → None（保留为空，表示无快照）
    - str  → 原样返回（调用方已序列化）
    - dict/list → DjangoJSONEncoder 规范序列化（支持日期、时间和 Decimal）
    """
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, cls=DjangoJSONEncoder,
    )


def record_evidence_event(
    tenant_id, module, object_type, object_id, event_type,
    actor_user_id=None, actor_username='', actor_name='',
    actor_department='', actor_ip='', actor_device='',
    object_snapshot=None, before_snapshot=None, after_snapshot=None,
    attachment_hashes=None, event_title='', remark='',
    audit_log_id=None, idempotency_key=None,
):
    """记录一条证据事件，自动构建按业务对象的哈希链。

    Args:
        tenant_id: 租户标识
        module: 业务模块（runlog/checksheet/radio_license/device/interference）
        object_type: 对象类型（业务自定义）
        object_id: 对象 ID
        event_type: 事件类型，见 VALID_EVENT_TYPES
        actor_user_id: 操作人账号 ID
        actor_username: 登录账号快照
        actor_name: 姓名快照
        actor_department: 部门快照
        actor_ip: 操作 IP
        actor_device: 设备信息
        object_snapshot: 业务对象快照（dict/JSON str/None）
        before_snapshot: 修改前快照
        after_snapshot: 修改后快照
        attachment_hashes: 附件哈希清单（dict/JSON str/None）
        event_title: 事件标题
        remark: 说明
        audit_log_id: 对应全局审计日志 ID
        idempotency_key: 幂等键（可选）。传入后在 30s 窗口内相同 key 的事件不会重复写入，
                         用于 Celery 任务重试场景。键存储在 remark 字段前缀 [idem:xxx]。

    Returns:
        EvidenceEvent 实例；失败返回 None（不抛异常，不阻断业务主流程）
    """
    if event_type not in VALID_EVENT_TYPES:
        logger.error(
            '[EVIDENCE] 非法事件类型: %s，合法值: %s', event_type, VALID_EVENT_TYPES
        )
        return None

    try:
        # R7 修复：幂等键去重，防止 Celery 重试重复写入
        if idempotency_key:
            from datetime import timedelta
            from django.utils import timezone as _tz
            threshold = _tz.now() - timedelta(seconds=30)
            idem_remark = f'[idem:{idempotency_key}]'
            if EvidenceEvent.objects.filter(
                tenant_id=tenant_id, module=module, object_type=object_type,
                object_id=str(object_id), event_type=event_type,
                remark__startswith=idem_remark, created_at__gte=threshold,
            ).exists():
                logger.info('[EVIDENCE] 幂等键重复，跳过事件写入: %s', idempotency_key)
                return None
            remark = f'{idem_remark} {remark}' if remark else idem_remark

        # 规范化快照字段为 JSON 字符串
        object_snapshot_s = _serialize_snapshot(object_snapshot)
        before_snapshot_s = _serialize_snapshot(before_snapshot)
        after_snapshot_s = _serialize_snapshot(after_snapshot)
        attachment_hashes_s = _serialize_snapshot(attachment_hashes)

        with transaction.atomic():
            # R4 修复：select_for_update 锁定行，防止并发读取相同 prev_hash 导致链断裂
            last_event = (
                EvidenceEvent.objects
                .select_for_update()
                .filter(
                    tenant_id=tenant_id,
                    module=module,
                    object_type=object_type,
                    object_id=str(object_id),
                )
                .order_by('-id')
                .first()
            )
            prev_hash = last_event.event_hash if last_event else ''

            # 显式生成 created_at，保证 event_hash 输入与落库值一致
            created_at = timezone.now()

            # 计算 event_hash（覆盖关键字段 + prev_hash）
            event_hash = compute_event_hash_from_values(
                tenant_id=tenant_id,
                module=module,
                object_type=object_type,
                object_id=object_id,
                event_type=event_type,
                actor_user_id=actor_user_id,
                actor_username=actor_username,
                actor_name=actor_name,
                object_snapshot=object_snapshot_s,
                attachment_hashes=attachment_hashes_s,
                prev_hash=prev_hash,
                created_at=created_at,
            )

            event = EvidenceEvent.objects.create(
                tenant_id=tenant_id,
                module=module,
                object_type=object_type,
                object_id=str(object_id),
                event_type=event_type,
                event_title=event_title,
                actor_user_id=actor_user_id,
                actor_username=actor_username,
                actor_name=actor_name,
                actor_department=actor_department,
                actor_ip=actor_ip,
                actor_device=actor_device,
                object_snapshot=object_snapshot_s,
                before_snapshot=before_snapshot_s,
                after_snapshot=after_snapshot_s,
                attachment_hashes=attachment_hashes_s,
                remark=remark,
                prev_hash=prev_hash,
                event_hash=event_hash,
                audit_log_id=audit_log_id,
                created_at=created_at,
            )
            return event
    except Exception as e:
        logger.error('[EVIDENCE] 记录证据事件失败: %s', e, exc_info=True)
        return None


def compute_attachment_hash(file_obj):
    """计算附件文件 SHA256（流式读取，避免大文件占内存）。

    Args:
        file_obj: 可读文件对象（Django UploadFile 或打开的文件句柄）

    Returns:
        str: 64 位十六进制 SHA256
    """
    import hashlib
    sha256 = hashlib.sha256()
    for chunk in iter(lambda: file_obj.read(8192), b''):
        sha256.update(chunk)
    # 重置指针，便于后续再次读取（如保存到磁盘）
    try:
        file_obj.seek(0)
    except Exception:
        pass
    return sha256.hexdigest()
