# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
import logging
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta

from django.db import IntegrityError
from django.views.generic import View

from libs import json_response, JsonParser, Argument, human_datetime, auth
from libs.tenant_utils import apply_tenant_filter, assign_tenant_id
from apps.logs.audit import record_audit_event
from apps.evidence.attachment_service import AttachmentService, AttachmentConfig, PREVIEWABLE_EXTENSIONS
from apps.evidence.models import EvidenceAttachment

from .models import (
    ContractAgreement,
    ContractAgreementReminderAck,
    EXPIRING_DAYS_THRESHOLD,
)
from .tasks import calculate_agreement_status, scan_single_contract_agreement

logger = logging.getLogger(__name__)

AUDIT_TARGET_TYPE = 'contract_agreement'
ATTACHMENT_MODULE = 'contract_agreement'
ATTACHMENT_OBJECT_TYPE = 'agreement'

ContractAgreementAttachmentConfig = AttachmentConfig(
    allowed_extensions=('.pdf', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp',
                        '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
                        '.zip', '.rar', '.7z'),
    max_size_mb=50,
)


def _parse_date(value, field_name):
    if not value:
        return None, f'请选择{field_name}'
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date(), None
    except ValueError:
        return None, f'{field_name}格式必须为 YYYY-MM-DD'


def _fmt_date(value):
    if not value:
        return None
    return value.strftime('%Y-%m-%d') if hasattr(value, 'strftime') else str(value)


def _fmt_decimal(value):
    if value is None:
        return None
    return str(value)


def _status_text(status):
    return dict(ContractAgreement.STATUS_CHOICES).get(status, status)


def _remind_text(remind_status):
    return {
        'normal': '正常',
        'expiring': '即将到期',
        'expired': '已过期',
    }.get(remind_status, remind_status)


def _serialize_agreement(agreement, user=None, include_attachment_count=True):
    business_status, remind_status, days_left = calculate_agreement_status(agreement.valid_end_date)
    data = agreement.to_view()
    data.update({
        'contract_type_display': agreement.contract_type_display,
        'valid_start_date': _fmt_date(agreement.valid_start_date),
        'valid_end_date': _fmt_date(agreement.valid_end_date),
        'fee_amount': _fmt_decimal(agreement.fee_amount),
        'fee_currency': agreement.fee_currency or '人民币',
        'status': business_status,
        'status_display': _status_text(business_status),
        'computed_status': business_status,
        'computed_status_display': _status_text(business_status),
        'remind_status': remind_status,
        'remind_status_display': _remind_text(remind_status),
        'days_left': days_left,
        'created_by_name': agreement.created_by.nickname or agreement.created_by.username if agreement.created_by else '',
        'updated_by_name': agreement.updated_by.nickname or agreement.updated_by.username if agreement.updated_by else '',
    })
    if include_attachment_count and user is not None:
        data['attachment_count'] = AttachmentService.count(
            user, ATTACHMENT_MODULE, ATTACHMENT_OBJECT_TYPE, agreement.id)
    return data


def _validate_form(form):
    valid_start_date, error = _parse_date(form.valid_start_date, '起始日期')
    if error:
        return None, error
    valid_end_date, error = _parse_date(form.valid_end_date, '截止日期')
    if error:
        return None, error
    if valid_start_date > valid_end_date:
        return None, '起始日期不能晚于截止日期'

    if form.contract_type not in dict(ContractAgreement.CONTRACT_TYPE_CHOICES):
        return None, '未知的合同类型'

    has_fee = bool(form.has_fee)
    fee_amount = None
    fee_detail = form.fee_detail or ''
    if has_fee:
        if form.fee_amount in (None, ''):
            return None, '有费用时请填写费用金额'
        try:
            fee_amount = Decimal(str(form.fee_amount))
        except (InvalidOperation, ValueError):
            return None, '费用金额格式不正确'
        if fee_amount < 0:
            return None, '费用金额不能小于 0'
    else:
        fee_detail = ''

    business_status, _, _ = calculate_agreement_status(valid_end_date)
    return {
        'contract_name': form.contract_name.strip(),
        'contract_type': form.contract_type,
        'valid_start_date': valid_start_date,
        'valid_end_date': valid_end_date,
        'has_fee': has_fee,
        'fee_amount': fee_amount,
        'fee_currency': '人民币',
        'fee_detail': fee_detail,
        'signing_party': form.signing_party.strip(),
        'status': business_status,
        'remark': form.remark or '',
    }, None


