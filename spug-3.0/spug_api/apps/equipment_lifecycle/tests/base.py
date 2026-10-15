# -*- coding: utf-8 -*-
"""设备全生命周期测试公共夹具（自定义字段机制已移除，扩展信息为固定字段）。"""
import time

from apps.account.models import User
from apps.equipment_lifecycle.models import (
    LifecycleSystem,
)

# 权限码（与 views/@auth、前端 routes/codes 一致）
P_SYS_VIEW = 'equipment_lifecycle.system.view'
P_SYS_ADD = 'equipment_lifecycle.system.add'
P_SYS_EDIT = 'equipment_lifecycle.system.edit'
P_SYS_DEL = 'equipment_lifecycle.system.del'
P_SYS_DEACT = 'equipment_lifecycle.system.deactivate'
P_SYS_EXPORT = 'equipment_lifecycle.system.export'

ALL_SYSTEM_PERMS = [P_SYS_VIEW, P_SYS_ADD, P_SYS_EDIT, P_SYS_DEL, P_SYS_DEACT, P_SYS_EXPORT]

URL_PREFIX = '/equipment-lifecycle'


def make_user(username, perms=None, tenant_id='default', is_supper=False):
    """创建指定租户/权限的测试用户。"""
    user = User.objects.create(
        username=username,
        nickname=username,
        password_hash='x',
        is_active=True,
        is_supper=is_supper,
        access_token=(username * 10)[:32],
        token_expired=int(time.time()) + 3600,
        last_login='2026-01-01',
        last_ip='127.0.0.1',
        type='default',
        tenant_id=tenant_id,
    )
    if not is_supper:
        user.set_perms_cache(set(perms or []), version=0)
    return user


def make_client(user):
    from django.test import Client
    client = Client()
    client.defaults['HTTP_X_TOKEN'] = user.access_token
    client.defaults['HTTP_X_FORWARDED_FOR'] = '127.0.0.1'
    return client


def make_system(created_by, tenant_id='default', **kwargs):
    defaults = dict(
        system_code='SYS-001',
        name='烟台中心站通信系统',
        system_model='HX-100',
        install_location='烟台中心站机房A',
        geo_coordinate='',
        callsign='',
        work_frequency='',
        system_purpose='',
        manufacturer='某通信设备厂',
        install_unit='安装一队',
        use_unit='运行一科',
        install_time='2026-01-01',
        enable_time='2026-02-01',
        responsible_user_name='张三',
        health_status=LifecycleSystem.HEALTH_NORMAL,
        is_active=True,
        remark='',
        tenant_id=tenant_id,
        created_by=created_by,
    )
    defaults.update(kwargs)
    return LifecycleSystem.objects.create(**defaults)


def system_payload(**overrides):
    from apps.equipment_lifecycle.models import LifecycleSystem
    payload = {
        'name': '新建测试系统',
        'system_model': 'MODEL-X',
        'install_location': '机房B',
        'geo_coordinate': '121.5,37.5',
        'callsign': '',
        'work_frequency': '',
        'system_purpose': '业务用途说明',
        'manufacturer': '某厂',
        'install_unit': '安装单位A',
        'use_unit': '使用单位B',
        'install_time': '2026-03-01',
        'enable_time': '2026-03-10',
        'responsible_user_name': '李四',
        'health_status': LifecycleSystem.HEALTH_NORMAL,
        'remark': '',
    }
    payload.update(overrides)
    return payload


# ==================== 运行处置记录（2026-10-11 合并改造） ====================
P_OP_VIEW = 'equipment_lifecycle.operation_record.view'
P_OP_ADD = 'equipment_lifecycle.operation_record.add'
P_OP_ADD_FAULT = 'equipment_lifecycle.operation_record.add_fault'
P_OP_EDIT = 'equipment_lifecycle.operation_record.edit'
P_OP_PROGRESS = 'equipment_lifecycle.operation_record.progress'
P_OP_COMPLETE = 'equipment_lifecycle.operation_record.complete'
P_OP_IDENTIFY_FAULT = 'equipment_lifecycle.operation_record.identify_fault'
P_OP_RECOVER = 'equipment_lifecycle.operation_record.recover'
P_OP_CLOSE = 'equipment_lifecycle.operation_record.close'
P_OP_CANCEL = 'equipment_lifecycle.operation_record.cancel'
P_OP_DEL = 'equipment_lifecycle.operation_record.del'
P_OP_EXPORT = 'equipment_lifecycle.operation_record.export'

ALL_OPERATION_PERMS = [
    P_OP_VIEW, P_OP_ADD, P_OP_ADD_FAULT, P_OP_EDIT, P_OP_PROGRESS,
    P_OP_COMPLETE, P_OP_IDENTIFY_FAULT, P_OP_RECOVER, P_OP_CLOSE,
    P_OP_CANCEL, P_OP_DEL, P_OP_EXPORT,
]

RECORDS_URL = URL_PREFIX + '/records'
RECORD_DETAIL_URL = RECORDS_URL + '/%d'
SYSTEM_RECORDS_URL = URL_PREFIX + '/systems/%d/records/'


def make_record(created_by, system, record_type='abnormal', tenant_id='default',
                occurred_at='2026-10-11 08:00:00', **overrides):
    """创建统一记录测试夹具（绕过视图，直接走 ORM；编号手动给定）。"""
    import itertools
    from apps.equipment_lifecycle.operation_models import SystemOperationRecord

    defaults = dict(
        record_no='JL20261011-%04d' % next(_record_no_counter()),
        record_type=record_type,
        system=system,
        system_code=system.system_code,
        system_name=system.name,
        system_location=system.install_location,
        occurred_at=occurred_at,
        title='测试记录',
        description='测试情况描述',
        registrar_name='张三',
        status='recorded',
        created_by=created_by,
        tenant_id=tenant_id,
    )
    if record_type == 'fault':
        defaults.update(status='handling')
    defaults.update(overrides)
    return SystemOperationRecord.objects.create(**defaults)


def _record_no_counter():
    import itertools
    if not hasattr(_record_no_counter, 'counter'):
        _record_no_counter.counter = itertools.count(1)
    return _record_no_counter.counter
