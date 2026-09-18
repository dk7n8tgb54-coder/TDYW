# -*- coding: utf-8 -*-
"""设备全生命周期（步骤二）测试公共夹具。"""
import time

from apps.account.models import User
from apps.equipment_lifecycle.models import (
    ConfigFieldDefinition,
    LifecycleSystem,
    SystemType,
)

# 权限码（与 views/@auth、前端 routes/codes 一致）
P_SYS_VIEW = 'equipment_lifecycle.system.view'
P_SYS_ADD = 'equipment_lifecycle.system.add'
P_SYS_EDIT = 'equipment_lifecycle.system.edit'
P_SYS_DEL = 'equipment_lifecycle.system.del'
P_SYS_DEACT = 'equipment_lifecycle.system.deactivate'
P_SYS_EXPORT = 'equipment_lifecycle.system.export'
P_TYPE_VIEW = 'equipment_lifecycle.system_type.view'
P_TYPE_ADD = 'equipment_lifecycle.system_type.add'
P_TYPE_EDIT = 'equipment_lifecycle.system_type.edit'
P_TYPE_DEL = 'equipment_lifecycle.system_type.del'
P_CFG_VIEW = 'equipment_lifecycle.system_config.view'
P_CFG_EDIT = 'equipment_lifecycle.system_config.edit'
P_CFG_FIELD = 'equipment_lifecycle.system_config.field'
P_CFG_SNAPSHOT = 'equipment_lifecycle.system_config.snapshot'
P_CFG_EXPORT = 'equipment_lifecycle.system_config.export'

ALL_SYSTEM_PERMS = [P_SYS_VIEW, P_SYS_ADD, P_SYS_EDIT, P_SYS_DEL, P_SYS_DEACT, P_SYS_EXPORT]
ALL_TYPE_PERMS = [P_TYPE_VIEW, P_TYPE_ADD, P_TYPE_EDIT, P_TYPE_DEL]
ALL_CONFIG_PERMS = [P_CFG_VIEW, P_CFG_EDIT, P_CFG_FIELD, P_CFG_SNAPSHOT, P_CFG_EXPORT]

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


def make_type(created_by, tenant_id='default', name='通信系统', **kwargs):
    defaults = dict(
        name=name, description='', display_order=0, is_active=True,
        tenant_id=tenant_id, created_by=created_by,
    )
    defaults.update(kwargs)
    return SystemType.objects.create(**defaults)


def make_system(created_by, system_type=None, tenant_id='default', **kwargs):
    defaults = dict(
        system_code='SYS-001',
        name='烟台中心站通信系统',
        system_type=system_type,
        system_model='HX-100',
        install_location='烟台中心站机房A',
        geo_coordinate='',
        system_purpose='',
        manufacturer='某通信设备厂',
        install_unit='安装一队',
        use_unit='运行一科',
        install_time='2026-01-01 08:00',
        enable_time='2026-02-01 09:00',
        responsible_user_name='张三',
        health_status=LifecycleSystem.HEALTH_NORMAL,
        is_active=True,
        remark='',
        tenant_id=tenant_id,
        created_by=created_by,
    )
    defaults.update(kwargs)
    if defaults.get('system_type') is None:
        defaults['system_type'] = make_type(created_by, tenant_id=tenant_id)
    return LifecycleSystem.objects.create(**defaults)


def make_field(owner_obj, created_by, tenant_id='default', scope='template', **kwargs):
    """创建配置字段定义。owner_obj 为 SystemType（模板）或 LifecycleSystem（自定义）。"""
    if scope == ConfigFieldDefinition.SCOPE_TEMPLATE:
        defaults = dict(system_type=owner_obj, system=None)
    else:
        defaults = dict(system=owner_obj, system_type=None)
    defaults.update(dict(
        scope_type=scope,
        scope_owner_id=str(owner_obj.id),
        field_code='frequency',
        display_name='工作频率',
        field_type=ConfigFieldDefinition.TYPE_TEXT,
        help_text='',
        display_order=0,
        is_required=False,
        default_value='',
        choices='',
        detail_columns='',
        number_min=None,
        number_max=None,
        text_regex='',
        is_searchable=False,
        is_filterable=False,
        is_exportable=False,
        visible_roles='',
        editable_roles='',
        is_sensitive=False,
        applies_to=ConfigFieldDefinition.APPLIES_ALL,
        is_active=True,
        tenant_id=tenant_id,
        created_by=created_by,
    ))
    defaults.update(kwargs)
    return ConfigFieldDefinition.objects.create(**defaults)


def system_payload(**overrides):
    from apps.equipment_lifecycle.models import LifecycleSystem
    payload = {
        'system_code': 'SYS-NEW-01',
        'name': '新建测试系统',
        'system_type': None,  # 由调用方覆盖
        'system_model': 'MODEL-X',
        'install_location': '机房B',
        'geo_coordinate': '121.5,37.5',
        'system_purpose': '业务用途说明',
        'manufacturer': '某厂',
        'install_unit': '安装单位A',
        'use_unit': '使用单位B',
        'install_time': '2026-03-01 08:00',
        'enable_time': '2026-03-10 09:30',
        'responsible_user_name': '李四',
        'health_status': LifecycleSystem.HEALTH_NORMAL,
        'remark': '',
    }
    payload.update(overrides)
    return payload
