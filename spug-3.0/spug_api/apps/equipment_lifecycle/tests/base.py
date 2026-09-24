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
