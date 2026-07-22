# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""账号签名 - 服务层

第一阶段：超级管理员集中维护账号签名图片的基础能力。
- set_signature: 赋予或替换签名
- disable_signature / enable_signature: 停用 / 重新启用
- get_signature_admin_detail: 管理端详情
- list_signature_versions: 历史版本分页
- get_my_current_signature: 普通用户查询本人当前签名
- build_signature_preview_info: 生成受控预览信息

第二阶段：签名公共调用能力（不接入任何业务模块）。
- SIGNATURE_SCENES: 显式场景注册表，生产环境保持为空
- canonicalize_business_snapshot / compute_business_snapshot_hash: 业务快照规范化与哈希
- apply_signature: 唯一正式签署入口（不可变 SignatureUsage + EvidenceEvent）
- get_usage / get_usages_for_object / get_signature_image_for_render: 受控历史读取
"""
import hashlib
import json
import logging
import os
import uuid

from django.conf import settings
from django.db import transaction, IntegrityError

from django.utils import timezone
from libs.utils import get_request_real_ip
from apps.account.models import User
from apps.evidence.models import EvidenceAttachment
from apps.evidence.attachment_service import AttachmentService, AttachmentConfig
from apps.evidence.attachment_preview_token import generate_attachment_preview_token
from apps.evidence.services import record_evidence_event
from apps.logs.audit import record_audit_event

from .models import AccountSignature, SignatureUsage, STATUS_ACTIVE, STATUS_DISABLED
from .image_validator import validate_and_normalize_signature_image

logger = logging.getLogger(__name__)

# 签名附件固定归属
SIGNATURE_MODULE = 'account_signature'
SIGNATURE_OBJECT_TYPE = 'user_signature'

# 签名附件配置：仅 PNG，2MB
SignatureAttachmentConfig = AttachmentConfig(
    allowed_extensions=('.png',),
    max_size_mb=2,
)

# 签名预览令牌有效期（秒），复用 attachment_preview_token 机制
SIGNATURE_PREVIEW_TOKEN_MAX_AGE = 300


class _BytesUploadFile:
    """把标准化后的 PNG 字节流包装成 AttachmentService.upload 可接受的 file 对象。

    提供 name / size / chunks() / read() 接口，模拟 Django UploadedFile。
    """

    def __init__(self, data, name='signature.png'):
        self._data = data
        self.name = name
        self.size = len(data)
        self._seek = 0

    def chunks(self, chunk_size=64 * 1024):
        for i in range(0, len(self._data), chunk_size):
            yield self._data[i:i + chunk_size]

    def read(self, size=None):
        if size is None:
            data = self._data[self._seek:]
            self._seek = len(self._data)
            return data
        data = self._data[self._seek:self._seek + size]
        self._seek += len(data)
        return data

    def seek(self, pos, whence=0):
        if whence == 0:
            self._seek = pos
        elif whence == 1:
            self._seek += pos
        elif whence == 2:
            self._seek = len(self._data) + pos


def _require_supper(operator):
    """第一层校验：只有超级管理员可管理签名。"""
    if not getattr(operator, 'is_supper', False):
        return '权限拒绝：仅超级管理员可管理账号签名'
    return None


def _get_active_target_user(target_user_id):
    """查询未逻辑删除的目标账号，返回 User 或 None。"""
    if target_user_id is None:
        return None
    try:
        return User.objects.filter(pk=target_user_id, deleted_by_id__isnull=True).first()
    except (ValueError, TypeError):
        return None


def _get_attachment_sha256(attachment_id):
    """从附件表读取真实 SHA256（不信任前端值）。"""
    if not attachment_id:
        return ''
    att = EvidenceAttachment.objects.filter(pk=attachment_id).first()
    return att.file_hash_sha256 if att else ''


def _cleanup_orphan_file(file_path):
    """数据库失败后清理本次产生的孤立新文件，不影响旧版本。"""
    if not file_path:
        return
    try:
        full_path = os.path.join(settings.MEDIA_ROOT, file_path)
        media_real = os.path.realpath(settings.MEDIA_ROOT)
        file_real = os.path.realpath(full_path)
        # 路径必须在 MEDIA_ROOT 下，防穿越
        if not (file_real == media_real or file_real.startswith(media_real + os.sep)):
            logger.error(f'[Signature] 拒绝清理 MEDIA_ROOT 外的文件: {file_path}')
            return
        if os.path.exists(file_real):
            os.remove(file_real)
            logger.warning(f'[Signature] 已清理孤立签名文件: {file_path}')
    except Exception as e:
        logger.error(f'[Signature] 清理孤立签名文件失败: {file_path} {e}')


def _upsert_signature_in_tx(target_user, operator, att, remark):
    """事务内创建或替换目标账号签名绑定。

    首次赋予版本为 1；替换时严格递增版本号并清除停用快照。
    并发首次赋予由唯一约束兜底，抛 _SignatureConcurrentError。

    Returns:
        dict: sig/is_replace/old_attachment_id/old_version/old_sha256/
              new_version/audit_action/audit_target_name
    Raises:
        _SignatureConcurrentError: 并发首次赋予冲突
    """
    try:
        sig = AccountSignature.objects.select_for_update().get(user_id=target_user.id)
    except AccountSignature.DoesNotExist:
        # 首次赋予：并发时唯一约束兜底
        try:
            sig = AccountSignature.objects.create(
                tenant_id=target_user.tenant_id,
                user_id=target_user.id,
                current_attachment_id=att.id,
                version=1,
                status=STATUS_ACTIVE,
                assigned_by_id=operator.id,
                assigned_by_name=operator.nickname or operator.username,
                assigned_at=timezone.now(),
                remark=remark or '',
            )
        except IntegrityError:
            raise _SignatureConcurrentError('签名正在被其他操作处理，请刷新后重试')
        return {
            'sig': sig,
            'is_replace': False,
            'old_attachment_id': None,
            'old_version': None,
            'old_sha256': '',
            'new_version': 1,
            'audit_action': 'create',
            'audit_target_name': '赋予账号签名',
        }

    # 替换：严格递增版本号
    old_attachment_id = sig.current_attachment_id
    old_version = sig.version
    old_sha256 = _get_attachment_sha256(old_attachment_id)
    new_version = (sig.version or 0) + 1
    sig.current_attachment_id = att.id
    sig.version = new_version
    sig.status = STATUS_ACTIVE
    sig.assigned_by_id = operator.id
    sig.assigned_by_name = operator.nickname or operator.username
    sig.assigned_at = timezone.now()
    sig.remark = remark or ''
    # 重新启用语义：替换后清除停用快照
    sig.disabled_by_id = None
    sig.disabled_by_name = None
    sig.disabled_at = None
    sig.updated_at = timezone.now()
    sig.save(update_fields=[
        'current_attachment_id', 'version', 'status',
        'assigned_by_id', 'assigned_by_name', 'assigned_at',
        'remark', 'disabled_by_id', 'disabled_by_name', 'disabled_at',
        'updated_at',
    ])
    return {
        'sig': sig,
        'is_replace': True,
        'old_attachment_id': old_attachment_id,
        'old_version': old_version,
        'old_sha256': old_sha256,
        'new_version': new_version,
        'audit_action': 'update',
        'audit_target_name': '替换账号签名',
    }


def set_signature(operator, target_user_id, image_file, remark='', request=None):
    """赋予或替换目标账号的签名图片。

    - 首次赋予版本为 1，替换时严格递增；
    - 以目标账号租户保存附件；
    - 上传人记录真实超级管理员；
    - 替换不覆盖、不软删、不物理删除旧版本；
    - 数据库失败时清理本次产生的孤立新文件；
    - 写审计日志（区分首次赋予和替换）。

    Returns:
        tuple: (detail_dict, error_str)  error_str 为空表示成功
    """
    err = _require_supper(operator)
    if err:
        return None, err

    target_user = _get_active_target_user(target_user_id)
    if not target_user:
        return None, '目标账号不存在或已删除'

    # 1. 校验并标准化图片（内存操作，无副作用）
    try:
        normalized_bytes, _normalized_sha = validate_and_normalize_signature_image(image_file)
    except Exception as e:
        return None, str(e)

    # 2. 以目标账号租户上传附件，使用 UUID 磁盘文件名
    disk_name = f'{uuid.uuid4().hex}.png'
    upload_wrapper = _BytesUploadFile(normalized_bytes, name='signature.png')
    att, error = AttachmentService.upload(
        file=upload_wrapper,
        user=operator,
        module=SIGNATURE_MODULE,
        object_type=SIGNATURE_OBJECT_TYPE,
        object_id=str(target_user.id),
        config=SignatureAttachmentConfig,
        owner_tenant_id=target_user.tenant_id,
        disk_name=disk_name,
    )
    if error or not att:
        # upload 失败时 AttachmentService 内部一般未落盘或落盘失败，无需额外清理
        return None, error or '签名图片保存失败'

    # 3. 事务内更新当前绑定（select_for_update 防并发替换产生错误版本号）
    try:
        with transaction.atomic():
            result = _upsert_signature_in_tx(target_user, operator, att, remark)
    except _SignatureConcurrentError as e:
        _cleanup_orphan_file(att.file_path)
        return None, str(e)
    except Exception:
        # 事务回滚：EvidenceAttachment 记录随之回滚，但物理文件已落盘 → 清理
        logger.error('[Signature] set_signature 事务失败，清理孤立文件', exc_info=True)
        _cleanup_orphan_file(att.file_path)
        return None, '签名保存失败，请重试'

    sig = result['sig']
    is_replace = result['is_replace']
    old_attachment_id = result['old_attachment_id']
    old_version = result['old_version']
    old_sha256 = result['old_sha256']
    new_version = result['new_version']
    audit_action = result['audit_action']
    audit_target_name = result['audit_target_name']

    # 4. 审计
    new_sha256 = att.file_hash_sha256 or ''
    audit_detail = {
        'target_user_id': target_user.id,
        'target_username': target_user.username,
        'target_tenant_id': target_user.tenant_id,
        'old_attachment_id': old_attachment_id,
        'old_version': old_version,
        'old_sha256': old_sha256,
        'new_attachment_id': att.id,
        'new_version': new_version,
        'new_sha256': new_sha256,
        'remark': remark or '',
        'is_replace': is_replace,
    }
    try:
        record_audit_event(
            request=request,
            action=audit_action,
            target_type='signature',
            target_id=str(target_user.id),
            target_name=audit_target_name,
            detail=audit_detail,
            is_success=True,
        )
    except Exception:
        logger.error('[Signature] 审计记录失败', exc_info=True)

    # 5. 返回详情
    detail = _serialize_signature_detail(sig, target_user, att)
    return detail, None


def disable_signature(operator, target_user_id, reason='', request=None):
    """停用目标账号当前签名。"""
    err = _require_supper(operator)
    if err:
        return None, err

    target_user = _get_active_target_user(target_user_id)
    if not target_user:
        return None, '目标账号不存在或已删除'

    with transaction.atomic():
        try:
            sig = AccountSignature.objects.select_for_update().get(user_id=target_user.id)
        except AccountSignature.DoesNotExist:
            return None, '该账号尚未配置签名'
        if sig.status == STATUS_DISABLED:
            return None, '签名已停用，无需重复操作'
        old_status = sig.status
        sig.status = STATUS_DISABLED
        sig.disabled_by_id = operator.id
        sig.disabled_by_name = operator.nickname or operator.username
        sig.disabled_at = timezone.now()
        sig.updated_at = timezone.now()
        sig.save(update_fields=[
            'status', 'disabled_by_id', 'disabled_by_name', 'disabled_at', 'updated_at',
        ])

    # 审计
    audit_detail = {
        'target_user_id': target_user.id,
        'target_username': target_user.username,
        'target_tenant_id': target_user.tenant_id,
        'current_attachment_id': sig.current_attachment_id,
        'current_version': sig.version,
        'current_sha256': _get_attachment_sha256(sig.current_attachment_id),
        'old_status': old_status,
        'new_status': STATUS_DISABLED,
        'reason': reason or '',
    }
    try:
        record_audit_event(
            request=request,
            action='update',
            target_type='signature',
            target_id=str(target_user.id),
            target_name='停用账号签名',
            detail=audit_detail,
            is_success=True,
        )
    except Exception:
        logger.error('[Signature] 审计记录失败', exc_info=True)

    detail = _serialize_signature_detail(sig, target_user)
    return detail, None


def enable_signature(operator, target_user_id, request=None):
    """重新启用目标账号当前签名（继续启用当前版本，不重复上传）。"""
    err = _require_supper(operator)
    if err:
        return None, err

    target_user = _get_active_target_user(target_user_id)
    if not target_user:
        return None, '目标账号不存在或已删除'

    with transaction.atomic():
        try:
            sig = AccountSignature.objects.select_for_update().get(user_id=target_user.id)
        except AccountSignature.DoesNotExist:
            return None, '该账号尚未配置签名'
        if sig.status == STATUS_ACTIVE:
            return None, '签名已启用，无需重复操作'
        if not sig.current_attachment_id:
            return None, '当前没有可启用的签名版本'
        old_status = sig.status
        sig.status = STATUS_ACTIVE
        sig.disabled_by_id = None
        sig.disabled_by_name = None
        sig.disabled_at = None
        sig.updated_at = timezone.now()
        sig.save(update_fields=[
            'status', 'disabled_by_id', 'disabled_by_name', 'disabled_at', 'updated_at',
        ])

    # 审计
    audit_detail = {
        'target_user_id': target_user.id,
        'target_username': target_user.username,
        'target_tenant_id': target_user.tenant_id,
        'current_attachment_id': sig.current_attachment_id,
        'current_version': sig.version,
        'current_sha256': _get_attachment_sha256(sig.current_attachment_id),
        'old_status': old_status,
        'new_status': STATUS_ACTIVE,
    }
    try:
        record_audit_event(
            request=request,
            action='update',
            target_type='signature',
            target_id=str(target_user.id),
            target_name='启用账号签名',
            detail=audit_detail,
            is_success=True,
        )
    except Exception:
        logger.error('[Signature] 审计记录失败', exc_info=True)

    detail = _serialize_signature_detail(sig, target_user)
    return detail, None


def get_signature_admin_detail(operator, target_user_id):
    """管理端：查询目标账号当前签名详情。"""
    err = _require_supper(operator)
    if err:
        return None, err

    target_user = _get_active_target_user(target_user_id)
    if not target_user:
        return None, '目标账号不存在或已删除'

    sig = AccountSignature.objects.filter(user_id=target_user.id).first()
    if not sig:
        return {
            'configured': False,
            'user_id': target_user.id,
            'username': target_user.username,
            'nickname': target_user.nickname,
            'tenant_id': target_user.tenant_id,
            'status': 'none',
        }, None

    return _serialize_signature_detail(sig, target_user, include_preview=True, operator=operator), None


def list_signature_versions(operator, target_user_id, page=1, page_size=20):
    """管理端：分页查看目标账号签名历史版本摘要。"""
    err = _require_supper(operator)
    if err:
        return None, err

    target_user = _get_active_target_user(target_user_id)
    if not target_user:
        return None, '目标账号不存在或已删除'

    qs = EvidenceAttachment.objects.filter(
        module=SIGNATURE_MODULE,
        object_type=SIGNATURE_OBJECT_TYPE,
        object_id=str(target_user.id),
        is_deleted=False,
    ).order_by('-uploaded_at', '-id')

    total = qs.count()
    try:
        page = max(1, int(page))
        page_size = max(1, min(100, int(page_size)))
    except (TypeError, ValueError):
        page, page_size = 1, 20
    offset = (page - 1) * page_size
    items = []
    for att in qs[offset:offset + page_size]:
        items.append({
            'attachment_id': att.id,
            'version': None,  # 历史附件本身不存版本号，版本由 AccountSignature 切换记录
            'file_name': att.file_name,
            'file_size': att.file_size,
            'file_ext': att.file_ext,
            'sha256': att.file_hash_sha256,
            'uploaded_by_id': att.uploaded_by_id,
            'uploaded_by_name': att.uploaded_by_name,
            'uploaded_at': att.uploaded_at,
            'is_current': False,  # 由调用方按当前指针标记，下方补充
        })

    # 标记当前版本
    sig = AccountSignature.objects.filter(user_id=target_user.id).first()
    current_attachment_id = sig.current_attachment_id if sig else None
    for it in items:
        if it['attachment_id'] == current_attachment_id:
            it['is_current'] = True
            it['version'] = sig.version if sig else None

    return {
        'total': total,
        'page': page,
        'page_size': page_size,
        'items': items,
    }, None


def get_my_current_signature(user):
    """普通用户查询本人当前签名（只读）。

    不返回物理路径、绝对路径、管理员备注或历史列表。
    disabled / 账号停用 / 账号删除时 available=False。
    只查询登录账号本人，不接受 user_id 参数。
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return {'available': False}
    # 账号停用或已逻辑删除时返回不可用
    if not getattr(user, 'is_active', True):
        return {'available': False, 'user_id': getattr(user, 'id', None)}
    if getattr(user, 'deleted_by_id', None) is not None:
        return {'available': False, 'user_id': getattr(user, 'id', None)}
    sig = AccountSignature.objects.filter(user_id=user.id).first()
    if not sig or sig.status != STATUS_ACTIVE or not sig.current_attachment_id:
        return {'available': False, 'user_id': user.id}
    att = EvidenceAttachment.objects.filter(
        pk=sig.current_attachment_id,
        module=SIGNATURE_MODULE,
        object_type=SIGNATURE_OBJECT_TYPE,
        object_id=str(user.id),
        is_deleted=False,
    ).first()
    if not att:
        return {'available': False, 'user_id': user.id}

    # 生成短期预览令牌（绑定本人 + 本人附件 + 本人租户）
    preview_token = generate_attachment_preview_token(
        attachment_id=att.id,
        user_id=user.id,
        tenant_id=user.tenant_id or '',
        module=att.module,
        object_type=att.object_type,
        object_id=att.object_id,
    )
    preview_url = f'/api/signature/preview/{att.id}/?preview_token={preview_token}'
    return {
        'available': True,
        'user_id': user.id,
        'version': sig.version,
        'attachment_id': att.id,
        'sha256': att.file_hash_sha256,
        'preview_url': preview_url,
    }


