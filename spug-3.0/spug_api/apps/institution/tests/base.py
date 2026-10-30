# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""制度管理测试公共夹具

设计要点（真实代码路径）：
- 全部断言通过 Django test client 发起真实 HTTP 请求，走完整
  中间件 -> 路由 -> 视图 -> 模型 -> 数据库链路，不做源码字符串匹配。
- 物理文件系统按需 patch 到进程级临时目录，绝不触碰容器真实 storage。
- 数据库使用 Django test runner 创建的隔离测试库。
"""
import json
import time
import uuid

from django.test import Client

from apps.account.models import Role, User
from apps.setting.utils import AppSetting

PERM_VIEW = 'institution.manual.view'
PERM_ADD = 'institution.manual.add'
PERM_EDIT = 'institution.manual.edit'
PERM_DELETE = 'institution.manual.delete'
PERM_CONFIG = 'institution.manual.config'
PERM_UPLOAD = 'institution.manual.upload'
PERM_DOWNLOAD = 'institution.manual.download'
PERM_DRAFT = 'institution.manual.draft_edit'
PERM_PUBLISH = 'institution.manual.publish'

ALL_PERMS = [
    PERM_VIEW, PERM_ADD, PERM_EDIT, PERM_DELETE, PERM_CONFIG,
    PERM_UPLOAD, PERM_DOWNLOAD, PERM_DRAFT, PERM_PUBLISH,
]


def make_uuid():
    return uuid.uuid4().hex


def _page_perms_json(perms):
    perm_tree = {}
    for p in perms:
        parts = p.split('.')
        if len(parts) >= 3:
            perm_tree.setdefault(parts[0], {}).setdefault(parts[1], set()).add(parts[2])
    pp = {}
    for m, models in perm_tree.items():
        pp[m] = {}
        for mo, acts in models.items():
            pp[m][mo] = {a: True for a in acts}
    return json.dumps(pp)


def _role_creator():
    """角色创建人夹具账号（Role.created_by 非空约束）"""
    user = User.objects.filter(username='__role_creator__').first()
    if not user:
        user = User.objects.create(
            username='__role_creator__', nickname='__role_creator__',
            password_hash=User.make_password('x'), access_token=make_uuid(),
            is_active=True, tenant_id='', token_expired=int(time.time()) + 3600,
            last_ip='127.0.0.1', last_login='2026-01-01', type='default')
    return user


def make_role(name=None, perms=None, tenant_id=''):
    """创建角色；perms 为模块权限码列表"""
    return Role.objects.create(
        name=name or f'role_{make_uuid()[:8]}', desc='',
        page_perms=_page_perms_json(perms or []),
        perms_version=1, tenant_id=tenant_id,
        created_by=_role_creator(),
    )


def make_user(username='user', is_supper=False, tenant_id='inst', perms=None,
              roles=None, password='test123'):
    """创建测试用户

    perms: 模块权限码列表（生成一个承载 page_perms 的角色）
    roles: 额外挂载的 account.Role 实例列表（手册级授权用）
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
        user.roles.add(make_role(perms=perms))
    for role in roles or []:
        user.roles.add(role)
    user.set_perms_cache(None)
    return user


def make_client(user):
    client = Client()
    client.defaults['HTTP_X_TOKEN'] = user.access_token
    return client


def setup_test_env():
    AppSetting.set('bind_ip', False)


def post_json(client, path, data):
    return client.post(path, data=json.dumps(data), content_type='application/json')


def put_json(client, path, data):
    return client.put(path, data=json.dumps(data), content_type='application/json')


def delete_json(client, path, data=None):
    return client.delete(path, data=json.dumps(data or {}),
                         content_type='application/json')


def get_data(resp):
    body = resp.json()
    data = body.get('data')
    return data if isinstance(data, (dict, list)) else None


def has_error(resp):
    return bool(resp.json().get('error'))
