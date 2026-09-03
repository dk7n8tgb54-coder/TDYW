# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
import logging
from decimal import Decimal, InvalidOperation
from datetime import timedelta
from django.views.generic import View
from django.utils import timezone
from django.http import FileResponse
from django.utils import timezone
from libs import json_response, JsonParser, Argument, auth
from libs.utils import DateTimeEncoder
from libs.tenant_utils import apply_tenant_filter, assign_tenant_id
from libs.idempotency import check_recent_duplicate
from apps.logs.audit import record_audit_event
from apps.radio_license.models import (
    RadioLicense, RadioLicenseFrequency,
    LicenseReminderAck,
    EXPIRING_DAYS_THRESHOLD,
)
from apps.radio_license.tasks import scan_single_license
from apps.evidence.attachment_service import AttachmentService, AttachmentConfig, PREVIEWABLE_EXTENSIONS
from apps.evidence.models import EvidenceAttachment
import json

logger = logging.getLogger(__name__)


# ==================== 证据闭环第三阶段：辅助函数 ====================

# 编辑模式下可比较的字段列表（用于检测变更字段）
_LICENSE_EDITABLE_FIELDS = (
    'station_name', 'purpose', 'valid_from', 'valid_to',
    'responsible_user_id', 'responsible_user_name',
)


def _compute_license_status_fields(record):
    """根据 valid_to 实时计算 status/days_left（与 BadgeView 的 60 天规则一致）。

    status 字段是缓存值（由 Celery 扫描维护），列表/详情/popup/ack
    一律以本函数的实时计算结果为准。
    """
    today = timezone.now().date()
    days_left = (record.valid_to - today).days
    if days_left < 0:
        computed_status = 'expired'
    elif days_left <= EXPIRING_DAYS_THRESHOLD:
        computed_status = 'expiring'
    else:
        computed_status = 'normal'
    return computed_status, days_left


def _apply_license_status_filter(qs, status, today):
    """列表 status 筛选转换为实时 valid_to 范围，不依赖缓存字段。

    边界（与 _compute_license_status_fields 一致）：
    - valid_to < today                        → expired
    - today <= valid_to <= today + 60 天      → expiring
    - valid_to > today + 60 天                → normal
    """
    if status == 'normal':
        return qs.filter(valid_to__gt=today + timedelta(days=EXPIRING_DAYS_THRESHOLD))
    if status == 'expiring':
        return qs.filter(valid_to__gte=today,
                         valid_to__lte=today + timedelta(days=EXPIRING_DAYS_THRESHOLD))
    if status == 'expired':
        return qs.filter(valid_to__lt=today)
    return qs


def _bulk_license_attachment_counts(user, license_ids):
    """批量聚合指定执照 ID 列表的未删除附件数量，避免列表 N+1 查询。

    与批复侧 _bulk_attachment_counts 同口径：
    只统计 module='radio_license' + object_type='license' 的未删除附件，
    且经过租户过滤（不绕过租户隔离）。
    """
    if not license_ids:
        return {}
    from django.db.models import Count
    qs = apply_tenant_filter(EvidenceAttachment.objects.all(), user).filter(
        module=ATTACHMENT_MODULE,
        object_type=ATTACHMENT_OBJECT_TYPE,
        object_id__in=[str(i) for i in license_ids],
        is_deleted=False,
    ).values('object_id').annotate(count=Count('object_id'))
    return {int(item['object_id']): item['count'] for item in qs}


def _validate_frequencies(frequencies):
    """校验完整频率列表，避免先删旧明细后才由数据库约束报错。"""
    for index, item in enumerate(frequencies, start=1):
        if not isinstance(item, dict):
            return f'第 {index} 条频率格式不正确'
        try:
            value = Decimal(str(item.get('frequency_value', '')))
        except (InvalidOperation, ValueError):
            return f'第 {index} 条频率数值格式不正确'
        if value <= 0:
            return f'第 {index} 条频率必须大于 0'
        sort_order = item.get('sort_order', index - 1)
        if isinstance(sort_order, bool) or not isinstance(sort_order, int) or sort_order < 0:
            return f'第 {index} 条频率排序必须是非负整数'
    return None


