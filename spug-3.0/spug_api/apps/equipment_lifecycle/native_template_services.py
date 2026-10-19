# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——原生维护台账模板服务（草稿/绑定/纸张/发布/版本，2026-10-18）。

结构对齐 Excel 模板管理（excel_template_manage.py），差异：
- 模板无物理源文件：版式 = Univer 工作簿快照 JSON 直接落库，无哈希比对、
  无文件存储；草稿保存为 整体替换（快照+绑定+纸张一起提交）；
- 发布级校验：草稿快照存在 + 绑定 ≥1；发布即快照为不可变版本，
  version_no 模板内 select_for_update 串行递增，(template, version_no)
  唯一约束兜底；版本只增不改不删；
- 停用/删除语义与 Excel 模板一致：停用=逻辑停用（幂等），删除=物理删除
  （行锁内复查引用，被任一版本台账引用的模板只能停用）；
- 绑定协议（前端编辑器提交，服务端全量校验后落库）：
  [{id, key, label, section, range, type, placeholder}]，range 为 A1 单元格
  引用，key/label/range 均唯一，type ∈ text/number/date/status/textarea；
- 纸张协议：{size: A4|A3, orientation: portrait|landscape, fitToWidth: bool,
  margins: {top,right,bottom,left ∈ 4..40}}；缺省用 DEFAULT_PAPER；
- 不参与本期应填台账自动生成（无生成配置字段）。

