# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""台站频率批复相关视图。

从 radio_license/views.py 拆分而来，用于控制单文件代码行数。
执照相关视图仍保留在 views.py。
"""
import logging
from datetime import timedelta

from django.db.models import Count
from django.views.generic import View
from django.utils import timezone
from django.utils import timezone
from libs import json_response, JsonParser, Argument, auth
from libs.tenant_utils import apply_tenant_filter, assign_tenant_id
from apps.radio_license.models import (
    StationFrequencyApproval,
    StationFrequencyApprovalReminderAck,
    EXPIRING_DAYS_THRESHOLD,
)
from apps.radio_license.tasks import scan_single_approval
from apps.evidence.attachment_service import AttachmentService, AttachmentConfig, PREVIEWABLE_EXTENSIONS
from apps.evidence.models import EvidenceAttachment

logger = logging.getLogger(__name__)


# ==================== 台站频率批复 ====================

# 批复业务对象标识（独立常量，避免与执照附件串用）
APPROVAL_ATTACHMENT_MODULE = 'radio_license'
APPROVAL_ATTACHMENT_OBJECT_TYPE = 'approval'

# 批复附件配置：与执照附件保持同值，但使用独立常量
ApprovalAttachmentConfig = AttachmentConfig(
    allowed_extensions=('.pdf', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp',
                        '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
                        '.zip', '.rar', '.7z'),
    max_size_mb=50,
)

# 批复审计事件 target_type
APPROVAL_AUDIT_TARGET_TYPE = 'radio_license_approval'


def _validate_and_fill_approval_responsible_user(form, request_user):
    """校验批复责任人账号并回填真实姓名。

    规则（设计方案 3.1）：
    1. 必须存在且 is_active=True；
    2. deleted_by_id IS NULL（未软删）；
    3. tenant_id 必须等于当前请求用户 tenant_id（超管除外，但仍要求账号未删除且启用）；
    4. 服务端用 nickname or username 回填 responsible_user_name；
    5. 不信任客户端传入的 responsible_user_name。

    Returns: 错误消息字符串；None 表示通过。
    """
    from apps.account.models import User as UserModel
    user = UserModel.objects.filter(
        pk=form.responsible_user_id,
        is_active=True,
        deleted_by_id__isnull=True,
    ).first()
    if user is None:
        return '责任人不存在或已禁用，请重新选择'

    # 超管可跨租户配置；普通用户必须与本租户一致
    if not getattr(request_user, 'is_supper', False):
        if getattr(user, 'tenant_id', None) != getattr(request_user, 'tenant_id', None):
            return '责任人不存在或已禁用，请重新选择'

    form.responsible_user_name = user.nickname or user.username
    return None


def _compute_approval_status_fields(record):
    """根据 valid_to 实时计算 status/days_left。

    所有列表、详情、popup、badge 统一调用本函数，避免逻辑分散。
    """
    today = timezone.now().date()
    days_left = (record.valid_to - today).days
    if days_left < 0:
        computed_status = StationFrequencyApproval.STATUS_EXPIRED
    elif days_left <= EXPIRING_DAYS_THRESHOLD:
        computed_status = StationFrequencyApproval.STATUS_EXPIRING
    else:
        computed_status = StationFrequencyApproval.STATUS_NORMAL
    return computed_status, days_left


def _apply_approval_status_filter(qs, status, today):
    """列表 status 筛选转换为实时 valid_to 范围，不依赖缓存字段。"""
    if status == StationFrequencyApproval.STATUS_NORMAL:
        return qs.filter(valid_to__gt=today + timedelta(days=EXPIRING_DAYS_THRESHOLD))
    if status == StationFrequencyApproval.STATUS_EXPIRING:
        return qs.filter(valid_to__gte=today, valid_to__lte=today + timedelta(days=EXPIRING_DAYS_THRESHOLD))
    if status == StationFrequencyApproval.STATUS_EXPIRED:
        return qs.filter(valid_to__lt=today)
    return qs


def _bulk_attachment_counts(user, approval_ids):
    """批量聚合指定批复 ID 列表的未删除附件数量，避免列表 N+1 查询。"""
    if not approval_ids:
        return {}
    qs = apply_tenant_filter(EvidenceAttachment.objects.all(), user).filter(
        module=APPROVAL_ATTACHMENT_MODULE,
        object_type=APPROVAL_ATTACHMENT_OBJECT_TYPE,
        object_id__in=[str(i) for i in approval_ids],
        is_deleted=False,
    ).values('object_id').annotate(count=Count('object_id'))
    return {int(item['object_id']): item['count'] for item in qs}


def _record_approval_audit(user, action, approval, detail=None, target_id=None):
    """统一写入批复审计日志。失败仅记日志，不阻断主流程。"""
    try:
        from apps.logs.audit import save_audit_log
        save_audit_log(
            user_id=getattr(user, 'id', 0) or 0,
            username=getattr(user, 'username', '') or '',
            action=action,
            target_type=APPROVAL_AUDIT_TARGET_TYPE,
            target_id=str(target_id if target_id is not None else approval.id),
            target_name=approval.name if approval else None,
            detail=detail,
            tenant_id=getattr(user, 'tenant_id', 'default'),
        )
    except Exception as e:
        logger.error(f'[StationFrequencyApproval] 审计日志写入失败: {e}')


class StationFrequencyApprovalView(View):
    """台站频率批复列表 / 新增编辑 / 删除入口"""

    @auth('radio_license.approval.view')
    def get(self, request):
        from datetime import timedelta
        records = apply_tenant_filter(StationFrequencyApproval.objects.all(), request.user)

        name = request.GET.get('name', '').strip()
        doc_no = request.GET.get('doc_no', '').strip()
        status = request.GET.get('status', '').strip()
        valid_to_start = request.GET.get('valid_to_start', '').strip()
        valid_to_end = request.GET.get('valid_to_end', '').strip()

        if name:
            records = records.filter(name__icontains=name)
        if doc_no:
            records = records.filter(doc_no__icontains=doc_no)
        today = timezone.now().date()
        if status:
            records = _apply_approval_status_filter(records, status, today)
        if valid_to_start:
            records = records.filter(valid_to__gte=valid_to_start)
        if valid_to_end:
            records = records.filter(valid_to__lte=valid_to_end)

        try:
            page = max(int(request.GET.get('page', 1)), 1)
        except (TypeError, ValueError):
            page = 1
        try:
            page_size = int(request.GET.get('page_size', 20))
        except (TypeError, ValueError):
            page_size = 20
        page_size = max(1, min(page_size, 100))

        records = records.select_related('created_by', 'updated_by')
        total_count = records.count()
        offset = (page - 1) * page_size
        page_records = list(records[offset:offset + page_size])

        # 批量聚合附件数（避免 N+1）
        approval_ids = [r.id for r in page_records]
        att_counts = _bulk_attachment_counts(request.user, approval_ids)

        data = []
        for record in page_records:
            item = record.to_view()
            computed_status, days_left = _compute_approval_status_fields(record)
            item['days_left'] = days_left
            item['computed_status'] = computed_status
            item['attachment_count'] = att_counts.get(record.id, 0)
            item['created_by_name'] = (
                record.created_by.nickname or record.created_by.username
                if record.created_by else ''
            )
            item['updated_by_name'] = (
                record.updated_by.nickname or record.updated_by.username
                if record.updated_by else ''
            )
            data.append(item)

        return json_response({
            'records': data,
            'total': total_count,
            'page': page,
            'page_size': page_size,
        })

    @auth('radio_license.approval.add|radio_license.approval.edit')
    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('name', required=False),
            Argument('doc_no', required=False),
            Argument('frequency_text', required=False),
            Argument('valid_from', required=False),
            Argument('valid_to', required=False),
            Argument('responsible_user_id', type=int, required=False),
            Argument('remark', required=False),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        if form.id:
            return self._post_edit(request, form)
        return self._post_create(request, form)

    def _post_edit(self, request, form):
        """编辑入口：日期校验 → 责任人校验 → 权限 → 落库"""
        if form.valid_from and form.valid_to and form.valid_from > form.valid_to:
            return json_response(error='起始日期不能晚于截止日期')
        user_err = _validate_and_fill_approval_responsible_user(form, request.user)
        if user_err:
            return json_response(error=user_err)
        if not request.user.has_perms({'radio_license.approval.edit'}):
            return json_response(error='权限拒绝：缺少编辑批复权限')
        return json_response(error=self._handle_edit(form, request.user))

    def _post_create(self, request, form):
        """创建入口：标准化 → 必填校验 → 日期校验 → 责任人校验 → 权限 → 落库"""
        form.name = (form.name or '').strip()
        form.doc_no = (form.doc_no or '').strip()
        form.frequency_text = (form.frequency_text or '').strip()
        if not form.name or not form.doc_no or not form.frequency_text:
            return json_response(error='文件名称、文件编号、批复频率不能为空')
        if form.valid_from and form.valid_to and form.valid_from > form.valid_to:
            return json_response(error='起始日期不能晚于截止日期')
        user_err = _validate_and_fill_approval_responsible_user(form, request.user)
        if user_err:
            return json_response(error=user_err)
        if not request.user.has_perms({'radio_license.approval.add'}):
            return json_response(error='权限拒绝：缺少新增批复权限')
        return json_response(error=self._handle_create(form, request.user))

    def _handle_create(self, form, user):
        """新增批复：租户内 doc_no 重复校验 + 落库 + 即时扫描 + 审计"""
        from django.db import transaction, IntegrityError

        # 租户内 doc_no 重复检查（数据库唯一约束为并发兜底）
        exists = apply_tenant_filter(
            StationFrequencyApproval.objects.all(), user
        ).filter(doc_no=form.doc_no).exists()
        if exists:
            return '文件编号已存在，请更换'

        form.pop('remark', None)
        assign_tenant_id(form, user)
        form.created_by = user

        try:
            with transaction.atomic():
                create_data = {k: v for k, v in form.items() if v is not None}
                approval = StationFrequencyApproval.objects.create(**create_data)
        except IntegrityError:
            return '文件编号已存在，请更换'

        # 即时扫描更新缓存状态（不等待每日 Celery）
        scan_single_approval(approval)

        _record_approval_audit(
            user, 'create', approval,
            detail={
                'name': approval.name, 'doc_no': approval.doc_no,
                'frequency_text': approval.frequency_text,
                'valid_from': str(approval.valid_from),
                'valid_to': str(approval.valid_to),
                'responsible_user_id': approval.responsible_user_id,
                'responsible_user_name': approval.responsible_user_name,
            },
        )
        return None

    def _handle_edit(self, form, user):
        """编辑批复：租户内 doc_no 重复校验（排除自身）+ 更新 + 即时扫描 + 审计"""
        from django.db import transaction, IntegrityError

        qs = apply_tenant_filter(StationFrequencyApproval.objects.all(), user)
        old_approval = qs.filter(pk=form.id).first()
        if not old_approval:
            return '编辑失败：记录不存在或无权限编辑'

        # 租户内 doc_no 重复检查（排除自身，仅当传了 doc_no 时）
        if form.doc_no is not None:
            dup_exists = qs.filter(doc_no=form.doc_no).exclude(pk=form.id).exists()
            if dup_exists:
                return '文件编号已存在，请更换'

        form.updated_at = timezone.now()
        form.updated_by = user
        record_id = form.pop('id')
        form.pop('remark', None)

        try:
            with transaction.atomic():
                update_data = {k: v for k, v in form.items() if v is not None}
                updated_count = qs.filter(pk=record_id).update(**update_data)
        except IntegrityError:
            return '文件编号已存在，请更换'

        if updated_count == 0:
            return '编辑失败：记录不存在或无权限编辑'

        approval = StationFrequencyApproval.objects.get(pk=record_id)
        # 即时扫描更新缓存状态
        scan_single_approval(approval)

        _record_approval_audit(
            user, 'update', approval,
            detail={
                'name': approval.name, 'doc_no': approval.doc_no,
                'valid_from': str(approval.valid_from),
                'valid_to': str(approval.valid_to),
                'responsible_user_id': approval.responsible_user_id,
                'responsible_user_name': approval.responsible_user_name,
            },
        )
        return None

    @auth('radio_license.approval.del')
    def delete(self, request):
        from django.db import transaction
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)
        if error is None:
            qs = apply_tenant_filter(StationFrequencyApproval.objects.all(), request.user)
            approval = qs.filter(pk=form.id).first()
            if not approval:
                error = '删除失败：记录不存在或无权限删除'
            else:
                snapshot = {
                    'name': approval.name,
                    'doc_no': approval.doc_no,
                    'valid_to': str(approval.valid_to),
                    'responsible_user_id': approval.responsible_user_id,
                    'responsible_user_name': approval.responsible_user_name,
                }
                with transaction.atomic():
                    # 软删附件（delete_file=False，物理文件由公共策略处理）
                    AttachmentService.soft_delete_by_object(
                        request.user, APPROVAL_ATTACHMENT_MODULE,
                        APPROVAL_ATTACHMENT_OBJECT_TYPE, form.id,
                        reason=f'批复删除 ID={form.id}', delete_file=False,
                    )
                    # 物理删除批复（CASCADE 自动级联删除 ack）
                    approval.delete()
                _record_approval_audit(
                    request.user, 'delete', None,
                    detail=snapshot, target_id=form.id,
                )
        return json_response(error=error)


class StationFrequencyApprovalDetailView(View):
    """批复详情"""

    @auth('radio_license.approval.view')
    def get(self, request, pk):
        qs = apply_tenant_filter(StationFrequencyApproval.objects.all(), request.user)
        try:
            record = qs.get(pk=pk)
        except StationFrequencyApproval.DoesNotExist:
            return json_response(error='记录不存在或无权限访问')

        item = record.to_view()
        computed_status, days_left = _compute_approval_status_fields(record)
        item['days_left'] = days_left
        item['computed_status'] = computed_status
        item['attachment_count'] = _bulk_attachment_counts(
            request.user, [record.id]
        ).get(record.id, 0)
        item['created_by_name'] = (
            record.created_by.nickname or record.created_by.username
            if record.created_by else ''
        )
        item['updated_by_name'] = (
            record.updated_by.nickname or record.updated_by.username
            if record.updated_by else ''
        )
        return json_response(item)


class ApprovalResponsibleUserListView(View):
    """批复可选责任人列表。

    仅返回当前租户内启用且未删除的用户；超管返回全量启用且未删除用户。
    复用 radio_license.approval.view 权限，避免给非管理员开账户管理权限。
    """

    @auth('radio_license.approval.view')
    def get(self, request):
        from apps.account.models import User as UserModel
        qs = UserModel.objects.filter(is_active=True, deleted_by_id__isnull=True)
        if not getattr(request.user, 'is_supper', False):
            qs = qs.filter(tenant_id=request.user.tenant_id)
        data = [
            {'id': u.id, 'nickname': u.nickname or u.username, 'username': u.username}
            for u in qs.order_by('nickname', 'username')
        ]
        return json_response(data)


# ==================== 批复附件桥接视图 ====================


def _get_approval_for_user(user, approval_id):
    """获取当前用户可访问的批复，不存在返回 None。"""
    qs = apply_tenant_filter(StationFrequencyApproval.objects.all(), user)
    return qs.filter(pk=approval_id).first()


def _get_approval_attachment_for_user(user, attachment_id):
    """获取附件并校验归属：必须是批复附件且父批复属于当前用户可访问租户。

    返回 (attachment, error)。
    """
    att = EvidenceAttachment.objects.filter(pk=attachment_id).first()
    if not att:
        return None, '附件不存在或无权限访问'
    if att.module != APPROVAL_ATTACHMENT_MODULE or att.object_type != APPROVAL_ATTACHMENT_OBJECT_TYPE:
        return None, '附件不存在或无权限访问'
    # 校验父批复租户可见性
    if not _get_approval_for_user(user, att.object_id):
        return None, '附件不存在或无权限访问'
    return att, None


class ApprovalAttachmentListView(View):
    """批复附件列表 / 上传"""

    @auth('radio_license.approval.view')
    def get(self, request, pk):
        if not _get_approval_for_user(request.user, pk):
            return json_response(error='批复不存在或无权限访问')
        data = AttachmentService.list(
            request.user, APPROVAL_ATTACHMENT_MODULE,
            APPROVAL_ATTACHMENT_OBJECT_TYPE, pk,
        )
        return json_response(data)

    @auth('radio_license.attachment.upload')
    def post(self, request, pk):
        # 装饰器只校验附件上传权限，需在方法内显式校验 approval.view
        if not request.user.has_perms({'radio_license.approval.view'}):
            return json_response(error='权限拒绝')
        if not _get_approval_for_user(request.user, pk):
            return json_response(error='批复不存在或无权限访问')

        file = request.FILES.get('file')
        if not file:
            return json_response(error='请选择要上传的文件')

        att, error = AttachmentService.upload(
            file=file,
            user=request.user,
            module=APPROVAL_ATTACHMENT_MODULE,
            object_type=APPROVAL_ATTACHMENT_OBJECT_TYPE,
            object_id=pk,
            config=ApprovalAttachmentConfig,
        )
        if error:
            return json_response(error=error)

        result = att.to_view()
        result['uploaded_by_name'] = request.user.nickname
        result['created_at'] = att.uploaded_at
        result['previewable'] = att.file_ext in PREVIEWABLE_EXTENSIONS
        return json_response(result)


class ApprovalAttachmentDownloadView(View):
    """批复附件下载"""

    @auth('radio_license.attachment.download')
    def get(self, request, pk):
        if not request.user.has_perms({'radio_license.approval.view'}):
            return json_response(error='权限拒绝')
        att, err = _get_approval_attachment_for_user(request.user, pk)
        if err:
            return json_response(error=err)
        inline = request.GET.get('inline') in ('1', 'true', 'True')
        # 已通过桥接校验，直接读取文件流
        response, error = AttachmentService.download_response(request.user, pk, inline=inline)
        if error:
            return json_response(error=error)
        return response


class ApprovalAttachmentPreviewUrlView(View):
    """批复附件 kkFileView 预览地址"""

    @auth('radio_license.approval.view')
    def get(self, request, pk):
        att, err = _get_approval_attachment_for_user(request.user, pk)
        if err:
            return json_response(error=err)
        preview_file_api_path = f'/api/radio-license/approvals/attachments/{pk}/preview-file/'
        data, error = AttachmentService.get_preview_url(
            request.user, pk, preview_file_api_path,
        )
        if error:
            return json_response(error=error)
        return json_response(data)


class ApprovalAttachmentPreviewFileView(View):
    """批复附件 kkFileView 回调读取文件流（preview_token 鉴权）

    无 @auth，由 preview_token 校验 token 中 object_type 与数据库一致。
    """

    def get(self, request, pk):
        preview_token = request.GET.get('preview_token')
        if not preview_token:
            return json_response(error='缺少 preview_token 参数')
        # AttachmentService.preview_file_response 会校验 token 中的
        # module/object_type/object_id/tenant_id 与附件记录一致。
        response, error = AttachmentService.preview_file_response(preview_token, pk)
        if error:
            return json_response(error=error)
        return response


class ApprovalAttachmentDeleteView(View):
    """批复附件删除（软删除）"""

    @auth('radio_license.attachment.delete')
    def delete(self, request):
        if not request.user.has_perms({'radio_license.approval.view'}):
            return json_response(error='权限拒绝')
        form, error = JsonParser(
            Argument('id', type=int, help='请指定附件ID'),
            Argument('delete_reason', required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)

        att, err = _get_approval_attachment_for_user(request.user, form.id)
        if err:
            return json_response(error=err)

        # 软删除前再校验一次 is_deleted
        if att.is_deleted:
            return json_response(error='附件不存在或无权限删除')

        error = AttachmentService.soft_delete(
            request.user, form.id, form.delete_reason, delete_file=True,
        )
        if error:
            return json_response(error=error)

        # 附件删除审计事件必须使用附件记录中的真实 module/object_type/object_id
        try:
            from apps.evidence.services import record_evidence_event
            att.refresh_from_db()
            record_evidence_event(
                tenant_id=att.tenant_id,
                module=att.module,
                object_type=att.object_type,
                object_id=att.object_id,
                event_type='delete',
                actor_user_id=getattr(request.user, 'id', None),
                actor_username=getattr(request.user, 'username', ''),
                actor_name=request.user.nickname or request.user.username,
                object_snapshot={
                    'attachment_id': att.id,
                    'file_name': att.file_name,
                    'file_hash_sha256': att.file_hash_sha256,
                    'delete_reason': form.delete_reason or '',
                },
                event_title=f'删除批复附件 {att.file_name}',
            )
        except Exception as ev_err:
            logger.error(f'批复附件删除证据事件写入失败: {ev_err}')

        return json_response()


# ==================== 批复到期提醒接口 ====================


class ApprovalReminderPopupView(View):
    """批复弹窗提醒查询接口。

    实时查询当前用户负责的 expiring/expired 批复，排除已 ack 的当前周期。
    days_left 实时计算，status 与列表口径一致。
    """

    @auth('radio_license.approval.view')
    def get(self, request):
        today = timezone.now().date()
        qs = apply_tenant_filter(StationFrequencyApproval.objects.all(), request.user)
        approvals = qs.filter(
            responsible_user_id=request.user.id,
            valid_to__lte=today + timedelta(days=EXPIRING_DAYS_THRESHOLD),
        )

        # 查询该用户所有 ack，构造 (approval_id, ack_valid_to) 集合用于排除
        acks = StationFrequencyApprovalReminderAck.objects.filter(
            tenant_id=getattr(request.user, 'tenant_id', ''),
            user_id=request.user.id,
        ).values_list('approval_id', 'ack_valid_to')
        ack_set = {(aid, avid) for aid, avid in acks}

        records = []
        for approval in approvals:
            if (approval.id, approval.valid_to) in ack_set:
                continue
            computed_status, days_left = _compute_approval_status_fields(approval)
            records.append({
                'approval_id': approval.id,
                'name': approval.name,
                'doc_no': approval.doc_no,
                'frequency_text': approval.frequency_text,
                'valid_from': str(approval.valid_from),
                'valid_to': str(approval.valid_to),
                'days_left': days_left,
                'status': computed_status,
                'remind_type': 'expired' if days_left < 0 else 'expiring_daily',
                'reminder_cycle': f'{approval.id}:{approval.valid_to}',
            })
        return json_response({'records': records})


class ApprovalReminderAckView(View):
    """批复提醒确认（已处理）接口。

    幂等：使用 get_or_create，重复请求成功返回。
    非责任人或正常状态记录不得写入 ack。
    """

    @auth('radio_license.approval.view')
    def post(self, request):
        from django.db import transaction
        form, error = JsonParser(
            Argument('approval_id', type=int, help='请指定批复ID'),
        ).parse(request.body)
        if error is not None:
            return json_response(error=error)

        qs = apply_tenant_filter(StationFrequencyApproval.objects.all(), request.user)
        approval = qs.filter(pk=form.approval_id).first()
        if not approval:
            return json_response(error='批复不存在或无权限')

        # 当前用户必须是责任人
        if approval.responsible_user_id != request.user.id:
            return json_response(error='仅责任人可确认处理提醒')

        # 实时状态必须是 expiring 或 expired
        computed_status, days_left = _compute_approval_status_fields(approval)
        if computed_status == StationFrequencyApproval.STATUS_NORMAL:
            return json_response(error='当前批复状态正常，无需确认处理')

        try:
            with transaction.atomic():
                _, created = StationFrequencyApprovalReminderAck.objects.get_or_create(
                    tenant_id=approval.tenant_id,
                    approval=approval,
                    user_id=request.user.id,
                    ack_valid_to=approval.valid_to,
                    defaults={
                        'user_name': request.user.nickname or request.user.username,
                    },
                )
        except Exception as e:
            logger.error(f'[StationFrequencyApproval] ack 写入失败: {e}')
            return json_response(error='确认处理失败，请稍后重试')

        logger.info(
            f'[StationFrequencyApproval] 用户 {request.user.id} 确认处理批复 '
            f'{form.approval_id} (valid_to={approval.valid_to}, new_ack={created})'
        )

        _record_approval_audit(
            request.user, 'update', approval,
            detail={
                'approval_id': approval.id,
                'ack_valid_to': str(approval.valid_to),
                'user_id': request.user.id,
                'user_name': request.user.nickname or request.user.username,
            },
        )
        return json_response(data={'approval_id': form.approval_id, 'acked': True})


class ApprovalBadgeView(View):
    """批复菜单红点统计。

    只统计当前用户负责且当前周期未 ack 的记录；
    使用 Exists + OuterRef 排除当前周期 ack，避免将全部 ack 加载到 Python。
    """

    @auth('radio_license.approval.view')
    def get(self, request):
        from django.db.models import Exists, OuterRef
        today = timezone.now().date()
        qs = apply_tenant_filter(StationFrequencyApproval.objects.all(), request.user)
        qs = qs.filter(responsible_user_id=request.user.id)

        # 当前周期 ack：approval_id + user_id + ack_valid_to == approval.valid_to
        acked_exists = StationFrequencyApprovalReminderAck.objects.filter(
            tenant_id=getattr(request.user, 'tenant_id', ''),
            approval_id=OuterRef('pk'),
            user_id=request.user.id,
            ack_valid_to=OuterRef('valid_to'),
        )
        qs = qs.filter(~Exists(acked_exists))

        expiring_count = qs.filter(
            valid_to__gte=today,
            valid_to__lte=today + timedelta(days=EXPIRING_DAYS_THRESHOLD),
        ).count()
        expired_count = qs.filter(valid_to__lt=today).count()
        return json_response(data={
            'count': expiring_count + expired_count,
            'expiring_count': expiring_count,
            'expired_count': expired_count,
        })
