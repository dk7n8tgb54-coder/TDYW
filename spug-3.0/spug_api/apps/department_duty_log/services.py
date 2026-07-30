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

from django.utils import timezone
from apps.logs.audit import record_audit_event
from apps.signature import services as signature_services
from apps.signature.services import apply_signature

from .models import (
    DepartmentDutyLog,
    STATUS_DRAFT, STATUS_SIGNED,
)

logger = logging.getLogger(__name__)

# ---- 签署场景常量 ----
MODULE = 'department_duty_log'
OBJECT_TYPE = 'department_duty_log'
SCENE_CODE = 'duty_person'

# ---- 输入长度限制 ----
MAX_WEATHER_LEN = 50
MAX_DUTY_RECORD_LEN = 10000
MAX_REMARK_LEN = 2000
MAX_KEYWORD_LEN = 100
MAX_DUTY_PERSON_NAME_LEN = 100

# ---- 受保护字段：客户端提交时必须拒绝 ----
PROTECTED_FIELDS = frozenset({
    'tenant_id', 'duty_person', 'duty_person_id', 'duty_person_name',
    'created_by', 'created_by_id', 'updated_by', 'updated_by_id',
    'deleted_by', 'deleted_by_id', 'signed_by', 'signed_by_id',
    'signed_by_name', 'signed_at', 'signature_usage_id',
    'signature_version', 'signature_sha256', 'business_snapshot_hash',
    'status', 'supersedes', 'supersedes_id', 'created_at', 'updated_at', 'deleted_at',
    'id',
})

# 默认查询天数
DEFAULT_QUERY_DAYS = 31
# P3(R9): 最大查询天数，防止无界查询导致 TextField LIKE 全表扫描
MAX_QUERY_DAYS = 365


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
    """可选字符串：None/空串返回空串，非空去空格+校验长度。"""
    if value is None or value == '':
        return ''
    if not isinstance(value, str):
        raise ValueError(f'{field_name} 格式不正确')
    value = value.strip()
    if not value:
        return ''
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
        weather = _clean_str(raw_data.get('weather'), MAX_WEATHER_LEN, '天气情况', required=True)
        duty_record = _clean_str(raw_data.get('duty_record'), MAX_DUTY_RECORD_LEN, '值班记录', required=True)
        remark = _clean_optional_str(raw_data.get('remark'), MAX_REMARK_LEN, '备注')
    except ValueError as e:
        return None, str(e)

    form = {
        'duty_date': duty_date,
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
    }
    data.update(compute_record_capabilities(record, user))
    return data


def serialize_list_item(record, user):
    """序列化列表项，包含完整正文供编辑回填。"""
    record_text = record.duty_record or ''
    summary = record_text[:100] + '...' if len(record_text) > 100 else record_text
    data = {
        'id': record.id,
        'duty_date': _format_date(record.duty_date),
        'duty_person_name': record.duty_person_name,
        'weather': record.weather or '',
        'duty_record': record_text,
        'duty_record_summary': summary,
        'remark': record.remark or '',
        'status': record.status,
        'version': record.version,
        'signature_usage_id': record.signature_usage_id,
        'signed_by_name': record.signed_by_name or '',
        'signed_at': record.signed_at or '',
        'signature_version': record.signature_version,
        'business_snapshot_hash': record.business_snapshot_hash or '',
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
        'can_return': bool(is_signed and user.has_perms(['department_duty_log.department_duty_log.return'])),
        # 已签记录可被导出；草稿永不进入导出
        'can_export': bool(
            is_signed
            and user.has_perms(['department_duty_log.department_duty_log.export'])
        ),
    }


# ============================================================
# 可见性查询
# ============================================================

def get_visible_department_duty_logs(user):
    """返回当前用户可见的基础 QuerySet（未删除 + 可见性过滤）。

    - 超级管理员：可见全部未删除记录（含他人草稿），仅查看，不授予编辑/删除/签署他人草稿的能力（由 compute_record_capabilities 的 is_owner 限制保证）。
    - 普通用户：已签全局可见，草稿仅本人可见。
    不加任何租户条件。
    """
    qs = DepartmentDutyLog.objects.filter(deleted_at__isnull=True)
    if getattr(user, 'is_supper', False):
        return qs
    return qs.filter(
        Q(status=STATUS_SIGNED) |
        Q(status=STATUS_DRAFT, duty_person_id=user.id)
    )


