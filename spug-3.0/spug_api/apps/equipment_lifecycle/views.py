# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""设备生命周期视图：设备档案（独立主数据）+ 位置历史 + 系统主数据 + 系统—设备关系。

权限模型（后端独立校验，不依赖前端）：
- equipment_lifecycle.device.view     查看设备档案列表/详情/位置历史
- equipment_lifecycle.device.manage   新建/编辑/删除设备档案、变更设备位置
- equipment_lifecycle.system.view    查看系统列表/详情
- equipment_lifecycle.system.manage  新建/编辑/删除系统
- equipment_lifecycle.relation.view    查看关系
- equipment_lifecycle.relation.manage  新建/编辑/退出关系

核心业务约束：
1. 设备档案为本应用独立主数据，不读写旧 device 模块（apps.device）；
2. 位置变更走独立接口（devices/location-change/），普通编辑接口不接收
   current_location，避免静默覆盖；位置历史只进不出，变更仅封存旧时段；
3. 同一设备同一时间至多一条有效位置记录（命名锁 el_loc:{tenant}:{device}
   串行化写入 + 事务内 select_for_update + 应用层校验）；
4. 同一 (系统, 设备, 角色) 的关系时间段（半开区间 [valid_from, valid_to)）不可重叠；
5. 退出关系只封存（status=ended + valid_to），不删除记录；重新加入必须建立新时间段；
6. 系统/设备删除：存在任何关系记录或位置历史时禁止删除。

