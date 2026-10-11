# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""设备全生命周期——系统主数据视图（步骤二）。

权限域（前后端一致，后端独立校验）：
- equipment_lifecycle.system.view|add|edit|del|deactivate|export

系统新增（POST /systems/）与编辑（PUT /systems/<pk>/）支持结构化聚合提交：
{"system": {...}}。固定字段在同一事务内写入；旧平铺载荷仍兼容。
自定义配置字段/系统当前配置/配置附件接口已于 2026-09 下线一并移除，
扩展信息由固定字段承载（callsign 呼号 / geo_coordinate 安装经纬度 /
work_frequency 工作频率，均选填）。
系统编号（system_code）为后端内部标识：新增时由后端自动生成（租户内唯一、
创建后不可修改），客户端传入的取值一律忽略，前端不展示。

所有写操作记录业务审计（record_audit_event）；
所有查询经租户过滤（apply_tenant_filter / TenantModelManager.for_user）。
"""
import csv
import io
import json
from datetime import datetime
from secrets import token_hex

from django.db import IntegrityError, models, transaction
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from django.views.generic import View

from libs import JsonParser, Argument, json_response, auth
from libs.tenant_utils import apply_tenant_filter
from apps.logs.audit import record_audit_event

from apps.equipment_lifecycle.models import (
    LifecycleSystem,
)
from apps.equipment_lifecycle import operation_services
from apps.equipment_lifecycle.operation_models import SystemOperationRecord

AUDIT_TARGET_SYSTEM = 'el_system'

# 本模块附件归属标识（module 常量，台账等附件场景共用；object_type 由各业务自定义）
EL_ATTACHMENT_MODULE = 'equipment_lifecycle'

COMPONENT_MAINTENANCE_EMPTY = {'fault_count': 0}


def _component_maintenance_rows(systems):
    """部件维护状态汇总（与系统运行健康状态分离展示）。

    - fault_count：有效（处置中）且不影响系统运行的正式故障数（部件故障提示）。
    部件故障不参与系统健康状态计算，只作独立提示展示（"维修中"已随
    故障维修工单功能整体删除，2026-09-30；合并改造后只统计统一主表内
    record_type=fault 的处置中记录）；
    入参 systems 必须来自租户过滤后的查询结果，避免跨租户计数。
    返回 {system_id: {'fault_count': n}}。
    """
    ids = [s.id for s in systems]
    if not ids:
        return {}
    result = {i: dict(COMPONENT_MAINTENANCE_EMPTY) for i in ids}
    fault_rows = (
        SystemOperationRecord.objects
        .filter(system_id__in=ids,
                record_type='fault',
                status__in=operation_services.ACTIVE_FAULT_STATUSES,
                affects_system_operation=False)
        .values_list('system_id')
        .annotate(total=models.Count('id')))
    for system_id, total in fault_rows:
        result[system_id]['fault_count'] = total
    return result


DATE_FORMAT = '%Y-%m-%d'
# 兼容历史调用仍提交带时分的值：只取日期部分，时间丢弃
LEGACY_DATETIME_FORMATS = ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M')


def _parse_date(value):
    """解析安装/启用时间为 date；非法返回 None。"""
    text = str(value or '').strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, DATE_FORMAT).date()
    except ValueError:
        pass
    for fmt in LEGACY_DATETIME_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None

# 系统固定字段的变更历史展示名（与模型 help_text 口径一致）
# 注意：health_status 由有效正式故障统一计算（operation_services），不属于可编辑固定字段
FIXED_CHANGE_LABELS = {
    'name': '系统名称', 'system_model': '系统型号', 'install_location': '安装地点',
    'geo_coordinate': '安装经纬度', 'callsign': '呼号',
    'work_frequency': '工作频率', 'system_purpose': '系统用途',
    'manufacturer': '生产厂家', 'install_unit': '安装单位', 'use_unit': '使用单位',
    'install_time': '安装时间', 'enable_time': '启用时间',
    'responsible_user_name': '系统负责人', 'remark': '备注',
}


def _read_json_body(request):
    """读取 JSON 请求体为 dict；格式不合法返回 None。"""
    try:
        body = json.loads(request.body.decode('utf-8')) if request.body else {}
    except (ValueError, UnicodeDecodeError):
        return None
    return body if isinstance(body, dict) else None


def _parse_system_fields(data):
    """解析系统固定字段（data 为已解析的 dict）。

    system_code 为后端内部标识，不接收客户端取值，新增时自动生成。
    """
    parser = JsonParser(
        Argument('name', type=str, required=True, help='系统名称'),
        Argument('system_model', type=str, required=True, help='系统型号'),
        Argument('install_location', type=str, required=True, help='安装地点'),
        Argument('geo_coordinate', type=str, required=False, default=''),
        Argument('callsign', type=str, required=False, default=''),
        Argument('work_frequency', type=str, required=False, default=''),
        Argument('system_purpose', type=str, required=False, default=''),
        Argument('manufacturer', type=str, required=True, help='生产厂家'),
        Argument('install_unit', type=str, required=True, help='安装单位'),
        Argument('use_unit', type=str, required=True, help='使用单位'),
        Argument('install_time', type=str, required=True, help='安装时间'),
        Argument('enable_time', type=str, required=True, help='启用时间'),
        Argument('responsible_user_name', type=str, required=True, help='系统负责人'),
        Argument('remark', type=str, required=False, default=''),
    )
    return parser.parse(data or {})


def _fixed_field_snapshot(item):
    """提取参与变更历史比对的系统固定字段快照。

    health_status 不参与比对：它由有效正式故障统一计算（operation_services），
    不是用户可编辑字段，其变化通过健康状态审计留痕（系统履历已退役）。
    """
    return {
        'name': item.name, 'system_model': item.system_model,
        'install_location': item.install_location, 'geo_coordinate': item.geo_coordinate,
        'callsign': item.callsign, 'work_frequency': item.work_frequency,
        'system_purpose': item.system_purpose, 'manufacturer': item.manufacturer,
        'install_unit': item.install_unit, 'use_unit': item.use_unit,
        'install_time': item.install_time.isoformat() if item.install_time else '',
        'enable_time': item.enable_time.isoformat() if item.enable_time else '',
        'responsible_user_name': item.responsible_user_name, 'remark': item.remark,
    }


def _diff_fixed_changes(before, after):
    """比较固定字段前后快照，生成差异条目（供保存审计 before_value）。"""
    return [
        {'scope': 'fixed', 'code': key, 'label': FIXED_CHANGE_LABELS[key],
         'old': before[key], 'new': after[key]}
        for key in before if before[key] != after[key]
    ]


def _apply_fixed_fields(item, form, install_time, enable_time, user):
    """把校验通过的固定字段写入系统实例（不落库）。

    health_status 不在此写入：普通系统编辑不能覆盖由有效故障计算的健康状态
    （步骤 3.5 收口，新建系统初始化为 normal，后续变化只由重算服务写入）。
    """
    item.name = form.name.strip()
    item.system_model = form.system_model.strip()
    item.install_location = form.install_location.strip()
    item.geo_coordinate = (form.geo_coordinate or '').strip()
    item.callsign = (form.callsign or '').strip()[:50]
    item.work_frequency = (form.work_frequency or '').strip()[:100]
    item.system_purpose = (form.system_purpose or '').strip()[:500]
    item.manufacturer = form.manufacturer.strip()
    item.install_unit = form.install_unit.strip()
    item.use_unit = form.use_unit.strip()
    item.install_time = install_time
    item.enable_time = enable_time
    item.responsible_user_name = form.responsible_user_name.strip()
    item.remark = (form.remark or '').strip()[:1000]
    item.updated_at = timezone.now()
    item.updated_by = user


def _validate_system_fixed_payload(request, form):
    """校验系统固定字段公共部分，返回 (install_time, enable_time, error)。

    system_code 不来自客户端：新增由 _generate_system_code 生成，编辑保持原值。
    安装/启用时间只需日期（YYYY-MM-DD）；仍兼容历史调用提交的带时分值，时间部分丢弃。
    """
    err = SystemView._check_geo(form.geo_coordinate)
    if err:
        return None, None, err
    install_time = _parse_date(form.install_time)
    enable_time = _parse_date(form.enable_time)
    if not install_time or not enable_time:
        return None, None, '安装时间/启用时间格式不正确，应为 YYYY-MM-DD'
    return install_time, enable_time, None


def _generate_system_code(user):
    """生成租户内唯一的系统编号：SYS-日期-6位随机十六进制。

    编号仅作后端标识（快照/审计/导出命名），不向前端展示。预检查避开已有
    编号，极小概率的并发碰撞由 (tenant_id, system_code) 唯一约束兜底。
    """
    # USE_TZ=False 下 timezone.now() 即本地 naive 时间，直接取日期（localdate 会抛错）
    prefix = 'SYS-%s-' % timezone.now().strftime('%Y%m%d')
    for _ in range(5):
        code = prefix + token_hex(3).upper()
        if not apply_tenant_filter(LifecycleSystem.objects.all(), user).filter(
                system_code=code).exists():
            return code
    return prefix + token_hex(8).upper()


def _get_system_for_user(pk, user):
    return apply_tenant_filter(LifecycleSystem.objects.all(), user).filter(pk=pk).first()


def _collect_system_references(system):
    """删除保护：返回引用该系统的业务对象描述列表，非空则禁止物理删除。

    运行与故障记录、运维台账明细与升级记录均以系统 ID 建立业务关联
    （PROTECT）。历史记录必须继续可查，存在关联的系统不得物理删除。
    fail-closed 语义。（"工单"引用检查已随工单功能删除，2026-09-30；
    "系统履历事件"检查已随系统履历整体退役删除，2026-10-11）
    """
    from apps.equipment_lifecycle.models import OperationLedgerItem
    from apps.equipment_lifecycle.operation_models import SystemOperationRecord
    from apps.upgrade.models import UpgradeRecord
    refs = []
    if SystemOperationRecord.objects.filter(
            tenant_id=system.tenant_id, system_id=system.id).exists():
        refs.append('运行与故障记录')
    if OperationLedgerItem.objects.filter(
            tenant_id=system.tenant_id, system_id=system.id).exists():
        refs.append('运维台账明细')
    if UpgradeRecord.objects.filter(
            tenant_id=system.tenant_id, system_id=system.id,
            is_deleted=False).exists():
        refs.append('升级记录')
    return refs


def _parse_health_status_filter(raw):
    """解析健康状态筛选参数，兼容三种提交形态，非法返回 None。

    - 前端单选以标量字符串提交（axios 不做 JSON 编码）：normal；
    - 多值以逗号分隔提交：normal,fault；
    - 历史调用以 JSON 数组字符串提交（json.dumps 形态）：["fault"]。
    """
    text = str(raw).strip()
    if not text:
        return []
    if text.startswith('['):
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            return None
        if not isinstance(data, list):
            return None
        return [str(x).strip() for x in data if str(x).strip()]
    return [part.strip() for part in text.split(',') if part.strip()]


class SystemView(View):
    @auth('equipment_lifecycle.system.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('keyword', type=str, required=False),
            # 前端单选以标量字符串提交，声明为 list 会使 JsonParser 对普通
            # 字符串执行 json.loads 而报错（见 _parse_health_status_filter）
            Argument('health_status', type=str, required=False),
            Argument('is_active', type=bool, required=False),
            Argument('use_unit', type=str, required=False),
            Argument('install_location', type=str, required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)

        query = apply_tenant_filter(LifecycleSystem.objects.all(), request.user)
        if form.keyword:
            query = query.filter(
                Q(system_code__icontains=form.keyword) | Q(name__icontains=form.keyword))
        if form.health_status:
            statuses = _parse_health_status_filter(form.health_status)
            if statuses is None:
                return json_response(error='运行健康状态筛选值不合法')
            if statuses:
                query = query.filter(health_status__in=statuses)
        if form.is_active is not None:
            query = query.filter(is_active=form.is_active)
        if form.use_unit:
            query = query.filter(use_unit__icontains=form.use_unit)
        if form.install_location:
            query = query.filter(install_location__icontains=form.install_location)

        from libs.pagination import paginate
        page, page_size = paginate(request)
        total = query.count()
        records = list(query[(page - 1) * page_size: page * page_size])
        # 部件维护提示与系统健康状态分离展示（部件故障/部件维修中不影响运行状态）
        component_map = _component_maintenance_rows(records)
        rows = []
        for record in records:
            row = record.to_view()
            row['component_maintenance'] = component_map.get(
                record.id, dict(COMPONENT_MAINTENANCE_EMPTY))
            rows.append(row)
        return json_response({
            'data': rows,
            'total': total,
            'page': page,
            'page_size': page_size,
        })

    @auth('equipment_lifecycle.system.add')
    def post(self, request):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        if isinstance(body.get('system'), dict):
            return self._create_aggregate(request, body)
        form, error = _parse_system_fields(body)
        if error:
            return json_response(error=error)
        return self._create_flat(request, form)

    def _create_flat(self, request, form):
        """旧平铺载荷：仅创建系统固定字段。"""
        install_time, enable_time, error = _validate_system_fixed_payload(request, form)
        if error:
            return json_response(error=error)
        system_code = _generate_system_code(request.user)

        with transaction.atomic():
            item = LifecycleSystem.objects.create(
                tenant_id=request.user.tenant_id,
                system_code=system_code,
                name=form.name.strip(),
                system_model=form.system_model.strip(),
                install_location=form.install_location.strip(),
                geo_coordinate=(form.geo_coordinate or '').strip(),
                callsign=(form.callsign or '').strip()[:50],
                work_frequency=(form.work_frequency or '').strip()[:100],
                system_purpose=(form.system_purpose or '').strip()[:500],
                manufacturer=form.manufacturer.strip(),
                install_unit=form.install_unit.strip(),
                use_unit=form.use_unit.strip(),
                install_time=install_time,
                enable_time=enable_time,
                responsible_user_name=form.responsible_user_name.strip(),
                health_status=LifecycleSystem.HEALTH_NORMAL,
                is_active=True,
                remark=(form.remark or '').strip()[:1000],
                created_by=request.user,
            )
            record_audit_event(request, 'create', AUDIT_TARGET_SYSTEM, item.id, item.name,
                               after_value={'system_code': item.system_code, 'name': item.name})
        return json_response(item.to_view())

    def _create_aggregate(self, request, body):
        """结构化聚合创建：系统固定字段一次提交。

        所有校验在写入前完成；写操作在单事务内执行，任何一步失败整体回滚。
        已下线的 custom_fields / config_values / components 键随整体载荷被忽略。
        """
        form, error = _parse_system_fields(body.get('system'))
        if error:
            return json_response(error=error)
        install_time, enable_time, error = _validate_system_fixed_payload(request, form)
        if error:
            return json_response(error=error)
        system_code = _generate_system_code(request.user)

        try:
            with transaction.atomic():
                item = LifecycleSystem.objects.create(
                    tenant_id=request.user.tenant_id,
                    system_code=system_code,
                    name=form.name.strip(),
                    system_model=form.system_model.strip(),
                    install_location=form.install_location.strip(),
                    geo_coordinate=(form.geo_coordinate or '').strip(),
                    callsign=(form.callsign or '').strip()[:50],
                    work_frequency=(form.work_frequency or '').strip()[:100],
                    system_purpose=(form.system_purpose or '').strip()[:500],
                    manufacturer=form.manufacturer.strip(),
                    install_unit=form.install_unit.strip(),
                    use_unit=form.use_unit.strip(),
                    install_time=install_time,
                    enable_time=enable_time,
                    responsible_user_name=form.responsible_user_name.strip(),
                    health_status=LifecycleSystem.HEALTH_NORMAL,
                    is_active=True,
                    remark=(form.remark or '').strip()[:1000],
                    created_by=request.user,
                )
                record_audit_event(request, 'create', AUDIT_TARGET_SYSTEM, item.id, item.name,
                                   after_value={'system_code': item.system_code, 'name': item.name})
        except IntegrityError:
            return json_response(error='保存失败：系统编号冲突，请检查后重试')
        return json_response(item.to_view())

    @staticmethod
    def _check_geo(value):
        if not value:
            return None
        parts = str(value).split(',')
        if len(parts) != 2:
            return '安装经纬度格式应为: 经度,纬度'
        try:
            lng, lat = float(parts[0]), float(parts[1])
        except ValueError:
            return '安装经纬度格式应为: 经度,纬度'
        if not (-180 <= lng <= 180 and -90 <= lat <= 90):
            return '安装经纬度超出有效范围'
        return None


class SystemDetailView(View):
    @auth('equipment_lifecycle.system.view')
    def get(self, request, pk):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        data = item.to_view()
        data['created_by_name'] = item.created_by.username if item.created_by_id else ''
        # 部件维护提示与系统健康状态分离展示（部件故障/部件维修中不影响运行状态）
        data['component_maintenance'] = _component_maintenance_rows([item]).get(
            item.id, dict(COMPONENT_MAINTENANCE_EMPTY))
        return json_response(data)

    @auth('equipment_lifecycle.system.edit')
    def put(self, request, pk):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        if isinstance(body.get('system'), dict):
            return self._update_aggregate(request, item, body)
        form, error = _parse_system_fields(body)
        if error:
            return json_response(error=error)
        return self._update_flat(request, item, form)

    def _update_flat(self, request, item, form):
        """旧平铺载荷：仅更新系统固定字段。"""
        install_time, enable_time, error = _validate_system_fixed_payload(request, form)
        if error:
            return json_response(error=error)
        before = _fixed_field_snapshot(item)
        _apply_fixed_fields(item, form, install_time, enable_time, request.user)
        changes = _diff_fixed_changes(before, _fixed_field_snapshot(item))
        with transaction.atomic():
            item.save()
            record_audit_event(request, 'update', AUDIT_TARGET_SYSTEM, item.id, item.name,
                               before_value={'changed': [c['label'] for c in changes]},
                               after_value={'system_code': item.system_code})
        return json_response(item.to_view())

    def _update_aggregate(self, request, item, body):
        """结构化聚合编辑：固定字段一次提交。

        所有校验在写入前完成；写操作在单事务内执行，任何一步失败整体回滚。
        已下线的 custom_fields / config_values / components 键随整体载荷被忽略。
        """
        form, error = _parse_system_fields(body.get('system'))
        if error:
            return json_response(error=error)
        install_time, enable_time, error = _validate_system_fixed_payload(request, form)
        if error:
            return json_response(error=error)

        before = _fixed_field_snapshot(item)
        _apply_fixed_fields(item, form, install_time, enable_time, request.user)
        changes = _diff_fixed_changes(before, _fixed_field_snapshot(item))

        with transaction.atomic():
            item.save()
            record_audit_event(request, 'update', AUDIT_TARGET_SYSTEM, item.id, item.name,
                               before_value={'changed': [c['label'] for c in changes]},
                               after_value={'system_code': item.system_code})
        return json_response(item.to_view())

    @auth('equipment_lifecycle.system.del')
    def delete(self, request, pk):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        blockers = _collect_system_references(item)
        if blockers:
            return json_response(error='系统已被以下业务引用，不能删除：' + '、'.join(blockers))
        audit_snapshot = {
            'system_code': item.system_code, 'name': item.name,
        }
        with transaction.atomic():
            item.delete()
            record_audit_event(request, 'delete', AUDIT_TARGET_SYSTEM, item.system_code,
                               audit_snapshot['name'], before_value=audit_snapshot)
        return json_response({})


class SystemActiveView(View):
    @auth('equipment_lifecycle.system.deactivate')
    def post(self, request, pk):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        form, error = JsonParser(
            Argument('is_active', type=bool, required=True, help='是否可用'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        if item.is_active == form.is_active:
            return json_response(error='系统状态未发生变化')
        item.is_active = form.is_active
        item.updated_at = timezone.now()
        item.updated_by = request.user
        with transaction.atomic():
            item.save(update_fields=['is_active', 'updated_at', 'updated_by'])
            record_audit_event(request, 'update', AUDIT_TARGET_SYSTEM, item.id, item.name,
                               before_value={'is_active': not form.is_active},
                               after_value={'is_active': form.is_active})
        return json_response(item.to_view())


class SystemExportView(View):
    @auth('equipment_lifecycle.system.export')
    def get(self, request):
        query = apply_tenant_filter(LifecycleSystem.objects.all(), request.user)
        headers = ['系统编号', '系统名称', '系统型号', '安装地点', '安装经纬度',
                   '呼号', '工作频率', '系统用途', '生产厂家', '安装单位', '使用单位',
                   '安装时间', '启用时间', '系统负责人', '运行健康状态', '是否可用',
                   '备注', '创建时间']
        rows = []
        for item in query:
            rows.append([
                item.system_code, item.name, item.system_model,
                item.install_location, item.geo_coordinate,
                item.callsign, item.work_frequency, item.system_purpose,
                item.manufacturer, item.install_unit, item.use_unit,
                item.install_time.strftime('%Y-%m-%d') if item.install_time else '',
                item.enable_time.strftime('%Y-%m-%d') if item.enable_time else '',
                item.responsible_user_name,
                item.HEALTH_STATUS_TEXT_MAP.get(item.health_status, item.health_status),
                '是' if item.is_active else '否', item.remark,
                item.created_at.strftime('%Y-%m-%d %H:%M'),
            ])
        record_audit_event(request, 'export', AUDIT_TARGET_SYSTEM, '', '',
                           detail={'count': len(rows)})
        return _csv_response('el_systems', headers, rows)


def _csv_response(filename_prefix, headers, rows):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    writer.writerows(rows)
    response = HttpResponse('\ufeff' + buf.getvalue(), content_type='text/csv; charset=utf-8')
    stamp = timezone.now().strftime('%Y%m%d%H%M%S')
    response['Content-Disposition'] = f"attachment; filename={filename_prefix}_{stamp}.csv"
    return response
