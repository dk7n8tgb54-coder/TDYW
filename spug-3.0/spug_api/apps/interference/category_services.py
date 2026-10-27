"""干扰分类选项域服务：选项查询、事件写入校验与编码-名称映射。

选项是全平台共用字典（InterferenceCategoryOption，无租户字段），
仅超级管理员维护；事件写入时以「编码存在且启用」为准，停用编码
仅允许既有事件原值保留；历史事件显示按编码查选项名称。

并发约定（选项删除 vs 事件写入）：事件写入路径在写库前必须调用
lock_event_options 对将引用的选项行加行锁并复核；删除路径先对选项
行 select_for_update 再检查引用。两侧遵循同一行锁顺序，保证事件
不会引用一个已被（或正在被）删除的选项。
"""

from apps.interference.models import (
    CATEGORY_GROUP_KIND,
    CATEGORY_GROUP_SOURCE,
    CATEGORY_GROUP_SYSTEM,
    CATEGORY_GROUP_TEXT,
    InterferenceCategoryOption,
    InterferenceEvent,
    SCENE_CODE_TEXT,
)

# 事件分类字段 → 选项分组的固定对应关系（分组键 = 字段名去 _code 后缀）
EVENT_CATEGORY_FIELDS = (
    ('interference_kind_code', CATEGORY_GROUP_KIND, '具体干扰类型'),
    ('affected_system_code', CATEGORY_GROUP_SYSTEM, '受影响系统'),
    ('source_type_code', CATEGORY_GROUP_SOURCE, '疑似干扰源'),
)
EVENT_CATEGORY_FIELD_GROUPS = {
    field: group for field, group, _ in EVENT_CATEGORY_FIELDS
}
EVENT_CATEGORY_FIELD_LABELS = {
    field: label for field, _, label in EVENT_CATEGORY_FIELDS
}


def get_group_options(group, include_inactive=False):
    """返回分组内选项（默认仅启用），按排序值和创建顺序排列。"""
    qs = InterferenceCategoryOption.objects.filter(group=group)
    if not include_inactive:
        qs = qs.filter(is_active=True)
    return list(qs.order_by('sort_id', 'id'))


def load_category_text_maps(include_inactive=True):
    """构建 {分组: {编码: 名称}} 映射；一次查询覆盖全部分组。

    事件展示默认包含停用选项，保证历史编码始终能映射到名称。
    """
    qs = InterferenceCategoryOption.objects.all()
    if not include_inactive:
        qs = qs.filter(is_active=True)
    maps = {group: {} for group in CATEGORY_GROUP_TEXT}
    for option in qs:
        maps[option.group][option.code] = option.name
    return maps


def load_active_grouped_options():
    """构建 {事件字段名: [{value, label}]}，供事件表单/筛选下拉使用。"""
    options = {field: [] for field, _, _ in EVENT_CATEGORY_FIELDS}
    for option in InterferenceCategoryOption.objects.filter(
            is_active=True).order_by('group', 'sort_id', 'id'):
        field = f'{option.group}_code'
        if field in options:
            options[field].append({'value': option.code, 'label': option.name})
    return options


def load_option_maps():
    """一次查询构建事件写入校验所需的全部映射。

    返回 ``(active_code_maps, all_code_maps, name_maps)``：
    - active_code_maps：启用编码 → 名称（新写入允许的取值）；
    - all_code_maps：全部编码 → 名称（停用编码原值保留时校验存在性）；
    - name_maps：名称 → 编码（CSV 导入按名称回填）。
    """
    active_code_maps = {group: {} for group in CATEGORY_GROUP_TEXT}
    all_code_maps = {group: {} for group in CATEGORY_GROUP_TEXT}
    name_maps = {group: {} for group in CATEGORY_GROUP_TEXT}
    for option in InterferenceCategoryOption.objects.all().order_by('sort_id', 'id'):
        all_code_maps[option.group][option.code] = option.name
        name_maps[option.group][option.name] = option.code
        if option.is_active:
            active_code_maps[option.group][option.code] = option.name
    return active_code_maps, all_code_maps, name_maps


def _resolve_scene_value(raw):
    """场景取值兼容编码与显示名称，返回 (code, error)。"""
    if raw in SCENE_CODE_TEXT:
        return raw, None
    for code, text in SCENE_CODE_TEXT.items():
        if text == raw:
            return code, None
    return None, '发生场景值无效'


def _resolve_category_value(group, raw, all_codes, names, label):
    """分类取值兼容编码与显示名称，返回 (code, error)。"""
    if not isinstance(raw, str):
        return None, f'{label}值无效'
    value = raw.strip()
    if value in all_codes:
        return value, None
    if value in names:
        return names[value], None
    return None, f'{label}值无效'


def normalize_event_options(values, existing=None, option_maps=None):
    """解析并校验事件负载中的场景与三个分类字段，返回错误或 None。

    - 场景与分类入参兼容编码与显示名称（CSV 导入往返）；
    - 分类编码必须存在且启用；停用编码仅允许既有事件原值保留，
      保证停用选项不影响历史事件的编辑保存。
    """
    if option_maps is None:
        option_maps = load_option_maps()
    active_code_maps, all_code_maps, name_maps = option_maps
    scene, error = _resolve_scene_value(values.get('scene_code'))
    if error:
        return error
    values['scene_code'] = scene
    for field, group, label in EVENT_CATEGORY_FIELDS:
        code, error = _resolve_category_value(
            group, values.get(field), all_code_maps[group],
            name_maps[group], label)
        if error:
            return error
        values[field] = code
        if code not in active_code_maps[group]:
            retained = existing is not None and getattr(existing, field, None) == code
            if not retained:
                return f'{label}选项不存在或已停用'
    return None


def lock_event_options(values, existing=None):
    """对事件将引用的三个分类选项行加行锁并复核可用性。

    事件新增/编辑/导入在写库前、事务内调用；按 EVENT_CATEGORY_FIELDS
    固定顺序加锁，与选项删除（先锁选项行再查引用）形成同一锁序：
    - 事件写入先持锁：删除阻塞，提交后其引用检查能看到新事件并拒绝删除；
    - 删除先持锁并删除：事件写入的 select_for_update 读不到行，拒绝保存。
    任何一侧都不可能留下引用已删除选项的事件。
    """
    for field, group, label in EVENT_CATEGORY_FIELDS:
        code = values.get(field)
        option = InterferenceCategoryOption.objects.select_for_update().filter(
            group=group, code=code).first()
        if option is None:
            return f'{label}选项不存在或已被删除'
        retained = existing is not None and getattr(existing, field, None) == code
        if not option.is_active and not retained:
            return f'{label}选项不存在或已停用'
    return None


def count_option_references(option):
    """统计选项被干扰事件引用的次数（跨全部租户、含软删除事件）。"""
    field = f'{option.group}_code'
    if field not in EVENT_CATEGORY_FIELD_GROUPS:
        return 0
    # all_with_deleted：不走租户过滤与 is_deleted 过滤，软删除的历史
    # 事件同样占用编码，保证删除后历史显示不被破坏。
    return InterferenceEvent.objects.all_with_deleted().filter(
        **{field: option.code}).count()


__all__ = [
    'EVENT_CATEGORY_FIELDS', 'EVENT_CATEGORY_FIELD_GROUPS',
    'EVENT_CATEGORY_FIELD_LABELS', 'get_group_options',
    'load_category_text_maps', 'load_active_grouped_options',
    'load_option_maps', 'normalize_event_options',
    'lock_event_options', 'count_option_references',
]
