# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""台站频率批复相关视图。

从 radio_license/views.py 拆分而来，用于控制单文件代码行数。
执照相关视图仍保留在 views.py。

数据范围（2026-09 第一轮改造）：
- 批复不再按租户隔离：拥有 radio_license.approval.* 权限的用户全局可见可管。
- tenant_id 仅记录创建人租户（来源/附件归属/审计），不作为访问边界。
- 无个人主动提醒：popup/ack/责任人与指定提醒接收人接口不存在；
  菜单红点为全局只读统计（badge，2026-09 第二轮恢复）。
"""
import logging
from datetime import timedelta

from django.db.models import Count
from django.views.generic import View
from django.utils import timezone
from libs import json_response, JsonParser, Argument, auth
from libs.tenant_utils import assign_tenant_id
from apps.radio_license.models import (
    StationFrequencyApproval,
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


def _compute_approval_status_fields(record):
    """根据 valid_to 实时计算 status/days_left。

    所有列表、详情统一调用本函数，避免逻辑分散。
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


def _bulk_attachment_counts(approval_ids):
    """批量聚合指定批复 ID 列表的未删除附件数量，避免列表 N+1 查询。

    批复列表本身已做权限校验（@auth approval.view）且跨租户可见，
    因此附件计数直接按 module/object_type/object_id 全局统计。
    """
    if not approval_ids:
        return {}
    qs = EvidenceAttachment.objects.filter(
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
    """台站频率批复列表 / 新增编辑 / 删除入口

    数据范围：批复跨租户全局共享（权限由 @auth 独立校验），
    查询不做租户过滤；tenant_id 仅作来源与审计信息。
    """

    @auth('radio_license.approval.view')
    def get(self, request):
        records = StationFrequencyApproval.objects.all()

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
        att_counts = _bulk_attachment_counts(approval_ids)

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
            Argument('remark', required=False),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        if form.id:
            return self._post_edit(request, form)
        return self._post_create(request, form)

    def _post_edit(self, request, form):
        """编辑入口：日期校验 → 权限 → 落库（跨租户可编辑原租户批复）"""
        if form.valid_from and form.valid_to and form.valid_from > form.valid_to:
            return json_response(error='起始日期不能晚于截止日期')
        if not request.user.has_perms({'radio_license.approval.edit'}):
            return json_response(error='权限拒绝：缺少编辑批复权限')
        return json_response(error=self._handle_edit(form, request.user))

    def _post_create(self, request, form):
        """创建入口：标准化 → 必填校验 → 日期校验 → 权限 → 落库"""
        form.name = (form.name or '').strip()
        form.doc_no = (form.doc_no or '').strip()
        form.frequency_text = (form.frequency_text or '').strip()
        if not form.name or not form.doc_no or not form.frequency_text:
            return json_response(error='文件名称、文件编号、批复频率不能为空')
        if form.valid_from and form.valid_to and form.valid_from > form.valid_to:
            return json_response(error='起始日期不能晚于截止日期')
        if not request.user.has_perms({'radio_license.approval.add'}):
            return json_response(error='权限拒绝：缺少新增批复权限')
        return json_response(error=self._handle_create(form, request.user))

    def _handle_create(self, form, user):
        """新增批复：落库（记录创建人租户）+ 即时扫描 + 审计（文件编号允许重复）"""
        from django.db import transaction

        form.pop('remark', None)
        assign_tenant_id(form, user)
        form.created_by = user

        with transaction.atomic():
            create_data = {k: v for k, v in form.items() if v is not None}
            approval = StationFrequencyApproval.objects.create(**create_data)
            # 即时扫描更新缓存状态（不等待每日 Celery）
            scan_single_approval(approval)
            _record_approval_audit(
                user, 'create', approval,
                detail={
                    'name': approval.name, 'doc_no': approval.doc_no,
                    'frequency_text': approval.frequency_text,
                    'valid_from': str(approval.valid_from),
                    'valid_to': str(approval.valid_to),
                    'tenant_id': approval.tenant_id,
                },
            )

        return None

    def _handle_edit(self, form, user):
        """编辑批复：更新（跨租户，不按租户过滤）+ 即时扫描 + 审计"""
        from django.db import transaction

        old_approval = StationFrequencyApproval.objects.filter(pk=form.id).first()
        if not old_approval:
            return '编辑失败：记录不存在或无权限编辑'

        form.updated_at = timezone.now()
        form.updated_by = user
        record_id = form.pop('id')
        form.pop('remark', None)

        with transaction.atomic():
            update_data = {k: v for k, v in form.items() if v is not None}
            updated_count = StationFrequencyApproval.objects.filter(
                pk=record_id).update(**update_data)
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
                    'tenant_id': approval.tenant_id,
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
            approval = StationFrequencyApproval.objects.filter(pk=form.id).first()
            if not approval:
                error = '删除失败：记录不存在或无权限删除'
            else:
                snapshot = {
                    'name': approval.name,
                    'doc_no': approval.doc_no,
                    'valid_to': str(approval.valid_to),
                    'tenant_id': approval.tenant_id,
                }
                with transaction.atomic():
                    # 软删附件（delete_file=False，物理文件由公共策略处理）。
                    # 跨租户删除：跳过附件租户过滤，仅按 module/object_type/object_id 匹配
                    AttachmentService.soft_delete_by_object(
                        request.user, APPROVAL_ATTACHMENT_MODULE,
                        APPROVAL_ATTACHMENT_OBJECT_TYPE, form.id,
                        reason=f'批复删除 ID={form.id}', delete_file=False,
                        skip_tenant_filter=True,
                    )
                    # 物理删除批复
                    approval.delete()
                    _record_approval_audit(
                        request.user, 'delete', None,
                        detail=snapshot, target_id=form.id,
                    )
        return json_response(error=error)


class StationFrequencyApprovalBadgeView(View):
    """台站频率批复菜单红点统计（全局只读，2026-09 第二轮恢复）。

    统计口径：
    - 直接统计全部 StationFrequencyApproval，不按租户/账户/责任人过滤，
      所有拥有 radio_license.approval.view 的账户看到相同统计；
    - 按 valid_to 实时计算，不依赖缓存 status 字段：
      expiring: today <= valid_to <= today + EXPIRING_DAYS_THRESHOLD
      expired:  valid_to < today
      count = expiring_count + expired_count；
    - 纯只读：不创建 ACK、提醒、审计或其他任何数据库副作用。
    """

    @auth('radio_license.approval.view')
    def get(self, request):
        today = timezone.now().date()
        qs = StationFrequencyApproval.objects.all()
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


class StationFrequencyApprovalDetailView(View):
    """批复详情（跨租户可见，权限由 @auth 校验）"""

    @auth('radio_license.approval.view')
    def get(self, request, pk):
        try:
            record = StationFrequencyApproval.objects.get(pk=pk)
        except StationFrequencyApproval.DoesNotExist:
            return json_response(error='记录不存在或无权限访问')

        item = record.to_view()
        computed_status, days_left = _compute_approval_status_fields(record)
        item['days_left'] = days_left
        item['computed_status'] = computed_status
        item['attachment_count'] = _bulk_attachment_counts([record.id]).get(record.id, 0)
        item['created_by_name'] = (
            record.created_by.nickname or record.created_by.username
            if record.created_by else ''
        )
        item['updated_by_name'] = (
            record.updated_by.nickname or record.updated_by.username
            if record.updated_by else ''
        )
        return json_response(item)


# ==================== 批复附件桥接视图 ====================


def _get_approval_by_id(approval_id):
    """按主键取批复（跨租户全局共享，仅校验存在性），不存在返回 None。"""
    return StationFrequencyApproval.objects.filter(pk=approval_id).first()


def _get_approval_attachment_for_user(user, attachment_id):
    """获取附件并校验归属（批复附件跨租户访问的安全闸门）。

    全部满足才放行：
    1. 附件存在且未软删除（默认 Manager 已过滤 is_deleted）；
    2. module == 'radio_license' 且 object_type == 'approval'（防跨模块越权）；
    3. attachment.object_id 对应的父批复真实存在。

    通过校验即视为父批复可访问（批复本身对有权限用户全局共享），
    调用方随后以 skip_tenant_filter=True 走 AttachmentService。
    返回 (attachment, error)。
    """
    att = EvidenceAttachment.objects.filter(pk=attachment_id).first()
    if not att:
        return None, '附件不存在或无权限访问'
    if att.module != APPROVAL_ATTACHMENT_MODULE or att.object_type != APPROVAL_ATTACHMENT_OBJECT_TYPE:
        return None, '附件不存在或无权限访问'
    # 校验父批复真实存在
    if not _get_approval_by_id(att.object_id):
        return None, '附件不存在或无权限访问'
    return att, None


class ApprovalAttachmentListView(View):
    """批复附件列表 / 上传"""

    @auth('radio_license.approval.view')
    def get(self, request, pk):
        if not _get_approval_by_id(pk):
            return json_response(error='批复不存在或无权限访问')
        # 父批复存在性已校验；批复对有权限用户全局共享，附件跨租户可列
        data = AttachmentService.list(
            request.user, APPROVAL_ATTACHMENT_MODULE,
            APPROVAL_ATTACHMENT_OBJECT_TYPE, pk,
            skip_tenant_filter=True,
        )
        return json_response(data)

    @auth('radio_license.attachment.upload')
    def post(self, request, pk):
        # 装饰器只校验附件上传权限，需在方法内显式校验 approval.view
        if not request.user.has_perms({'radio_license.approval.view'}):
            return json_response(error='权限拒绝')
        approval = _get_approval_by_id(pk)
        if not approval:
            return json_response(error='批复不存在或无权限访问')

        file = request.FILES.get('file')
        if not file:
            return json_response(error='请选择要上传的文件')

        # 跨租户上传时附件归属父批复租户（owner_tenant_id），而非上传人租户
        att, error = AttachmentService.upload(
            file=file,
            user=request.user,
            module=APPROVAL_ATTACHMENT_MODULE,
            object_type=APPROVAL_ATTACHMENT_OBJECT_TYPE,
            object_id=pk,
            config=ApprovalAttachmentConfig,
            owner_tenant_id=approval.tenant_id,
        )
        if error:
            return json_response(error=error)

        result = att.to_view()
        result['uploaded_by_name'] = request.user.nickname
        result['created_at'] = att.uploaded_at
        result['previewable'] = att.file_ext in PREVIEWABLE_EXTENSIONS
        return json_response(result)


class ApprovalAttachmentDownloadView(View):
    """批复附件下载（approval.view + attachment.download，跨租户）"""

    @auth('radio_license.attachment.download')
    def get(self, request, pk):
        if not request.user.has_perms({'radio_license.approval.view'}):
            return json_response(error='权限拒绝')
        att, err = _get_approval_attachment_for_user(request.user, pk)
        if err:
            return json_response(error=err)
        inline = request.GET.get('inline') in ('1', 'true', 'True')
        # 已通过桥接校验，跨租户读取文件流
        response, error = AttachmentService.download_response(
            request.user, pk, APPROVAL_ATTACHMENT_MODULE, APPROVAL_ATTACHMENT_OBJECT_TYPE,
            inline=inline, skip_tenant_filter=True)
        if error:
            return json_response(error=error)
        return response


class ApprovalAttachmentPreviewUrlView(View):
    """批复附件 kkFileView 预览地址（跨租户；preview_token 绑定附件真实租户）"""

    @auth('radio_license.approval.view')
    def get(self, request, pk):
        att, err = _get_approval_attachment_for_user(request.user, pk)
        if err:
            return json_response(error=err)
        preview_file_api_path = f'/api/radio-license/approvals/attachments/{pk}/preview-file/'
        data, error = AttachmentService.get_preview_url(
            request.user, pk, APPROVAL_ATTACHMENT_MODULE, APPROVAL_ATTACHMENT_OBJECT_TYPE,
            preview_file_api_path,
            skip_tenant_filter=True,
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

        # 父批复归属校验已通过，跨租户软删除
        error = AttachmentService.soft_delete(
            request.user, form.id, APPROVAL_ATTACHMENT_MODULE, APPROVAL_ATTACHMENT_OBJECT_TYPE,
            form.delete_reason, delete_file=True, skip_tenant_filter=True,
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
