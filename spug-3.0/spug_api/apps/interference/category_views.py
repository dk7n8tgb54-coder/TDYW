"""干扰分类选项查询与维护接口。

选项是全平台共用字典：查询对拥有干扰事件查看权限的用户开放
（事件表单/筛选下拉需要）；维护（新增/编辑/停用/删除）仅超级管理员
可以执行，接口以独立权限码 + is_supper 双重校验，普通用户只能
在事件表单中选择。

删除仅允许未被任何事件引用的选项：删除路径先对选项行
select_for_update 再做引用检查，与事件写入的 lock_event_options
遵循同一行锁顺序，避免并发保存引用到即将删除的选项。
"""

import json

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.views.generic import View

from apps.interference import category_services
from apps.interference.models import (
    CATEGORY_CODE_PATTERN,
    CATEGORY_GROUP_TEXT,
    InterferenceCategoryOption,
)
from apps.logs.audit import record_audit_event
from libs import auth, json_response

# 该权限码不进入任何角色权限树：只有超级管理员（is_supper 绕过权限检查）
# 能通过，普通用户即使在角色里手工配置也无法从页面获得此编码。
CATEGORY_MANAGE_PERMISSION = 'interference.category.manage'

# 三个分组的 unknown 是新建事件分类字段的缺省值，永不允许删除
CATEGORY_DEFAULT_CODE = 'unknown'
CATEGORY_DELETE_FORBIDDEN = (
    '「未知/待查」是新建事件的默认分类值，不允许删除')
CATEGORY_DELETE_REFERENCED = (
    '该选项已被干扰事件引用，不能删除；如需不再供新事件选择，请使用停用功能')


def _body(request):
    """解析 JSON 请求体；空请求统一返回空对象。"""
    if not request.body:
        return {}
    try:
        value = json.loads(request.body.decode('utf-8'))
    except (TypeError, ValueError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _parse_sort_id(raw):
    if raw in (None, ''):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return False
    return value


def _parse_is_active(raw):
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str) and raw.lower() in ('true', 'false'):
        return raw.lower() == 'true'
    if raw in (1, 0):
        return bool(raw)
    return None


def _next_sort_id(group):
    last = InterferenceCategoryOption.objects.filter(group=group).order_by(
        '-sort_id').first()
    return (last.sort_id + 10) if last else 10


def _parse_update_fields(data):
    """解析可更新字段（名称/排序/启用状态），返回 (updates, error)。"""
    updates = {}
    if 'name' in data:
        name = str(data.get('name') or '').strip()
        if not name:
            return None, '请输入选项名称'
        if len(name) > 100:
            return None, '选项名称不能超过100个字符'
        updates['name'] = name
    if 'sort_id' in data:
        sort_id = _parse_sort_id(data.get('sort_id'))
        if sort_id is False:
            return None, '排序值必须为整数'
        if sort_id is not None:
            updates['sort_id'] = sort_id
    if 'is_active' in data:
        is_active = _parse_is_active(data.get('is_active'))
        if is_active is None:
            return None, '启用状态值无效'
        updates['is_active'] = is_active
    return updates, None


