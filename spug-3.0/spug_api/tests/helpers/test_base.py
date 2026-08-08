"""共享测试辅助函数 - 资料与行政业务特征测试"""
import json
import time
import uuid

from django.test import Client
from apps.account.models import User, Role
from apps.setting.utils import AppSetting


def make_uuid():
    return uuid.uuid4().hex


def make_user(username='testuser', is_supper=False, tenant_id='admin',
              perms=None, password='test123'):
    """创建测试用户 (用户名自动加 UUID 后缀避免冲突)

    Args:
        username: 用户名前缀
        is_supper: 是否超管（跳过所有权限检查）
        tenant_id: 租户ID
        perms: 权限列表，如 ['radio_license.license.view', 'radio_license.license.add']
    """
    unique = f'{username}_{make_uuid()[:8]}'
    user = User.objects.create(
        username=unique,
        nickname=unique,
        password_hash=User.make_password(password),
        access_token=make_uuid(),
        is_supper=is_supper,
        is_active=True,
        tenant_id=tenant_id,
        token_expired=int(time.time()) + 3600,
        last_ip='127.0.0.1',
        last_login='2026-01-01',
        type='default',
    )
    if perms and not is_supper:
        role = Role.objects.create(
            name=f'{unique}_role', desc='', page_perms='',
            perms_version=1, created_by=user)
        perm_tree = {}
        for p in perms:
            parts = p.split('.')
            if len(parts) >= 3:
                perm_tree.setdefault(parts[0], {}).setdefault(
                    parts[1], set()).add(parts[2])
        pp = {}
        for m, models in perm_tree.items():
            pp[m] = {}
            for mo, acts in models.items():
                pp[m][mo] = {a: True for a in acts}
        role.page_perms = json.dumps(pp)
        role.save()
        user.roles.add(role)
        user.set_perms_cache(None)
    return user


def make_client(user):
    """创建已认证的测试客户端"""
    client = Client()
    client.defaults['HTTP_X_TOKEN'] = user.access_token
    return client


def setup_test_env():
    """测试环境初始化"""
    AppSetting.set('bind_ip', False)


def post_json(client, path, data):
    """POST JSON 请求"""
    return client.post(path, data=json.dumps(data), content_type='application/json')


def delete_json(client, path, data):
    """DELETE JSON 请求"""
    return client.delete(path, data=json.dumps(data), content_type='application/json')


def get_response_data(resp):
    """安全提取响应 data, 处理 error 时 data='' 的情况"""
    body = resp.json()
    data = body.get('data')
    return data if isinstance(data, (dict, list)) else None


def get_response_id(resp):
    """从创建响应中提取 ID"""
    data = get_response_data(resp)
    if isinstance(data, dict):
        return data.get('id')
    return None


def has_error(resp):
    """检查响应是否有业务错误"""
    return bool(resp.json().get('error'))
