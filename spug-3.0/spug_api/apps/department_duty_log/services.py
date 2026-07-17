# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""部门值班日志 - 服务层

集中实现输入校验、序列化、可见性查询、能力计算和生命周期操作。
View 不直接堆叠状态/签署/哈希逻辑，统一委托本模块。
"""
import hashlib
import json
import logging
import uuid
from datetime import date, datetime, timedelta

from django.db import transaction, IntegrityError
from django.db.models import F, Q

from libs import human_datetime
from apps.logs.audit import record_audit_event
from apps.signature import services as signature_services
from apps.signature.services import apply_signature

from .models import (
    DepartmentDutyLog,
    STATUS_DRAFT, STATUS_SIGNED, STATUS_VOID,
)

logger = logging.getLogger(__name__)

# ---- 签署场景常量 ----
MODULE = 'department_duty_log'
OBJECT_TYPE = 'department_duty_log'
SCENE_CODE = 'duty_person'

# ---- 输入长度限制 ----
MAX_VOLTAGE_LEN = 50
MAX_WEATHER_LEN = 50
MAX_DUTY_RECORD_LEN = 10000
MAX_REMARK_LEN = 2000
MAX_KEYWORD_LEN = 100
MAX_DUTY_PERSON_NAME_LEN = 100
MAX_VOID_REASON_LEN = 500

# ---- 受保护字段：客户端提交时必须拒绝 ----
PROTECTED_FIELDS = frozenset({
    'tenant_id', 'duty_person', 'duty_person_id', 'duty_person_name',
    'created_by', 'created_by_id', 'updated_by', 'updated_by_id',
    'deleted_by', 'deleted_by_id', 'signed_by', 'signed_by_id',
    'signed_by_name', 'signed_at', 'signature_usage_id',
    'signature_version', 'signature_sha256', 'business_snapshot_hash',
    'status', 'voided_by', 'voided_by_id', 'voided_at', 'void_reason',
    'supersedes', 'supersedes_id', 'created_at', 'updated_at', 'deleted_at',
    'id',
})

# 默认查询天数
DEFAULT_QUERY_DAYS = 31


# ============================================================
# 输入校验
# ============================================================

def _detect_protected_fields(raw_data):
    """检测原始 JSON 中是否包含受保护字段，返回违规字段名列表。"""
    if not isinstance(raw_data, dict):
        return []
    violations = []
    for key in raw_data.keys():
        # 去掉可能的 _id 后缀后再匹配
        base_key = key[:-3] if key.endswith('_id') else key
        if key in PROTECTED_FIELDS or base_key in PROTECTED_FIELDS:
            violations.append(key)
    return violations


def _parse_date(value, field_name, allow_future=False):
    """严格解析 YYYY-MM-DD 日期。返回 date 或抛出 ValueError。"""
    if not value or not isinstance(value, str):
        raise ValueError(f'{field_name} 日期格式不正确')
    try:
        d = datetime.strptime(value.strip(), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        raise ValueError(f'{field_name} 日期格式不正确，需为 YYYY-MM-DD')
    if not allow_future and d > date.today():
        raise ValueError(f'{field_name} 不能晚于当前日期')
    return d


def _clean_str(value, max_len, field_name, required=False):
    """去首尾空格，校验长度。required 为 True 时不允许空。"""
    if value is None:
        value = ''
    if not isinstance(value, str):
        raise ValueError(f'{field_name} 格式不正确')
    value = value.strip()
    if required and not value:
        raise ValueError(f'{field_name} 不能为空')
    if len(value) > max_len:
        raise ValueError(f'{field_name} 超过最大长度 {max_len}')
    return value


def _clean_optional_str(value, max_len, field_name):
    """可选字符串：None/空串返回 None，非空去空格+校验长度。"""
    if value is None or value == '':
        return None
    if not isinstance(value, str):
        raise ValueError(f'{field_name} 格式不正确')
    value = value.strip()
    if not value:
        return None
    if len(value) > max_len:
        raise ValueError(f'{field_name} 超过最大长度 {max_len}')
    return value


def validate_payload(raw_data, *, is_create=True):
    """校验创建/编辑 payload，返回 (form_dict, error_str)。

    form_dict 只包含允许客户端设置的字段。
    受保护字段在原始数据中出现时直接拒绝。
    """
    if not isinstance(raw_data, dict):
        return None, '请求体格式不正确'

    # 检测受保护字段
    violations = _detect_protected_fields(raw_data)
    if violations:
        logger.warning('[DepartmentDutyLog] protected fields rejected: %s', violations)
        return None, f'请求包含不允许提交的字段: {", ".join(sorted(violations))}'

    try:
        duty_date = _parse_date(raw_data.get('duty_date'), '值班日期')
        mains_voltage = _clean_str(raw_data.get('mains_voltage'), MAX_VOLTAGE_LEN, '市电电压', required=True)
        ups_voltage = _clean_str(raw_data.get('ups_voltage'), MAX_VOLTAGE_LEN, 'UPS电压', required=True)
        weather = _clean_str(raw_data.get('weather'), MAX_WEATHER_LEN, '天气情况', required=True)
        duty_record = _clean_str(raw_data.get('duty_record'), MAX_DUTY_RECORD_LEN, '值班记录', required=True)
        remark = _clean_optional_str(raw_data.get('remark'), MAX_REMARK_LEN, '备注')
    except ValueError as e:
        return None, str(e)

    form = {
        'duty_date': duty_date,
        'mains_voltage': mains_voltage,
        'ups_voltage': ups_voltage,
        'weather': weather,
        'duty_record': duty_record,
        'remark': remark,
    }

    # 编辑时需要 version
    if not is_create:
        version = raw_data.get('version')
        if version is None:
            return None, '缺少版本号'
        try:
            form['version'] = int(version)
            if form['version'] < 1:
                return None, '版本号不正确'
        except (TypeError, ValueError):
            return None, '版本号格式不正确'

    return form, None


# ============================================================
# 业务快照
# ============================================================

def _sha256_text(value):
    """计算 UTF-8 文本 SHA256。"""
    return hashlib.sha256((value or '').encode('utf-8')).hexdigest()


def build_business_snapshot(record):
    """从数据库草稿生成固定结构业务快照。"""
    return {
        'schema_version': 1,
        'record_id': record.id,
        'duty_date': record.duty_date.strftime('%Y-%m-%d'),
        'duty_person_id': record.duty_person_id,
        'duty_person_name': record.duty_person_name,
        'mains_voltage': record.mains_voltage or '',
        'ups_voltage': record.ups_voltage or '',
        'weather': record.weather or '',
        'duty_record_sha256': _sha256_text(record.duty_record),
        'duty_record_length': len(record.duty_record or ''),
        'remark_sha256': _sha256_text(record.remark or ''),
        'remark_length': len(record.remark or ''),
        'record_version': record.version,
    }


# ============================================================
# 序列化
# ============================================================

def _format_date(d):
    """DateField -> 'YYYY-MM-DD' 字符串"""
    if d is None:
        return None
    return d.strftime('%Y-%m-%d')


def serialize_department_duty_log(record, user):
    """序列化单条记录为 dict，包含能力字段。

    显式控制每个字段输出格式，不依赖 ModelMixin.to_dict()。
    """
    data = {
        'id': record.id,
        'duty_date': _format_date(record.duty_date),
        'duty_person_id': record.duty_person_id,
        'duty_person_name': record.duty_person_name,
        'mains_voltage': record.mains_voltage or '',
        'ups_voltage': record.ups_voltage or '',
        'weather': record.weather or '',
        'duty_record': record.duty_record or '',
        'remark': record.remark or '',
        'status': record.status,
        'version': record.version,
        'signature_usage_id': record.signature_usage_id,
        'signed_by_id': record.signed_by_id,
        'signed_by_name': record.signed_by_name or '',
        'signed_at': record.signed_at or '',
        'signature_version': record.signature_version,
        'signature_sha256': record.signature_sha256 or '',
        'business_snapshot_hash': record.business_snapshot_hash or '',
        'supersedes_id': record.supersedes_id,
        'created_at': record.created_at,
        'created_by_id': record.created_by_id,
        'updated_at': record.updated_at or '',
        'updated_by_id': record.updated_by_id,
        'voided_at': record.voided_at or '',
        'voided_by_id': record.voided_by_id,
        'void_reason': record.void_reason or '',
    }
    data.update(compute_record_capabilities(record, user))
    return data


def serialize_list_item(record, user):
    """序列化列表项（不含长文本全文，只含摘要）。"""
    record_text = record.duty_record or ''
    summary = record_text[:100] + '...' if len(record_text) > 100 else record_text
    data = {
        'id': record.id,
        'duty_date': _format_date(record.duty_date),
        'duty_person_name': record.duty_person_name,
        'mains_voltage': record.mains_voltage or '',
        'ups_voltage': record.ups_voltage or '',
        'weather': record.weather or '',
        'duty_record_summary': summary,
        'status': record.status,
        'version': record.version,
        'signature_usage_id': record.signature_usage_id,
        'signed_by_name': record.signed_by_name or '',
        'signed_at': record.signed_at or '',
        'signature_version': record.signature_version,
        'business_snapshot_hash': record.business_snapshot_hash or '',
        'voided_at': record.voided_at or '',
        'void_reason': record.void_reason or '',
        'supersedes_id': record.supersedes_id,
    }
    data.update(compute_record_capabilities(record, user))
    return data


def compute_record_capabilities(record, user):
    """根据当前用户、权限、状态和所有权计算能力字段。

    前端据此渲染按钮，后端仍重复校验。
    """
    is_owner = record.duty_person_id == getattr(user, 'id', None)
    is_draft = record.status == STATUS_DRAFT
    is_signed = record.status == STATUS_SIGNED

    return {
        'can_edit': bool(is_draft and is_owner and user.has_perms(['department_duty_log.department_duty_log.edit'])),
        'can_delete': bool(is_draft and is_owner and user.has_perms(['department_duty_log.department_duty_log.del'])),
        'can_sign': bool(is_draft and is_owner and user.has_perms(['department_duty_log.department_duty_log.sign'])),
        'can_void': bool(is_signed and user.has_perms(['department_duty_log.department_duty_log.void'])),
    }


# ============================================================
# 可见性查询
# ============================================================

def get_visible_department_duty_logs(user):
    """返回当前用户可见的基础 QuerySet（未删除 + 可见性过滤）。

    已签/已作废全局可见，草稿仅本人可见。
    不加任何租户条件。
    """
    return DepartmentDutyLog.objects.filter(
        deleted_at__isnull=True,
    ).filter(
        Q(status__in=(STATUS_SIGNED, STATUS_VOID)) |
        Q(status=STATUS_DRAFT, duty_person_id=user.id)
    )


def get_list_queryset(user, params):
    """根据筛选参数构建列表 QuerySet（未分页）。"""
    qs = get_visible_department_duty_logs(user)

    start_date = params.get('start_date')
    end_date = params.get('end_date')
    if start_date:
        qs = qs.filter(duty_date__gte=start_date)
    if end_date:
        qs = qs.filter(duty_date__lte=end_date)

    duty_person_name = params.get('duty_person_name')
    if duty_person_name:
        qs = qs.filter(duty_person_name__icontains=duty_person_name)

    status = params.get('status')
    if status:
        qs = qs.filter(status=status)

    keyword = params.get('keyword')
    if keyword:
        qs = qs.filter(Q(duty_record__icontains=keyword) | Q(remark__icontains=keyword))

    return qs


def _parse_list_date_range(query_params):
    """解析列表日期范围参数。返回 (start_date, end_date, error_str)。"""
    today = date.today()
    default_start = today - timedelta(days=DEFAULT_QUERY_DAYS - 1)
    start_date_str = query_params.get('start_date', '').strip()
    end_date_str = query_params.get('end_date', '').strip()
    try:
        if start_date_str:
            start_date = _parse_date(start_date_str, '开始日期')
        else:
            start_date = default_start
        if end_date_str:
            end_date = _parse_date(end_date_str, '结束日期')
        else:
            end_date = today
    except ValueError as e:
        return None, None, str(e)
    if end_date < start_date:
        return None, None, '结束日期不能早于开始日期'
    return start_date, end_date, None


def _parse_list_filters(query_params):
    """解析列表筛选参数。返回 (filter_dict, error_str)。"""
    filters = {}
    duty_person_name = query_params.get('duty_person_name', '').strip()
    if duty_person_name:
        if len(duty_person_name) > MAX_DUTY_PERSON_NAME_LEN:
            return None, '值班员姓名过长'
        filters['duty_person_name'] = duty_person_name

    status = query_params.get('status', '').strip()
    if status:
        if status not in (STATUS_DRAFT, STATUS_SIGNED, STATUS_VOID):
            return None, '状态值不正确'
        filters['status'] = status

    keyword = query_params.get('keyword', '').strip()
    if keyword:
        if len(keyword) > MAX_KEYWORD_LEN:
            return None, '关键字过长'
        filters['keyword'] = keyword
    return filters, None


def _parse_list_pagination(query_params):
    """解析列表分页参数。返回 (page, page_size)。"""
    try:
        page = int(query_params.get('page', 1))
        if page < 1:
            page = 1
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = int(query_params.get('page_size', 20))
        if page_size < 1:
            page_size = 20
        if page_size > 100:
            page_size = 100
    except (TypeError, ValueError):
        page_size = 20
    return page, page_size


def parse_list_params(request):
    """解析列表查询参数，返回 (params_dict, error_str)。"""
    start_date, end_date, err = _parse_list_date_range(request.GET)
    if err:
        return None, err
    filters, err = _parse_list_filters(request.GET)
    if err:
        return None, err
    page, page_size = _parse_list_pagination(request.GET)

    params = {
        'start_date': start_date,
        'end_date': end_date,
        'page': page,
        'page_size': page_size,
    }
    params.update(filters)
    return params, None


# ============================================================
# 生命周期操作
# ============================================================

def create_draft(user, form, request=None):
    """新建草稿。值班员和 created_by 固定为当前用户。"""
    duty_person_name = user.nickname or user.username
    record = DepartmentDutyLog.objects.create(
        duty_date=form['duty_date'],
        duty_person=user,
        duty_person_name=duty_person_name,
        mains_voltage=form['mains_voltage'],
        ups_voltage=form['ups_voltage'],
        weather=form['weather'],
        duty_record=form['duty_record'],
        remark=form['remark'],
        status=STATUS_DRAFT,
        version=1,
        created_by=user,
    )

    # 审计
    try:
        record_audit_event(
            request=request,
            action='create',
            target_type='department_duty_log',
            target_id=str(record.id),
            target_name='新建部门值班日志草稿',
            detail={
                'record_id': record.id,
                'duty_date': _format_date(record.duty_date),
                'duty_person_name': record.duty_person_name,
                'mains_voltage': record.mains_voltage or '',
                'ups_voltage': record.ups_voltage or '',
                'version': record.version,
            },
            is_success=True,
        )
    except Exception:
        logger.error('[DepartmentDutyLog] create audit failed', exc_info=True)

    return record, None


def update_draft(record_id, user, form, request=None):
    """编辑本人草稿（乐观锁）。"""
    # 先检查可见性和所有权
    record = DepartmentDutyLog.objects.filter(
        pk=record_id, deleted_at__isnull=True,
    ).first()
    if not record:
        return None, '记录不存在'
    if record.status != STATUS_DRAFT:
        return None, '已签署记录不可编辑'
    if record.duty_person_id != user.id:
        return None, '只能编辑本人草稿'

    # 收集变更字段
    old_snapshot = {
        'duty_date': _format_date(record.duty_date),
        'mains_voltage': record.mains_voltage or '',
        'ups_voltage': record.ups_voltage or '',
        'weather': record.weather or '',
        'duty_record_sha256': _sha256_text(record.duty_record),
        'remark_sha256': _sha256_text(record.remark or ''),
        'version': record.version,
    }

    # 原子条件更新
    updated = DepartmentDutyLog.objects.filter(
        pk=record_id,
        status=STATUS_DRAFT,
        deleted_at__isnull=True,
        duty_person_id=user.id,
        version=form['version'],
    ).update(
        duty_date=form['duty_date'],
        mains_voltage=form['mains_voltage'],
        ups_voltage=form['ups_voltage'],
        weather=form['weather'],
        duty_record=form['duty_record'],
        remark=form['remark'],
        version=F('version') + 1,
        updated_at=human_datetime(),
        updated_by_id=user.id,
    )

    if updated == 0:
        return None, '记录不存在、无权操作或版本冲突，请刷新后重试'

    # 重新读取
    record = DepartmentDutyLog.objects.get(pk=record_id)
    new_snapshot = {
        'duty_date': _format_date(record.duty_date),
        'mains_voltage': record.mains_voltage or '',
        'ups_voltage': record.ups_voltage or '',
        'weather': record.weather or '',
        'duty_record_sha256': _sha256_text(record.duty_record),
        'remark_sha256': _sha256_text(record.remark or ''),
        'version': record.version,
    }
    changed_fields = [k for k in new_snapshot if new_snapshot[k] != old_snapshot[k]]

    # 审计
    try:
        record_audit_event(
            request=request,
            action='update',
            target_type='department_duty_log',
            target_id=str(record.id),
            target_name='编辑部门值班日志草稿',
            detail={
                'record_id': record.id,
                'changed_fields': changed_fields,
                'before': old_snapshot,
                'after': new_snapshot,
            },
            is_success=True,
        )
    except Exception:
        logger.error('[DepartmentDutyLog] update audit failed', exc_info=True)

    return record, None


def soft_delete_draft(record_id, user, request=None):
    """软删除本人草稿。"""
    record = DepartmentDutyLog.objects.filter(
        pk=record_id, deleted_at__isnull=True,
    ).first()
    if not record:
        return None, '记录不存在'
    if record.status != STATUS_DRAFT:
        return None, '已签署记录不可删除'
    if record.duty_person_id != user.id:
        return None, '只能删除本人草稿'

    deleted_snapshot = {
        'record_id': record.id,
        'duty_date': _format_date(record.duty_date),
        'duty_person_name': record.duty_person_name,
        'version': record.version,
    }

    updated = DepartmentDutyLog.objects.filter(
        pk=record_id,
        status=STATUS_DRAFT,
        deleted_at__isnull=True,
        duty_person_id=user.id,
    ).update(
        deleted_at=human_datetime(),
        deleted_by_id=user.id,
    )

    if updated == 0:
        return None, '记录不存在或无权操作'

    # 审计
    try:
        record_audit_event(
            request=request,
            action='delete',
            target_type='department_duty_log',
            target_id=str(record.id),
            target_name='删除部门值班日志草稿',
            detail=deleted_snapshot,
            is_success=True,
        )
    except Exception:
        logger.error('[DepartmentDutyLog] delete audit failed', exc_info=True)

    return True, None


def sign_draft(record_id, user, client_version, request_id, confirm, request=None):
    """签署本人草稿。

    在同一外层事务中完成：锁定草稿 -> 校验 -> 生成快照 -> apply_signature ->
    回写签署字段 -> 状态变更。
    """
    if not confirm:
        return None, '请确认签署'
    if not request_id:
        return None, '缺少请求 ID'

    try:
        with transaction.atomic():
            # 锁定草稿
            record = DepartmentDutyLog.objects.select_for_update().filter(
                pk=record_id, deleted_at__isnull=True,
            ).first()
            if not record:
                raise _DutyLogError('记录不存在')
            if record.status != STATUS_DRAFT:
                raise _DutyLogError('当前记录状态不可签署')
            if record.duty_person_id != user.id:
                raise _DutyLogError('只能签署本人草稿')
            if client_version is not None and record.version != client_version:
                raise _DutyLogError('版本不一致，请刷新后重试')

            # 生成业务快照
            snapshot = build_business_snapshot(record)

            # 调用签名服务
            usage, error = apply_signature(
                actor=user,
                module=MODULE,
                object_type=OBJECT_TYPE,
                object_id=str(record.id),
                scene_code=SCENE_CODE,
                business_snapshot=snapshot,
                request_id=request_id,
                request=request,
            )
            if error:
                raise _DutyLogError(error)

            # 回写签署字段
            updated = DepartmentDutyLog.objects.filter(
                pk=record_id,
                status=STATUS_DRAFT,
                deleted_at__isnull=True,
                duty_person_id=user.id,
                version=record.version,
            ).update(
                status=STATUS_SIGNED,
                version=F('version') + 1,
                signature_usage_id=usage['usage_id'],
                signed_by_id=user.id,
                signed_by_name=usage['signer_name'],
                signed_at=usage['signed_at'],
                signature_version=usage['signature_version'],
                signature_sha256=usage['signature_sha256'],
                business_snapshot_hash=usage['business_snapshot_hash'],
            )

            if updated == 0:
                raise _DutyLogError('签署失败：记录状态已变更，请刷新后重试')

            record = DepartmentDutyLog.objects.get(pk=record_id)

            # 审计
            try:
                record_audit_event(
                    request=request,
                    action='update',
                    target_type='department_duty_log',
                    target_id=str(record.id),
                    target_name='签署部门值班日志',
                    detail={
                        'record_id': record.id,
                        'signature_usage_id': record.signature_usage_id,
                        'signature_version': record.signature_version,
                        'signature_sha256': record.signature_sha256,
                        'business_snapshot_hash': record.business_snapshot_hash,
                    },
                    is_success=True,
                )
            except Exception:
                logger.error('[DepartmentDutyLog] sign audit failed', exc_info=True)

            return record, None

    except _DutyLogError as e:
        return None, str(e)


def void_signed_record(record_id, user, reason, request=None):
    """作废已签记录。原因必填。"""
    reason = (reason or '').strip()
    if not reason:
        return None, '作废原因不能为空'
    if len(reason) > MAX_VOID_REASON_LEN:
        return None, '作废原因过长'

    try:
        with transaction.atomic():
            record = DepartmentDutyLog.objects.select_for_update().filter(
                pk=record_id, deleted_at__isnull=True,
            ).first()
            if not record:
                return None, '记录不存在'
            if record.status != STATUS_SIGNED:
                return None, '只能作废已签署记录'

            usage_id = record.signature_usage_id

            updated = DepartmentDutyLog.objects.filter(
                pk=record_id,
                status=STATUS_SIGNED,
                deleted_at__isnull=True,
            ).update(
                status=STATUS_VOID,
                voided_at=human_datetime(),
                voided_by_id=user.id,
                void_reason=reason,
            )

            if updated == 0:
                return None, '作废失败：记录状态已变更'

            # 写 void 证据事件（使用原 Usage tenant 链）
            if usage_id:
                void_err = signature_services.record_signature_void_event(
                    usage_id=usage_id,
                    actor=user,
                    module=MODULE,
                    object_type=OBJECT_TYPE,
                    object_id=str(record.id),
                    scene_code=SCENE_CODE,
                    reason=reason,
                    request=request,
                )
                if void_err:
                    # 证据事件失败 → 回滚作废
                    raise _DutyLogError(void_err)

            # 业务审计
            try:
                record_audit_event(
                    request=request,
                    action='update',
                    target_type='department_duty_log',
                    target_id=str(record.id),
                    target_name='作废部门值班日志',
                    detail={
                        'record_id': record.id,
                        'signature_usage_id': usage_id,
                        'voided_by_id': user.id,
                        'voided_by_name': user.nickname or user.username,
                        'void_reason': reason,
                    },
                    is_success=True,
                )
            except Exception:
                logger.error('[DepartmentDutyLog] void audit failed', exc_info=True)

            record = DepartmentDutyLog.objects.get(pk=record_id)
            return record, None

    except _DutyLogError as e:
        return None, str(e)


def create_correction_draft(voided_record_id, user, request=None):
    """基于已作废记录创建更正草稿。

    - 目标必须是未删除 void 记录
    - 新草稿值班员和 created_by 固定为当前用户
    - supersedes_id 指向原 void 记录
    - 复制业务字段，不复制签署/作废/删除/审计/版本字段
    """
    voided = DepartmentDutyLog.objects.filter(
        pk=voided_record_id, deleted_at__isnull=True,
    ).first()
    if not voided:
        return None, '原记录不存在'
    if voided.status != STATUS_VOID:
        return None, '只能基于已作废记录创建更正'

    duty_person_name = user.nickname or user.username
    record = DepartmentDutyLog.objects.create(
        duty_date=voided.duty_date,
        duty_person=user,
        duty_person_name=duty_person_name,
        mains_voltage=voided.mains_voltage,
        ups_voltage=voided.ups_voltage,
        weather=voided.weather,
        duty_record=voided.duty_record,
        remark=voided.remark,
        status=STATUS_DRAFT,
        version=1,
        supersedes=voided,
        created_by=user,
    )

    # 审计
    try:
        record_audit_event(
            request=request,
            action='create',
            target_type='department_duty_log',
            target_id=str(record.id),
            target_name='更正部门值班日志',
            detail={
                'new_record_id': record.id,
                'voided_record_id': voided.id,
                'supersedes_id': voided.id,
            },
            is_success=True,
        )
    except Exception:
        logger.error('[DepartmentDutyLog] correction audit failed', exc_info=True)

    return record, None


# ============================================================
# 选项
# ============================================================

def get_options(user):
    """返回当前用户信息。"""
    current_user = {
        'id': user.id,
        'name': user.nickname or user.username,
    }

    return {
        'current_user': current_user,
    }


# ============================================================
# 内部异常
# ============================================================

class _DutyLogError(Exception):
    """业务流程中可向用户展示的错误，用于事务内中断并触发回滚。"""