并发防护：关系创建/编辑前先获取 (租户, 系统, 设备, 角色) 粒度的 GET_LOCK 命名锁
串行化同键写入（覆盖空区间并发插入竞态），事务内再对已有行 select_for_update
并基于锁定行做重叠判断；命名锁在请求事务提交后释放。
"""
from datetime import datetime
import json
import logging

from django.views.generic import View
from django.db import transaction, DatabaseError, IntegrityError, connection
from django.db.models import Q, Count
from django.db.models import ProtectedError
from django.utils import timezone

from libs import JsonParser, Argument, json_response, auth
from libs.tenant_utils import apply_tenant_filter
from libs.pagination import paginate
from apps.logs.audit import record_audit_event

from apps.equipment_lifecycle.models import (
    LifecycleDevice, LifecycleDeviceLocation, LifecycleSystem, SystemDeviceRelation,
)

logger = logging.getLogger(__name__)

CONFLICT_ERROR = '操作冲突，请稍后重试'


def _parse_date(value, label):
    """解析 'YYYY-MM-DD' 日期字符串，返回 (date, error)"""
    try:
        return datetime.strptime(value.strip(), '%Y-%m-%d').date(), None
    except (AttributeError, ValueError):
        return None, f'{label}格式无效，应为 YYYY-MM-DD'


def _parse_status_list(request):
    """解析设备状态筛选参数，兼容三种前端格式，返回状态列表或 None。

    - axios(0.21) 数组默认带空括号：current_status[]=1&current_status[]=2
    - 重复键：current_status=1&current_status=2
    - JSON 串：current_status=["1","2"]
    """
    values = request.GET.getlist('current_status') or request.GET.getlist('current_status[]')
    if not values:
        return None
    result = []
    for value in values:
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            result.append(str(value))
            continue
        if isinstance(parsed, list):
            result.extend(str(item) for item in parsed)
        else:
            result.append(str(parsed))
    return result or None


def _acquire_named_lock(name, timeout=10):
    """获取命名锁（GET_LOCK 为连接级锁、与事务无关），返回 (是否成功, 锁名)。

    用于串行化关系的时间段校验与写入，补上 REPEATABLE READ 间隙锁无法可靠
    防护的"空区间并发插入"竞态窗口（实测双插入不构成死锁、会双双成功）。
    锁必须在请求事务提交之后再释放（transaction.on_commit），否则校验读
    可能看不到未提交的重叠行；异常路径由请求结束断开连接兜底释放。
    """
    with connection.cursor() as cursor:
        cursor.execute('SELECT GET_LOCK(%s, %s)', [name, timeout])
        acquired = cursor.fetchone()[0]
    return bool(acquired), name


def _acquire_trio_lock(tenant_id, system_id, device_id, role, timeout=10):
    """获取 (租户, 系统, 设备, 角色) 粒度的关系写入锁。"""
    return _acquire_named_lock(f'el_rel:{tenant_id}:{system_id}:{device_id}:{role}', timeout)


def _acquire_primary_lock(tenant_id, device_id, timeout=10):
    """获取 (租户, 设备) 粒度的主要归属锁：同一设备同时段最多一条主要归属关系。

    锁层级约定：先取关系 trio 锁、后取本锁，避免交叉死锁。
    """
    return _acquire_named_lock(f'el_primary:{tenant_id}:{device_id}', timeout)


def _release_named_lock(lock_name):
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT RELEASE_LOCK(%s)', [lock_name])
    except Exception:
        logger.warning('释放设备生命周期命名锁失败: %s', lock_name)


class DeviceView(View):
    """设备档案（独立主数据）：查看 / 维护"""

    @auth('equipment_lifecycle.device.view')
    def get(self, request):
        # 单条详情：?id=xx，租户隔离后取不到即返回业务错误（不泄露他租户信息）
        record_id = request.GET.get('id')
        if record_id:
            record = apply_tenant_filter(
                LifecycleDevice.objects.all(), request.user
            ).filter(pk=record_id).first()
            if not record:
                return json_response(error='设备不存在或无权限访问')
            return json_response(record.to_view())

        # 列表：关键字 + 筛选 + 分页
        form, error = JsonParser(
            Argument('keyword', type=str, required=False, help='设备编号/名称关键字'),
            Argument('device_model', type=str, required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)

        query = apply_tenant_filter(LifecycleDevice.objects.all(), request.user)

        # 统一关键字：同时匹配设备编号或设备名称
        if form.keyword:
            query = query.filter(
                Q(device_sn__icontains=form.keyword) | Q(device_name__icontains=form.keyword)
            )
        if form.device_model:
            query = query.filter(device_model__icontains=form.device_model)
        # 设备状态筛选：兼容 axios 数组（current_status[]=1）、重复键、JSON 串三种格式
        status_list = _parse_status_list(request)
        if status_list:
            query = query.filter(current_status__in=status_list)

        page, page_size = paginate(request)
        total = query.count()
        start = (page - 1) * page_size
        records = query[start:start + page_size]

        return json_response({
            'data': [r.to_view() for r in records],
            'total': total,
            'page': page,
            'page_size': page_size,
        })

    @auth('equipment_lifecycle.device.manage')
    def post(self, request):
        """新建设备档案（物理创建 + 审计留痕；填写当前位置时同步创建初始位置历史）"""
        form, error = JsonParser(
            Argument('device_sn', type=str, help='请输入设备资产编号'),
            Argument('device_name', type=str, help='请输入设备名称'),
            Argument('device_model', type=str, help='请输入设备型号'),
            Argument('install_time', type=str, required=False),
            Argument('enable_time', type=str, required=False),
            Argument('current_status', type=str, help='请选择当前设备状况'),
            Argument('current_location', type=str, required=False),
            Argument('remark', type=str, required=False),
        ).parse(request.body)
        if error:
            return json_response(error=error)

        device_sn = (form.device_sn or '').strip()
        device_name = (form.device_name or '').strip()
        device_model = (form.device_model or '').strip()
        current_location = (form.current_location or '').strip()
        if not device_sn:
            return json_response(error='设备资产编号不能为空')
        if not device_name:
            return json_response(error='设备名称不能为空')
        if not device_model:
            return json_response(error='设备型号不能为空')
        if len(current_location) > 200:
            return json_response(error='当前位置长度不能超过200字符')
        if form.current_status not in LifecycleDevice.STATUS_TEXT_MAP:
            return json_response(error='设备状态非法，仅支持：1=正常，2=故障，3=维修中，4=停用，5=报废')

        install_time, err = (None, None)
        if form.install_time:
            install_time, err = _parse_date(form.install_time, '安装时间')
            if err:
                return json_response(error=err)
        enable_time = None
        if form.enable_time:
            enable_time, err = _parse_date(form.enable_time, '启用时间')
            if err:
                return json_response(error=err)

        tenant_id = request.user.tenant_id
        # 设备编号租户内唯一（DB 级 tenant+device_sn 约束 + 应用层友好提示）
        if LifecycleDevice.objects.filter(tenant_id=tenant_id, device_sn=device_sn).exists():
            return json_response(error='设备资产编号已存在')

        try:
            with transaction.atomic():
                record = LifecycleDevice.objects.create(
                    tenant_id=tenant_id,
                    device_sn=device_sn, device_name=device_name, device_model=device_model,
                    install_time=install_time, enable_time=enable_time,
                    current_status=form.current_status,
                    current_location=current_location,
                    remark=(form.remark or '').strip(),
                    created_by=request.user,
                )
                if current_location:
                    # 初始位置历史与档案同事务创建，保证档案与历史一致
                    LifecycleDeviceLocation.objects.create(
                        tenant_id=tenant_id, device=record,
                        old_location='', new_location=current_location,
                        effective_at=timezone.now(),
                        change_type=LifecycleDeviceLocation.CHANGE_INITIAL,
                        created_by=request.user,
                    )
                record_audit_event(
                    request, 'create', 'el_device',
                    target_id=record.id, target_name=record.device_sn,
                    detail={'device_name': record.device_name,
                            'current_location': record.current_location},
                )
        except IntegrityError:
            return json_response(error='设备资产编号已存在')
        except DatabaseError:
            return json_response(error=CONFLICT_ERROR)
        return json_response(record.to_view())

    @auth('equipment_lifecycle.device.manage')
    def put(self, request):
        """编辑设备档案"""
        form, error = JsonParser(
            Argument('id', type=int, help='缺少设备ID'),
            Argument('device_name', type=str, required=False),
            Argument('device_model', type=str, required=False),
            Argument('install_time', type=str, required=False),
            Argument('enable_time', type=str, required=False),
            Argument('current_status', type=str, required=False),
            Argument('remark', type=str, required=False),
        ).parse(request.body)
        if error:
            return json_response(error=error)

        try:
            with transaction.atomic():
                record = apply_tenant_filter(
                    LifecycleDevice.objects.select_for_update().all(), request.user
                ).filter(pk=form.id).first()
                if not record:
                    return json_response(error='设备不存在或无权限访问')

                before = {'device_name': record.device_name, 'current_status': record.current_status}
                if form.current_status is not None and form.current_status not in LifecycleDevice.STATUS_TEXT_MAP:
                    return json_response(error='设备状态非法，仅支持：1=正常，2=故障，3=维修中，4=停用，5=报废')
                for field in ('device_name', 'device_model', 'remark', 'current_status'):
                    value = getattr(form, field)
                    if value is not None:
                        setattr(record, field, value.strip())
                for field, label in (('install_time', '安装时间'), ('enable_time', '启用时间')):
                    value = getattr(form, field)
                    if value is not None:
                        parsed, err = (None, None)
                        if value:
                            parsed, err = _parse_date(value, label)
                            if err:
                                return json_response(error=err)
                        setattr(record, field, parsed)
                record.updated_at = timezone.now()
                record.updated_by = request.user
                record.save()
                record_audit_event(
                    request, 'update', 'el_device',
                    target_id=record.id, target_name=record.device_sn,
                    before_value=before,
                    after_value={'device_name': record.device_name,
                                 'current_status': record.current_status},
                )
        except DatabaseError:
            return json_response(error=CONFLICT_ERROR)
        return json_response(record.to_view())

    @auth('equipment_lifecycle.device.manage')
    def delete(self, request):
        """删除设备档案：存在位置历史或系统关系记录（含历史）时禁止；物理删除 + 审计留痕"""
        record_id = request.GET.get('id')
        if not record_id:
            return json_response(error='缺少设备ID')
        record = apply_tenant_filter(
            LifecycleDevice.objects.all(), request.user
        ).filter(pk=record_id).first()
        if not record:
            return json_response(error='设备不存在或无权限访问')
        # 位置历史只进不出，PROTECT 外键也不允许级联删除
        if LifecycleDeviceLocation.objects.filter(device_id=record.id).exists():
            return json_response(error='该设备存在位置历史记录，无法删除')
        if SystemDeviceRelation.objects.filter(device_id=record.id).exists():
            return json_response(error='该设备存在系统关系记录（含历史），无法删除')

        try:
            with transaction.atomic():
                # delete() 会清空实例 pk，审计所需的 ID/名称必须先取
                target_id, target_name = record.id, record.device_sn
                record.delete()
                record_audit_event(
                    request, 'delete', 'el_device',
                    target_id=target_id, target_name=target_name,
                )
        except ProtectedError:
            return json_response(error='该设备存在系统关系记录，无法删除')
        except DatabaseError:
            return json_response(error=CONFLICT_ERROR)
        return json_response('')


class DeviceLocationChangeView(View):
    """设备位置变更：独立接口，普通设备编辑接口不接收位置字段。

    事务顺序：命名锁 → 锁定设备 → 读原位置 → 校验 → 封存旧有效时段
    → 新建历史 → 更新档案当前位置 → 审计；任何一步失败整体回滚。
    """

    @auth('equipment_lifecycle.device.manage')
    def post(self, request):
        form, error = JsonParser(
            Argument('device_id', type=int, help='缺少设备ID'),
            Argument('new_location', type=str, help='请输入新位置'),
            Argument('effective_at', type=str, required=False),
            Argument('change_type', type=str, required=False),
            Argument('reason', type=str, required=False),
        ).parse(request.body)
        if error:
            return json_response(error=error)

        new_location = (form.new_location or '').strip()
        if not new_location:
            return json_response(error='新位置不能为空')
        if len(new_location) > 200:
            return json_response(error='新位置长度不能超过200字符')
        # 未传时默认位置搬迁；传了（含空串）必须是明确合法的选项，initial 仅由建档流程写入
        if form.change_type is None:
            change_type = LifecycleDeviceLocation.CHANGE_RELOCATION
        else:
            change_type = str(form.change_type).strip()
            if change_type not in LifecycleDeviceLocation.CHANGE_TYPE_VALUES:
                return json_response(error='变更类型非法，仅支持 relocation=位置搬迁，correction=位置更正')
        reason = (form.reason or '').strip()
        if len(reason) > 500:
            return json_response(error='变更原因长度不能超过500字符')

        if form.effective_at:
            try:
                effective_at = datetime.strptime(form.effective_at.strip(), '%Y-%m-%d %H:%M:%S')
            except ValueError:
                return json_response(error='生效时间格式无效，应为 YYYY-MM-DD HH:MM:SS')
        else:
            effective_at = timezone.now()

        tenant_id = request.user.tenant_id
        acquired, lock_name = _acquire_named_lock(f'el_loc:{tenant_id}:{form.device_id}')
        if not acquired:
            return json_response(error=CONFLICT_ERROR)
        try:
            with transaction.atomic():
                record = apply_tenant_filter(
                    LifecycleDevice.objects.select_for_update().all(), request.user
                ).filter(pk=form.device_id).first()
                if not record:
                    return json_response(error='设备不存在或无权限访问')

                # 原位置一律由服务端读取，不信任前端传入
                old_location = (record.current_location or '').strip()
                if new_location == old_location:
                    return json_response(error='新位置与当前位置相同，无需变更')
                # 非首次登记（设备已有位置）时变更原因必填
                if old_location and not reason:
                    return json_response(error='请填写变更原因')

                # 封存当前有效位置时段（存量设备可能尚无任何位置历史）
                active = LifecycleDeviceLocation.objects.select_for_update().filter(
                    device_id=record.id, ended_at__isnull=True).first()
                if active:
                    active.ended_at = effective_at
                    active.save(update_fields=['ended_at'])
                history = LifecycleDeviceLocation.objects.create(
                    tenant_id=tenant_id, device=record,
                    old_location=old_location, new_location=new_location,
                    effective_at=effective_at, change_type=change_type,
                    reason=reason, created_by=request.user,
                )
                record.current_location = new_location
                record.updated_at = timezone.now()
                record.updated_by = request.user
                record.save(update_fields=['current_location', 'updated_at', 'updated_by'])
                record_audit_event(
                    request, 'update', 'el_device_location',
                    target_id=record.id, target_name=record.device_sn,
                    detail={'device_id': record.id, 'device_sn': record.device_sn,
                            'old_location': old_location, 'new_location': new_location,
                            'effective_at': str(effective_at), 'change_type': change_type,
                            'reason': reason},
                    before_value={'current_location': old_location},
                    after_value={'current_location': new_location},
                )
        except DatabaseError:
            return json_response(error=CONFLICT_ERROR)

        # 命名锁在请求事务提交后释放（异常路径由请求结束断连兜底释放）
        transaction.on_commit(lambda: _release_named_lock(lock_name))
        return json_response(history.to_view())


class DeviceLocationHistoryView(View):
    """设备位置历史查询（只读，历史只进不出）"""

    @auth('equipment_lifecycle.device.view')
    def get(self, request):
        device_id = request.GET.get('device_id')
        if not device_id:
            return json_response(error='缺少设备ID')
        # 先按租户过滤设备，再取其历史，避免泄露他租户设备的位置轨迹
        device = apply_tenant_filter(
            LifecycleDevice.objects.all(), request.user
        ).filter(pk=device_id).first()
        if not device:
            return json_response(error='设备不存在或无权限访问')
        records = LifecycleDeviceLocation.objects.select_related('created_by').filter(
            device_id=device.id)[:200]
        data = []
        for r in records:
            item = r.to_view()
            item['created_by_name'] = r.created_by.nickname or r.created_by.username
            data.append(item)
        return json_response({'data': data, 'total': len(data)})


class SystemView(View):
    """系统主数据：列表查看 / 维护"""

    @auth('equipment_lifecycle.system.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('keyword', type=str, required=False, help='系统名称/编码关键字'),
        ).parse(request.GET)
        if error:
            return json_response(error=error)

        query = apply_tenant_filter(LifecycleSystem.objects.all(), request.user)
        if form.keyword:
            query = query.filter(Q(name__icontains=form.keyword) | Q(code__icontains=form.keyword))

        page, page_size = paginate(request)
        total = query.count()
        start = (page - 1) * page_size
        records = query[start:start + page_size].annotate(
            active_device_count=Count('device_relations',
                                      filter=Q(device_relations__status=SystemDeviceRelation.STATUS_ACTIVE)))
        data = []
        for r in records:
            item = r.to_view()
            item['active_device_count'] = r.active_device_count
            data.append(item)
        return json_response({'data': data, 'total': total, 'page': page, 'page_size': page_size})

    @auth('equipment_lifecycle.system.manage')
    def post(self, request):
        """新建系统（物理创建 + 审计留痕）"""
        form, error = JsonParser(
            Argument('name', type=str, help='请输入系统名称'),
            Argument('code', type=str, required=False),
            Argument('description', type=str, required=False),
        ).parse(request.body)
        if error:
            return json_response(error=error)

        name = (form.name or '').strip()
        code = (form.code or '').strip()
        description = (form.description or '').strip()
        if not name:
            return json_response(error='系统名称不能为空')
        if len(name) > 100 or len(code) > 50 or len(description) > 500:
            return json_response(error='字段长度超限')

        tenant_id = request.user.tenant_id
        if LifecycleSystem.objects.filter(tenant_id=tenant_id, name=name).exists():
            return json_response(error='系统名称已存在')
        if code and LifecycleSystem.objects.filter(tenant_id=tenant_id, code=code).exists():
            return json_response(error='系统编码已存在')

        try:
            with transaction.atomic():
                record = LifecycleSystem.objects.create(
                    tenant_id=tenant_id, name=name, code=code, description=description,
                    created_by=request.user,
                )
                record_audit_event(
                    request, 'create', 'el_system',
                    target_id=record.id, target_name=record.name,
                    detail={'code': record.code},
                )
        except IntegrityError:
            return json_response(error='系统名称已存在')
        except DatabaseError:
            return json_response(error=CONFLICT_ERROR)
        return json_response(record.to_view())

    @auth('equipment_lifecycle.system.manage')
    def put(self, request):
        """编辑系统"""
        form, error = JsonParser(
            Argument('id', type=int, help='缺少系统ID'),
            Argument('name', type=str, required=False),
            Argument('code', type=str, required=False),
            Argument('description', type=str, required=False),
        ).parse(request.body)
        if error:
            return json_response(error=error)

        try:
            with transaction.atomic():
                record = apply_tenant_filter(
                    LifecycleSystem.objects.select_for_update().all(), request.user
                ).filter(pk=form.id).first()
                if not record:
                    return json_response(error='系统不存在或无权限访问')

                before = {'name': record.name, 'code': record.code}
                if form.name is not None:
                    name = form.name.strip()
                    if not name:
                        return json_response(error='系统名称不能为空')
                    if name != record.name:
                        if LifecycleSystem.objects.filter(tenant_id=record.tenant_id, name=name).exists():
                            return json_response(error='系统名称已存在')
                        record.name = name
                if form.code is not None:
                    code = form.code.strip()
                    if code and code != record.code:
                        if LifecycleSystem.objects.filter(tenant_id=record.tenant_id, code=code).exists():
                            return json_response(error='系统编码已存在')
                    record.code = code
                if form.description is not None:
                    record.description = form.description.strip()
                record.updated_at = timezone.now()
                record.updated_by = request.user
                record.save()
                record_audit_event(
                    request, 'update', 'el_system',
                    target_id=record.id, target_name=record.name,
                    detail={'code': record.code}, before_value=before,
                    after_value={'name': record.name, 'code': record.code},
                )
        except DatabaseError:
            return json_response(error=CONFLICT_ERROR)
        return json_response(record.to_view())

    @auth('equipment_lifecycle.system.manage')
    def delete(self, request):
        """删除系统：存在任何关系记录（含历史）时禁止；物理删除 + 审计留痕"""
        record_id = request.GET.get('id')
        if not record_id:
            return json_response(error='缺少系统ID')
        record = apply_tenant_filter(
            LifecycleSystem.objects.all(), request.user
        ).filter(pk=record_id).first()
        if not record:
            return json_response(error='系统不存在或无权限访问')
        if SystemDeviceRelation.objects.filter(system_id=record.id).exists():
            return json_response(error='该系统下存在设备关系记录（含历史），无法删除')

        try:
            with transaction.atomic():
                # delete() 会清空实例 pk，审计所需的 ID/名称必须先取
                target_id, target_name = record.id, record.name
                record.delete()
                record_audit_event(
                    request, 'delete', 'el_system',
                    target_id=target_id, target_name=target_name,
                )
        except ProtectedError:
            return json_response(error='该系统下存在设备关系记录，无法删除')
        except DatabaseError:
            return json_response(error=CONFLICT_ERROR)
        return json_response('')


class SystemDetailView(View):
    """系统详情：system.view 或 relation.view 均可查看（关系维护页需要读取系统信息）"""

    @auth('equipment_lifecycle.system.view|equipment_lifecycle.relation.view')
    def get(self, request):
        record_id = request.GET.get('id')
        if not record_id:
            return json_response(error='缺少系统ID')
        record = apply_tenant_filter(
            LifecycleSystem.objects.all(), request.user
        ).filter(pk=record_id).first()
        if not record:
            return json_response(error='系统不存在或无权限访问')
        data = record.to_view()
        data['active_device_count'] = record.device_relations.filter(
            status=SystemDeviceRelation.STATUS_ACTIVE).count()
        return json_response(data)


class RelationView(View):
    """系统—设备关系：查看 / 维护（历史只进不出，无删除能力）"""

    @auth('equipment_lifecycle.relation.view')
    def get(self, request):
        # 系统下拉选项（关系维护页使用，relation.view 即可读，避免依赖 system.view）
        if request.GET.get('system_options'):
            systems = apply_tenant_filter(
                LifecycleSystem.objects.all(), request.user
            ).order_by('name')[:200]
            return json_response([
                {'id': s.id, 'name': s.name, 'code': s.code} for s in systems
            ])

        # 设备下拉选项：默认返回前 50 台，可选关键字过滤（仅返回最小字段）
        if request.GET.get('device_options'):
            keyword = (request.GET.get('keyword') or '').strip()
            query = apply_tenant_filter(LifecycleDevice.objects.all(), request.user)
            if keyword:
                query = query.filter(
                    Q(device_sn__icontains=keyword) | Q(device_name__icontains=keyword))
            devices = query.order_by('device_sn')[:50]
            return json_response([
                {'id': d.id, 'device_sn': d.device_sn, 'device_name': d.device_name} for d in devices
            ])

        record_id = request.GET.get('id')
        if record_id:
            record = apply_tenant_filter(
                SystemDeviceRelation.objects.all(), request.user
            ).filter(pk=record_id).first()
            if not record:
                return json_response(error='关系不存在或无权限访问')
            return json_response(record.to_view())

        # 关系统一列表：可按系统/设备过滤，也可全局查询（多对多两侧视图共用）
        form, error = JsonParser(
            Argument('system_id', type=int, required=False),
            Argument('device_id', type=int, required=False),
            Argument('keyword', type=str, required=False, help='设备编号/名称关键字'),
        ).parse(request.GET)
        if error:
            return json_response(error=error)

        query = apply_tenant_filter(
            SystemDeviceRelation.objects.select_related('system'), request.user)
        if form.system_id:
            query = query.filter(system_id=form.system_id)
        if form.device_id:
            query = query.filter(device_id=form.device_id)
        if form.keyword:
            query = query.filter(
                Q(device_sn__icontains=form.keyword) | Q(device_name__icontains=form.keyword))
        status = request.GET.get('status')
        if status in (SystemDeviceRelation.STATUS_ACTIVE, SystemDeviceRelation.STATUS_ENDED):
            query = query.filter(status=status)

        page, page_size = paginate(request)
        total = query.count()
        start = (page - 1) * page_size
        records = query[start:start + page_size]
        data = []
        for r in records:
            item = r.to_view()
            item['system_name'] = r.system.name
            data.append(item)
        return json_response({
            'data': data,
            'total': total, 'page': page, 'page_size': page_size,
        })

    @auth('equipment_lifecycle.relation.manage')
    def post(self, request):
        """建立关系：同一 (系统, 设备, 角色) 的时间段不可重叠"""
        form, error = JsonParser(
            Argument('system_id', type=int, help='请选择系统'),
            Argument('device_id', type=int, help='请选择设备'),
            Argument('role', type=str, help='请选择关系角色'),
            Argument('is_primary', type=bool, required=False),
            Argument('valid_from', type=str, help='请选择生效日期'),
            Argument('valid_to', type=str, required=False),
            Argument('remark', type=str, required=False),
        ).parse(request.body)
        if error:
            return json_response(error=error)

        system = apply_tenant_filter(
            LifecycleSystem.objects.all(), request.user
        ).filter(pk=form.system_id).first()
        if not system:
            return json_response(error='系统不存在或无权限访问')
        device = apply_tenant_filter(
            LifecycleDevice.objects.all(), request.user
        ).filter(pk=form.device_id).first()
        if not device:
            return json_response(error='设备不存在或无权限访问')
        if form.role not in SystemDeviceRelation.ROLE_VALUES:
            return json_response(error='关系角色非法')

        valid_from, err = _parse_date(form.valid_from, '生效日期')
        if err:
            return json_response(error=err)
        valid_to = None
        if form.valid_to:
            valid_to, err = _parse_date(form.valid_to, '失效日期')
            if err:
                return json_response(error=err)
            if valid_to <= valid_from:
                return json_response(error='失效日期必须晚于生效日期')

        tenant_id = request.user.tenant_id
        # 不做 30s 去重：双击重复提交会被命名锁串行化后被重叠校验拒绝，
        # 而去重窗口会误伤"退出后立即重新加入（同键新时间段）"的正常流程

        acquired, lock_name = _acquire_trio_lock(tenant_id, system.id, device.id, form.role)
        if not acquired:
            return json_response(error=CONFLICT_ERROR)
        primary_lock_name = None
        if form.is_primary:
            # 锁层级：先 trio 后 primary，避免交叉死锁
            acquired_p, primary_lock_name = _acquire_primary_lock(tenant_id, device.id)
            if not acquired_p:
                return json_response(error=CONFLICT_ERROR)
        try:
            with transaction.atomic():
                # 行锁保护同键已有行（并发编辑场景），重叠判断基于锁定行
                locked_rows = list(
                    SystemDeviceRelation.objects.select_for_update().filter(
                        tenant_id=tenant_id, system_id=system.id,
                        device_id=device.id, role=form.role,
                    )
                )
                conflict = SystemDeviceRelation.find_overlap(locked_rows, valid_from, valid_to)
                if conflict:
                    return json_response(error='该设备在此系统下同角色的关系时间段与现有记录重叠'
                                              f'（{conflict.valid_from} ~ {conflict.valid_to or "长期"}）')
                if form.is_primary:
                    # 主要归属唯一性：同一设备同一时间段（跨系统）最多一条主要归属关系
                    primary_rows = list(
                        SystemDeviceRelation.objects.select_for_update().select_related('system').filter(
                            tenant_id=tenant_id, device_id=device.id, is_primary=True,
                        )
                    )
                    conflict_primary = SystemDeviceRelation.find_overlap(primary_rows, valid_from, valid_to)
                    if conflict_primary:
                        return json_response(error='该设备在同一时间段已存在主要归属关系'
                                                  f'（系统：{conflict_primary.system.name}，'
                                                  f'{conflict_primary.valid_from} ~ {conflict_primary.valid_to or "长期"}）')
                record = SystemDeviceRelation.objects.create(
                    tenant_id=tenant_id, system=system, device=device,
                    device_sn=device.device_sn, device_name=device.device_name,
                    role=form.role, is_primary=bool(form.is_primary),
                    valid_from=valid_from, valid_to=valid_to,
                    created_by=request.user,
                )
                record_audit_event(
                    request, 'create', 'el_relation',
                    target_id=record.id,
                    target_name=f'{system.name}-{device.device_name}',
                    detail={'role': record.role, 'is_primary': record.is_primary,
                            'valid_from': str(record.valid_from),
                            'valid_to': str(record.valid_to or '')},
                )
        except IntegrityError:
            return json_response(error=CONFLICT_ERROR)
        except DatabaseError:
            return json_response(error=CONFLICT_ERROR)
        # 命名锁必须在外层请求事务提交后释放，保证并发请求能读到已提交的重叠行

        def _release_locks():
            _release_named_lock(lock_name)
            if primary_lock_name:
                _release_named_lock(primary_lock_name)

        transaction.on_commit(_release_locks)
        return json_response(record.to_view())

    @auth('equipment_lifecycle.relation.manage')
    def put(self, request):
        """编辑关系：仅生效中的关系可编辑；已退出的关系为历史记录，不可修改"""
        form, error = JsonParser(
            Argument('id', type=int, help='缺少关系ID'),
            Argument('role', type=str, required=False),
            Argument('is_primary', type=bool, required=False),
            Argument('valid_from', type=str, required=False),
            Argument('valid_to', type=str, required=False),
            Argument('remark', type=str, required=False),
        ).parse(request.body)
        if error:
            return json_response(error=error)

        lock_name = None
        primary_lock_name = None
        try:
            with transaction.atomic():
                record = apply_tenant_filter(
                    SystemDeviceRelation.objects.select_for_update().all(), request.user
                ).filter(pk=form.id).first()
                if not record:
                    return json_response(error='关系不存在或无权限访问')
                if record.status != SystemDeviceRelation.STATUS_ACTIVE:
                    return json_response(error='已退出的关系为历史记录，不可修改，请建立新的关系时间段')

                before = {'role': record.role, 'valid_from': str(record.valid_from),
                          'valid_to': str(record.valid_to or ''), 'is_primary': record.is_primary}

                new_role = record.role
                if form.role is not None:
                    if form.role not in SystemDeviceRelation.ROLE_VALUES:
                        return json_response(error='关系角色非法')
                    new_role = form.role

                new_valid_from = record.valid_from
                if form.valid_from:
                    parsed, err = _parse_date(form.valid_from, '生效日期')
                    if err:
                        return json_response(error=err)
                    new_valid_from = parsed
                # 未提供→保持不变；传空串→清空失效日期（改为长期有效）；传日期→解析
                if form.valid_to is None:
                    new_valid_to = record.valid_to
                elif form.valid_to == '':
                    new_valid_to = None
                else:
                    parsed, err = _parse_date(form.valid_to, '失效日期')
                    if err:
                        return json_response(error=err)
                    new_valid_to = parsed
                if new_valid_to and new_valid_to <= new_valid_from:
                    return json_response(error='失效日期必须晚于生效日期')

                # 角色/时间可变，系统与设备不可变（保护历史语义）
                new_is_primary = form.is_primary if form.is_primary is not None else record.is_primary
                period_changed = (new_role != record.role or new_valid_from != record.valid_from
                                  or new_valid_to != record.valid_to)
                if period_changed:
                    acquired, lock_name = _acquire_trio_lock(
                        record.tenant_id, record.system_id, record.device_id, new_role)
                    if not acquired:
                        return json_response(error=CONFLICT_ERROR)
                    locked_rows = list(
                        SystemDeviceRelation.objects.select_for_update().filter(
                            tenant_id=record.tenant_id, system_id=record.system_id,
                            device_id=record.device_id, role=new_role,
                        )
                    )
                    conflict = SystemDeviceRelation.find_overlap(
                        locked_rows, new_valid_from, new_valid_to, exclude_id=record.id)
                    if conflict:
                        return json_response(error='修改后的关系时间段与现有记录重叠'
                                                  f'（{conflict.valid_from} ~ {conflict.valid_to or "长期"}）')
                if new_is_primary and (new_is_primary != record.is_primary or period_changed):
                    # 主要归属唯一性：同一设备同一时间段（跨系统）最多一条主要归属关系
                    acquired_p, primary_lock_name = _acquire_primary_lock(
                        record.tenant_id, record.device_id)
                    if not acquired_p:
                        return json_response(error=CONFLICT_ERROR)
                    primary_rows = list(
                        SystemDeviceRelation.objects.select_for_update().select_related('system').filter(
                            tenant_id=record.tenant_id, device_id=record.device_id, is_primary=True,
                        )
                    )
                    conflict_primary = SystemDeviceRelation.find_overlap(
                        primary_rows, new_valid_from, new_valid_to, exclude_id=record.id)
                    if conflict_primary:
                        return json_response(error='修改后的主要归属时间段与该设备现有主要归属关系重叠'
                                                  f'（系统：{conflict_primary.system.name}，'
                                                  f'{conflict_primary.valid_from} ~ {conflict_primary.valid_to or "长期"}）')

                record.role = new_role
                record.is_primary = new_is_primary
                record.valid_from = new_valid_from
                record.valid_to = new_valid_to
                if form.remark is not None:
                    record.remark = form.remark.strip()
                record.updated_at = timezone.now()
                record.updated_by = request.user
                record.save()
                record_audit_event(
                    request, 'update', 'el_relation',
                    target_id=record.id,
                    target_name=f'{record.device_sn}-{record.device_name}',
                    detail={'system_id': record.system_id},
                    before_value=before,
                    after_value={'role': record.role, 'valid_from': str(record.valid_from),
                                 'valid_to': str(record.valid_to or ''), 'is_primary': record.is_primary},
                )
        except DatabaseError:
            return json_response(error=CONFLICT_ERROR)

        def _release_locks():
            if lock_name:
                _release_named_lock(lock_name)
            if primary_lock_name:
                _release_named_lock(primary_lock_name)

        if lock_name or primary_lock_name:
            # 命名锁在外层请求事务提交后释放（异常路径由请求结束断连兜底释放）
            transaction.on_commit(_release_locks)
        return json_response(record.to_view())


class RelationExitView(View):
    """退出关系：不删除记录，封存时间段并留痕；重新加入需建立新时间段"""

    @auth('equipment_lifecycle.relation.manage')
    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='缺少关系ID'),
        ).parse(request.body)
        if error:
            return json_response(error=error)

        try:
            with transaction.atomic():
                record = apply_tenant_filter(
                    SystemDeviceRelation.objects.select_for_update().all(), request.user
                ).filter(pk=form.id).first()
                if not record:
                    return json_response(error='关系不存在或无权限访问')
                if record.status == SystemDeviceRelation.STATUS_ENDED:
                    return json_response(error='该关系已退出，无需重复操作')

                # 项目 USE_TZ=False，timezone.now() 为 naive 本地时间
                today = timezone.now().date()
                # 只缩短、不延长已记录的失效日期，保证历史不被放大
                record.valid_to = min(record.valid_to, today) if record.valid_to else today
                record.status = SystemDeviceRelation.STATUS_ENDED
                record.ended_at = timezone.now()
                record.ended_by = request.user
                record.updated_at = timezone.now()
                record.updated_by = request.user
                record.save(update_fields=['valid_to', 'status', 'ended_at', 'ended_by',
                                           'updated_at', 'updated_by'])
                record_audit_event(
                    request, 'update', 'el_relation_exit',
                    target_id=record.id,
                    target_name=f'{record.device_sn}-{record.device_name}',
                    detail={'system_id': record.system_id, 'valid_to': str(record.valid_to)},
                )
        except DatabaseError:
            return json_response(error=CONFLICT_ERROR)
        return json_response(record.to_view())
