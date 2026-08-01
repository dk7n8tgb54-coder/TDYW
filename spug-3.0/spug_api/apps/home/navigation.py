# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.views.generic import View
from django.db import transaction
from django.utils import timezone
from libs import json_response, JsonParser, Argument, auth
from libs.idempotency import check_recent_duplicate
from apps.home.models import Navigation
from apps.logs.audit import record_audit_event
import json


def _get_user_name(user):
    """获取用户显示名"""
    return getattr(user, 'nickname', '') or getattr(user, 'username', '')


class NavView(View):
    @auth('home.navigation.view')
    def get(self, request):
        navs = Navigation.objects.filter(is_deleted=False)[:100]
        return json_response([x.to_view() for x in navs])

    @auth('home.navigation.add|home.navigation.edit')
    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('title', required=False),
            Argument('desc', required=False),
            Argument('logo', required=False),
            Argument('links', type=list, required=False, filter=lambda x: len(x)),
        ).parse(request.body)
        if error is None:
            if form.links is not None:
                form.links = json.dumps(form.links)
            now = timezone.now()
            user_id = request.user.id
            user_name = _get_user_name(request.user)
            if form.id:
                # 编辑：只更新传入的非 None 字段，pop id 避免覆盖主键
                record_id = form.pop('id')
                update_data = {k: v for k, v in form.items() if v is not None}
                update_data['updated_at'] = now
                update_data['updated_by_id'] = user_id
                update_data['updated_by_name'] = user_name
                affected = Navigation.objects.filter(is_deleted=False, pk=record_id).update(**update_data)
                if affected == 0:
                    return json_response(error='未找到指定记录')
                record_audit_event(
                    request, 'edit', 'navigation',
                    target_id=str(record_id),
                    target_name=form.get('title', ''),
                    detail=update_data
                )
            else:
                # 创建：校验必填字段
                required = {'title': '导航标题', 'desc': '导航描述', 'logo': '导航logo', 'links': '导航链接'}
                for field, label in required.items():
                    if not form.get(field):
                        return json_response(error=f'请输入{label}')
                if check_recent_duplicate(Navigation, {
                    'title': form.get('title'),
                    'desc': form.get('desc'),
                }):
                    return json_response(error='检测到重复提交，请勿重复操作')
                form.pop('id', None)
                with transaction.atomic():
                    nav = Navigation.objects.create(**form)
                    nav.sort_id = nav.id
                    nav.updated_at = now
                    nav.updated_by_id = user_id
                    nav.updated_by_name = user_name
                    nav.save(update_fields=['sort_id', 'updated_at', 'updated_by_id', 'updated_by_name'])
                record_audit_event(
                    request, 'create', 'navigation',
                    target_id=str(nav.id),
                    target_name=nav.title,
                    detail={'title': nav.title, 'desc': nav.desc}
                )
        return json_response(error=error)

    @auth('home.navigation.edit')
    def patch(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('sort', filter=lambda x: x in ('up', 'down'), required=False),
        ).parse(request.body)
        if error is None:
            nav = Navigation.objects.filter(is_deleted=False, pk=form.id).first()
            if not nav:
                return json_response(error='未找到指定记录')
            if form.sort:
                with transaction.atomic():
                    # select_for_update 锁行，防止并发排序竞态
                    nav = Navigation.objects.select_for_update().filter(is_deleted=False, pk=form.id).first()
                    if form.sort == 'up':
                        tmp = Navigation.objects.select_for_update().filter(
                            is_deleted=False, sort_id__gt=nav.sort_id
                        ).order_by('sort_id').first()
                    else:
                        tmp = Navigation.objects.select_for_update().filter(
                            is_deleted=False, sort_id__lt=nav.sort_id
                        ).order_by('-sort_id').first()
                    if tmp:
                        tmp.sort_id, nav.sort_id = nav.sort_id, tmp.sort_id
                        tmp.save(update_fields=['sort_id'])
                        nav.save(update_fields=['sort_id'])
                        record_audit_event(
                            request, 'sort', 'navigation',
                            target_id=str(nav.id),
                            target_name=nav.title,
                            detail={'action': form.sort, 'swap_id': tmp.id}
                        )
        return json_response(error=error)

    @auth('home.navigation.del')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误')
        ).parse(request.GET)
        if error is None:
            nav = Navigation.objects.filter(is_deleted=False, pk=form.id).first()
            if nav:
                with transaction.atomic():
                    record_audit_event(
                        request, 'delete', 'navigation',
                        target_id=str(nav.id),
                        target_name=nav.title,
                        detail={'title': nav.title, 'desc': nav.desc}
                    )
                    nav.is_deleted = True
                    nav.deleted_at = timezone.now()
                    nav.deleted_by_id = request.user.id
                    nav.deleted_by_name = _get_user_name(request.user)
                    nav.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by_id', 'deleted_by_name'])
            else:
                return json_response(error='未找到指定记录')
        return json_response(error=error)