def list_duty_dates(user, year, month):
    """返回当前用户可见的某月内已有值班日志的 duty_date 列表（去重，升序）。

    供前端日期选择器在面板上标记已有值班日志的日期。
    仅返回日期字符串（YYYY-MM-DD），不暴露任何业务字段。
    """
    qs = get_visible_department_duty_logs(user)
    # P0(R2): 改用 __gte/__lt 半开区间范围查询。
    # Django 4.2 已将 __year 优化为 BETWEEN（走索引），但 __month 仍生成
    # EXTRACT(MONTH FROM duty_date)=N 函数调用，绕过索引。
    # 半开区间 __gte/__lt 同时消除 EXTRACT 函数和 BETWEEN 闭区间，最稳妥。
    # 已通过 EXPLAIN 验证：含 OR 可见性条件时仍走 duty_log_date_idx 索引。
    start_date = date(year, month, 1)
    end_date = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    qs = qs.filter(
        duty_date__gte=start_date,
        duty_date__lt=end_date,
    )
    values = (
        qs.values_list('duty_date', flat=True)
        .order_by('duty_date')
        .distinct()
    )
    return [d.isoformat() for d in values]


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
    # P3(R9): 限制最大查询范围，防止无界 TextField LIKE 扫描
    if (end_date - start_date).days > MAX_QUERY_DAYS:
        return None, None, f'查询范围不能超过 {MAX_QUERY_DAYS} 天'
    return start_date, end_date, None