def build_signature_preview_info(operator, attachment_id):
    """管理端预览：超管在管理目标账号时可预览对应版本。

    校验：
    - 超管身份
    - 附件存在且为签名模块附件
    - 返回短期预览令牌和 url

    Returns:
        tuple: (info_dict, error_str)
    """
    err = _require_supper(operator)
    if err:
        return None, err
    att = EvidenceAttachment.objects.filter(
        pk=attachment_id,
        module=SIGNATURE_MODULE,
        object_type=SIGNATURE_OBJECT_TYPE,
        is_deleted=False,
    ).first()
    if not att:
        return None, '签名附件不存在或无权限访问'
    preview_token = generate_attachment_preview_token(
        attachment_id=att.id,
        user_id=operator.id,
        tenant_id=att.tenant_id or '',
        module=att.module,
        object_type=att.object_type,
        object_id=att.object_id,
    )
    preview_url = f'/api/signature/preview/{att.id}/?preview_token={preview_token}'
    return {
        'attachment_id': att.id,
        'preview_url': preview_url,
        'preview_token': preview_token,
    }, None


def _serialize_signature_detail(sig, target_user, current_attachment=None, include_preview=False, operator=None):
    """序列化管理端详情，不含绝对路径。"""
    if current_attachment is None and sig.current_attachment_id:
        current_attachment = EvidenceAttachment.objects.filter(pk=sig.current_attachment_id).first()

    data = {
        'configured': True,
        'user_id': target_user.id,
        'username': target_user.username,
        'nickname': target_user.nickname,
        'tenant_id': target_user.tenant_id,
        'signature_id': sig.id,
        'current_attachment_id': sig.current_attachment_id,
        'version': sig.version,
        'status': sig.status,
        'assigned_by_id': sig.assigned_by_id,
        'assigned_by_name': sig.assigned_by_name,
        'assigned_at': sig.assigned_at,
        'disabled_by_id': sig.disabled_by_id,
        'disabled_by_name': sig.disabled_by_name,
        'disabled_at': sig.disabled_at,
        'remark': sig.remark,
        'created_at': sig.created_at,
        'updated_at': sig.updated_at,
        'sha256': current_attachment.file_hash_sha256 if current_attachment else '',
        'file_size': current_attachment.file_size if current_attachment else 0,
        'uploaded_at': current_attachment.uploaded_at if current_attachment else '',
    }
    if include_preview and operator is not None and sig.current_attachment_id:
        info, _ = build_signature_preview_info(operator, sig.current_attachment_id)
        if info:
            data['preview_url'] = info['preview_url']
    return data