业务错误统一抛 NativeTemplateError，View 层转 json_response(error=...)。
"""
import json
import re
from datetime import datetime

from django.db import transaction
from django.db.models import Count, Max
from django.utils import timezone

from libs.tenant_utils import apply_tenant_filter

from apps.equipment_lifecycle.ledger_services import (
    LedgerValidationError,
    validate_ledger_type,
)
from apps.equipment_lifecycle.native_models import (
    NATIVE_BINDING_TYPE_VALUES,
    NATIVE_PAPER_ORIENTATIONS,
    NATIVE_PAPER_SIZES,
    NATIVE_STATUS_VALUES,
    OperationLedgerNativeTemplate,
    OperationLedgerNativeTemplateVersion,
)

# 草稿/版本快照 JSON 字符上限（Univer 快照量级为百 KB，4MB 已远超正常模板）
MAX_SNAPSHOT_CHARS = 4 * 1024 * 1024
# 单模板绑定字段数量上限（超大规模模板应走 Excel 路线）
MAX_BINDING_COUNT = 500
# A1 单元格引用（列字母 1-3 位 + 行号无前导零）
_RANGE_RE = re.compile(r'^[A-Z]{1,3}[1-9][0-9]{0,6}$')
_KEY_RE = re.compile(r'^[A-Za-z0-9_]{1,64}$')
_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')

DEFAULT_PAPER = {
    'size': 'A4',
    'orientation': 'landscape',
    'fitToWidth': True,
    'margins': {'top': 12, 'right': 10, 'bottom': 12, 'left': 10},
}


class NativeTemplateError(Exception):
    """原生模板业务校验错误（View 层转业务错误响应）。"""


class NativeValueError(Exception):
    """原生台账填写值校验错误（ledger 服务与模板服务共用协议）。"""


def _fail(message):
    raise NativeTemplateError(message)


def _canonical(data):
    return json.dumps(data, ensure_ascii=False, separators=(',', ':'))


def get_template(pk, user, for_update=False):
    """按租户取模板；不存在返回 None（跨租户与不存在不区分，避免探测）。"""
    query = apply_tenant_filter(OperationLedgerNativeTemplate.objects.all(), user)
    if for_update:
        query = query.select_for_update()
    return query.filter(pk=pk).first()


def get_version(version_id, user):
    """按租户取已发布版本；不存在返回 None。"""
    query = apply_tenant_filter(OperationLedgerNativeTemplateVersion.objects.all(), user)
    return query.select_related('template').filter(pk=version_id).first()


# ======================================================================
# 草稿载荷校验（快照 / 绑定 / 纸张）
# ======================================================================

def validate_snapshot(snapshot):
    """Univer 快照基础校验：dict + sheets 非空 + 序列化尺寸上限。

    只做结构性边界校验（编辑器为本平台自研，内容细节由编辑器保证），
    校验通过返回原 dict；序列化失败/超限显式拒绝。
    """
    if not isinstance(snapshot, dict):
        _fail('模板快照格式不正确')
    sheets = snapshot.get('sheets')
    if not isinstance(sheets, dict) or not sheets:
        _fail('模板快照缺少工作表数据，请先在编辑器中绘制底表')
    try:
        canonical = _canonical(snapshot)
    except (TypeError, ValueError):
        _fail('模板快照包含不可序列化的内容')
    if len(canonical) > MAX_SNAPSHOT_CHARS:
        _fail('模板快照超过大小限制（%dMB），请精简模板内容'
              % (MAX_SNAPSHOT_CHARS // (1024 * 1024)))
    return snapshot


def _parse_binding_fields(item):
    """解析并校验单条绑定的标量字段（存在性/长度/格式/类型枚举）。"""
    if not isinstance(item, dict):
        _fail('字段绑定格式不正确')
    key = str(item.get('key') or '').strip()
    label = str(item.get('label') or '').strip()
    section = str(item.get('section') or '').strip()
    field_range = str(item.get('range') or '').strip().upper()
    field_type = str(item.get('type') or '').strip()
    if not _KEY_RE.match(key):
        _fail('字段标识不合法：%s（仅限字母/数字/下划线，≤64 字符）' % (key or '(空)'))
    if not label or len(label) > 100:
        _fail('字段名称不能为空且不超过 100 字：%s' % label)
    if len(section) > 50:
        _fail('字段分组名称不超过 50 字')
    if not _RANGE_RE.match(field_range):
        _fail('绑定单元格引用不合法：%s（应为 A1 形式的单元格）' % field_range)
    if field_type not in NATIVE_BINDING_TYPE_VALUES:
        _fail('字段类型不合法：%s' % field_type)
    return {
        'key': key, 'label': label, 'section': section,
        'range': field_range, 'type': field_type,
        'placeholder': str(item.get('placeholder') or '')[:100],
        'is_required': bool(item.get('is_required', False)),
    }


def _validate_binding_item(item, seen_keys, seen_ranges):
    """单条绑定校验（字段合法性 + key/range 唯一），返回规范化 dict。"""
    fields = _parse_binding_fields(item)
    if fields['key'] in seen_keys:
        _fail('字段标识重复：%s' % fields['key'])
    if fields['range'] in seen_ranges:
        _fail('单元格 %s 被绑定到多个字段' % fields['range'])
    seen_keys.add(fields['key'])
    seen_ranges.add(fields['range'])
    return {
        'id': str(item.get('id') or fields['key'])[:64],
        **fields,
    }


def validate_bindings(bindings):
    """字段绑定全量校验（整体替换；key/label/range 唯一）。"""
    if not isinstance(bindings, list):
        _fail('字段绑定格式不正确')
    if len(bindings) > MAX_BINDING_COUNT:
        _fail('绑定字段数量超过上限 %d' % MAX_BINDING_COUNT)
    normalized = []
    seen_keys = set()
    seen_ranges = set()
    for item in bindings:
        normalized.append(_validate_binding_item(item, seen_keys, seen_ranges))
    return normalized


def validate_paper(paper):
    """纸张/打印设置校验；缺省字段用 DEFAULT_PAPER 兜底。"""
    merged = {
        'size': DEFAULT_PAPER['size'],
        'orientation': DEFAULT_PAPER['orientation'],
        'fitToWidth': DEFAULT_PAPER['fitToWidth'],
        'margins': dict(DEFAULT_PAPER['margins']),
    }
    if paper in (None, ''):
        return merged
    if not isinstance(paper, dict):
        _fail('纸张设置格式不正确')
    size = str(paper.get('size') or merged['size'])
    if size not in NATIVE_PAPER_SIZES:
        _fail('纸张规格仅支持 A4/A3')
    orientation = str(paper.get('orientation') or merged['orientation'])
    if orientation not in NATIVE_PAPER_ORIENTATIONS:
        _fail('纸张方向仅支持 portrait/landscape')
    margins = paper.get('margins')
    if margins is not None:
        if not isinstance(margins, dict):
            _fail('页边距设置格式不正确')
        for side in ('top', 'right', 'bottom', 'left'):
            if side not in margins:
                continue
            value = margins.get(side)
            if not isinstance(value, (int, float)) or isinstance(value, bool) \
                    or not (4 <= value <= 40):
                _fail('页边距须为 4~40mm 之间的数字')
            merged['margins'][side] = value
    merged['size'] = size
    merged['orientation'] = orientation
    merged['fitToWidth'] = bool(paper.get('fitToWidth', merged['fitToWidth']))
    return merged


def validate_values(bindings, values):
    """填写值整体校验（保存与更正共用）：键值域按绑定类型收敛。

    - 只接受当前绑定内的 key（未知键显式拒绝，不静默丢弃）；
    - number：空串或可解析为数字（≤50 字符）；date：空串或 YYYY-MM-DD；
      status：空串或 正常/不正常；text/textarea：字符串（长度上限 2000/10000）；
    - 必填校验不在此处（完成填写时统一终验）。
    校验通过返回规范化后的 dict（原值字符串保真，不转数字/日期对象）。
    """
    if not isinstance(values, dict):
        raise NativeValueError('填写值格式不正确')
    binding_by_key = {b['key']: b for b in bindings}
    normalized = {}
    for key, value in values.items():
        binding = binding_by_key.get(key)
        if binding is None:
            raise NativeValueError('填写值包含模板中不存在的字段：%s' % key)
        field_type = binding['type']
        if value in (None,):
            value = ''
        if not isinstance(value, str):
            if field_type == 'number':
                value = str(value)
            else:
                raise NativeValueError('字段「%s」的填写值格式不正确' % binding['label'])
        value = value.strip() if field_type != 'textarea' else value
        _validate_single_value(binding, field_type, value)
        normalized[key] = value
    return normalized


def _validate_single_value(binding, field_type, value):
    label = binding['label']
    if field_type == 'number':
        if value and not _parse_number(value):
            raise NativeValueError('字段「%s」须填写数字' % label)
        if len(value) > 50:
            raise NativeValueError('字段「%s」的数值长度超过限制' % label)
    elif field_type == 'date':
        if value and not _valid_date(value):
            raise NativeValueError('字段「%s」须为 YYYY-MM-DD 格式日期' % label)
    elif field_type == 'status':
        if value and value not in NATIVE_STATUS_VALUES:
            raise NativeValueError('字段「%s」只能选择 正常/不正常' % label)
    elif field_type == 'textarea':
        if len(value) > 10000:
            raise NativeValueError('字段「%s」的内容超过 10000 字上限' % label)
    else:
        if len(value) > 2000:
            raise NativeValueError('字段「%s」的内容超过 2000 字上限' % label)


def _parse_number(value):
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _valid_date(value):
    if not _DATE_RE.match(value):
        return False
    try:
        datetime.strptime(value, '%Y-%m-%d')
        return True
    except ValueError:
        return False


# ======================================================================
# 模板 CRUD / 草稿 / 发布
# ======================================================================

def _validate_template_meta(body, with_name=True):
    name = str(body.get('name') or '').strip()
    if with_name and not name:
        _fail('模板名称不能为空')
    if len(name) > 100:
        _fail('模板名称超过长度限制')
    description = str(body.get('description') or '').strip()
    if len(description) > 500:
        _fail('模板说明超过长度限制')
    return name, description


def create_template(user, body):
    """创建原生模板（空草稿；ledger_type 创建后不可修改）。"""
    name, description = _validate_template_meta(body)
    ledger_type = body.get('ledger_type')
    try:
        validate_ledger_type(ledger_type)
    except LedgerValidationError as e:
        _fail(str(e))
    return OperationLedgerNativeTemplate.objects.create(
        tenant_id=user.tenant_id,
        name=name,
        ledger_type=ledger_type,
        description=description,
        created_by=user,
    )


def update_template_meta(user, template, body):
    """修改模板基础信息（名称/说明；ledger_type 不可修改，出现即拒绝）。"""
    if not template.is_active:
        _fail('模板已停用，不能修改基础信息')
    if 'ledger_type' in body and body.get('ledger_type') != template.ledger_type:
        _fail('台账类型创建后不可修改')
    name, description = _validate_template_meta(body, with_name=False)
    updates = {}
    if name:
        updates['name'] = name
    if 'description' in body:
        updates['description'] = description
    if not updates:
        return template
    for field, value in updates.items():
        setattr(template, field, value)
    template.updated_at = timezone.now()
    template.updated_by = user
    template.save(update_fields=list(updates.keys()) + ['updated_at', 'updated_by'])
    return template


@transaction.atomic
def save_draft(user, template, body):
    """保存草稿（整体替换：快照 + 绑定 + 纸张一起校验一起落库）。"""
    if not template.is_active:
        _fail('模板已停用，不能修改草稿')
    if not isinstance(body, dict):
        _fail('草稿参数格式不正确')
    if 'snapshot' not in body:
        _fail('草稿缺少模板快照')
    snapshot = validate_snapshot(body.get('snapshot'))
    bindings = validate_bindings(body.get('bindings') or [])
    paper = validate_paper(body.get('paper'))
    locked = get_template(template.pk, user, for_update=True)
    if locked is None:
        _fail('原生台账模板不存在')
    if not locked.is_active:
        _fail('模板已停用，不能修改草稿')
    locked.draft_snapshot = _canonical(snapshot)
    locked.draft_bindings = _canonical(bindings)
    locked.draft_paper = _canonical(paper)
    locked.draft_updated_at = timezone.now()
    locked.draft_updated_by = user
    locked.updated_at = timezone.now()
    locked.updated_by = user
    locked.save(update_fields=[
        'draft_snapshot', 'draft_bindings', 'draft_paper',
        'draft_updated_at', 'draft_updated_by', 'updated_at', 'updated_by'])
    return locked


@transaction.atomic
def publish_version(user, template):
    """发布：校验 → 草稿快照落库为不可变版本（只增不改）。

    - 发布级校验：草稿快照存在 + 绑定 ≥1（发布前须先保存草稿）；
    - version_no 行锁内取 max+1，(template, version_no) 唯一约束兜底。
    """
    locked = get_template(template.pk, user, for_update=True)
    if locked is None:
        _fail('原生台账模板不存在')
    if not locked.is_active:
        _fail('模板已停用，不能发布新版本')
    if not locked.draft_snapshot:
        _fail('当前没有可发布的草稿，请先在编辑器中保存草稿')
    bindings = json.loads(locked.draft_bindings) if locked.draft_bindings else []
    if not bindings:
        _fail('请先绑定至少一个可填写字段再发布')
    latest_no = locked.versions.aggregate(max_no=Max('version_no'))['max_no'] or 0
    version = OperationLedgerNativeTemplateVersion.objects.create(
        tenant_id=user.tenant_id,
        template=locked,
        version_no=latest_no + 1,
        template_name_snapshot=locked.name,
        snapshot=locked.draft_snapshot,
        bindings=locked.draft_bindings,
        paper=locked.draft_paper or _canonical(DEFAULT_PAPER),
        field_count=len(bindings),
        published_by=user,
    )
    locked.updated_at = timezone.now()
    locked.updated_by = user
    locked.save(update_fields=['updated_at', 'updated_by'])
    return version


def deactivate_template(user, template):
    """停用模板（逻辑停用，幂等）；返回 (template, deactivated_now)。"""
    if not template.is_active:
        return template, False
    template.is_active = False
    template.updated_at = timezone.now()
    template.updated_by = user
    template.save(update_fields=['is_active', 'updated_at', 'updated_by'])
    return template, True


def template_ledger_reference_count(template):
    """统计引用模板任意版本的台账数（含已作废——阻止物理删除）。"""
    return template.versions.aggregate(
        total=Count('ledger_records', distinct=True))['total'] or 0


@transaction.atomic
def destroy_template(user, template):
    """物理删除模板（含版本）：行锁内复查引用，被引用只能停用。"""
    locked = get_template(template.pk, user, for_update=True)
    if locked is None:
        _fail('原生台账模板不存在')
    refs = template_ledger_reference_count(locked)
    if refs:
        _fail('模板已被 %s 个台账引用（含已作废），不能删除；如需停止使用请改为停用' % refs)
    info = {'id': locked.pk, 'name': locked.name, 'versions_count': locked.versions.count()}
    locked.delete()
    return info


# ======================================================================
# 查询 / 视图组装
# ======================================================================

def list_templates(user):
    query = apply_tenant_filter(OperationLedgerNativeTemplate.objects.all(), user)
    query = query.annotate(
        latest_version_no=Max('versions__version_no'),
        versions_count=Count('versions', distinct=True),
        ledgers_count=Count('versions__ledger_records', distinct=True))
    return [t.to_view(t.latest_version_no or 0, t.versions_count or 0, t.ledgers_count or 0)
            for t in query]


def available_templates(user, ledger_type=None):
    """台账创建用：启用且有已发布版本的模板（可按类型过滤），含版本列表。"""
    query = apply_tenant_filter(
        OperationLedgerNativeTemplate.objects.filter(is_active=True), user)
    if ledger_type:
        query = query.filter(ledger_type=ledger_type)
    query = query.annotate(versions_count=Count('versions')).filter(versions_count__gt=0)
    items = []
    for template in query:
        versions = [v.to_view() for v in template.versions.all()]
        items.append({
            'id': template.id,
            'name': template.name,
            'ledger_type': template.ledger_type,
            'description': template.description,
            'versions': versions,
        })
    return items


def draft_meta_view(template):
    """草稿内容视图（编辑器 iframe 载入数据源）；无草稿返回 None。"""
    if not template.draft_snapshot:
        return None
    return {
        'snapshot': json.loads(template.draft_snapshot),
        'bindings': json.loads(template.draft_bindings) if template.draft_bindings else [],
        'paper': json.loads(template.draft_paper) if template.draft_paper
                 else dict(DEFAULT_PAPER),
        'draft_updated_at': template.draft_updated_at,
        'draft_updated_by': template.draft_updated_by.nickname
        if template.draft_updated_by else '',
    }


def version_meta_view(version):
    """版本内容视图（版式回放/打印数据源）：快照 + 绑定 + 纸张。"""
    part = version.get_paper()
    return {
        'snapshot': version.get_snapshot(),
        'bindings': version.get_bindings(),
        'paper': part or dict(DEFAULT_PAPER),
    }


def template_detail(template):
    latest_no = template.versions.aggregate(max_no=Max('version_no'))['max_no'] or 0
    total = template.versions.count()
    ledgers = template.versions.aggregate(
        total=Count('ledger_records', distinct=True))['total'] or 0
    view = template.to_view(latest_no, total, ledgers)
    view['draft'] = draft_meta_view(template)
    view['versions'] = [v.to_view() for v in template.versions.all()]
    return view


def default_prefill(bindings):
    """台账创建时的默认值骨架（当前全部字段为空串）。"""
    return {b['key']: '' for b in bindings}
