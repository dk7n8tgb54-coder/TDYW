# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""值班巡检服务（今日巡检改造）。

业务规则（与模型 docstring 一致）：
- 巡检单唯一范围 = 值班日 + 巡检模板，值班人员登记在单上（支持多人+姓名快照）；
- 每个值班日固定四轮（r1 11:00-11:20 / r2 16:00-16:20 / r3 22:00-22:20 / r4 次日 6:30-6:50，
  第四轮归属前一值班日）；不记录实际填写时间、不判断迟填；
- 模板结构 = 模板 → 设备名称 → 检查内容，设备名称不关联 LifecycleSystem；
- 巡检明细保存全量快照，模板修改/停用不影响历史记录；
- 结果由后端按填写值派生（choice 填"不正常"→ abnormal），不由前端决定；
- 异常明细转故障时才由用户选择系统（视图层实现，见 fault_views）。

安全规则：
- 后端不信任前端传来的单据状态与系统信息，转换前重新查询校验；
- 所有查询经租户过滤（apply_tenant_filter / TenantModelManager）。
"""
import json
from datetime import datetime
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.account.models import User
from libs.tenant_utils import apply_tenant_filter

from apps.equipment_lifecycle.models import (
    InspectionDutyPerson,
    InspectionDutySheet,
    InspectionRecord,
    InspectionTemplate,
    InspectionTemplateDevice,
    InspectionTemplateItem,
    SystemFault,
    INSPECTION_CHOICE_ABNORMAL,
    INSPECTION_DEFAULT_CHOICES,
    INSPECTION_INPUT_TYPE_CHOICE,
    INSPECTION_INPUT_TYPE_TEXT,
    INSPECTION_INPUT_TYPE_VALUES,
    INSPECTION_RESULT_ABNORMAL,
    INSPECTION_RESULT_NORMAL,
    INSPECTION_RESULT_VALUES,
    INSPECTION_ROUND_TEXT_MAP,
    INSPECTION_ROUND_VALUES,
    INSPECTION_SHEET_DRAFT,
    INSPECTION_SHEET_EDITABLE_STATUSES,
    INSPECTION_SHEET_NO_PREFIX,
    INSPECTION_SHEET_RETURNED,
    INSPECTION_SHEET_SUBMITTED,
    INSPECTION_SHEET_VOID,
)

AUDIT_TARGET_INSPECTION_SHEET = 'el_inspection_sheet'
AUDIT_TARGET_INSPECTION_TEMPLATE = 'el_inspection_template'

# 巡检单号重试上限（编号由"当日序号"生成，唯一约束兜底并发冲突）
_SHEET_NO_MAX_RETRY = 5


class InspectionValidationError(Exception):
    """巡检业务校验失败（视图层转为 json_response(error=...)）。"""


def parse_duty_date(value):
    """解析值班日（YYYY-MM-DD），缺省为当天（值班日可回选，用于次日 6:30-6:50 轮次）。"""
    if not value:
        return timezone.now().date()
    try:
        return datetime.strptime(str(value).strip(), '%Y-%m-%d').date()
    except ValueError:
        raise InspectionValidationError('值班日格式不正确，应为 YYYY-MM-DD')


def _validate_round(round_no):
    if round_no not in INSPECTION_ROUND_VALUES:
        raise InspectionValidationError('巡检轮次不合法（应为固定四轮之一）')
    return round_no


def _validate_input_type(input_type):
    if input_type not in INSPECTION_INPUT_TYPE_VALUES:
        raise InspectionValidationError('录入类型不合法（应为 choice 或 text）')
    return input_type


def _clean_text(value, limit):
    """可选文本字段规范化（None 视为空串，去首尾空白并限长）。"""
    return (value or '').strip()[:limit]


# ----------------------------------------------------------------------
# 巡检模板（模板 → 设备名称 → 检查内容）
# ----------------------------------------------------------------------

def get_templates_for_user(user, only_active=False):
    qs = apply_tenant_filter(InspectionTemplate.objects.all(), user)
    if only_active:
        qs = qs.filter(is_active=True)
    return qs


def get_template_tree(template, only_active=False):
    """模板完整树（设备 → 检查内容），供模板管理与巡检工作台渲染。"""
    devices = template.devices.all().order_by('display_order', 'id')
    if only_active:
        devices = devices.filter(is_active=True)
    data = template.to_view()
    data['devices'] = []
    for device in devices:
        device_data = device.to_view()
        items = device.items.all().order_by('display_order', 'id')
        if only_active:
            items = items.filter(is_active=True)
        device_data['items'] = [item.to_view() for item in items]
        data['devices'].append(device_data)
    return data


def create_template(user, body):
    """聚合创建模板：模板 + 设备名称 + 检查内容一次提交。"""
    devices = body.get('devices')
    if not isinstance(devices, list) or not devices:
        raise InspectionValidationError('请至少配置一个设备名称')
    name = (body.get('name') or '').strip()
    if not name:
        raise InspectionValidationError('模板名称不能为空')
    with transaction.atomic():
        template = InspectionTemplate.objects.create(
            tenant_id=user.tenant_id,
            name=name[:100],
            description=(body.get('description') or '').strip()[:500],
            is_active=body.get('is_active', True),
            created_by=user,
        )
        _reconcile_devices(user, template, devices)
    return template


def update_template(user, template_id, body):
    """聚合更新模板：带 id 的设备/检查内容更新，不带 id 的新建，
    载荷中缺失的既有条目删除（历史巡检明细依靠快照，不受影响）。"""
    devices = body.get('devices')
    if devices is not None and (not isinstance(devices, list) or not devices):
        raise InspectionValidationError('请至少配置一个设备名称')
    name = (body.get('name') or '').strip()
    if not name:
        raise InspectionValidationError('模板名称不能为空')
    with transaction.atomic():
        template = apply_tenant_filter(
            InspectionTemplate.objects.select_for_update().all(), user,
        ).filter(pk=template_id).first()
        if not template:
            raise InspectionValidationError('巡检模板不存在')
        template.name = name[:100]
        template.description = (body.get('description') or '').strip()[:500]
        if 'is_active' in body:
            template.is_active = bool(body['is_active'])
        template.updated_at = timezone.now()
        template.updated_by = user
        template.save()
        if devices is not None:
            _reconcile_devices(user, template, devices)
    return template


def _reconcile_devices(user, template, device_specs):
    """按载荷对账设备名称与其检查内容（设备名同模板内唯一）。"""
    if not isinstance(device_specs, list):
        raise InspectionValidationError('设备名称配置不合法')
    existing_devices = {d.id: d for d in template.devices.all()}
    seen_device_ids = set()
    seen_names = set()
    order = 0
    for spec in device_specs:
        if not isinstance(spec, dict):
            raise InspectionValidationError('设备名称配置不合法')
        device_name = (spec.get('device_name') or '').strip()[:100]
        if not device_name:
            raise InspectionValidationError('设备名称不能为空')
        if device_name in seen_names:
            raise InspectionValidationError(f'设备名称「{device_name}」重复')
        seen_names.add(device_name)
        device_id = spec.get('id')
        items = spec.get('items') or []
        if not isinstance(items, list):
            raise InspectionValidationError('检查内容配置不合法')
        if device_id:
            device = existing_devices.get(int(device_id))
            if not device or device.template_id != template.id:
                raise InspectionValidationError('设备名称不存在或不属于当前模板')
            seen_device_ids.add(device.id)
            device.device_name = device_name
            device.is_active = bool(spec.get('is_active', device.is_active))
            device.display_order = order
            device.save()
        else:
            device = InspectionTemplateDevice.objects.create(
                tenant_id=user.tenant_id,
                template=template,
                device_name=device_name,
                display_order=order,
                is_active=bool(spec.get('is_active', True)),
                created_by=user,
            )
        _reconcile_items(user, device, items)
        order += 1
    # 载荷中缺失的既有设备 → 删除（级联删除其检查内容，历史明细快照不受影响）
    for device_id, device in existing_devices.items():
        if device_id not in seen_device_ids:
            device.delete()


def _build_item_fields(spec, order):
    """由载荷构建检查内容字段（名称必填，choices 按录入类型规范化）。"""
    name = _clean_text(spec.get('name'), 200)
    if not name:
        raise InspectionValidationError('检查内容不能为空')
    input_type = _validate_input_type(spec.get('input_type') or INSPECTION_INPUT_TYPE_CHOICE)
    if input_type == INSPECTION_INPUT_TYPE_CHOICE:
        choices = spec.get('choices')
        choices_json = json.dumps(
            choices if isinstance(choices, list) and choices else INSPECTION_DEFAULT_CHOICES,
            ensure_ascii=False)
    else:
        choices_json = ''
    return dict(
        name=name,
        input_type=input_type,
        choices=choices_json,
        is_required=bool(spec.get('is_required', True)),
        display_order=order,
    )


def _reconcile_items(user, device, item_specs):
    """按载荷对账检查内容（键 = 记录 ID；载荷缺失的既有条目删除）。"""
    existing_items = {i.id: i for i in device.items.all()}
    seen_item_ids = set()
    order = 0
    for spec in item_specs:
        if not isinstance(spec, dict):
            raise InspectionValidationError('检查内容配置不合法')
        fields = _build_item_fields(spec, order)
        item_id = spec.get('id')
        if item_id:
            item = existing_items.get(int(item_id))
            if not item or item.device_id != device.id:
                raise InspectionValidationError('检查内容不存在或不属于当前设备名称')
            seen_item_ids.add(item.id)
            for key, value in fields.items():
                setattr(item, key, value)
            item.is_active = bool(spec.get('is_active', item.is_active))
            item.save()
        else:
            InspectionTemplateItem.objects.create(
                tenant_id=user.tenant_id,
                device=device,
                is_active=bool(spec.get('is_active', True)),
                created_by=user,
                **fields,
            )
        order += 1
    for item_id, item in existing_items.items():
        if item_id not in seen_item_ids:
            item.delete()


def toggle_template_active(user, template_id, is_active):
    with transaction.atomic():
        template = apply_tenant_filter(
            InspectionTemplate.objects.select_for_update().all(), user,
        ).filter(pk=template_id).first()
        if not template:
            raise InspectionValidationError('巡检模板不存在')
        template.is_active = bool(is_active)
        template.updated_at = timezone.now()
        template.updated_by = user
        template.save()
    return template


# ----------------------------------------------------------------------
# 值班巡检单（值班日 + 模板 唯一；值班人员多人快照；固定四轮明细）
# ----------------------------------------------------------------------

def _generate_sheet_no(tenant_id):
    """生成租户内当日序号巡检单编号 XJ{yyyymmdd}-{seq:04d}（事务内调用）。"""
    prefix = INSPECTION_SHEET_NO_PREFIX + timezone.now().date().strftime('%Y%m%d') + '-'
    existing = set(InspectionDutySheet.objects.filter(
        tenant_id=tenant_id, sheet_no__startswith=prefix).values_list('sheet_no', flat=True))
    index = len(existing) + 1
    while f'{prefix}{index:04d}' in existing:
        index += 1
    return f'{prefix}{index:04d}'


def get_sheet_for_user(user, sheet_id, for_update=False):
    qs = InspectionDutySheet.objects.select_related('template')
    if for_update:
        qs = qs.select_for_update()
    sheet = apply_tenant_filter(qs, user).filter(pk=sheet_id).first()
    if not sheet:
        raise InspectionValidationError('巡检单不存在')
    return sheet


def _resolve_person_specs(user, person_specs):
    """解析值班人员载荷：优先账号（稳定 ID + 姓名快照），允许手工补录姓名。

    返回 [(user_or_None, person_name)]；按账号/姓名去重（唯一约束兜底）。
    """
    if not isinstance(person_specs, list):
        raise InspectionValidationError('值班人员配置不合法')
    resolved = []
    seen_user_ids = set()
    seen_names = set()
    for spec in person_specs:
        if not isinstance(spec, dict):
            raise InspectionValidationError('值班人员配置不合法')
        person_name = (spec.get('person_name') or spec.get('name') or '').strip()[:100]
        user_id = spec.get('user')
        account = None
        if user_id:
            account = apply_tenant_filter(User.objects.all(), user).filter(
                pk=int(user_id)).first()
            if not account:
                raise InspectionValidationError('值班人员账号不存在或无权限')
            if account.id in seen_user_ids:
                continue
            seen_user_ids.add(account.id)
            if not person_name:
                person_name = (account.nickname or account.username or '').strip()[:100]
        if not person_name:
            raise InspectionValidationError('值班人员姓名不能为空')
        if person_name in seen_names and account is None:
            continue
        seen_names.add(person_name)
        resolved.append((account, person_name))
    return resolved


def _reconcile_persons(user, sheet, person_specs):
    """按载荷对账值班人员（人员名单随单保存姓名快照）。

    允许空名单（草稿可先建单后登记人员）；提交时由 submit_sheet 校验。
    """
    resolved = _resolve_person_specs(user, person_specs or [])
    existing = {p.id: p for p in sheet.persons.all()}
    seen_ids = set()
    rows = []
    for account, person_name in resolved:
        if account is not None:
            person = next(
                (p for p in existing.values() if p.user_id == account.id), None)
        else:
            person = next(
                (p for p in existing.values()
                 if p.user_id is None and p.person_name == person_name), None)
        if person:
            seen_ids.add(person.id)
            if person.person_name != person_name:
                person.person_name = person_name
                person.save()
        else:
            rows.append(InspectionDutyPerson(
                tenant_id=user.tenant_id, sheet=sheet, user=account,
                person_name=person_name))
    if rows:
        InspectionDutyPerson.objects.bulk_create(rows)
    for person_id, person in existing.items():
        if person_id not in seen_ids:
            person.delete()


def create_sheet(user, body):
    """创建值班巡检单（client_token 幂等；同值班日同模板仅一张有效单）。"""
    duty_date = parse_duty_date(body.get('duty_date'))
    template_id = body.get('template_id')
    template = apply_tenant_filter(InspectionTemplate.objects.all(), user).filter(
        pk=template_id).first()
    if not template:
        raise InspectionValidationError('巡检模板不存在')
    if not template.is_active:
        raise InspectionValidationError('巡检模板已停用，不能用于新建巡检单')
    client_token = (body.get('client_token') or '').strip()[:64]
    if client_token:
        # 幂等回放只匹配有效单：已作废单不作为幂等返回值（重试可重新建单）
        existing = apply_tenant_filter(InspectionDutySheet.objects.all(), user).filter(
            client_token=client_token).exclude(status=INSPECTION_SHEET_VOID).order_by('id').first()
        if existing:
            return existing
    _resolve_person_specs(user, body.get('persons') or [])  # 建单即校验人员载荷
    with transaction.atomic():
        conflict = apply_tenant_filter(InspectionDutySheet.objects.all(), user).filter(
            duty_date=duty_date, template=template,
        ).exclude(status=INSPECTION_SHEET_VOID).first()
        if conflict:
            raise InspectionValidationError(
                f'该值班日已存在此模板的巡检单（{conflict.sheet_no}），不能重复建单')
        for _ in range(_SHEET_NO_MAX_RETRY):
            try:
                sheet = InspectionDutySheet.objects.create(
                    tenant_id=user.tenant_id,
                    sheet_no=_generate_sheet_no(user.tenant_id),
                    duty_date=duty_date,
                    template=template,
                    status=INSPECTION_SHEET_DRAFT,
                    uniq_key=f'{duty_date}|{template.id}',
                    client_token=client_token,
                    created_by=user,
                )
                break
            except Exception:
                # 并发下编号或唯一键冲突：重查冲突单，编号冲突则重试
                conflict = apply_tenant_filter(InspectionDutySheet.objects.all(), user).filter(
                    duty_date=duty_date, template=template,
                ).exclude(status=INSPECTION_SHEET_VOID).first()
                if conflict:
                    raise InspectionValidationError(
                        f'该值班日已存在此模板的巡检单（{conflict.sheet_no}），不能重复建单')
                sheet = None
        else:
            raise InspectionValidationError('巡检单创建繁忙，请稍后重试')
        _reconcile_persons(user, sheet, body.get('persons') or [])
    return sheet


def _apply_record_values(record, spec):
    """按载荷应用填写值并派生结果（快照字段不可变）。"""
    input_type = record.input_type_snapshot
    value_text = '' if spec.get('value_text') is None else str(spec.get('value_text'))
    value_number = None
    if input_type == INSPECTION_INPUT_TYPE_TEXT:
        stripped = value_text.strip()
        if stripped:
            try:
                value_number = float(stripped)
            except (TypeError, ValueError):
                value_number = None
    elif input_type == INSPECTION_INPUT_TYPE_CHOICE:
        allowed = record.get_choices() or INSPECTION_DEFAULT_CHOICES
        if value_text.strip() and value_text.strip() not in allowed:
            raise InspectionValidationError(
                f'「{record.item_name_snapshot}」填写值不合法（应为 {" / ".join(allowed)}）')
    result = spec.get('result')
    if result in INSPECTION_RESULT_VALUES:
        record.result = result
    elif input_type == INSPECTION_INPUT_TYPE_CHOICE and value_text.strip() == INSPECTION_CHOICE_ABNORMAL:
        record.result = INSPECTION_RESULT_ABNORMAL
    else:
        record.result = INSPECTION_RESULT_NORMAL
    record.value_text = value_text
    record.value_number = value_number
    record.abnormal_desc = '' if spec.get('abnormal_desc') is None else str(spec.get('abnormal_desc'))
    record.onsite_action = '' if spec.get('onsite_action') is None else str(spec.get('onsite_action'))
    record.save()


def _upsert_template_record(user, sheet, item, spec):
    """模板行 upsert：键 =（巡检单, 轮次, 模板检查内容）。"""
    round_no = _validate_round(spec.get('round_no'))
    defaults = dict(
        tenant_id=user.tenant_id,
        device_name_snapshot=item.device.device_name,
        item_name_snapshot=item.name,
        input_type_snapshot=item.input_type,
        choices_snapshot=item.choices,
        is_required_snapshot=item.is_required,
        display_order=item.display_order,
        updated_at=timezone.now(),
    )
    record, created = InspectionRecord.objects.get_or_create(
        sheet=sheet, round_no=round_no, template_item=item, defaults=defaults)
    if created:
        _apply_record_values(record, spec)
    else:
        # 已有记录：快照保持不变（模板修改不影响本单已存快照），仅更新填写值
        _apply_record_values(record, spec)
    return record


def _upsert_manual_record(user, sheet, spec):
    """手工临时加项 upsert：按 client_key 匹配，同样保存全量快照。"""
    client_key = (spec.get('client_key') or '').strip()[:64]
    if not client_key:
        raise InspectionValidationError('临时加项缺少行键（client_key）')
    device_name = (spec.get('device_name') or '').strip()[:100]
    item_name = (spec.get('item_name') or '').strip()[:200]
    if not item_name:
        raise InspectionValidationError('临时加项的检查内容不能为空')
    round_no = _validate_round(spec.get('round_no'))
    input_type = _validate_input_type(spec.get('input_type') or INSPECTION_INPUT_TYPE_TEXT)
    choices_json = json.dumps(INSPECTION_DEFAULT_CHOICES, ensure_ascii=False) \
        if input_type == INSPECTION_INPUT_TYPE_CHOICE else ''
    record = InspectionRecord.objects.filter(
        sheet=sheet, client_key=client_key, template_item__isnull=True).first()
    if record:
        record.round_no = round_no
        record.device_name_snapshot = device_name
        record.item_name_snapshot = item_name
        record.input_type_snapshot = input_type
        record.choices_snapshot = choices_json
        record.updated_at = timezone.now()
        record.save()
    else:
        record = InspectionRecord.objects.create(
            tenant_id=user.tenant_id,
            sheet=sheet,
            round_no=round_no,
            template_item=None,
            is_temporary=True,
            client_key=client_key,
            device_name_snapshot=device_name,
            item_name_snapshot=item_name,
            input_type_snapshot=input_type,
            choices_snapshot=choices_json,
            is_required_snapshot=bool(spec.get('is_required', False)),
            display_order=int(spec.get('display_order') or 0),
        )
    _apply_record_values(record, spec)
    return record


def _delete_sheet_record(sheet, spec):
    """按载荷删除一条巡检记录（仅草稿/已退回可编辑单，必须提供记录 ID）。"""
    record_id = spec.get('id')
    if not record_id:
        raise InspectionValidationError('删除记录必须提供记录 ID')
    deleted, _ = InspectionRecord.objects.filter(
        pk=int(record_id), sheet=sheet).delete()
    if not deleted:
        raise InspectionValidationError('巡检记录不存在或不属于当前巡检单')


def _move_record_round(sheet, record, round_no):
    """轮次变更校验并应用（同轮次同检查内容的记录唯一）。"""
    if not round_no or round_no == record.round_no:
        return
    new_round = _validate_round(round_no)
    conflict = InspectionRecord.objects.filter(
        sheet=sheet, round_no=new_round,
        template_item=record.template_item,
    ).exclude(pk=record.pk).first()
    if conflict:
        raise InspectionValidationError('该轮次已存在此检查内容的记录')
    record.round_no = new_round


def _check_template_item_writable(sheet, item, round_no):
    """停用的检查内容不允许新增记录；该单已有其记录时允许继续补填。"""
    if item.is_active or InspectionRecord.objects.filter(
            sheet=sheet, template_item=item, round_no=round_no).exists():
        return
    raise InspectionValidationError(f'检查内容「{item.name}」已停用，不能新增记录')


def _apply_record_spec(user, sheet, items, spec):
    """应用单条记录载荷（删除 / 按 ID 更新 / 模板行 upsert / 临时加项 upsert）。"""
    if spec.get('deleted'):
        _delete_sheet_record(sheet, spec)
        return
    if spec.get('id'):
        record = InspectionRecord.objects.filter(
            pk=int(spec['id']), sheet=sheet).first()
        if not record:
            raise InspectionValidationError('巡检记录不存在或不属于当前巡检单')
        _move_record_round(sheet, record, spec.get('round_no'))
        record.updated_at = timezone.now()
        record.save()
        _apply_record_values(record, spec)
    elif spec.get('template_item_id'):
        item = items.get(int(spec['template_item_id']))
        if not item:
            raise InspectionValidationError(
                '检查内容不存在或不属于巡检单模板（不能跨模板引用）')
        _check_template_item_writable(sheet, item, spec.get('round_no'))
        _upsert_template_record(user, sheet, item, spec)
    elif spec.get('client_key'):
        _upsert_manual_record(user, sheet, spec)
    else:
        raise InspectionValidationError('巡检记录缺少定位键（id/template_item_id/client_key）')


def _resolve_spec_round(sheet, spec):
    """解析单条记录载荷的目标轮次（id 载荷取已存记录的轮次，其余取 round_no）。"""
    if spec.get('id'):
        record = InspectionRecord.objects.filter(
            pk=int(spec['id']), sheet=sheet).only('round_no').first()
        if not record:
            raise InspectionValidationError('巡检记录不存在或不属于当前巡检单')
        return record.round_no
    return spec.get('round_no')


def _validate_record_rounds(sheet, records, allow_recorded=False):
    """"记录本轮"轮次保护（与前端单轮提交契约一致）：

    - 一次请求只允许提交一个轮次的记录（含删除，删除按已存记录轮次计）；
    - 该轮次已记录（recorded_rounds）时拒绝再次修改（allow_recorded=True
      时放行：仅退回整改状态的巡检单允许重改已记录轮次）；
    - round_no 缺失的载荷不在此拦截，由后续逐条校验报错。
    返回本次提交的唯一轮次（可能为 None）。
    """
    rounds = {_resolve_spec_round(sheet, spec) for spec in records}
    rounds.discard(None)
    if len(rounds) > 1:
        raise InspectionValidationError('一次只能记录一个轮次，请按轮次分开提交')
    if not rounds:
        return None
    round_no = rounds.pop()
    if not allow_recorded and round_no in sheet.get_recorded_rounds():
        round_text = INSPECTION_ROUND_TEXT_MAP.get(round_no, round_no)
        raise InspectionValidationError(
            f'「{round_text}」轮次已记录，不能再次修改（如需调整请作废巡检单重开）')
    return round_no


def update_sheet(user, sheet_id, body):
    """编辑可修改状态（草稿/已退回整改）的巡检单：值班人员 + 单轮巡检记录
    upsert（version 乐观锁）。

    记录载荷 spec 支持：
    - {template_item_id, round_no, 填写值...}：模板行 upsert；
    - {client_key, round_no, device_name?, item_name?, 填写值...}：临时加项 upsert；
    - {id, 填写值...}：按记录 ID 更新填写值；
    - {id, deleted: true}：删除该条记录。

    轮次保护：一次请求只允许提交一个轮次；该轮次写入成功后记入
    recorded_rounds（与明细、版本号同一事务），已记录轮次再提交即被拒绝；
    已退回整改的单例外：recorded_rounds 不阻止整改（原有填写内容保留，
    已记录轮次允许重改/补填），重新提交后恢复只读。
    """
    records = body.get('records')
    if records is not None and not isinstance(records, list):
        raise InspectionValidationError('巡检记录载荷不合法')
    with transaction.atomic():
        sheet = get_sheet_for_user(user, sheet_id, for_update=True)
        if sheet.status not in INSPECTION_SHEET_EDITABLE_STATUSES:
            raise InspectionValidationError('已提交或已作废的巡检单不能再修改')
        try:
            version = int(body.get('version'))
        except (TypeError, ValueError):
            raise InspectionValidationError('缺少有效的版本号（version）')
        if version != sheet.version:
            raise InspectionValidationError('巡检单已被他人修改，请刷新后重试')
        record_round = None
        if records:
            record_round = _validate_record_rounds(
                sheet, records,
                allow_recorded=sheet.status == INSPECTION_SHEET_RETURNED)
        if body.get('persons') is not None:
            _reconcile_persons(user, sheet, body.get('persons'))
        if records:
            items = {
                item.id: item
                for item in InspectionTemplateItem.objects.filter(
                    device__template=sheet.template, tenant_id=user.tenant_id,
                ).select_related('device')
            }
            for spec in records:
                if not isinstance(spec, dict):
                    raise InspectionValidationError('巡检记录载荷不合法')
                _apply_record_spec(user, sheet, items, spec)
            recorded = sheet.get_recorded_rounds()
            if record_round and record_round not in recorded:
                sheet.set_recorded_rounds(recorded + [record_round])
        sheet.version += 1
        sheet.updated_at = timezone.now()
        sheet.updated_by = user
        sheet.save()
    return sheet


def submit_sheet(user, sheet_id):
    """提交巡检单（记录/提交分离）：草稿/已退回 → 已提交，提交后不可再修改。

    已退回单重新提交：仍需满足值班人员、巡检记录等原有提交校验，
    提交成功后更新提交人与提交时间（原退回留痕保留）。
    """
    with transaction.atomic():
        sheet = get_sheet_for_user(user, sheet_id, for_update=True)
        if sheet.status not in (INSPECTION_SHEET_DRAFT, INSPECTION_SHEET_RETURNED):
            raise InspectionValidationError('只有草稿或已退回状态的巡检单可以提交')
        if not sheet.persons.exists():
            raise InspectionValidationError('请先登记值班人员再提交')
        if not sheet.records.exists():
            raise InspectionValidationError('暂无巡检记录，不能提交空巡检单')
        sheet.status = INSPECTION_SHEET_SUBMITTED
        sheet.submitted_at = timezone.now()
        sheet.submitted_by = user
        sheet.updated_at = timezone.now()
        sheet.updated_by = user
        sheet.save()
    return sheet


def return_sheet(user, sheet_id, reason):
    """超级管理员退回整改：已提交 → 已退回（原因必填，行锁事务）。

    - 仅允许 submitted → returned（草稿/已退回/已作废一律拒绝）；
    - 退回不删除、不修改任何巡检记录与值班人员，历史故障来源
      关系（source_inspection_record）原样保留；
    - 不释放值班日+模板唯一占用（单据仍有效，仅回到可编辑状态）。
    """
    reason = str(reason or '').strip()
    if not reason:
        raise InspectionValidationError('退回原因不能为空')
    if len(reason) > 200:
        raise InspectionValidationError('退回原因不能超过 200 字')
    with transaction.atomic():
        sheet = get_sheet_for_user(user, sheet_id, for_update=True)
        if sheet.status != INSPECTION_SHEET_SUBMITTED:
            raise InspectionValidationError('只有已提交状态的巡检单可以退回整改')
        sheet.status = INSPECTION_SHEET_RETURNED
        sheet.returned_at = timezone.now()
        sheet.returned_by = user
        sheet.return_reason = reason[:200]
        sheet.updated_at = timezone.now()
        sheet.updated_by = user
        sheet.save()
    return sheet


def void_sheet(user, sheet_id, reason):
    """受控作废巡检单（留档可查，并释放当日唯一占用）。"""
    if not (reason or '').strip():
        raise InspectionValidationError('作废原因不能为空')
    with transaction.atomic():
        sheet = get_sheet_for_user(user, sheet_id, for_update=True)
        if sheet.status == INSPECTION_SHEET_VOID:
            raise InspectionValidationError('巡检单已作废')
        sheet.status = INSPECTION_SHEET_VOID
        sheet.voided_at = timezone.now()
        sheet.voided_by = user
        sheet.void_reason = reason.strip()[:200]
        sheet.uniq_key = f'{sheet.build_uniq_key()}|voided_{sheet.id}'
        sheet.updated_at = timezone.now()
        sheet.updated_by = user
        sheet.save()
    return sheet


# ----------------------------------------------------------------------
# 巡检异常处置状态（由来源故障关系动态推导，只读展示；转工单已随
# 工单功能整体删除，2026-09-30；历史来源数据继续可追溯）
# ----------------------------------------------------------------------

def _merge_disposition_targets(result, targets, id_attr, key, no_attr,
                               cancelled_status, converted_status):
    """把一批转换目标并入处置槽位：最新一条作追溯信息，未取消目标决定状态。"""
    for target in targets:
        slot = result.get(getattr(target, id_attr))
        if slot is None:
            continue
        if slot[key] is None:
            slot[key] = {'id': target.id, no_attr: getattr(target, no_attr),
                         'status': target.status}
        if target.status != cancelled_status and slot['status'] == 'none':
            slot['status'] = converted_status


def compute_record_disposition(tenant_id, record_ids):
    """计算巡检异常明细的处置状态（由来源关系动态推导，不落库）。

    返回 {record_id: {'status': ..., 'fault': {...} 或 None}}。
    """
    record_ids = [int(i) for i in record_ids]
    result = {
        i: {'status': 'none', 'fault': None}
        for i in record_ids
    }
    if not record_ids or not tenant_id:
        return result
    faults = SystemFault.objects.filter(
        tenant_id=tenant_id, source_inspection_record_id__in=record_ids).order_by('-id')
    _merge_disposition_targets(
        result, faults, 'source_inspection_record_id', 'fault', 'fault_no',
        SystemFault.STATUS_CANCELLED, 'converted_fault')
    for slot in result.values():
        if slot['status'] == 'none' and slot['fault']:
            slot['status'] = 'target_cancelled'
    return result


def append_record_disposition(tenant_id, records):
    """把处置状态批量并入巡检明细序列化结果（records 为 to_view() 后的 dict 列表）。"""
    ids = [r.get('id') for r in records if r.get('id')]
    disposition_map = compute_record_disposition(tenant_id, ids) if ids else {}
    for record in records:
        record['disposition'] = disposition_map.get(record.get('id'), {
            'status': 'none', 'fault': None})
    return records


# 批量处置状态查询分块大小（防止单条 IN 子句过长）
_DISPOSITION_CHUNK_SIZE = 1000


def append_batch_record_disposition(tenant_id, sheet_details):
    """把处置状态批量并入多张巡检单的明细序列化结果（批量导出用）。

    与 append_record_disposition 口径一致，但所有巡检单的明细合并后
    分块查询来源故障，避免批量导出时逐单循环重复查询。
    sheet_details 为 to_detail_view() 后的 dict 列表，原地并入后原样返回。
    """
    record_map = {}
    for detail in sheet_details:
        for record in detail.get('records') or []:
            if record.get('id'):
                record_map[record['id']] = record
    disposition_map = {}
    ids = list(record_map)
    for start in range(0, len(ids), _DISPOSITION_CHUNK_SIZE):
        chunk = ids[start:start + _DISPOSITION_CHUNK_SIZE]
        disposition_map.update(compute_record_disposition(tenant_id, chunk))
    for record in record_map.values():
        record['disposition'] = disposition_map.get(record['id'], {
            'status': 'none', 'fault': None})
    return sheet_details