def get_account_signature_status_map(user_ids):
    """批量查询账号签名状态，避免账号列表 N+1。

    Args:
        user_ids: 用户 ID 可迭代对象

    Returns:
        dict: {user_id: {'status': 'none'|'active'|'disabled', 'version': int|None}}
    """
    if not user_ids:
        return {}
    user_id_list = [int(uid) for uid in user_ids if uid is not None]
    if not user_id_list:
        return {}
    sigs = AccountSignature.objects.filter(user_id__in=user_id_list)
    return {
        s.user_id: {'status': s.status, 'version': s.version}
        for s in sigs
    }


class _SignatureConcurrentError(Exception):
    """并发首次赋予冲突时抛出，用于事务内中断并触发清理。"""


# ============================================================
# 第二阶段：签名公共调用能力
# ============================================================

# ---------------- 场景注册 ----------------

# 部门值班日志签署场景（第三阶段首个业务模块接入）
DEPARTMENT_DUTY_LOG_SIGNATURE_SCENE = (
    'department_duty_log',
    'department_duty_log',
    'duty_person',
)

# 生产场景注册表：只包含已批准的业务场景。
# 测试通过 override_settings(SIGNATURE_SCENES_OVERRIDE=frozenset({(m,o,s)})) 注入测试专用场景，
# 测试场景不得写入生产代码默认值。
SIGNATURE_SCENES = frozenset({
    DEPARTMENT_DUTY_LOG_SIGNATURE_SCENE,
})

