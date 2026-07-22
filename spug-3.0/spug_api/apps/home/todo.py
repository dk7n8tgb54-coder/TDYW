# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.views.generic import View
from django.utils import timezone
from libs import json_response, JsonParser, Argument
from apps.home.models import Todo


class TodoView(View):
    def get(self, request):
        user_id = request.user.id
        todos = Todo.objects.filter(user_id=user_id)
        return json_response([x.to_view() for x in todos])

    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('title', required=False),
            Argument('description', required=False),
            Argument('status', required=False, default='pending'),
            Argument('priority', required=False, default='medium'),
            Argument('due_date', required=False)
        ).parse(request.body)
        if error is None:
            if form.id:
                # 编辑：只更新传入的非 None 字段
                todo_id = form.pop('id')
                update_data = {k: v for k, v in form.items() if v is not None}
                update_data['updated_at'] = timezone.now()
                update_data['updated_by'] = request.user.username
                Todo.objects.filter(pk=todo_id).update(**update_data)
            else:
                # 创建：校验必填字段
                if not form.get('title'):
                    return json_response(error='请输入待办事项标题')
                form.user_id = request.user.id
                form.user_name = request.user.username
                form.created_by = request.user.username
                form.updated_by = request.user.username
                create_data = {k: v for k, v in form.items() if v is not None}
                Todo.objects.create(**create_data)
        return json_response(error=error)

    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)
        if error is None:
            Todo.objects.filter(pk=form.id).delete()
        return json_response(error=error)