def _validate_and_fill_responsible_user(form, request_user):
    """校验执照责任人账号并回填真实姓名。

    与批复侧 _validate_and_fill_approval_responsible_user 规则一致：
    1. 必须存在且 is_active=True；
    2. deleted_by_id IS NULL（未软删）；
    3. tenant_id 必须等于当前请求用户 tenant_id（超管除外，但仍要求账号未删除且启用）；
    4. 服务端用 nickname or username 回填 responsible_user_name；
    5. 不信任客户端传入的 responsible_user_name。

    Returns:
        错误消息字符串；None 表示通过
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


def _detect_license_changed_fields(old_license, form):
    """检测本次编辑相对旧记录变更的字段列表"""
    changed = []
    for fname in _LICENSE_EDITABLE_FIELDS:
        new_val = getattr(form, fname, None)
        old_val = getattr(old_license, fname, None)
        # DateField 转 str 比较
        if old_val is not None and not isinstance(old_val, str):
            old_val = str(old_val)
        if str(new_val) != str(old_val):
            changed.append(fname)
    return changed


def _record_license_edit_evidence(license_obj, old_valid_to, changed_fields, user):
    """根据本次编辑的变更情况写入证据事件

    - valid_to 变化 → 续期事件（含 before/after）
    - 其他字段变更 → 通用更新事件（含 changed_fields）
    - 无变更 → 不写
    """
    from apps.evidence.services import record_evidence_event
    new_valid_to = license_obj.valid_to
    actor_name = user.nickname or user.username

    if str(old_valid_to) != str(new_valid_to):
        try:
            record_evidence_event(
                tenant_id=license_obj.tenant_id,
                module='radio_license',
                object_type='license',
                object_id=license_obj.id,
                event_type='other',
                actor_user_id=getattr(user, 'id', None),
                actor_username=getattr(user, 'username', ''),
                actor_name=actor_name,
                before_snapshot={'valid_to': str(old_valid_to)},
                after_snapshot={'valid_to': str(new_valid_to)},
                event_title=f'执照续期 {license_obj.station_name}: {old_valid_to} → {new_valid_to}',
                remark=f'有效期由 {old_valid_to} 续期至 {new_valid_to}',
            )
        except Exception as ev_err:
            logger.error(f'执照续期证据事件写入失败: {ev_err}')
        return

    if changed_fields:
        try:
            record_evidence_event(
                tenant_id=license_obj.tenant_id,
                module='radio_license',
                object_type='license',
                object_id=license_obj.id,
                event_type='other',
                actor_user_id=getattr(user, 'id', None),
                actor_username=getattr(user, 'username', ''),
                actor_name=actor_name,
                event_title=f'执照更新 {license_obj.station_name}',
                remark=f'变更字段: {", ".join(changed_fields)}',
            )
        except Exception as ev_err:
            logger.error(f'执照更新证据事件写入失败: {ev_err}')


class RadioLicenseView(View):
    """执照列表 / 新增编辑 / 删除"""

    @auth('radio_license.license.view')
    def get(self, request):
        records = apply_tenant_filter(RadioLicense.objects.all(), request.user)

        # 筛选参数
        station_name = request.GET.get('station_name', '')
        purpose = request.GET.get('purpose', '')
        status = request.GET.get('status', '')
        valid_to_start = request.GET.get('valid_to_start', '')
        valid_to_end = request.GET.get('valid_to_end', '')

        if station_name:
            records = records.filter(station_name__icontains=station_name)
        if purpose:
            records = records.filter(purpose__icontains=purpose)
        if status:
            # 实时按 valid_to 计算状态筛选，不依赖 Celery 维护的缓存 status 字段，
            # 保证新增/编辑/扫描后同一时刻查询口径一致
            records = _apply_license_status_filter(records, status, timezone.now().date())
        if valid_to_start:
            records = records.filter(valid_to__gte=valid_to_start)
        if valid_to_end:
            records = records.filter(valid_to__lte=valid_to_end)

        # 分页（page/page_size 非数字或越界时回退默认值，与批复侧行为对齐）
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
        records = records.prefetch_related('frequencies')
        total_count = records.count()
        offset = (page - 1) * page_size
        records = list(records[offset:offset + page_size])

        # 批量聚合附件数（避免逐条 count 的 N+1 查询）
        att_counts = _bulk_license_attachment_counts(
            request.user, [record.id for record in records])

        # 构造返回数据，附带频率信息和计算字段
        data = []
        for record in records:
            item = record.to_view()
            # 附加频率列表（prefetch_related 一次性取回，不再逐条查询）
            item['frequencies'] = [f.to_view() for f in record.frequencies.all()]
            # 附件数量（批量聚合结果）
            item['attachment_count'] = att_counts.get(record.id, 0)
            # 计算剩余天数和状态（与 BadgeView 的 60 天规则保持一致）
            computed_status, days_left = _compute_license_status_fields(record)
            item['days_left'] = days_left
            item['computed_status'] = computed_status
            data.append(item)

        return json_response({
            'records': data,
            'total': total_count,
            'page': page,
            'page_size': page_size,
        })

    @auth('radio_license.license.add|radio_license.license.edit')
    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('station_name', required=False),
            Argument('purpose', required=False),
            Argument('valid_from', required=False),
            Argument('valid_to', required=False),
            Argument('responsible_user_id', type=int, required=False),
            Argument('responsible_user_name', required=False),
            Argument('remark', required=False),
            Argument('frequencies', type=list, required=False, help='频率列表'),
        ).parse(request.body)

        if error is None:
            # 责任人账号存在性/租户一致性校验 + 姓名回填
            user_err = _validate_and_fill_responsible_user(form, request.user)
            if user_err:
                return json_response(error=user_err)

            # 日期校验
            if form.valid_from and form.valid_to and form.valid_from > form.valid_to:
                return json_response(error='起始日期不能晚于截止日期')

            # 客户端未传 frequencies 时 JsonParser 存入 None，统一归一为空列表
            frequencies = form.pop('frequencies', None) or []
            frequency_err = _validate_frequencies(frequencies)
            if frequency_err:
                return json_response(error=frequency_err)

            if form.id:
                # 编辑：只更新传入的非 None 字段
                if not request.user.has_perms({'radio_license.license.edit'}):
                    return json_response(error='权限拒绝：缺少编辑执照权限')
                error = self._handle_edit(form, frequencies, request)
            else:
                # 创建：校验必填字段
                if not request.user.has_perms({'radio_license.license.add'}):
                    return json_response(error='权限拒绝：缺少新增执照权限')
                required = {
                    'station_name': '台站名称', 'purpose': '用途',
                    'valid_from': '起始日期', 'valid_to': '截止日期',
                    'responsible_user_id': '责任人',
                }
                for field, label in required.items():
                    if not form.get(field):
                        return json_response(error=f'请输入{label}')
                error = self._handle_create(form, frequencies, request)
        return json_response(error=error)

    def _handle_create(self, form, frequencies, request):
        """新增模式：创建执照 + 频率明细 + 即时扫描"""
        from django.db import transaction
        user = request.user
        form.created_by = user
        form.pop('remark', None)
        assign_tenant_id(form, user)
        create_data = {k: v for k, v in form.items() if v is not None}

        # 幂等性检查：防止双击重复提交
        if check_recent_duplicate(RadioLicense, {
            'tenant_id': user.tenant_id,
            'station_name': form.get('station_name'),
            'purpose': form.get('purpose'),
        }):
            return '提交过于频繁，请勿重复提交'

        with transaction.atomic():
            license_obj = RadioLicense.objects.create(**create_data)
            _create_frequencies(license_obj, frequencies, user)
            scan_single_license(license_obj)
            record_audit_event(
                request, 'create', 'radio_license',
                target_id=license_obj.id, target_name=license_obj.station_name,
                detail={'purpose': license_obj.purpose,
                        'valid_from': str(license_obj.valid_from),
                        'valid_to': str(license_obj.valid_to)},
            )
        return None

    def _handle_edit(self, form, frequencies, request):
        """编辑模式：版本快照 + 状态流转 + 续期/更新证据事件"""
        from django.db import transaction
        user = request.user
        qs = apply_tenant_filter(RadioLicense.objects.all(), user)
        old_license = qs.filter(pk=form.id).first()
        if not old_license:
            return '编辑失败：记录不存在或无权限编辑'

        # 编辑只传单个日期时，也要按合并后的完整日期范围校验。
        new_valid_from = form.valid_from or str(old_license.valid_from)
        new_valid_to = form.valid_to or str(old_license.valid_to)
        if new_valid_from > new_valid_to:
            return '起始日期不能晚于截止日期'

        form.updated_at = timezone.now()
        form.updated_by = user
        record_id = form.pop('id')
        form.pop('remark', None)
        update_data = {k: v for k, v in form.items() if v is not None}

        with transaction.atomic():
            # 行锁序列化同一执照的并发编辑：两个并发请求不会同时读到
            # 相同的最大版本号，保证 version_no 按单张执照严格递增不重复。
            # 锁定后重新读取，快照基于最新的"修改前"状态。
            try:
                locked_license = qs.select_for_update().get(pk=record_id)
            except RadioLicense.DoesNotExist:
                return '编辑失败：记录不存在或无权限编辑'
            # 证据闭环第三阶段：保存版本历史（修改前快照）
            # 变更字段基于锁定后的修改前状态与表单对比得出，
            # 同一份结果写入版本记录 changed_fields 和证据事件
            changed_fields = _detect_license_changed_fields(locked_license, form)
            _save_license_version_snapshot(
                locked_license, user, changed_fields=changed_fields)
            old_valid_to = locked_license.valid_to
            updated_count = qs.filter(pk=record_id).update(**update_data)
            if updated_count == 0:
                return '编辑失败：记录不存在或无权限编辑'
            _update_frequencies(record_id, frequencies, user)
            license_obj = RadioLicense.objects.get(pk=record_id)
            scan_single_license(license_obj)
            _record_license_edit_evidence(license_obj, old_valid_to, changed_fields, user)
            record_audit_event(
                # AuditLog 动作约束只允许 update（无 edit），用错值会被约束拒绝导致审计丢失
                request, 'update', 'radio_license',
                target_id=license_obj.id, target_name=license_obj.station_name,
                detail={'purpose': license_obj.purpose,
                        'valid_from': str(license_obj.valid_from),
                        'valid_to': str(license_obj.valid_to)},
            )
        return None

    @auth('radio_license.license.del')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)
        if error is None:
            qs = apply_tenant_filter(RadioLicense.objects.all(), request.user)
            license_obj = qs.filter(pk=form.id).first()
            if not license_obj:
                error = '删除失败：记录不存在或无权限删除'
            else:
                from django.db import transaction
                with transaction.atomic():
                    # 联动软删除通用附件表中的附件记录
                    AttachmentService.soft_delete_by_object(
                        request.user, 'radio_license', 'license', form.id,
                        reason=f'执照删除 ID={form.id}', delete_file=True,
                    )
                    # 写入删除审计日志（在物理删除前调用，license_obj 字段仍可读取）
                    record_audit_event(
                        request, 'delete', 'radio_license',
                        target_id=license_obj.id, target_name=license_obj.station_name,
                        detail={'purpose': license_obj.purpose,
                                'valid_from': str(license_obj.valid_from),
                                'valid_to': str(license_obj.valid_to)},
                    )
                    # 物理删除执照（CASCADE 自动级联删除频率/提醒确认记录）
                    license_obj.delete()
        return json_response(error=error)


class RadioLicenseDetailView(View):
    """执照详情"""

    @auth('radio_license.license.view')
    def get(self, request, pk):
        qs = apply_tenant_filter(RadioLicense.objects.all(), request.user)
        try:
            record = qs.get(pk=pk)
        except RadioLicense.DoesNotExist:
            return json_response(error='记录不存在或无权限访问')

        item = record.to_view()
        # 附加频率列表
        freqs = RadioLicenseFrequency.objects.filter(license=record).order_by('sort_order', 'id')
        item['frequencies'] = [f.to_view() for f in freqs]
        # 计算剩余天数和状态（与 BadgeView 的 60 天规则保持一致）
        computed_status, days_left = _compute_license_status_fields(record)
        item['days_left'] = days_left
        item['computed_status'] = computed_status
        # 附件数量（从通用附件表统计）
        item['attachment_count'] = AttachmentService.count(
            request.user, 'radio_license', 'license', record.id)
        return json_response(item)


def _create_frequencies(license_obj, frequencies, user):
    """创建频率明细"""
    for idx, freq_data in enumerate(frequencies):
        RadioLicenseFrequency.objects.create(
            tenant_id=license_obj.tenant_id,
            license=license_obj,
            frequency_value=freq_data.get('frequency_value', 0),
            frequency_unit=freq_data.get('frequency_unit', 'MHz'),
            frequency_text=freq_data.get('frequency_text', ''),
            remark=freq_data.get('remark', ''),
            sort_order=freq_data.get('sort_order', idx),
            created_by=user,
        )


def _update_frequencies(license_id, frequencies, user):
    """更新频率明细：先删后建"""
    license_obj = RadioLicense.objects.get(pk=license_id)
    RadioLicenseFrequency.objects.filter(license_id=license_id).delete()
    _create_frequencies(license_obj, frequencies, user)


def _save_license_version_snapshot(license_obj, user, changed_fields=None):
    """证据闭环第三阶段：保存执照修改前版本快照

    每次编辑核心字段前，将修改前的完整字段保存为版本历史。
    version_no 按 license 递增；snapshot_hash 用于证明快照未被篡改。

    Args:
        changed_fields: 本次编辑实际变更的字段名列表（按 license 编辑顺序传入），
            以逗号分隔写入 changed_fields 字段；None/空列表写空串。
    """
    from apps.radio_license.models import RadioLicenseVersion
    import hashlib as _hashlib

    # 计算当前最大版本号
    last_version = RadioLicenseVersion.objects.filter(
        license=license_obj
    ).order_by('-version_no').first()
    next_version_no = (last_version.version_no + 1) if last_version else 1

    # 构建修改前完整快照
    snapshot = {
        'id': license_obj.id,
        'station_name': license_obj.station_name,
        'purpose': license_obj.purpose,
        'valid_from': str(license_obj.valid_from),
        'valid_to': str(license_obj.valid_to),
        'responsible_user_id': license_obj.responsible_user_id,
        'responsible_user_name': license_obj.responsible_user_name,
        'status': license_obj.status,
        'last_remind_at': license_obj.last_remind_at,
        'created_at': license_obj.created_at,
        'updated_at': license_obj.updated_at,
    }
    # created_at/updated_at/last_remind_at 是 datetime，必须用 DateTimeEncoder 序列化
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, cls=DateTimeEncoder)
    snapshot_hash = _hashlib.sha256(snapshot_json.encode('utf-8')).hexdigest()

    RadioLicenseVersion.objects.create(
        tenant_id=license_obj.tenant_id,
        license=license_obj,
        version_no=next_version_no,
        snapshot_json=snapshot_json,
        changed_fields=','.join(changed_fields) if changed_fields else '',
        changed_by_id=getattr(user, 'id', None),
        changed_by_name=user.nickname or user.username,
        changed_at=timezone.now(),
        snapshot_hash=snapshot_hash,
    )


# ==================== 证据闭环第三阶段：证据包导出 ====================

def _build_license_snapshot(license_obj):
    """构建执照业务快照（用于证据事件 + 证据包）"""
    from apps.radio_license.models import RadioLicenseVersion
    freqs = RadioLicenseFrequency.objects.filter(license=license_obj).order_by('sort_order', 'id')
    versions = RadioLicenseVersion.objects.filter(license=license_obj).order_by('-version_no', '-id')
    # 附件列表（含软删除的，便于审计）从通用附件表查询
    attachments = EvidenceAttachment.objects.filter(
        tenant_id=license_obj.tenant_id,
        module='radio_license', object_type='license', object_id=str(license_obj.id),
    ).order_by('-uploaded_at')
    acks = LicenseReminderAck.objects.filter(license=license_obj).order_by('-created_at')
    return {
        'license': {
            'id': license_obj.id,
            'station_name': license_obj.station_name,
            'purpose': license_obj.purpose,
            'valid_from': str(license_obj.valid_from),
            'valid_to': str(license_obj.valid_to),
            'responsible_user_id': license_obj.responsible_user_id,
            'responsible_user_name': license_obj.responsible_user_name,
            'status': license_obj.status,
            'last_remind_at': license_obj.last_remind_at,
            'created_at': license_obj.created_at,
            'created_by_id': license_obj.created_by_id,
            'updated_at': license_obj.updated_at,
            'updated_by_id': license_obj.updated_by_id,
        },
        'frequencies': [
            {
                'id': f.id, 'frequency_value': str(f.frequency_value),
                'frequency_unit': f.frequency_unit, 'frequency_text': f.frequency_text,
                'remark': f.remark, 'sort_order': f.sort_order,
            }
            for f in freqs
        ],
        'versions': [
            {
                'id': v.id, 'version_no': v.version_no,
                'snapshot_hash': v.snapshot_hash,
                'changed_fields': v.changed_fields,
                'change_reason': v.change_reason,
                'changed_by_id': v.changed_by_id,
                'changed_by_name': v.changed_by_name,
                'changed_at': v.changed_at,
            }
            for v in versions
        ],
        'attachments': [
            {
                'id': a.id, 'file_name': a.file_name, 'file_path': a.file_path,
                'file_size': a.file_size, 'file_ext': a.file_ext,
                'file_hash_sha256': a.file_hash_sha256,
                'is_deleted': a.is_deleted,
                'uploaded_by_id': a.uploaded_by_id,
                'uploaded_by_name': a.uploaded_by_name,
                'uploaded_at': a.uploaded_at,
                'deleted_at': a.deleted_at,
                'delete_reason': a.delete_reason,
            }
            for a in attachments
        ],
        'reminder_acks': [
            {
                'id': a.id, 'user_id': a.user_id, 'user_name': a.user_name,
                'ack_valid_to': str(a.ack_valid_to), 'created_at': a.created_at,
            }
            for a in acks
        ],
    }


class RadioLicenseEvidencePackageView(View):
    """执照证据包导出 - 包含业务快照/版本历史/证据事件/审计日志/附件哈希清单"""

    @auth('radio_license.license.view')
    def get(self, request):
        import zipfile
        from io import BytesIO
        from apps.evidence.models import EvidenceEvent
        from apps.logs.models import AuditLog

        license_id = request.GET.get('id')
        if not license_id:
            return json_response(error='缺少 id 参数')

        license_obj = apply_tenant_filter(
            RadioLicense.objects.all(), request.user
        ).filter(pk=license_id).first()
        if not license_obj:
            return json_response(error='执照不存在或无权限')

        tenant_id = getattr(request.user, 'tenant_id', 'default')
        snapshot = _build_license_snapshot(license_obj)

        events = list(EvidenceEvent.objects.filter(
            tenant_id=tenant_id, module='radio_license',
            object_type='license', object_id=str(license_obj.id),
        ).order_by('id'))
        events_data = [e.to_dict() for e in events]

        audit_logs = list(AuditLog.objects.filter(
            tenant_id=tenant_id, target_type='radio_license',
            target_id=str(license_obj.id),
        ).order_by('id'))
        if not audit_logs:
            audit_logs = list(AuditLog.objects.filter(
                tenant_id=tenant_id, target_type='radio_license',
            ).order_by('id'))
        audit_data = [l.to_dict() for l in audit_logs]

        # 附件哈希清单（仅未删除）
        atts = [a for a in snapshot['attachments'] if not a['is_deleted']]
        att_hashes = [
            {
                'file_name': a['file_name'], 'file_path': a['file_path'],
                'sha256': a['file_hash_sha256'], 'size': a['file_size'],
            }
            for a in atts
        ]

        buf = BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            # 快照/事件/审计/哈希中含 datetime 字段，统一用 DateTimeEncoder 序列化
            zf.writestr('object_snapshot.json', json.dumps(snapshot, ensure_ascii=False, indent=2, cls=DateTimeEncoder))
            zf.writestr('evidence_events.json', json.dumps(events_data, ensure_ascii=False, indent=2, cls=DateTimeEncoder))
            zf.writestr('audit_logs.json', json.dumps(audit_data, ensure_ascii=False, indent=2, cls=DateTimeEncoder))
            zf.writestr('hashes.json', json.dumps({
                'module': 'radio_license', 'object_id': license_obj.id,
                'station_name': license_obj.station_name,
                'valid_to': str(license_obj.valid_to),
                'attachments': att_hashes,
                'events_count': len(events_data),
                'versions_count': len(snapshot['versions']),
                'generated_at': timezone.now(),
            }, ensure_ascii=False, indent=2, cls=DateTimeEncoder))
            zf.writestr('verify.txt',
                        '本证据包包含执照业务快照JSON、证据事件JSON、审计日志JSON、版本历史、附件哈希清单。\n'
                        '校验方式：重新计算 object_snapshot.json 的 SHA256；附件 sha256 可重新计算文件哈希比对。\n'
                        '证据事件哈希链可通过 evidence_events.json 中的 prev_hash/event_hash 校验连续性。\n')

        buf.seek(0)
        # FileResponse 必须传文件对象；传 bytes 会被按整数迭代导致内容损坏
        resp = FileResponse(buf, content_type='application/zip')
        resp['Content-Disposition'] = f'attachment; filename="evidence_radio_license_{license_obj.id}.zip"'
        return resp


# ==================== 附件接口（转调 evidence.AttachmentService）====================

# radio_license 模块附件配置
RadioLicenseAttachmentConfig = AttachmentConfig(
    allowed_extensions=('.pdf', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp',
                         '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
                         '.zip', '.rar', '.7z'),
    max_size_mb=50,
)

# 业务对象标识
ATTACHMENT_MODULE = 'radio_license'
ATTACHMENT_OBJECT_TYPE = 'license'

# 附件归属校验统一错误（不泄露附件真实所属模块/对象/租户）
ATTACHMENT_FORBIDDEN_ERROR = '附件不存在或无权限访问'


def _get_license_attachment_for_user(user, attachment_id):
    """执照附件专用归属校验（F-01/F-02/F-03 修复）。

    处理执照附件前必须同时满足：
    1. 附件存在且未软删除（默认 Manager 自动过滤 is_deleted=True）；
    2. module == 'radio_license'；
    3. object_type == 'license'；
    4. object_id 对应的 RadioLicense 存在；
    5. 父执照属于当前用户可访问的租户范围（apply_tenant_filter，超管放行）。

    任一不满足统一返回 ATTACHMENT_FORBIDDEN_ERROR。
    权限由各端点的 @auth 装饰器独立校验。

    Returns:
        (attachment, error)
    """
    att = EvidenceAttachment.objects.filter(pk=attachment_id).first()
    if not att:
        return None, ATTACHMENT_FORBIDDEN_ERROR
    if att.module != ATTACHMENT_MODULE or att.object_type != ATTACHMENT_OBJECT_TYPE:
        return None, ATTACHMENT_FORBIDDEN_ERROR
    try:
        license_exists = apply_tenant_filter(
            RadioLicense.objects.all(), user,
        ).filter(pk=att.object_id).exists()
    except (ValueError, TypeError):
        return None, ATTACHMENT_FORBIDDEN_ERROR
    if not license_exists:
        return None, ATTACHMENT_FORBIDDEN_ERROR
    return att, None


class AttachmentListView(View):
    """附件列表 / 上传"""

    @auth('radio_license.license.view')
    def get(self, request, pk):
        """获取指定执照的附件列表"""
        qs = apply_tenant_filter(RadioLicense.objects.all(), request.user)
        if not qs.filter(pk=pk).exists():
            return json_response(error='执照不存在或无权限访问')
        data = AttachmentService.list(
            request.user, ATTACHMENT_MODULE, ATTACHMENT_OBJECT_TYPE, pk)
        return json_response(data)

    @auth('radio_license.attachment.upload')
    def post(self, request, pk):
        """上传附件"""
        qs = apply_tenant_filter(RadioLicense.objects.all(), request.user)
        license_obj = qs.filter(pk=pk).first()
        if not license_obj:
            return json_response(error='执照不存在或无权限访问')

        file = request.FILES.get('file')
        if not file:
            return json_response(error='请选择要上传的文件')

        att, error = AttachmentService.upload(
            file=file,
            user=request.user,
            module=ATTACHMENT_MODULE,
            object_type=ATTACHMENT_OBJECT_TYPE,
            object_id=pk,
            config=RadioLicenseAttachmentConfig,
        )
        if error:
            return json_response(error=error)

        result = att.to_view()
        result['uploaded_by_name'] = request.user.nickname
        result['created_at'] = att.uploaded_at
        result['previewable'] = att.file_ext in PREVIEWABLE_EXTENSIONS
        return json_response(result)


class AttachmentDownloadView(View):
    """附件下载（鉴权），支持 ?inline=1 内联预览图片/PDF"""

    @auth('radio_license.attachment.download')
    def get(self, request, pk):
        # F-01 修复：下载前必须通过执照附件专用归属校验，
        # inline 与普通下载共用同一校验路径，跨模块/跨租户附件一律拒绝
        att, err = _get_license_attachment_for_user(request.user, pk)
        if err:
            return json_response(error=err)
        inline = request.GET.get('inline') in ('1', 'true', 'True')
        response, error = AttachmentService.download_response(request.user, pk, inline=inline)
        if error:
            return json_response(error=error)
        return response


class AttachmentPreviewUrlView(View):
    """获取 kkFileView 在线预览地址"""

    @auth('radio_license.license.view')
    def get(self, request, pk):
        # F-03 修复：签发预览令牌前必须通过执照附件专用归属校验，
        # 不得为其他模块/其他租户附件生成执照预览地址
        att, err = _get_license_attachment_for_user(request.user, pk)
        if err:
            return json_response(error=err)
        preview_file_api_path = f'/api/radio-license/attachments/{pk}/preview-file/'
        data, error = AttachmentService.get_preview_url(
            request.user, pk, preview_file_api_path)
        if error:
            return json_response(error=error)
        return json_response(data)


class AttachmentPreviewFileView(View):
    """kkFileView 回调读取文件流（preview_token 鉴权）"""

    def get(self, request, pk):
        preview_token = request.GET.get('preview_token')
        if not preview_token:
            return json_response(error='缺少 preview_token 参数')
        response, error = AttachmentService.preview_file_response(preview_token, pk)
        if error:
            return json_response(error=error)
        return response


class AttachmentDeleteView(View):
    """附件删除（软删除）"""

    @auth('radio_license.attachment.delete')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定附件ID'),
            Argument('delete_reason', required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)

        # F-02 修复：删除前必须通过执照附件专用归属校验，
        # 跨模块（合同/批复/协作任务等）和跨租户附件一律拒绝
        att, err = _get_license_attachment_for_user(request.user, form.id)
        if err:
            return json_response(error=err)

        # F-04 修复：软删除前保存删除前快照。
        # 软删除后默认 Manager 会过滤 is_deleted=True，旧实现在删除后再查询
        # 必然得到 None，导致证据事件永远不写入（死代码）。
        delete_reason = form.delete_reason or ''
        snapshot = {
            'attachment_id': att.id,
            'file_name': att.file_name,
            'file_hash_sha256': att.file_hash_sha256,
            'module': att.module,
            'object_type': att.object_type,
            'object_id': att.object_id,
            'tenant_id': att.tenant_id,
            'delete_reason': delete_reason,
        }

        error = AttachmentService.soft_delete(
            request.user, form.id, delete_reason, delete_file=True)
        if error:
            return json_response(error=error)

        # 使用删除前快照写入证据事件（EvidenceEvent：证据链事件；
        # 全局 AuditLog 由既有业务逻辑独立记录，此处不重复制造）。
        # 写入失败不回滚已完成的业务删除，仅记录错误日志。
        try:
            from apps.evidence.services import record_evidence_event
            record_evidence_event(
                tenant_id=snapshot['tenant_id'],
                module=ATTACHMENT_MODULE,
                object_type=ATTACHMENT_OBJECT_TYPE,
                object_id=snapshot['object_id'],
                event_type='delete',
                actor_user_id=getattr(request.user, 'id', None),
                actor_username=getattr(request.user, 'username', ''),
                actor_name=request.user.nickname or request.user.username,
                object_snapshot=snapshot,
                event_title=f'删除附件 {snapshot["file_name"]}',
            )
        except Exception as ev_err:
            logger.error(f'附件删除证据事件写入失败: {ev_err}')

        return json_response()


# ==================== 到期提醒接口 ====================


class ReminderPopupView(View):
    """弹窗提醒查询接口（执照中心模型）

    实时查询当前用户负责的 expiring/expired 执照，排除已 ack 的。
    days_left 实时计算，content 前端拼装，不依赖预生成数据。

    返回格式与旧 reminder 兼容（前端 ReminderNotification.js 无需大改）：
        records: [{
            license_id, station_name, valid_to, days_left, status, ...
        }]
    """

    @auth('radio_license.license.view')
    def get(self, request):
        from datetime import date, timedelta
        today = date.today()
        # 查询当前用户负责的、即将到期或已过期的执照
        qs = apply_tenant_filter(RadioLicense.objects.all(), request.user)
        licenses = qs.filter(
            responsible_user_id=request.user.id,
            valid_to__lte=today + timedelta(days=EXPIRING_DAYS_THRESHOLD),
        ).select_related('created_by')

        # 查询该用户所有 ack，构造 (license_id, ack_valid_to) 集合用于排除
        acks = LicenseReminderAck.objects.filter(
            user_id=request.user.id,
        ).values_list('license_id', 'ack_valid_to')
        ack_set = {(lid, vid) for lid, vid in acks}

        records = []
        for lic in licenses:
            days_left = (lic.valid_to - today).days
            # 排除已 ack 且 ack_valid_to 匹配当前 valid_to 的（续期后自动失效）
            if (lic.id, lic.valid_to) in ack_set:
                continue
            # 实时计算状态（不依赖缓存 status 字段，与 ack/badge 口径一致）
            if days_left < 0:
                computed_status = 'expired'
            else:
                computed_status = 'expiring'
            # 兼容旧 reminder 字段命名，前端无需改
            records.append({
                'license_id': lic.id,
                'station_name': lic.station_name,
                'valid_from': str(lic.valid_from),
                'valid_to': str(lic.valid_to),
                'days_left': days_left,
                'status': computed_status,
                'remind_type': 'expired' if days_left < 0 else 'expiring_daily',
            })
        return json_response({'records': records})


class ReminderAckView(View):
    """提醒确认（已处理）接口（执照中心模型）

    用户点击"已处理"→ 写一条 LicenseReminderAck
    续期后 license.valid_to 变化 → 旧 ack 自动失效 → 重新弹窗

    校验规则（与批复侧 ApprovalReminderAckView 对齐）：
    1. 权限：@auth 要求 radio_license.license.view；
    2. 租户：apply_tenant_filter 过滤，跨租户对象一律"执照不存在或无权限"；
    3. 责任人：仅执照责任人本人可确认；
    4. 状态：按 valid_to 实时计算，必须是 expiring/expired（normal 拒绝）；
    5. ack_valid_to 取数据库当前 valid_to，不信任客户端传值；
    6. 幂等：get_or_create + 唯一约束，同周期重复确认返回成功。
    """

    @auth('radio_license.license.view')
    def post(self, request):
        form, error = JsonParser(
            Argument('license_id', type=int, help='执照ID'),
        ).parse(request.body)

        if error is not None:
            return json_response(error=error)

        # 校验执照存在且属于当前租户
        qs = apply_tenant_filter(RadioLicense.objects.all(), request.user)
        license_obj = qs.filter(pk=form.license_id).first()
        if not license_obj:
            return json_response(error='执照不存在或无权限')

        # 仅责任人本人可确认处理提醒
        if license_obj.responsible_user_id != request.user.id:
            return json_response(error='仅责任人可确认处理提醒')

        # 实时状态必须是 expiring 或 expired（normal 无需确认）
        computed_status, _ = _compute_license_status_fields(license_obj)
        if computed_status == 'normal':
            return json_response(error='当前执照状态正常，无需确认处理')

        # 写入 ack：ack_valid_to 取数据库当前 valid_to（不信任客户端）；
        # get_or_create + 唯一约束保证同周期重复确认幂等
        from django.db import transaction
        try:
            with transaction.atomic():
                _, created = LicenseReminderAck.objects.get_or_create(
                    tenant_id=license_obj.tenant_id,
                    license=license_obj,
                    user_id=request.user.id,
                    ack_valid_to=license_obj.valid_to,
                    defaults={
                        'user_name': request.user.nickname or request.user.username,
                    },
                )
        except Exception as e:
            logger.error(f'[RadioLicense] ack 写入失败: {e}')
            return json_response(error='确认处理失败，请稍后重试')

        if created:
            logger.info(f'[RadioLicense] 用户 {request.user.id} 确认处理执照 {form.license_id} '
                        f'(valid_to={license_obj.valid_to})')
        else:
            logger.debug(f'[RadioLicense] 执照 {form.license_id} 本周期已确认，跳过')

        return json_response(data={'license_id': form.license_id, 'acked': True})


# ==================== 菜单红点接口 ====================

class ResponsibleUserListView(View):
    """可选责任人列表（轻量接口）

    为前端执照表单提供可选用户下拉。复用 radio_license.license.view 权限，
    不要求用户具备 system.account.view，避免给非管理员开账户管理权限。

    租户隔离：非超管只返回本租户激活用户；超管返回全量激活用户。

    Returns:
        list: [{id, nickname, username}, ...]
    """

    @auth('radio_license.license.view')
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


class RadioLicenseBadgeView(View):
    """菜单红点统计。

    只统计当前用户负责且当前周期未 ack 的记录（与批复红点口径一致）；
    使用 Exists + OuterRef 排除当前周期 ack，避免将全部 ack 加载到 Python。
    实时计算（按 valid_to 与 today 差值），不依赖 status 缓存字段。

    鉴权：复用 radio_license.license.view（查看权限才能看到红点）。
    """

    @auth('radio_license.license.view')
    def get(self, request):
        from datetime import date
        from django.db.models import Exists, OuterRef
        qs = apply_tenant_filter(RadioLicense.objects.all(), request.user)
        qs = qs.filter(responsible_user_id=request.user.id)

        # 当前周期 ack：license_id + user_id + ack_valid_to == license.valid_to
        acked_exists = LicenseReminderAck.objects.filter(
            tenant_id=getattr(request.user, 'tenant_id', ''),
            license_id=OuterRef('pk'),
            user_id=request.user.id,
            ack_valid_to=OuterRef('valid_to'),
        )
        qs = qs.filter(~Exists(acked_exists))

        today = date.today()
        # 即将到期：到期前 60 天内且未过期；已过期：valid_to < today
        expiring_count = qs.filter(
            valid_to__gte=today,
            valid_to__lte=today + timedelta(days=60),
        ).count()
        expired_count = qs.filter(valid_to__lt=today).count()
        return json_response(data={
            'count': expiring_count + expired_count,  # 红点总数
            'expiring_count': expiring_count,        # 即将到期
            'expired_count': expired_count,          # 已过期
        })
