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


def _validate_and_fill_responsible_user(form):
    """校验责任人账号存在性并回填真实姓名

    Returns: 错误消息字符串；None 表示通过
    """
    from apps.account.models import User as UserModel
    if not UserModel.objects.filter(
        pk=form.responsible_user_id, is_active=True
    ).exists():
        return '责任人不存在或已禁用，请重新选择'
    user = UserModel.objects.get(pk=form.responsible_user_id)
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
            records = records.filter(status=status)
        if valid_to_start:
            records = records.filter(valid_to__gte=valid_to_start)
        if valid_to_end:
            records = records.filter(valid_to__lte=valid_to_end)

        # 分页
        page = int(request.GET.get('page', 1))
        page_size = min(int(request.GET.get('page_size', 20)), 100)

        records = records.select_related('created_by', 'updated_by')
        total_count = records.count()
        offset = (page - 1) * page_size
        records = records[offset:offset + page_size]

        # 构造返回数据，附带频率信息和计算字段
        data = []
        for record in records:
            item = record.to_view()
            # 附加频率列表
            freqs = RadioLicenseFrequency.objects.filter(license=record).order_by('sort_order', 'id')
            item['frequencies'] = [f.to_view() for f in freqs]
            # 附件数量（从通用附件表统计）
            item['attachment_count'] = AttachmentService.count(
                request.user, 'radio_license', 'license', record.id)
            # 计算剩余天数和状态（与 BadgeView 的 60 天规则保持一致）
            today = timezone.now().date()
            days_left = (record.valid_to - today).days
            if days_left < 0:
                computed_status = 'expired'
            elif days_left <= EXPIRING_DAYS_THRESHOLD:
                computed_status = 'expiring'
            else:
                computed_status = 'normal'
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
            # 责任人账号存在性校验 + 姓名回填
            user_err = _validate_and_fill_responsible_user(form)
            if user_err:
                return json_response(error=user_err)

            # 日期校验
            if form.valid_from and form.valid_to and form.valid_from > form.valid_to:
                return json_response(error='起始日期不能晚于截止日期')

            frequencies = form.pop('frequencies', []) if hasattr(form, 'frequencies') else []
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

        old_valid_to = old_license.valid_to
        form.updated_at = timezone.now()
        form.updated_by = user
        record_id = form.pop('id')
        form.pop('remark', None)
        update_data = {k: v for k, v in form.items() if v is not None}

        with transaction.atomic():
            # 证据闭环第三阶段：保存版本历史（修改前快照）
            _save_license_version_snapshot(old_license, user)
            updated_count = qs.filter(pk=record_id).update(**update_data)
            if updated_count == 0:
                return '编辑失败：记录不存在或无权限编辑'
            _update_frequencies(record_id, frequencies, user)
            license_obj = RadioLicense.objects.get(pk=record_id)
            scan_single_license(license_obj)
            _record_license_edit_evidence(license_obj, old_valid_to, _detect_license_changed_fields(old_license, form), user)
            record_audit_event(
                request, 'edit', 'radio_license',
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
        today = timezone.now().date()
        days_left = (record.valid_to - today).days
        if days_left < 0:
            computed_status = 'expired'
        elif days_left <= EXPIRING_DAYS_THRESHOLD:
            computed_status = 'expiring'
        else:
            computed_status = 'normal'
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


def _save_license_version_snapshot(license_obj, user):
    """证据闭环第三阶段：保存执照修改前版本快照

    每次编辑核心字段前，将修改前的完整字段保存为版本历史。
    version_no 按 license 递增；snapshot_hash 用于证明快照未被篡改。
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
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    snapshot_hash = _hashlib.sha256(snapshot_json.encode('utf-8')).hexdigest()

    RadioLicenseVersion.objects.create(
        tenant_id=license_obj.tenant_id,
        license=license_obj,
        version_no=next_version_no,
        snapshot_json=snapshot_json,
        changed_fields='',
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
            zf.writestr('object_snapshot.json', json.dumps(snapshot, ensure_ascii=False, indent=2))
            zf.writestr('evidence_events.json', json.dumps(events_data, ensure_ascii=False, indent=2))
            zf.writestr('audit_logs.json', json.dumps(audit_data, ensure_ascii=False, indent=2))
            zf.writestr('hashes.json', json.dumps({
                'module': 'radio_license', 'object_id': license_obj.id,
                'station_name': license_obj.station_name,
                'valid_to': str(license_obj.valid_to),
                'attachments': att_hashes,
                'events_count': len(events_data),
                'versions_count': len(snapshot['versions']),
                'generated_at': timezone.now(),
            }, ensure_ascii=False, indent=2))
            zf.writestr('verify.txt',
                        '本证据包包含执照业务快照JSON、证据事件JSON、审计日志JSON、版本历史、附件哈希清单。\n'
                        '校验方式：重新计算 object_snapshot.json 的 SHA256；附件 sha256 可重新计算文件哈希比对。\n'
                        '证据事件哈希链可通过 evidence_events.json 中的 prev_hash/event_hash 校验连续性。\n')

        buf.seek(0)
        resp = FileResponse(buf.getvalue(), content_type='application/zip')
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
        inline = request.GET.get('inline') in ('1', 'true', 'True')
        response, error = AttachmentService.download_response(request.user, pk, inline=inline)
        if error:
            return json_response(error=error)
        return response


class AttachmentPreviewUrlView(View):
    """获取 kkFileView 在线预览地址"""

    @auth('radio_license.license.view')
    def get(self, request, pk):
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

        error = AttachmentService.soft_delete(
            request.user, form.id, form.delete_reason, delete_file=True)
        if error:
            return json_response(error=error)

        # 写入证据事件
        try:
            from apps.evidence.services import record_evidence_event
            att = EvidenceAttachment.objects.filter(pk=form.id).first()
            if att:
                record_evidence_event(
                    tenant_id=att.tenant_id,
                    module='radio_license',
                    object_type='license',
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
                    event_title=f'删除附件 {att.file_name}',
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
            # 兼容旧 reminder 字段命名，前端无需改
            records.append({
                'license_id': lic.id,
                'station_name': lic.station_name,
                'valid_from': str(lic.valid_from),
                'valid_to': str(lic.valid_to),
                'days_left': days_left,
                'status': lic.status,
                'remind_type': 'expired' if days_left < 0 else 'expiring_daily',
            })
        return json_response({'records': records})


class ReminderAckView(View):
    """提醒确认（已处理）接口（执照中心模型）

    用户点击"已处理"→ 写一条 LicenseReminderAck
    续期后 license.valid_to 变化 → 旧 ack 自动失效 → 重新弹窗
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

        # 写入 ack（唯一约束会自动去重同周期重复确认）
        from django.db import IntegrityError, transaction
        try:
            LicenseReminderAck.objects.create(
                tenant_id=license_obj.tenant_id,
                license=license_obj,
                user_id=request.user.id,
                user_name=request.user.nickname or request.user.username,
                ack_valid_to=license_obj.valid_to,
            )
            logger.info(f'[RadioLicense] 用户 {request.user.id} 确认处理执照 {form.license_id} '
                        f'(valid_to={license_obj.valid_to})')
        except IntegrityError:
            # 同周期已确认过，幂等返回成功
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
    """菜单红点统计

    返回本租户下"即将到期 + 已过期"执照的数量，用于左侧菜单红点提示。
    实时计算（按 valid_to 与 today 差值），不依赖 status 缓存字段。

    鉴权：复用 radio_license.license.view（查看权限才能看到红点）。
    """

    @auth('radio_license.license.view')
    def get(self, request):
        from datetime import date, timedelta
        qs = apply_tenant_filter(RadioLicense.objects.all(), request.user)
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