def _parse_list_filters(query_params):
    """解析列表筛选参数。返回 (filter_dict, error_str)。"""
    filters = {}
    duty_person_name = query_params.get('duty_person_name', '').strip()
    if duty_person_name:
        if len(duty_person_name) > MAX_DUTY_PERSON_NAME_LEN:
            return None, '值班人员姓名过长'
        filters['duty_person_name'] = duty_person_name

    status = query_params.get('status', '').strip()
    if status:
        if status not in (STATUS_DRAFT, STATUS_SIGNED):
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
    """新建草稿。值班人员和 created_by 固定为当前用户。"""
    duty_person_name = user.nickname or user.username
    record = DepartmentDutyLog.objects.create(
        duty_date=form['duty_date'],
        duty_person=user,
        duty_person_name=duty_person_name,
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
        weather=form['weather'],
        duty_record=form['duty_record'],
        remark=form['remark'],
        version=F('version') + 1,
        updated_at=timezone.now(),
        updated_by_id=user.id,
    )

    if updated == 0:
        return None, '记录不存在、无权操作或版本冲突，请刷新后重试'

    # 重新读取
    record = DepartmentDutyLog.objects.get(pk=record_id)
    new_snapshot = {
        'duty_date': _format_date(record.duty_date),
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
        deleted_at=timezone.now(),
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


def return_signed_record(record_id, user, request=None):
    """退回已签记录到草稿状态。

    清除所有签署字段，状态改回 draft，记录退回到值班人员。
    保留审计日志记录原签署信息以供追溯。
    """
    try:
        with transaction.atomic():
            record = DepartmentDutyLog.objects.select_for_update().filter(
                pk=record_id, deleted_at__isnull=True,
            ).first()
            if not record:
                return None, '记录不存在'
            if record.status != STATUS_SIGNED:
                return None, '只能退回已签署记录'

            # 保存原签署信息用于审计
            original_signer_id = record.signed_by_id
            original_signer_name = record.signed_by_name
            original_signed_at = record.signed_at
            original_usage_id = record.signature_usage_id

            updated = DepartmentDutyLog.objects.filter(
                pk=record_id,
                status=STATUS_SIGNED,
                deleted_at__isnull=True,
            ).update(
                status=STATUS_DRAFT,
                signed_by=None,
                signed_by_name='',
                signed_at=None,
                signature_usage_id=None,
                signature_version=None,
                signature_sha256='',
                business_snapshot_hash='',
                version=F('version') + 1,
            )

            if updated == 0:
                return None, '退回失败：记录状态已变更'

            # 写 void 证据事件（使用原 Usage tenant 链）
            if original_usage_id:
                void_err = signature_services.record_signature_void_event(
                    usage_id=original_usage_id,
                    actor=user,
                    module=MODULE,
                    object_type=OBJECT_TYPE,
                    object_id=str(record.id),
                    scene_code=SCENE_CODE,
                    reason='管理员退回',
                    request=request,
                )
                if void_err:
                    raise _DutyLogError(void_err)

            # 业务审计
            try:
                record_audit_event(
                    request=request,
                    action='update',
                    target_type='department_duty_log',
                    target_id=str(record.id),
                    target_name='退回部门值班日志',
                    detail={
                        'record_id': record.id,
                        'returned_by_id': user.id,
                        'returned_by_name': user.nickname or user.username,
                        'original_signer_id': original_signer_id,
                        'original_signer_name': original_signer_name,
                        'original_signed_at': str(original_signed_at) if original_signed_at else '',
                        'original_usage_id': original_usage_id,
                    },
                    is_success=True,
                )
            except Exception:
                logger.error('[DepartmentDutyLog] return audit failed', exc_info=True)

            record = DepartmentDutyLog.objects.get(pk=record_id)
            return record, None

    except _DutyLogError as e:
        return None, str(e)



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
# PDF 导出
# ============================================================

# 单次导出上限（提示词第 824 条：单次最多 500 条）
PDF_EXPORT_LIMIT = 500


def _parse_export_filters(raw_data):
    """解析 PDF 导出请求体筛选参数。

    与列表筛选保持一致：start_date / end_date / duty_person_name / keyword。
    额外支持导出筛选。

    Returns:
        (filters_dict, error_str)
    """
    if not isinstance(raw_data, dict):
        return None, '请求体格式不正确'

    filters = {}

    # 日期范围（导出允许更宽范围，不强制 31 天默认）
    start_date_str = str(raw_data.get('start_date', '')).strip()
    end_date_str = str(raw_data.get('end_date', '')).strip()
    try:
        if start_date_str:
            filters['start_date'] = _parse_date(start_date_str, '开始日期')
        if end_date_str:
            filters['end_date'] = _parse_date(end_date_str, '结束日期')
    except ValueError as e:
        return None, str(e)
    if filters.get('start_date') and filters.get('end_date') \
            and filters['end_date'] < filters['start_date']:
        return None, '结束日期不能早于开始日期'

    # 值班人员姓名
    duty_person_name = str(raw_data.get('duty_person_name', '')).strip()
    if duty_person_name:
        if len(duty_person_name) > MAX_DUTY_PERSON_NAME_LEN:
            return None, '值班人员姓名过长'
        filters['duty_person_name'] = duty_person_name

    # 关键字
    keyword = str(raw_data.get('keyword', '')).strip()
    if keyword:
        if len(keyword) > MAX_KEYWORD_LEN:
            return None, '关键字过长'
        filters['keyword'] = keyword

    return filters, None


def _get_export_queryset(user, filters):
    """构建 PDF 导出 QuerySet。

    只导出 view 可见的已签记录，永不导出草稿。
    """
    qs = DepartmentDutyLog.objects.filter(deleted_at__isnull=True)

    # 状态过滤：草稿永不导出
    qs = qs.filter(status=STATUS_SIGNED)

    # 日期范围
    start_date = filters.get('start_date')
    end_date = filters.get('end_date')
    if start_date:
        qs = qs.filter(duty_date__gte=start_date)
    if end_date:
        qs = qs.filter(duty_date__lte=end_date)

    # 值班人员姓名（跨租户可见，无需额外过滤）
    duty_person_name = filters.get('duty_person_name')
    if duty_person_name:
        qs = qs.filter(duty_person_name__icontains=duty_person_name)

    # 关键字
    keyword = filters.get('keyword')
    if keyword:
        qs = qs.filter(Q(duty_record__icontains=keyword) | Q(remark__icontains=keyword))

    # PDF 导出按日期从早到晚排列（覆盖模型默认的倒序）
    return qs.order_by('duty_date', 'id')


def _build_filters_text(filters):
    """构建筛选条件的人类可读描述（用于 PDF 副标题）。"""
    parts = []
    start_date = filters.get('start_date')
    end_date = filters.get('end_date')
    if start_date and end_date:
        parts.append(f'{start_date}~{end_date}')
    elif start_date:
        parts.append(f'{start_date}起')
    elif end_date:
        parts.append(f'至{end_date}')
    if filters.get('duty_person_name'):
        parts.append(f'值班人员={filters["duty_person_name"]}')
    if filters.get('keyword'):
        parts.append(f'关键字={filters["keyword"]}')
    return '，'.join(parts) if parts else '全部已签'


def _serialize_for_pdf(record):
    """序列化为 PDF 渲染所需的 dict（含完整长文本和签署字段）。"""
    return {
        'id': record.id,
        'duty_date': _format_date(record.duty_date),
        'duty_person_name': record.duty_person_name or '',
        'department_name': '',
        'weather': record.weather or '',
        'duty_record': record.duty_record or '',
        'remark': record.remark or '',
        'status': record.status,
        'signature_usage_id': record.signature_usage_id,
        'signed_by_name': record.signed_by_name or '',
        'signed_at': record.signed_at or '',
        'signature_version': record.signature_version,
        'signature_sha256': record.signature_sha256 or '',
        'business_snapshot_hash': record.business_snapshot_hash or '',
    }


def _user_display_name(user_id):
    """根据 user_id 查询显示名（避免 N+1，调用方应批量预取）。"""
    if not user_id:
        return ''
    from apps.account.models import User
    u = User.objects.filter(pk=user_id).only('nickname', 'username').first()
    if not u:
        return f'用户#{user_id}'
    return u.nickname or u.username


def export_pdf(user, raw_data, request=None):
    """生成部门值班日志 PDF。

    流程：
    1. 解析筛选参数；
    2. 构建 QuerySet（已签，不含草稿）；
    3. 检查导出上限（500）；
    4. 逐条通过 signature_usage_id 调用签名公共服务读取固定版本签名图片
       （完整校验 SHA256 + 业务坐标匹配），任一校验失败则拒绝生成不完整 PDF；
    5. 调用 pdf_export 生成 PDF；
    6. 计算 PDF SHA256；
    7. 写审计（含 filters / record_ids / record_count / pdf_sha256）。

    Returns:
        (pdf_bytes, filename, error_str)
        - 成功：pdf_bytes 为 bytes，filename 为建议文件名
        - 失败：pdf_bytes 为 None，error_str 非空
    """
    from . import pdf_export
    from apps.signature import services as signature_services

    filters, error = _parse_export_filters(raw_data)
    if error:
        return None, None, error

    qs = _get_export_queryset(user, filters)

    # 上限检查
    total = qs.count()
    if total == 0:
        return None, None, '当前筛选条件下没有可导出的已签记录'
    if total > PDF_EXPORT_LIMIT:
        return None, None, f'导出数据超过 {PDF_EXPORT_LIMIT} 条，请缩小筛选范围后重试'

    # 拉取全部记录（按 duty_date 升序排列：从早到晚）
    records = list(qs.select_related('duty_person', 'signed_by').order_by('duty_date', 'id'))

    # 序列化 + 收集每条记录对应的签名图片（已校验 SHA256）
    serialized = []
    signature_images = {}  # record_id -> reportlab Image 或 None

    for record in records:
        item = _serialize_for_pdf(record)
        serialized.append(item)

        # 已签记录必须有 signature_usage_id
        if not record.signature_usage_id:
            return None, None, f'记录 {record.id} 缺少签署记录 ID，无法生成完整 PDF'

        info, sig_err = signature_services.get_signature_image_for_global_business(
            usage_id=record.signature_usage_id,
            module=MODULE,
            object_type=OBJECT_TYPE,
            object_id=str(record.id),
            scene_code=SCENE_CODE,
        )
        if sig_err:
            logger.warning(
                '[DepartmentDutyLog PDF] signature verify failed: record_id=%s usage_id=%s err=%s',
                record.id, record.signature_usage_id, sig_err,
            )
            return None, None, f'记录 {record.id} 签名校验失败：{sig_err}'

        # 构建等比例缩放的 Image（可能返回 None，比如 PIL 不可用）
        sig_img = pdf_export._build_signature_image(info['file_path'])
        if sig_img is None:
            return None, None, f'记录 {record.id} 签名图片读取失败'
        signature_images[record.id] = sig_img

    # 生成 PDF
    filters_text = _build_filters_text(filters)
    exporter_name = user.nickname or user.username

    try:
        pdf_output = pdf_export.generate_department_duty_log_pdf(
            serialized,
            exporter_name=exporter_name,
            filters_text=filters_text,
            signature_images=signature_images,
        )
        pdf_bytes = pdf_output.getvalue()
    except Exception as e:
        logger.error('[DepartmentDutyLog PDF] generate failed', exc_info=True)
        return None, None, f'PDF 生成失败：{e}'

    # 计算 PDF SHA256
    pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()

    # 文件名：部门值班日志_YYYYMMDD_HHmmss.pdf
    from datetime import datetime
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'部门值班日志_{timestamp}.pdf'

    # 审计
    try:
        record_audit_event(
            request=request,
            action='export',
            target_type='department_duty_log',
            target_id=None,
            target_name='导出部门值班日志 PDF',
            detail={
                'format': 'pdf',
                'filters': {
                    'start_date': _format_date(filters.get('start_date')) if filters.get('start_date') else '',
                    'end_date': _format_date(filters.get('end_date')) if filters.get('end_date') else '',
                    'duty_person_name': filters.get('duty_person_name', ''),
                    'keyword': filters.get('keyword', ''),
                },
                'record_ids': [r.id for r in records],
                'record_count': len(records),
                'pdf_sha256': pdf_sha256,
            },
            is_success=True,
        )
    except Exception:
        logger.error('[DepartmentDutyLog PDF] audit failed', exc_info=True)

    logger.info(
        '[DepartmentDutyLog PDF] export success: user=%s records=%d sha256=%s',
        user.id, len(records), pdf_sha256,
    )

    return pdf_bytes, filename, None


# ============================================================
# 内部异常
# ============================================================

class _DutyLogError(Exception):
    """业务流程中可向用户展示的错误，用于事务内中断并触发回滚。"""