# 全局共享业务场景：历史签名可按业务权限跨租户读取（不放开通用签名查询）。
# get_signature_image_for_global_business 只允许这些场景。
GLOBAL_SHARED_SIGNATURE_SCENES = frozenset({
    DEPARTMENT_DUTY_LOG_SIGNATURE_SCENE,
})

# 输入长度限制（与模型字段长度对齐，并兼容 EvidenceEvent.object_id 的 50 字符限制）
_MAX_MODULE_LEN = 50
_MAX_OBJECT_TYPE_LEN = 50
_MAX_OBJECT_ID_LEN = 50
_MAX_SCENE_CODE_LEN = 50
_MAX_REQUEST_ID_LEN = 64


def _get_effective_scenes():
    """读取生效的场景注册表。

    生产代码默认返回 SIGNATURE_SCENES（空）。
    测试通过 override_settings(SIGNATURE_SCENES_OVERRIDE=...) 注入测试专用场景。
    """
    override = getattr(settings, 'SIGNATURE_SCENES_OVERRIDE', None)
    if override is not None:
        return frozenset(override)
    return SIGNATURE_SCENES


def _is_scene_registered(module, object_type, scene_code):
    """判断场景是否已注册。"""
    return (module, object_type, scene_code) in _get_effective_scenes()


# ---------------- 业务快照规范化 ----------------

def canonicalize_business_snapshot(snapshot):
    """规范化业务快照为确定性 JSON 字符串。

    规则：
    1. 只接受 dict/list/str/int/float/bool/None 等 JSON 基础类型；
    2. 字典键稳定排序（sort_keys=True）；
    3. 使用 UTF-8 编码；
    4. 使用固定 JSON 分隔符 (',', ':')；
    5. ensure_ascii=False，Unicode 序列化规则固定；
    6. allow_nan=False，拒绝 NaN/Infinity；
    7. 日期、Decimal、Model 等非原生对象必须显式转换或拒绝（json.dumps 默认抛 TypeError）；
    8. 同一逻辑数据必须产生相同字符串；
    9. 字段顺序变化不能改变字符串；
    10. 实际值变化必须改变字符串。

    Args:
        snapshot: dict/list/None 或 JSON 基础类型

    Returns:
        str: 规范化后的 JSON 字符串

    Raises:
        ValueError: 类型不支持或包含 NaN/Infinity
    """
    try:
        return json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(',', ':'),
            allow_nan=False,
        )
    except (TypeError, ValueError) as e:
        raise ValueError('业务快照包含不支持的类型或非法值: %s' % e)


def compute_business_snapshot_hash(snapshot):
    """计算业务快照规范化 SHA256。

    对 canonicalize_business_snapshot 的输出计算 SHA256，保证：
    - 同一逻辑数据产生相同哈希；
    - 字段顺序变化不改变哈希；
    - 实际值变化必须改变哈希。

    Args:
        snapshot: dict/list/None 或 JSON 基础类型

    Returns:
        str: 64 位十六进制 SHA256

    Raises:
        ValueError: 同 canonicalize_business_snapshot
    """
    canonical = canonicalize_business_snapshot(snapshot)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


# ---------------- 内部工具 ----------------

class _SignatureError(Exception):
    """签署流程中可向用户展示的错误，用于事务内中断并触发回滚。"""


class _SignatureEvidenceError(Exception):
    """EvidenceEvent 创建失败时抛出，用于触发整体回滚。"""


def _compute_file_sha256(file_path):
    """流式计算文件 SHA256。"""
    h = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def _get_request_ip(request):
    """从请求中获取真实 IP，无请求时返回空串。"""
    if not request:
        return ''
    headers = getattr(request, 'headers', None)
    if not headers:
        return ''
    try:
        return get_request_real_ip(headers) or ''
    except Exception:
        return ''


