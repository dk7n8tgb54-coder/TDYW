"""用户工厂 - 创建租户 A/B 的测试用户和角色"""
import uuid
import json
import time

_uid = lambda: uuid.uuid4().hex[:12]

ALL_PERMS = json.dumps({
    "home": {
        "navigation": ["view", "add", "edit", "del"],
        "notice": ["view", "add", "edit", "del"],
        "reminder": ["view", "add", "edit", "delete"],
    },
    "runlog": {
        "runlog": ["view", "add", "edit", "del",
                   "update_view", "update_add", "update_edit", "update_del"],
    },
    "fault": {
        "faultrecord": ["view", "add", "edit", "del"],
        "faultpart": ["view", "add", "edit", "del"],
    },
    "regulation": {
        "regulation": ["view", "add", "edit", "del"],
    },
    "dashboard": {
        "dashboard": ["view"],
    },
    "system": {
        "account": ["view", "add", "edit", "del"],
        "role": ["view", "add", "edit", "del"],
    },
    "logs": {
        "audit": ["view"],
    },
})


def make_role(name, tenant_id, created_by_user, perms_json=None):
    """创建角色

    Args:
        name: 角色名称
        tenant_id: 租户 ID
        created_by_user: 创建者 User 实例
        perms_json: 权限 JSON 字符串 (默认全权限)

    Returns:
        Role 实例
    """
    from apps.account.models import Role
    return Role.objects.create(
        name=name,
        tenant_id=tenant_id,
        page_perms=perms_json or ALL_PERMS,
        created_by=created_by_user,
    )


def make_user(username, tenant_id, nickname=None, is_supper=False,
              password='test123456'):
    """创建用户并生成 access_token

    Args:
        username: 用户名
        tenant_id: 租户 ID
        nickname: 昵称 (默认同 username)
        is_supper: 是否超管
        password: 密码

    Returns:
        User 实例 (已保存，access_token 已设置)
    """
    from apps.account.models import User
    nickname = nickname or username
    user = User(
        username=username,
        nickname=nickname,
        password_hash=User.make_password(password),
        tenant_id=tenant_id,
        is_supper=is_supper,
        is_active=True,
        access_token=uuid.uuid4().hex,
        last_ip='127.0.0.1',
        token_expired=time.time() + 86400,
    )
    user.save()
    return user


def make_user_pair(tenants, bootstrap_user):
    """创建租户 A/B 各一个普通用户

    Args:
        tenants: make_tenant_pair() 的返回值
        bootstrap_user: 用于 Role.created_by 的已有用户

    Returns:
        dict: {'ua': User, 'ub': User, 'tk_ua': token, 'tk_ub': token}
    """
    tid_a = tenants['tid_a']
    tid_b = tenants['tid_b']
    uname_a = f'ti_a_{_uid()}'
    uname_b = f'ti_b_{_uid()}'

    role_a = make_role(f'r{uname_a}', tid_a, bootstrap_user)
    role_b = make_role(f'r{uname_b}', tid_b, bootstrap_user)

    user_a = make_user(uname_a, tid_a, nickname=f'租户A用户')
    user_a.roles.add(role_a)

    user_b = make_user(uname_b, tid_b, nickname=f'租户B用户')
    user_b.roles.add(role_b)

    return {
        'ua': user_a,
        'ub': user_b,
        'tk_ua': user_a.access_token,
        'tk_ub': user_b.access_token,
    }


def cleanup_users(users_data):
    """清理测试用户和角色

    Args:
        users_data: make_user_pair() 的返回值
    """
    from apps.account.models import User, Role
    for key in ['ua', 'ub']:
        if key in users_data:
            user = users_data[key]
            user.roles.clear()
            user.delete()
    tid_a = getattr(users_data.get('ua'), 'tenant_id', None)
    tid_b = getattr(users_data.get('ub'), 'tenant_id', None)
    if tid_a and tid_b:
        Role.objects.filter(tenant_id__in=[tid_a, tid_b]).delete()