class ContractAgreementView(View):
    """合同协议列表 / 新增编辑 / 删除"""

    @auth('contract_agreement.agreement.view')
    def get(self, request):
        qs = apply_tenant_filter(ContractAgreement.objects.all(), request.user)

        contract_name = request.GET.get('contract_name', '')
        contract_type = request.GET.get('contract_type', '')
        status = request.GET.get('status', '')
        signing_party = request.GET.get('signing_party', '')
        has_fee = request.GET.get('has_fee', '')
        valid_start_from = request.GET.get('valid_start_from', '')
        valid_start_to = request.GET.get('valid_start_to', '')
        valid_end_from = request.GET.get('valid_end_from', '')
        valid_end_to = request.GET.get('valid_end_to', '')

        if contract_name:
            qs = qs.filter(contract_name__icontains=contract_name)
        if contract_type:
            qs = qs.filter(contract_type=contract_type)
        if status:
            qs = qs.filter(status=status)
        if signing_party:
            qs = qs.filter(signing_party__icontains=signing_party)
        if has_fee != '':
            qs = qs.filter(has_fee=str(has_fee).lower() in ('1', 'true', 'yes'))
        if valid_start_from:
            qs = qs.filter(valid_start_date__gte=valid_start_from)
        if valid_start_to:
            qs = qs.filter(valid_start_date__lte=valid_start_to)
        if valid_end_from:
            qs = qs.filter(valid_end_date__gte=valid_end_from)
        if valid_end_to:
            qs = qs.filter(valid_end_date__lte=valid_end_to)

        page = max(1, int(request.GET.get('page', 1)))
        page_size = min(max(1, int(request.GET.get('page_size', 20))), 100)

        qs = qs.select_related('created_by', 'updated_by').order_by('-created_at', '-id')
        total_count = qs.count()
        records = qs[(page - 1) * page_size: page * page_size]

        data = [_serialize_agreement(item, request.user) for item in records]
        return json_response({
            'records': data,
            'total': total_count,
            'page': page,
            'page_size': page_size,
        })

    @auth('contract_agreement.agreement.add|contract_agreement.agreement.edit')
    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('contract_name', help='请输入合同名称'),
            Argument('contract_type', help='请选择类型'),
            Argument('valid_start_date', help='请选择起始日期'),
            Argument('valid_end_date', help='请选择截止日期'),
            Argument('has_fee', type=bool, required=False, default=False),
            Argument('fee_amount', required=False),
            Argument('fee_detail', required=False, default=''),
            Argument('signing_party', help='请输入签约方'),
            Argument('remark', required=False, default=''),
        ).parse(request.body)
        if error:
            return json_response(error=error)

        data, error = _validate_form(form)
        if error:
            return json_response(error=error)

        if form.id:
            if not request.user.has_perms({'contract_agreement.agreement.edit'}):
                return json_response(error='权限拒绝：缺少编辑合同协议权限')
            qs = apply_tenant_filter(ContractAgreement.objects.all(), request.user)
            agreement = qs.filter(pk=form.id).first()
            if not agreement:
                return json_response(error='合同协议不存在或无权限编辑')
            for key, value in data.items():
                setattr(agreement, key, value)
            agreement.updated_at = human_datetime()
            agreement.updated_by = request.user
            agreement.save()
            scan_single_contract_agreement(agreement)
            record_audit_event(
                request, 'update', AUDIT_TARGET_TYPE,
                target_id=agreement.id, target_name=agreement.contract_name,
                detail={'contract_type': agreement.contract_type, 'valid_end_date': _fmt_date(agreement.valid_end_date)},
            )
            return json_response(data=_serialize_agreement(agreement, request.user))

        if not request.user.has_perms({'contract_agreement.agreement.add'}):
            return json_response(error='权限拒绝：缺少新增合同协议权限')
        assign_tenant_id(data, request.user)
        agreement = ContractAgreement.objects.create(
            **data,
            created_by=request.user,
        )
        scan_single_contract_agreement(agreement)
        record_audit_event(
            request, 'create', AUDIT_TARGET_TYPE,
            target_id=agreement.id, target_name=agreement.contract_name,
            detail={'contract_type': agreement.contract_type, 'valid_end_date': _fmt_date(agreement.valid_end_date)},
        )
        return json_response(data=_serialize_agreement(agreement, request.user))

    @auth('contract_agreement.agreement.del')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)
        if error:
            return json_response(error=error)

        qs = apply_tenant_filter(ContractAgreement.objects.all(), request.user)
        agreement = qs.filter(pk=form.id).first()
        if not agreement:
            return json_response(error='合同协议不存在或无权限删除')

        AttachmentService.soft_delete_by_object(
            request.user, ATTACHMENT_MODULE, ATTACHMENT_OBJECT_TYPE, form.id,
            reason=f'合同协议删除 ID={form.id}', delete_file=True,
        )
        record_audit_event(
            request, 'delete', AUDIT_TARGET_TYPE,
            target_id=agreement.id, target_name=agreement.contract_name,
            detail={'contract_type': agreement.contract_type},
        )
        agreement.delete()
        return json_response()