class CategoryListView(View):
    @auth('interference.interference.view')
    def get(self, request):
        include_inactive = request.GET.get('include_inactive') in ('1', 'true', 'True')
        if include_inactive and not request.user.is_supper:
            include_inactive = False
        group = request.GET.get('group')
        if group:
            if group not in CATEGORY_GROUP_TEXT:
                return json_response(error='无效的选项分组')
            records = category_services.get_group_options(
                group, include_inactive=include_inactive)
        else:
            qs = InterferenceCategoryOption.objects.all()
            if not include_inactive:
                qs = qs.filter(is_active=True)
            records = list(qs.order_by('group', 'sort_id', 'id'))
        return json_response({
            'records': [option.to_view() for option in records],
            'groups': [
                {'value': key, 'label': label}
                for key, label in CATEGORY_GROUP_TEXT.items()
            ],
        })

    @auth(CATEGORY_MANAGE_PERMISSION)
    def post(self, request):
        if not request.user.is_supper:
            return json_response(error='仅超级管理员可维护分类选项')
        data = _body(request)
        if data is None:
            return json_response(error='请求体必须是 JSON 对象')
        group = data.get('group')
        if group not in CATEGORY_GROUP_TEXT:
            return json_response(error='请选择有效的选项分组')
        code = str(data.get('code') or '').strip()
        if not CATEGORY_CODE_PATTERN.match(code):
            return json_response(
                error='编码必须以小写字母开头，仅含小写字母、数字和下划线')
        name = str(data.get('name') or '').strip()
        if not name:
            return json_response(error='请输入选项名称')
        if len(name) > 100:
            return json_response(error='选项名称不能超过100个字符')
        sort_id = _parse_sort_id(data.get('sort_id'))
        if sort_id is False:
            return json_response(error='排序值必须为整数')
        if sort_id is None:
            sort_id = _next_sort_id(group)
        if InterferenceCategoryOption.objects.filter(group=group, code=code).exists():
            return json_response(error='该分组下已存在相同编码的选项')
        try:
            with transaction.atomic():
                option = InterferenceCategoryOption.objects.create(
                    group=group, code=code, name=name, sort_id=sort_id,
                    created_by=request.user,
                )
                record_audit_event(
                    request, 'create', 'interference_category', str(option.id),
                    option.name,
                    {'group': group, 'code': code, 'sort_id': sort_id},
                )
        except IntegrityError:
            return json_response(error='该分组下已存在相同编码的选项')
        return json_response(option.to_view())


class CategoryDetailView(View):
    @auth(CATEGORY_MANAGE_PERMISSION)
    def put(self, request, pk):
        return self._update(request, pk)

    @auth(CATEGORY_MANAGE_PERMISSION)
    def patch(self, request, pk):
        return self._update(request, pk)

    def _update(self, request, pk):
        if not request.user.is_supper:
            return json_response(error='仅超级管理员可维护分类选项')
        data = _body(request)
        if data is None:
            return json_response(error='请求体必须是 JSON 对象')
        updates, error = _parse_update_fields(data)
        if error:
            return json_response(error=error)
        with transaction.atomic():
            option = InterferenceCategoryOption.objects.select_for_update().filter(
                pk=pk).first()
            if not option:
                return json_response(error='选项不存在')
            for immutable in ('group', 'code'):
                if immutable in data and str(data[immutable]).strip() != getattr(
                        option, immutable):
                    return json_response(error='分组与编码不可修改')
            before = option.to_view()
            for key, value in updates.items():
                setattr(option, key, value)
            option.updated_by = request.user
            option.updated_at = timezone.now()
            option.save()
            record_audit_event(
                request, 'update', 'interference_category', str(option.id),
                option.name, {'group': option.group, 'code': option.code},
                before_value=before, after_value=option.to_view(),
            )
        return json_response(option.to_view())

    @auth(CATEGORY_MANAGE_PERMISSION)
    def delete(self, request, pk):
        if not request.user.is_supper:
            return json_response(error='仅超级管理员可维护分类选项')
        with transaction.atomic():
            # 先锁选项行再查引用，与事件写入路径的 lock_event_options
            # 形成同一行锁顺序：并发保存的事件要么先持锁（删除被阻塞、
            # 引用落库后删除被拒），要么在删除提交后因选项缺失被拒绝。
            option = InterferenceCategoryOption.objects.select_for_update().filter(
                pk=pk).first()
            if not option:
                return json_response(error='选项不存在')
            if option.code == CATEGORY_DEFAULT_CODE:
                return json_response(error=CATEGORY_DELETE_FORBIDDEN)
            if category_services.count_option_references(option):
                return json_response(error=CATEGORY_DELETE_REFERENCED)
            detail = {'group': option.group, 'code': option.code}
            option_id, option_name = option.id, option.name
            option.delete()
            record_audit_event(
                request, 'delete', 'interference_category', str(option_id),
                option_name, detail,
            )
        return json_response()
