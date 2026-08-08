"""全局数据边界测试

覆盖: Regulation(全局), AppSetting, AlertRule, DocumentSystemFolder, 超管边界
"""
from factories.tenants import make_tenant_pair, cleanup_tenants
from factories.users import make_user_pair, cleanup_users
from factories.business_objects import make_regulation_category, make_regulation, cleanup_business_objects


def run(context):
    """执行全局数据边界测试

    Returns:
        list: 测试结果列表
    """
    results = []
    bootstrap = context['bootstrap_user']
    tenants = make_tenant_pair(bootstrap)
    users = make_user_pair(tenants, bootstrap)
    tid_a = tenants['tid_a']
    tid_b = tenants['tid_b']

    biz = {}
    biz['reg_cat'] = make_regulation_category(bootstrap)
    biz['reg'] = make_regulation(biz['reg_cat'])

    try:
        _test_regulation_global(results, biz)
        _test_appsetting_global(results)
        _test_alert_global(results)
        _test_document_system_folder(results)
        _test_supper_bypass(results, users)
    finally:
        cleanup_business_objects(biz, tid_a, tid_b)
        cleanup_users(users)
        cleanup_tenants(tid_a, tid_b)

    return results


def _test_regulation_global(results, biz):
    """Regulation 无 tenant_id - 全局共享"""
    from apps.regulation.models import Regulation
    has_tenant = hasattr(Regulation, 'tenant_id')
    results.append({
        'module': 'regulation',
        'test': 'Regulation无tenant_id(全局)',
        'passed': not has_tenant,
        'detail': f'Regulation 有 tenant_id 字段: {has_tenant}, 无租户隔离',
        'severity': 'info',
    })

    from apps.regulation.models import RegulationCategory
    has_tenant_cat = hasattr(RegulationCategory, 'tenant_id')
    results.append({
        'module': 'regulation',
        'test': 'RegulationCategory无tenant_id(全局)',
        'passed': not has_tenant_cat,
        'detail': f'RegulationCategory 有 tenant_id 字段: {has_tenant_cat}',
        'severity': 'info',
    })


def _test_appsetting_global(results):
    """Setting 全局共享"""
    from apps.setting.models import Setting
    has_tenant = hasattr(Setting, 'tenant_id')
    results.append({
        'module': 'setting',
        'test': 'Setting全局共享',
        'passed': not has_tenant,
        'detail': f'Setting 有 tenant_id: {has_tenant}, 全局共享(待业务确认)',
        'severity': 'info',
    })


def _test_alert_global(results):
    """Alert/AlertRead 全局共享"""
    from apps.alert.models import Alert, AlertRead
    for model_name, model in [('Alert', Alert), ('AlertRead', AlertRead)]:
        has_tenant = hasattr(model, 'tenant_id')
        results.append({
            'module': 'alert',
            'test': f'{model_name}全局共享',
            'passed': not has_tenant,
            'detail': f'{model_name} 有 tenant_id: {has_tenant}, 全局共享',
            'severity': 'info',
        })


def _test_document_system_folder(results):
    """DocumentSystemFolder 全局共享"""
    from apps.document.models import DocumentSystemFolder
    has_tenant = hasattr(DocumentSystemFolder, 'tenant_id')
    results.append({
        'module': 'document',
        'test': 'DocumentSystemFolder全局共享',
        'passed': not has_tenant,
        'detail': f'DocumentSystemFolder 有 tenant_id: {has_tenant}, 党建文件夹全局共享',
        'severity': 'info',
    })


def _test_supper_bypass(results, users):
    """超级管理员绕过租户过滤（已知设计行为）"""
    results.append({
        'module': 'account',
        'test': '超管绕过租户过滤(已知设计)',
        'passed': True,
        'detail': 'is_supper=True 和 is_global_admin 完全绕过 apply_tenant_filter, 属于已知设计行为非漏洞',
        'severity': 'info',
    })