class ContractAgreementDetailView(View):
    """合同协议详情"""

    @auth('contract_agreement.agreement.view')
    def get(self, request, pk):
        qs = apply_tenant_filter(ContractAgreement.objects.all(), request.user)
        agreement = qs.select_related('created_by', 'updated_by').filter(pk=pk).first()
        if not agreement:
            return json_response(error='合同协议不存在或无权限访问')
        return json_response(_serialize_agreement(agreement, request.user))


class AttachmentListView(View):
    """附件列表 / 上传"""

    @auth('contract_agreement.agreement.view')
    def get(self, request, pk):
        qs = apply_tenant_filter(ContractAgreement.objects.all(), request.user)
        if not qs.filter(pk=pk).exists():
            return json_response(error='合同协议不存在或无权限访问')
        data = AttachmentService.list(
            request.user, ATTACHMENT_MODULE, ATTACHMENT_OBJECT_TYPE, pk)
        return json_response(data)

    @auth('contract_agreement.attachment.upload')
    def post(self, request, pk):
        qs = apply_tenant_filter(ContractAgreement.objects.all(), request.user)
        if not qs.filter(pk=pk).exists():
            return json_response(error='合同协议不存在或无权限访问')
        file = request.FILES.get('file')
        if not file:
            return json_response(error='请选择要上传的附件')

        att, error = AttachmentService.upload(
            file=file,
            user=request.user,
            module=ATTACHMENT_MODULE,
            object_type=ATTACHMENT_OBJECT_TYPE,
            object_id=pk,
            config=ContractAgreementAttachmentConfig,
        )
        if error:
            return json_response(error=error)
        result = att.to_view()
        result['uploaded_by_name'] = request.user.nickname
        result['created_at'] = att.uploaded_at
        result['previewable'] = att.file_ext in PREVIEWABLE_EXTENSIONS
        return json_response(result)


class AttachmentDownloadView(View):
    @auth('contract_agreement.attachment.download')
    def get(self, request, pk):
        response, error = AttachmentService.download_response(request.user, pk)
        if error:
            return json_response(error=error)
        return response


class AttachmentPreviewUrlView(View):
    @auth('contract_agreement.agreement.view')
    def get(self, request, pk):
        preview_file_api_path = f'/api/contract-agreement/attachments/{pk}/preview-file/'
        data, error = AttachmentService.get_preview_url(request.user, pk, preview_file_api_path)
        if error:
            return json_response(error=error)
        return json_response(data)


class AttachmentPreviewFileView(View):
    def get(self, request, pk):
        preview_token = request.GET.get('preview_token')
        if not preview_token:
            return json_response(error='缺少 preview_token 参数')
        response, error = AttachmentService.preview_file_response(preview_token, pk)
        if error:
            return json_response(error=error)
        return response