def _compute_request_fingerprint(tenant_id, signer_user_id, module, object_type,
                                 object_id, scene_code, business_snapshot_hash):
    """计算请求指纹 SHA256。

    至少覆盖：tenant_id / signer_user_id / module / object_type / object_id /
    scene_code / business_snapshot_hash。
    """
    payload = {
        'tenant_id': '' if tenant_id is None else str(tenant_id),
        'signer_user_id': str(signer_user_id),
        'module': str(module),
        'object_type': str(object_type),
        'object_id': str(object_id),
        'scene_code': str(scene_code),
        'business_snapshot_hash': str(business_snapshot_hash),
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _serialize_usage(usage):
    """把 SignatureUsage 序列化为普通字典，不返回 Django Model。

    不返回 business_snapshot 全文（可能含敏感数据），只返回 hash。
    调用方需要原始快照时自行存储。
    """
    return {
        'usage_id': usage.id,
        'tenant_id': usage.tenant_id,
        'module': usage.module,
        'object_type': usage.object_type,
        'object_id': usage.object_id,
        'scene_code': usage.scene_code,
        'signer_user_id': usage.signer_user_id,
        'signer_username': usage.signer_username,
        'signer_name': usage.signer_name,
        'signature_attachment_id': usage.signature_attachment_id,
        'signature_version': usage.signature_version,
        'signature_sha256': usage.signature_sha256,
        'business_snapshot_hash': usage.business_snapshot_hash,
        'signed_at': usage.signed_at,
        'signer_ip': usage.signer_ip,
        'request_id': usage.request_id,
        'request_fingerprint': usage.request_fingerprint,
        'evidence_event_id': usage.evidence_event_id,
    }


def _validate_actor_for_apply(actor):
    """校验签署人身份有效、启用且未逻辑删除。返回 error_str 或 None。"""
    if actor is None or not getattr(actor, 'is_authenticated', False):
        return '签署人未登录'
    if not getattr(actor, 'is_active', True):
        return '签署人账号已停用'
    if getattr(actor, 'deleted_by_id', None) is not None:
        return '签署人账号已删除'
    if not actor.id:
        return '签署人账号无效'
    return None


def _validate_scene_strings(module, object_type, object_id, scene_code, request_id):
    """校验场景坐标字符串的格式与长度。返回 error_str 或 None。"""
    # 纯字符串字段：非空 + 必须为 str + 长度限制
    str_fields = (
        (module, _MAX_MODULE_LEN, 'module'),
        (object_type, _MAX_OBJECT_TYPE_LEN, 'object_type'),
        (scene_code, _MAX_SCENE_CODE_LEN, 'scene_code'),
        (request_id, _MAX_REQUEST_ID_LEN, 'request_id'),
    )
    for value, max_len, label in str_fields:
        if not value or not isinstance(value, str) or len(value) > max_len:
            return f'{label} 非法或超长'
    # object_id 允许非字符串（int 等），单独校验
    if object_id is None or len(str(object_id)) == 0 or len(str(object_id)) > _MAX_OBJECT_ID_LEN:
        return 'object_id 非法或超长'
    return None


def _validate_business_snapshot_type(business_snapshot):
    """业务快照类型预检（dict/list/None/基础类型）。返回 error_str 或 None。"""
    if business_snapshot is not None and not isinstance(
            business_snapshot, (dict, list, str, int, float, bool)):
        return '业务快照类型不支持'
    return None


def _validate_apply_inputs(actor, module, object_type, object_id, scene_code,
                            business_snapshot, request_id):
    """apply_signature 的输入校验（无 DB 操作）。返回 error_str 或 None。"""
    err = _validate_actor_for_apply(actor)
    if err:
        return err
    err = _validate_scene_strings(module, object_type, object_id, scene_code, request_id)
    if err:
        return err
    # 场景注册校验
    if not _is_scene_registered(module, object_type, scene_code):
        logger.warning(
            '[Signature] apply_signature rejected unregistered scene: '
            'module=%s object_type=%s scene_code=%s',
            module, object_type, scene_code,
        )
        return '签署场景未注册，拒绝签署'
    return _validate_business_snapshot_type(business_snapshot)


# ---------------- apply_signature ----------------

def _lock_and_validate_actor_signature(actor):
    """事务内锁定 actor 当前 active 签名并校验附件归属。

    Returns:
        tuple: (sig, att)
    Raises:
        _SignatureError: 任一校验失败
    """
    sig = (AccountSignature.objects
           .select_for_update()
           .filter(user_id=actor.id)
           .first())
    if not sig or sig.status != STATUS_ACTIVE or not sig.current_attachment_id:
        raise _SignatureError('当前账号未配置有效签名，无法签署')

    att = EvidenceAttachment.objects.filter(pk=sig.current_attachment_id).first()
    if not att:
        logger.warning(
            '[Signature] current attachment missing: user_id=%s att_id=%s',
            actor.id, sig.current_attachment_id)
        raise _SignatureError('签名附件不存在')
    if att.is_deleted:
        logger.warning(
            '[Signature] current attachment soft-deleted: user_id=%s att_id=%s',
            actor.id, att.id)
        raise _SignatureError('签名附件已删除')
    if att.module != SIGNATURE_MODULE or att.object_type != SIGNATURE_OBJECT_TYPE:
        logger.error(
            '[Signature] attachment module/type mismatch: att_id=%s module=%s/%s type=%s/%s',
            att.id, att.module, SIGNATURE_MODULE, att.object_type, SIGNATURE_OBJECT_TYPE)
        raise _SignatureError('签名附件类型不正确')
    if str(att.object_id) != str(actor.id):
        logger.error(
            '[Signature] attachment owner mismatch: att_id=%s att.object_id=%s actor.id=%s',
            att.id, att.object_id, actor.id)
        raise _SignatureError('签名附件归属不正确')
    if str(att.tenant_id or '') != str(actor.tenant_id or ''):
        logger.error(
            '[Signature] attachment tenant mismatch: att_id=%s att.tenant=%s actor.tenant=%s',
            att.id, att.tenant_id, actor.tenant_id)
        raise _SignatureError('签名附件租户不一致')
    return sig, att


def _verify_signature_file(att):
    """校验签名物理文件路径安全、存在且哈希与数据库一致。

    Returns:
        tuple: (db_sha256, file_real)
    Raises:
        _SignatureError: 路径越界、文件丢失或哈希不一致
    """
    full_path = os.path.join(settings.MEDIA_ROOT, att.file_path)
    media_real = os.path.realpath(settings.MEDIA_ROOT)
    file_real = os.path.realpath(full_path)
    if not (file_real == media_real or file_real.startswith(media_real + os.sep)):
        logger.error(
            '[Signature] file path outside MEDIA_ROOT: %s', att.file_path)
        raise _SignatureError('签名文件路径异常')
    if not os.path.exists(file_real):
        logger.warning(
            '[Signature] signature file missing: %s', att.file_path)
        raise _SignatureError('签名文件不存在')

    db_sha256 = att.file_hash_sha256 or ''
    if not db_sha256:
        logger.error(
            '[Signature] attachment has empty sha256 in db: att_id=%s', att.id)
        raise _SignatureError('签名附件缺少哈希记录')
    actual_sha256 = _compute_file_sha256(file_real)
    if actual_sha256 != db_sha256:
        logger.error(
            '[Signature] file hash mismatch: att_id=%s db=%s actual=%s',
            att.id, db_sha256, actual_sha256)
        raise _SignatureError('签名文件哈希不一致，签署已拒绝')
    return db_sha256, file_real


def _build_signature_evidence_snapshot(usage, actor, att, db_version, db_sha256,
                                       module, object_type, object_id_str,
                                       scene_code, snapshot_hash, request_id,
                                       signer_ip, signed_at):
    """构建 EvidenceEvent 的 object_snapshot。"""
    return {
        'signature_usage_id': usage.id,
        'signer_user_id': actor.id,
        'signer_username': actor.username or '',
        'signer_name': actor.nickname or actor.username or '',
        'signature_attachment_id': att.id,
        'signature_version': db_version,
        'signature_sha256': db_sha256,
        'business_snapshot_hash': snapshot_hash,
        'module': module,
        'object_type': object_type,
        'object_id': object_id_str,
        'scene_code': scene_code,
        'request_id': request_id,
        'signer_ip': signer_ip,
        'signed_at': signed_at,
    }


def _create_signed_usage_in_tx(actor, module, object_type, object_id_str, scene_code,
                               snapshot_canonical, snapshot_hash, request_id,
                               fingerprint, request):
    """事务内完成签名锁定、附件校验、文件哈希重算、Usage 与 EvidenceEvent 创建。

    幂等：并发相同 (tenant_id, request_id) 由唯一约束保证只创建一条，
    IntegrityError 后重查并按指纹比对处理。

    Returns:
        tuple: (usage_dict, error_str)  error_str 为空表示成功
    """
    tenant_id = actor.tenant_id or ''
    try:
        with transaction.atomic():
            sig, att = _lock_and_validate_actor_signature(actor)
            db_sha256, _file_real = _verify_signature_file(att)
            db_version = sig.version
            signed_at = timezone.now()
            signer_ip = _get_request_ip(request)

            # 创建不可变 SignatureUsage
            try:
                usage = SignatureUsage.objects.create(
                    tenant_id=tenant_id,
                    module=module,
                    object_type=object_type,
                    object_id=object_id_str,
                    scene_code=scene_code,
                    signer_user_id=actor.id,
                    signer_username=actor.username or '',
                    signer_name=actor.nickname or actor.username or '',
                    signature_attachment_id=att.id,
                    signature_version=db_version,
                    signature_sha256=db_sha256,
                    business_snapshot=snapshot_canonical,
                    business_snapshot_hash=snapshot_hash,
                    signed_at=signed_at,
                    signer_ip=signer_ip,
                    request_id=request_id,
                    request_fingerprint=fingerprint,
                    evidence_event_id=None,
                )
            except IntegrityError:
                # 并发：对方先创建成功，重新查询并按幂等逻辑处理
                existing = SignatureUsage.objects.filter(
                    tenant_id=tenant_id, request_id=request_id).first()
                if existing is not None and existing.request_fingerprint == fingerprint:
                    return _serialize_usage(existing), None
                logger.warning(
                    '[Signature] concurrent idempotent conflict: tenant=%s request_id=%s',
                    tenant_id, request_id)
                raise _SignatureError('签署请求幂等冲突：相同 request_id 已用于不同签署上下文')

            # 创建 EvidenceEvent（复用项目现有证据事件服务，不自行实现哈希链）
            evidence_snapshot = _build_signature_evidence_snapshot(
                usage, actor, att, db_version, db_sha256, module, object_type,
                object_id_str, scene_code, snapshot_hash, request_id,
                signer_ip, signed_at)
            event = record_evidence_event(
                tenant_id=tenant_id,
                module=module,
                object_type=object_type,
                object_id=object_id_str,
                event_type='other',
                actor_user_id=actor.id,
                actor_username=actor.username or '',
                actor_name=actor.nickname or actor.username or '',
                actor_department='',
                actor_ip=signer_ip,
                object_snapshot=evidence_snapshot,
                event_title='账号签名使用',
                remark='apply_signature',
            )
            if event is None:
                # EvidenceEvent 失败时本次签署整体失败（事务回滚 Usage）
                logger.error(
                    '[Signature] record_evidence_event returned None, rolling back usage=%s',
                    usage.id)
                raise _SignatureEvidenceError('证据事件记录失败，签署已回滚')

            # 回填 evidence_event_id（创建流程的最终步骤）
            usage.evidence_event_id = event.id
            usage.save(update_fields=['evidence_event_id'])

            return _serialize_usage(usage), None
    except _SignatureError as e:
        return None, str(e)
    except _SignatureEvidenceError as e:
        return None, str(e)


def apply_signature(actor, module, object_type, object_id, scene_code,
                    business_snapshot, request_id, request=None):
    """正式签署入口：创建不可变 SignatureUsage 并写入 EvidenceEvent。

    actor 是唯一签署人来源，不接受 signer_user_id 参数。
    客户端或调用方不得决定签署人 ID、签名附件 ID、签名版本、图片 SHA256、
    tenant_id、签署时间或 IP 地址，全部由服务端从 actor 和数据库读取。

    流程：
    1. 校验 actor 有效、启用且未逻辑删除；
    2. 校验 module/object_type/scene_code 已注册；
    3. 校验 object_id 和 request_id 格式、长度；
    4. 规范化 business_snapshot 并计算业务哈希；
    5. 计算 request_fingerprint；
    6. 幂等预检查 (tenant_id, request_id)；
    7. 事务内：锁定 actor 当前 active 签名 → 读取附件 → 校验归属 →
       校验物理文件 → 重新计算文件 SHA256 → 创建 SignatureUsage →
       创建 EvidenceEvent → 回填 evidence_event_id；
    8. 返回普通字典，不返回 Django Model。

    支持由未来业务模块包裹在 transaction.atomic() 中调用：本函数内部使用
    transaction.atomic() 作为 savepoint，外层事务回滚时 Usage 和 Event 一并回滚。

    幂等：
    - 相同 (tenant_id, request_id) 重试且关键字段一致 → 返回已有 Usage；
    - 任一关键字段不同 → 返回冲突；
    - 并发相同请求由 (tenant_id, request_id) 唯一约束保证只创建一条。

    Args:
        actor: 当前请求用户（签署人），User 实例
        module: 已注册的业务模块标识
        object_type: 已注册的业务对象类型
        object_id: 业务对象 ID（≤50 字符，兼容 EvidenceEvent）
        scene_code: 签署场景码
        business_snapshot: 业务快照（dict/list/JSON 基础类型）
        request_id: 请求幂等键（≤64 字符）
        request: HTTP 请求对象，用于提取 IP；可为 None

    Returns:
        tuple: (usage_dict, error_str)  error_str 为空表示成功
    """
    err = _validate_apply_inputs(
        actor, module, object_type, object_id, scene_code,
        business_snapshot, request_id)
    if err:
        return None, err

    # 规范化业务快照 + 计算哈希
    try:
        snapshot_canonical = canonicalize_business_snapshot(business_snapshot)
        snapshot_hash = compute_business_snapshot_hash(business_snapshot)
    except ValueError as e:
        return None, str(e)

    tenant_id = actor.tenant_id or ''
    object_id_str = str(object_id)

    # 计算请求指纹
    fingerprint = _compute_request_fingerprint(
        tenant_id, actor.id, module, object_type, object_id_str,
        scene_code, snapshot_hash)

    # 幂等预检查（快速路径，无锁）
    existing = SignatureUsage.objects.filter(
        tenant_id=tenant_id, request_id=request_id).first()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return _serialize_usage(existing), None
        logger.warning(
            '[Signature] idempotent conflict: tenant=%s request_id=%s '
            'existing_fp=%s incoming_fp=%s',
            tenant_id, request_id, existing.request_fingerprint, fingerprint,
        )
        return None, '签署请求幂等冲突：相同 request_id 已用于不同签署上下文'

    # 事务内完成锁定、校验、创建
    return _create_signed_usage_in_tx(
        actor, module, object_type, object_id_str, scene_code,
        snapshot_canonical, snapshot_hash, request_id, fingerprint, request)


# ---------------- 历史读取和渲染服务 ----------------

def _check_usage_tenant(usage, requester):
    """校验请求者与 Usage 的租户一致性。超管放行。"""
    if getattr(requester, 'is_supper', False):
        return None
    if str(getattr(requester, 'tenant_id', '') or '') != str(usage.tenant_id or ''):
        logger.warning(
            '[Signature] cross-tenant usage access: requester=%s tenant=%s usage_tenant=%s usage_id=%s',
            getattr(requester, 'id', None), getattr(requester, 'tenant_id', ''),
            usage.tenant_id, usage.id)
        return '无权限访问该签名使用记录'
    return None


def get_usage(usage_id, requester):
    """按 ID 读取单条签名使用记录。

    边界：
    - 本阶段不开放通用历史签名 HTTP 查询接口，仅供内部服务调用；
    - 公共服务无法代替业务模块判断对象查看权限，调用方应先完成业务权限校验；
    - 服务内部仍校验 tenant_id；
    - 返回普通字典，不返回 Django Model，不返回 business_snapshot 全文。

    Args:
        usage_id: SignatureUsage.id
        requester: 请求者 User 实例

    Returns:
        tuple: (usage_dict, error_str)
    """
    if requester is None or not getattr(requester, 'is_authenticated', False):
        return None, '请求者未登录'
    try:
        usage_id_int = int(usage_id)
    except (TypeError, ValueError):
        return None, 'usage_id 非法'
    usage = SignatureUsage.objects.filter(pk=usage_id_int).first()
    if not usage:
        return None, '签名使用记录不存在'
    err = _check_usage_tenant(usage, requester)
    if err:
        return None, err
    return _serialize_usage(usage), None


def get_usages_for_object(requester, module, object_type, object_id):
    """按业务对象读取签名使用记录列表。

    边界：
    - 本阶段不开放通用 HTTP 查询接口；
    - 调用方应先完成业务对象查看权限校验；
    - 服务内部按 requester 租户过滤（超管放行）；
    - 返回普通字典列表，不返回 business_snapshot 全文。

    Args:
        requester: 请求者 User 实例
        module: 业务模块标识
        object_type: 业务对象类型
        object_id: 业务对象 ID

    Returns:
        tuple: (list[dict], error_str)
    """
    if requester is None or not getattr(requester, 'is_authenticated', False):
        return None, '请求者未登录'
    qs = SignatureUsage.objects.filter(
        module=module, object_type=object_type, object_id=str(object_id))
    if not getattr(requester, 'is_supper', False):
        qs = qs.filter(tenant_id=getattr(requester, 'tenant_id', '') or '')
    qs = qs.order_by('-id')
    return [_serialize_usage(u) for u in qs], None


def get_signature_image_for_render(usage_id, requester):
    """按使用记录读取固定版本的签名图片，供服务端渲染（PDF/Word 导出等）。

    边界：
    - 本服务仅供服务端渲染调用，不把绝对路径返回给前端；
    - 调用方必须先完成业务对象查看权限校验，本服务只校验 tenant_id；
    - 历史图片必须按 Usage 中固定的 signature_attachment_id 读取，
      禁止按 signer_user_id 查询当前签名代替历史版本；
    - 文件丢失或哈希异常时明确报错，不能回退到当前签名。

    Args:
        usage_id: SignatureUsage.id
        requester: 请求者 User 实例

    Returns:
        tuple: (render_info_dict, error_str)
        render_info_dict 包含：
            - file_path: 物理绝对路径（仅供服务端渲染，不得返回前端）
            - file_size: 文件大小
            - sha256: 实际文件 SHA256（已与 Usage 固化值比对）
            - attachment_id: 固定的附件 ID
            - content_type: 固定为 image/png
            - signature_version: 签署时版本
    """
    if requester is None or not getattr(requester, 'is_authenticated', False):
        return None, '请求者未登录'
    try:
        usage_id_int = int(usage_id)
    except (TypeError, ValueError):
        return None, 'usage_id 非法'
    usage = SignatureUsage.objects.filter(pk=usage_id_int).first()
    if not usage:
        return None, '签名使用记录不存在'
    err = _check_usage_tenant(usage, requester)
    if err:
        return None, err

    # 按使用记录中固定的 attachment_id 读取，不查当前签名
    att = EvidenceAttachment.objects.filter(pk=usage.signature_attachment_id).first()
    if not att:
        logger.warning(
            '[Signature] render: fixed attachment missing: usage_id=%s att_id=%s',
            usage.id, usage.signature_attachment_id)
        return None, '签名附件不存在'
    if att.module != SIGNATURE_MODULE or att.object_type != SIGNATURE_OBJECT_TYPE:
        logger.error(
            '[Signature] render: attachment module/type mismatch: att_id=%s', att.id)
        return None, '签名附件类型不正确'

    # 路径安全 + 物理文件存在
    full_path = os.path.join(settings.MEDIA_ROOT, att.file_path)
    media_real = os.path.realpath(settings.MEDIA_ROOT)
    file_real = os.path.realpath(full_path)
    if not (file_real == media_real or file_real.startswith(media_real + os.sep)):
        logger.error(
            '[Signature] render: path outside MEDIA_ROOT: %s', att.file_path)
        return None, '签名文件路径异常'
    if not os.path.exists(file_real):
        logger.warning(
            '[Signature] render: file missing: usage_id=%s path=%s', usage.id, att.file_path)
        return None, '签名文件不存在'

    # 重新计算实际文件 SHA256，与 Usage 固化值比对
    actual_sha256 = _compute_file_sha256(file_real)
    if actual_sha256 != usage.signature_sha256:
        logger.error(
            '[Signature] render: hash mismatch: usage_id=%s usage_sha=%s actual=%s',
            usage.id, usage.signature_sha256, actual_sha256)
        return None, '签名文件哈希异常，禁止渲染'

    return {
        'file_path': file_real,
        'file_size': os.path.getsize(file_real),
        'sha256': actual_sha256,
        'attachment_id': att.id,
        'content_type': 'image/png',
        'signature_version': usage.signature_version,
    }, None


# ============================================================
# 第三阶段扩展：全局共享业务的固定历史签名读取与作废证据事件
# ============================================================

def get_signature_image_for_global_business(
    usage_id, module, object_type, object_id, scene_code,
):
    """全局共享业务按固定版本读取签名图片。

    专为部门值班日志等全局共享业务设计，不校验请求者与 Usage 的租户一致性
    （因为业务表本身无 tenant_id，跨租户用户均可按业务权限查看）。

    边界：
    - 只允许 GLOBAL_SHARED_SIGNATURE_SCENES 中的场景；
    - 精确校验 Usage 的 module/object_type/object_id/scene_code 与调用参数一致；
    - 始终读取 Usage.signature_attachment_id 指向的历史版本，不查当前签名；
    - 重新计算物理文件 SHA256 并与 Usage 固化值比对；
    - 只返回服务端渲染所需信息，不新增通用 HTTP 入口。

    Args:
        usage_id: SignatureUsage.id
        module: 业务模块标识
        object_type: 业务对象类型
        object_id: 业务对象 ID
        scene_code: 签署场景码

    Returns:
        tuple: (render_info_dict, error_str)
        render_info_dict 包含 file_path/file_size/sha256/attachment_id/
                          content_type/signature_version
    """
    # 场景白名单校验
    if (module, object_type, scene_code) not in GLOBAL_SHARED_SIGNATURE_SCENES:
        logger.warning(
            '[Signature] global_business: scene not in whitelist: module=%s type=%s scene=%s',
            module, object_type, scene_code)
        return None, '签署场景不支持全局共享读取'

    try:
        usage_id_int = int(usage_id)
    except (TypeError, ValueError):
        return None, 'usage_id 非法'

    usage = SignatureUsage.objects.filter(pk=usage_id_int).first()
    if not usage:
        return None, '签名使用记录不存在'

    # 精确匹配业务坐标
    if (usage.module != module or usage.object_type != object_type
            or str(usage.object_id) != str(object_id)
            or usage.scene_code != scene_code):
        logger.warning(
            '[Signature] global_business: usage coordinate mismatch: '
            'usage_id=%s expected=(%s,%s,%s,%s) actual=(%s,%s,%s,%s)',
            usage.id, module, object_type, object_id, scene_code,
            usage.module, usage.object_type, usage.object_id, usage.scene_code)
        return None, '签名使用记录与业务对象不匹配'

    # 按使用记录中固定的 attachment_id 读取
    att = EvidenceAttachment.objects.filter(pk=usage.signature_attachment_id).first()
    if not att:
        logger.warning(
            '[Signature] global_business: fixed attachment missing: usage_id=%s att_id=%s',
            usage.id, usage.signature_attachment_id)
        return None, '签名附件不存在'
    if att.module != SIGNATURE_MODULE or att.object_type != SIGNATURE_OBJECT_TYPE:
        logger.error(
            '[Signature] global_business: attachment module/type mismatch: att_id=%s', att.id)
        return None, '签名附件类型不正确'

    # 路径安全 + 物理文件存在
    full_path = os.path.join(settings.MEDIA_ROOT, att.file_path)
    media_real = os.path.realpath(settings.MEDIA_ROOT)
    file_real = os.path.realpath(full_path)
    if not (file_real == media_real or file_real.startswith(media_real + os.sep)):
        logger.error(
            '[Signature] global_business: path outside MEDIA_ROOT: %s', att.file_path)
        return None, '签名文件路径异常'
    if not os.path.exists(file_real):
        logger.warning(
            '[Signature] global_business: file missing: usage_id=%s path=%s',
            usage.id, att.file_path)
        return None, '签名文件不存在'

    # 重新计算实际文件 SHA256
    actual_sha256 = _compute_file_sha256(file_real)
    if actual_sha256 != usage.signature_sha256:
        logger.error(
            '[Signature] global_business: hash mismatch: usage_id=%s usage_sha=%s actual=%s',
            usage.id, usage.signature_sha256, actual_sha256)
        return None, '签名文件哈希异常，禁止渲染'

    return {
        'file_path': file_real,
        'file_size': os.path.getsize(file_real),
        'sha256': actual_sha256,
        'attachment_id': att.id,
        'content_type': 'image/png',
        'signature_version': usage.signature_version,
    }, None


def record_signature_void_event(
    usage_id, actor, module, object_type, object_id, scene_code,
    reason, request=None,
):
    """为全局共享业务作废写入 void 证据事件。

    要求：
    - 校验 Usage 业务坐标完全一致；
    - 使用原 SignatureUsage.tenant_id 写 void EvidenceEvent，使事件进入原业务对象证据链；
    - actor 仍记录真实作废人；
    - 不修改 SignatureUsage；
    - EvidenceEvent 创建失败时返回错误，由外层作废事务回滚业务状态。

    Args:
        usage_id: SignatureUsage.id
        actor: 作废操作人 User 实例
        module/object_type/object_id/scene_code: 业务坐标
        reason: 作废原因
        request: HTTP 请求对象

    Returns:
        error_str: 空表示成功，非空表示失败
    """
    from apps.evidence.services import record_evidence_event
    from libs.utils import get_request_real_ip

    try:
        usage_id_int = int(usage_id)
    except (TypeError, ValueError):
        return 'usage_id 非法'

    usage = SignatureUsage.objects.filter(pk=usage_id_int).first()
    if not usage:
        return '签名使用记录不存在'

    # 精确校验业务坐标
    if (usage.module != module or usage.object_type != object_type
            or str(usage.object_id) != str(object_id)
            or usage.scene_code != scene_code):
        logger.warning(
            '[Signature] void_event: usage coordinate mismatch: usage_id=%s', usage.id)
        return '签名使用记录与业务对象不匹配'

    # 使用原 Usage tenant_id，使事件进入原业务对象证据链
    tenant_id = usage.tenant_id or ''
    signer_ip = ''
    if request:
        try:
            signer_ip = get_request_real_ip(getattr(request, 'headers', None)) or ''
        except Exception:
            signer_ip = ''

    actor_name = getattr(actor, 'nickname', '') or getattr(actor, 'username', '') or ''
    actor_username = getattr(actor, 'username', '') or ''

    event_snapshot = {
        'signature_usage_id': usage.id,
        'void_actor_user_id': getattr(actor, 'id', None),
        'void_actor_username': actor_username,
        'void_actor_name': actor_name,
        'void_reason': reason,
        'module': module,
        'object_type': object_type,
        'object_id': str(object_id),
        'scene_code': scene_code,
        'original_signer_user_id': usage.signer_user_id,
        'original_signed_at': usage.signed_at,
        'signature_attachment_id': usage.signature_attachment_id,
        'signature_version': usage.signature_version,
        'signature_sha256': usage.signature_sha256,
    }

    event = record_evidence_event(
        tenant_id=tenant_id,
        module=module,
        object_type=object_type,
        object_id=str(object_id),
        event_type='void',
        actor_user_id=getattr(actor, 'id', None),
        actor_username=actor_username,
        actor_name=actor_name,
        actor_department='',
        actor_ip=signer_ip,
        object_snapshot=event_snapshot,
        event_title='部门值班日志作废',
        remark='record_signature_void_event',
    )
    if event is None:
        logger.error(
            '[Signature] void_event: record_evidence_event returned None, usage_id=%s', usage.id)
        return '作废证据事件记录失败，已回滚'

    return ''
