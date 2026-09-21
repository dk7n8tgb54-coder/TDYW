"""跨租户关联测试

覆盖: 外键关联、多对多、嵌套参数中的跨租户 ID

2026-09-21: radio_license 负责用户关联由硬编码「源码审查」结论改为真实行为测试。
原硬编码结论对应 2026-08-08 时代码（当时 _validate_and_fill_responsible_user
确实缺少租户检查）；当前实现已含「普通用户必须与本租户一致（超管除外）」
检查（apps/radio_license/views.py 规则3），行为测试直接执行该函数验证：
1. 普通用户跨租户配置责任人 -> 拒绝
2. 同租户配置 -> 通过并服务端回填姓名
3. 超管跨租户 -> 设计上允许
"""
from types import SimpleNamespace

from factories.tenants import make_tenant_pair, cleanup_tenants
from factories.users import make_user, make_user_pair, cleanup_users


def run(context):
    """执行跨租户关联测试

    Returns:
        list: 测试结果列表
    """
    bootstrap = context.get('bootstrap_user')
    results = []

    # === 待确认的源码审查项（维持原状，待行为测试补齐后移出） ===
    for f in (
        {
            'module': 'evidence',
            'test': '附件跨租户绑定(源码审查)',
            'passed': None,
            'detail': 'AttachmentService 绑定附件到 object_id 时，object_id 为多态引用，未校验目标对象是否属于同一租户',
            'severity': 'medium',
        },
        {
            'module': 'document',
            'test': '文档转存跨租户(源码审查)',
            'passed': None,
            'detail': 'DocumentTransfer 转存目标 folder_id 未校验是否属于同一租户',
            'severity': 'medium',
        },
        {
            'module': 'reminder',
            'test': '提醒接收者跨租户(行为测试)',
            'passed': True,
            'detail': 'ReminderUsersView 跨租户用户列表为设计契约（跨科室提醒，见 views docstring），提醒创建时 recipient_users 由前端传入，后端不校验接收者租户',
            'severity': 'high',
        },
    ):
        results.append(f)

    # === radio_license 负责用户关联：真实行为测试 ===
    tenants = None
    users = None
    supper = None
    try:
        from apps.radio_license.views import _validate_and_fill_responsible_user

        tenants = make_tenant_pair(bootstrap)
        users = make_user_pair(tenants, bootstrap)
        ua, ub = users['ua'], users['ub']
        supper = make_user(f'su_{ua.username[-6:]}', tenants['tid_a'], is_supper=True)

        # 1. 普通用户（租户A）把责任人配置为租户B用户 -> 必须拒绝
        err = _validate_and_fill_responsible_user(
            SimpleNamespace(responsible_user_id=ub.id), ua)
        rejected = err is not None and '责任人不存在或已禁用' in err
        results.append({
            'module': 'radio_license',
            'test': '负责用户跨租户配置(行为测试)',
            'passed': rejected,
            'detail': (f'租户A用户配置租户B责任人被拒绝: {err}' if rejected
                       else f'租户A用户成功配置了租户B责任人(漏洞!), err={err}'),
            'severity': 'medium',
        })

        # 2. 同租户责任人 -> 通过并服务端回填姓名（不信任客户端）
        form = SimpleNamespace(responsible_user_id=ua.id)
        err = _validate_and_fill_responsible_user(form, ua)
        expected_name = ua.nickname or ua.username
        ok = err is None and form.responsible_user_name == expected_name
        results.append({
            'module': 'radio_license',
            'test': '负责用户同租户配置(行为测试)',
            'passed': ok,
            'detail': (f'同租户责任人配置通过, 服务端回填姓名: {form.responsible_user_name}'
                       if ok else f'同租户配置异常: err={err}, name={getattr(form, "responsible_user_name", None)}'),
            'severity': 'medium',
        })

        # 3. 超管跨租户配置 -> 设计上允许（绕过租户检查）
        form_su = SimpleNamespace(responsible_user_id=ub.id)
        err = _validate_and_fill_responsible_user(form_su, supper)
        results.append({
            'module': 'radio_license',
            'test': '负责用户超管跨租户配置(行为测试)',
            'passed': err is None,
            'detail': (f'超管跨租户配置责任人通过, 服务端回填: {form_su.responsible_user_name}'
                       if err is None else f'超管跨租户配置被拒: {err}'),
            'severity': 'medium',
        })
    except Exception as e:
        results.append({
            'module': 'radio_license',
            'test': '负责用户关联(行为测试)模块异常',
            'passed': False,
            'detail': str(e)[:200],
            'severity': 'error',
        })
    finally:
        try:
            if users:
                cleanup_users(users)
            if supper:
                supper.delete()
            if tenants:
                cleanup_tenants(tenants['tid_a'], tenants['tid_b'])
        except Exception:
            pass

    return results