class AttachmentDeleteView(View):
    @auth('contract_agreement.attachment.delete')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定附件ID'),
            Argument('delete_reason', required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)

        att = EvidenceAttachment.objects.filter(pk=form.id).first()
        error = AttachmentService.soft_delete(
            request.user, form.id, form.delete_reason, delete_file=True)
        if error:
            return json_response(error=error)
        if att:
            record_audit_event(
                request, 'delete', 'contract_agreement_attachment',
                target_id=att.object_id, target_name=att.file_name,
                detail={'attachment_id': att.id, 'file_name': att.file_name, 'delete_reason': form.delete_reason or ''},
            )
        return json_response()


def _unacked_reminder_queryset(user):
    today = datetime.today().date()
    qs = apply_tenant_filter(ContractAgreement.objects.all(), user).filter(
        valid_end_date__lte=today + timedelta(days=EXPIRING_DAYS_THRESHOLD),
    ).select_related('created_by')
    acks = ContractAgreementReminderAck.objects.filter(
        user_id=user.id,
    ).values_list('agreement_id', 'ack_valid_end_date')
    ack_set = {(aid, valid_end) for aid, valid_end in acks}
    records = []
    for agreement in qs:
        _, remind_status, days_left = calculate_agreement_status(agreement.valid_end_date, today)
        if remind_status == 'normal':
            continue
        if (agreement.id, agreement.valid_end_date) in ack_set:
            continue
        records.append((agreement, remind_status, days_left))
    return records


class ReminderPopupView(View):
    """合同协议到期提醒弹窗。"""

    @auth('contract_agreement.agreement.view')
    def get(self, request):
        records = []
        for agreement, remind_status, days_left in _unacked_reminder_queryset(request.user):
            records.append({
                'agreement_id': agreement.id,
                'contract_name': agreement.contract_name,
                'contract_type': agreement.contract_type,
                'contract_type_display': agreement.contract_type_display,
                'valid_start_date': _fmt_date(agreement.valid_start_date),
                'valid_end_date': _fmt_date(agreement.valid_end_date),
                'days_left': days_left,
                'status': agreement.status,
                'remind_status': remind_status,
                'remind_type': 'expired' if remind_status == 'expired' else 'expiring_daily',
                'signing_party': agreement.signing_party,
                'has_fee': agreement.has_fee,
                'fee_amount': _fmt_decimal(agreement.fee_amount),
            })
        return json_response({'records': records})


class ReminderAckView(View):
    """确认处理合同协议到期提醒。"""

    @auth('contract_agreement.agreement.view')
    def post(self, request):
        form, error = JsonParser(
            Argument('agreement_id', type=int, help='合同协议ID'),
        ).parse(request.body)
        if error:
            return json_response(error=error)

        qs = apply_tenant_filter(ContractAgreement.objects.all(), request.user)
        agreement = qs.filter(pk=form.agreement_id).first()
        if not agreement:
            return json_response(error='合同协议不存在或无权限访问')

        _, remind_status, _ = calculate_agreement_status(agreement.valid_end_date)
        if remind_status == 'normal':
            return json_response(data={'agreement_id': form.agreement_id, 'acked': False, 'message': '当前合同无需提醒'})

        try:
            ContractAgreementReminderAck.objects.create(
                tenant_id=agreement.tenant_id,
                agreement=agreement,
                user_id=request.user.id,
                user_name=request.user.nickname or request.user.username,
                ack_valid_end_date=agreement.valid_end_date,
            )
            record_audit_event(
                request, 'other', AUDIT_TARGET_TYPE,
                target_id=agreement.id, target_name=agreement.contract_name,
                detail={'action': 'reminder_ack', 'valid_end_date': _fmt_date(agreement.valid_end_date)},
            )
        except IntegrityError:
            logger.debug('[ContractAgreement] reminder already acked: agreement=%s user=%s',
                         agreement.id, request.user.id)
        return json_response(data={'agreement_id': form.agreement_id, 'acked': True})


class ContractAgreementBadgeView(View):
    """菜单角标数量。"""

    @auth('contract_agreement.agreement.view')
    def get(self, request):
        count = 0
        expiring_count = 0
        expired_count = 0
        for _, remind_status, _ in _unacked_reminder_queryset(request.user):
            count += 1
            if remind_status == 'expired':
                expired_count += 1
            elif remind_status == 'expiring':
                expiring_count += 1
        return json_response(data={
            'count': count,
            'expiring_count': expiring_count,
            'expired_count': expired_count,
        })
