# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
用户角色委派权限边界工具

所有角色列表、用户创建/编辑、角色创建/编辑/删除都应通过本模块的方法
判断当前操作者可委派/可管理的角色范围。安全判断以后端为准，前端只做体验优化。

设计原则：
- 超级管理员（is_supper=True）不受限制，可管理全部租户和全部角色。
- 普通管理员只能操作本租户内、非系统、非全局管理员的普通角色。
- 普通管理员创建或编辑角色时，新角色权限必须是当前操作者已有权限的子集。
"""
import json


def get_assignable_roles(operator):
    """返回当前操作者可分配给其他用户的角色 queryset。

    超级管理员：全部角色。
    普通管理员：本租户内、非系统、非全局管理员的普通角色。
    """
    from apps.account.models import Role

    if operator.is_supper:
        return Role.objects.all()

    return Role.objects.filter(
        tenant_id=operator.tenant_id,
        is_system=False,
        is_global_admin=False,
    )


def validate_assignable_role_ids(operator, role_ids, target_tenant_id=None):
    """校验操作者是否有权将给定的 role_ids 分配给目标租户用户。

    返回 None 表示通过，返回字符串表示错误信息。

    - 普通管理员：只能分配本租户、非系统、非全局管理员角色。
      target_tenant_id 必须等于操作者自身 tenant_id（由调用方保证）。
    - 超级管理员：默认不再无差别放行，需校验角色与目标租户的一致性：
        * 平台级角色（tenant_id is null）：可分配给任意租户用户
        * 全局管理员角色：可分配给任意租户用户
        * 租户角色（tenant_id 非空）：仅当 tenant_id == target_tenant_id 才可分配
      target_tenant_id 为 None 时（无法确定目标租户）超管按宽松策略放行，
      以保持向后兼容；但创建/编辑用户场景调用方应传入明确的目标租户。
    """
    requested_ids = set(role_ids or [])
    if not requested_ids:
        return None

    from apps.account.models import Role

    # 先校验所有 role_id 都存在，避免 user.roles.set 抛异常或 500
    found_ids = set(Role.objects.filter(id__in=requested_ids).values_list('id', flat=True))
    missing_ids = requested_ids - found_ids
    if missing_ids:
        return '包含不存在的角色'

    if operator.is_supper:
        # 无法确定目标租户时，超管宽松放行（向后兼容旧调用）
        if target_tenant_id is None:
            return None
        # 超管：校验租户角色与目标租户一致性，平台级角色和全局管理员角色不限
        conflict_roles = Role.objects.filter(
            id__in=requested_ids,
            is_global_admin=False,
            tenant_id__isnull=False,
        ).exclude(tenant_id=target_tenant_id)
        if conflict_roles.exists():
            return '不能将其他租户的角色分配给该租户用户'
        return None

    # 普通管理员：只能分配本租户普通角色
    allowed_ids = set(
        get_assignable_roles(operator).values_list('id', flat=True)
    )

    if not requested_ids.issubset(allowed_ids):
        return '无权分配所选角色，仅可分配本租户内的普通角色'

    return None


def get_manageable_role(operator, role_id):
    """返回当前操作者可管理的单个角色，取不到返回 None。

    用于角色编辑/删除场景。普通管理员只能操作本租户、非系统、非全局管理员角色。
    取不到时不返回过细错误，避免泄露其他租户或系统角色信息。
    """
    from apps.account.models import Role

    queryset = Role.objects.filter(pk=role_id)

    if not operator.is_supper:
        queryset = queryset.filter(
            tenant_id=operator.tenant_id,
            is_system=False,
            is_global_admin=False,
        )

    return queryset.first()


def flatten_page_perms(page_perms):
    """将嵌套字典的 page_perms 展平成权限 key 集合。

    输入格式：{'module_key': {'page_key': ['perm_key', ...]}}
    输出格式：{'module_key.page_key.perm_key', ...}
    """
    result = set()
    for module_key, pages in (page_perms or {}).items():
        for page_key, perms in (pages or {}).items():
            for perm_key in perms or []:
                result.add(f'{module_key}.{page_key}.{perm_key}')
    return result


def _parse_json_field(value):
    """安全解析 JSON 字段，None/空返回 None。"""
    if not value:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def validate_page_perms_subset(operator, page_perms):
    """校验角色 page_perms 是否为操作者已有权限的子集。

    返回 None 表示通过，返回字符串表示错误信息。
    超级管理员直接通过。
    """
    if operator.is_supper:
        return None

    requested = flatten_page_perms(page_perms)
    if not requested:
        return None

    allowed = operator.page_perms
    extra = requested - allowed
    if extra:
        return '角色页面权限不能超过当前账号权限范围'

    return None


def validate_group_perms_subset(operator, group_perms):
    """校验角色 group_perms 是否为操作者已有 group_perms 的子集。

    返回 None 表示通过，返回字符串表示错误信息。
    超级管理员直接通过。
    """
    if operator.is_supper:
        return None

    requested = set(group_perms or [])
    if not requested:
        return None

    allowed = set(operator.group_perms)
    extra = requested - allowed
    if extra:
        return '角色分组权限不能超过当前账号权限范围'

    return None


def validate_deploy_perms_subset(operator, deploy_perms):
    """校验角色 deploy_perms 是否为操作者已有 deploy 权限范围的子集。

    deploy_perms 结构：{'apps': [...], 'envs': [...]}
    普通管理员只能选择自己已有 deploy 权限范围内的应用和环境。
    返回 None 表示通过，返回字符串表示错误信息。
    超级管理员直接通过。
    """
    if operator.is_supper:
        return None

    requested = _parse_json_field(deploy_perms)
    if not requested:
        return None

    # 聚合操作者所有角色的 deploy_perms 并集
    allowed = {'apps': set(), 'envs': set()}
    for role in operator.roles.all():
        role_deploy = _parse_json_field(role.deploy_perms)
        if not role_deploy:
            continue
        allowed['apps'].update(role_deploy.get('apps') or [])
        allowed['envs'].update(role_deploy.get('envs') or [])

    req_apps = set(requested.get('apps') or [])
    req_envs = set(requested.get('envs') or [])

    extra_apps = req_apps - allowed['apps']
    extra_envs = req_envs - allowed['envs']

    if extra_apps or extra_envs:
        return '角色发布权限不能超过当前账号权限范围'

    return None
