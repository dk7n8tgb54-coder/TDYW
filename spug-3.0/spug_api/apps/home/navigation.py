# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.views.generic import View
from libs import json_response, JsonParser, Argument
from apps.home.models import Navigation
import json


class NavView(View):
    def get(self, request):
        navs = Navigation.objects.all()
        return json_response([x.to_view() for x in navs])

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
            if form.id:
                # 编辑：只更新传入的非 None 字段，pop id 避免覆盖主键
                record_id = form.pop('id')
                update_data = {k: v for k, v in form.items() if v is not None}
                Navigation.objects.filter(pk=record_id).update(**update_data)
            else:
                # 创建：校验必填字段
                required = {'title': '导航标题', 'desc': '导航描述', 'logo': '导航logo', 'links': '导航链接'}
                for field, label in required.items():
                    if not form.get(field):
                        return json_response(error=f'请输入{label}')
                nav = Navigation.objects.create(**form)
                nav.sort_id = nav.id
                nav.save()
        return json_response(error=error)

    def patch(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('sort', filter=lambda x: x in ('up', 'down'), required=False),
        ).parse(request.body)
        if error is None:
            nav = Navigation.objects.filter(pk=form.id).first()
            if not nav:
                return json_response(error='未找到指定记录')
            if form.sort:
                if form.sort == 'up':
                    tmp = Navigation.objects.filter(sort_id__gt=nav.sort_id).last()
                else:
                    tmp = Navigation.objects.filter(sort_id__lt=nav.sort_id).first()
                if tmp:
                    tmp.sort_id, nav.sort_id = nav.sort_id, tmp.sort_id
                    tmp.save()
            nav.save()
        return json_response(error=error)

    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误')
        ).parse(request.GET)
        if error is None:
            Navigation.objects.filter(pk=form.id).delete()
        return json_response(error=error)
