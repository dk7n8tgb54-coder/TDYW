# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""上线门禁测试公共辅助（radio_license 模块）。

复用 apps/radio_license/tests/test_smoke.py 的用户/权限/客户端构造函数，
补充执照与批复的载荷工厂。所有测试数据使用 RG（Release Gate）前缀，
隔离租户使用 rg_ta / rg_tb。
"""
from datetime import date, timedelta

from apps.radio_license.tests.test_smoke import (
    _make_user, _grant_perms, _make_client,
)

# 上线门禁专用租户（避免与既有测试数据混淆）
TENANT_A = 'rg_ta'
TENANT_B = 'rg_tb'

# 全量权限（管理员角色）
FULL_LICENSE_PERMS = [('radio_license', 'license', ['view', 'add', 'edit', 'del'])]
FULL_APPROVAL_PERMS = [('radio_license', 'approval', ['view', 'add', 'edit', 'del'])]
FULL_ATTACHMENT_PERMS = [('radio_license', 'attachment', ['upload', 'download', 'delete'])]


def rg_license_payload(user, **overrides):
    """构造一份合法的执照创建载荷。"""
    today = date.today()
    payload = {
        'station_name': 'RG-门禁台站',
        'purpose': 'RG-门禁用途',
        'valid_from': str(today - timedelta(days=30)),
        'valid_to': str(today + timedelta(days=300)),
        'responsible_user_id': user.id,
        'frequencies': [
            {'frequency_value': 100.5, 'frequency_unit': 'MHz',
             'frequency_text': '主频', 'sort_order': 0},
            {'frequency_value': 200.0, 'frequency_unit': 'MHz',
             'frequency_text': '备用', 'sort_order': 1},
        ],
    }
    payload.update(overrides)
    return payload


def rg_approval_payload(user, **overrides):
    """构造一份合法的批复创建载荷。"""
    today = date.today()
    payload = {
        'name': 'RG-门禁批复',
        'doc_no': 'RG-DOC-001',
        'frequency_text': '88-108 MHz',
        'valid_from': str(today - timedelta(days=30)),
        'valid_to': str(today + timedelta(days=300)),
        'responsible_user_id': user.id,
    }
    payload.update(overrides)
    return payload


def rg_make_license(user, **kwargs):
    """直接 ORM 创建一条执照记录（绕过 API，用于构造前置数据）。"""
    from apps.radio_license.models import RadioLicense
    today = date.today()
    defaults = {
        'tenant_id': getattr(user, 'tenant_id', TENANT_A),
        'station_name': 'RG-ORM台站',
        'purpose': 'RG-ORM用途',
        'valid_from': today - timedelta(days=365),
        'valid_to': today + timedelta(days=300),
        'responsible_user_id': user.id,
        'responsible_user_name': user.nickname or user.username,
        'status': 'normal',
        'created_by': user,
    }
    defaults.update(kwargs)
    return RadioLicense.objects.create(**defaults)


def rg_make_approval(user, **kwargs):
    """直接 ORM 创建一条批复记录。"""
    from apps.radio_license.models import StationFrequencyApproval
    today = date.today()
    defaults = {
        'tenant_id': getattr(user, 'tenant_id', TENANT_A),
        'name': 'RG-ORM批复',
        'doc_no': 'RG-ORM-DOC',
        'frequency_text': '100MHz',
        'valid_from': today - timedelta(days=365),
        'valid_to': today + timedelta(days=300),
        'responsible_user_id': user.id,
        'responsible_user_name': user.nickname or user.username,
        'status': 'normal',
        'created_by': user,
    }
    defaults.update(kwargs)
    return StationFrequencyApproval.objects.create(**defaults)


__all__ = [
    '_make_user', '_grant_perms', '_make_client',
    'TENANT_A', 'TENANT_B',
    'FULL_LICENSE_PERMS', 'FULL_APPROVAL_PERMS', 'FULL_ATTACHMENT_PERMS',
    'rg_license_payload', 'rg_approval_payload',
    'rg_make_license', 'rg_make_approval',
]
