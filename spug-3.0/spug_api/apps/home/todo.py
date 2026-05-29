# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.views.generic import View
from libs import json_response, JsonParser, Argument, human_datetime
from apps.home.models import Todo


class TodoView(View):
    def get(self, request):
        user_id = request.user.id
        todos = Todo.objects.filter(user_id=user_id)
        return json_response([x.to_view() for x in todos])

    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('title', help='请输入待办事项标题'),
            Argument('description', required=False),
            Argument('status', required=False, default='pending'),
            Argument('priority', required=False, default='medium'),
            Argument('due_date', required=False)
        ).parse(request.body)
        if error is None:
            if form.id:
                todo_id = form.pop('id')
                update_data = dict(form)
                update_data['updated_at'] = human_datetime()
                update_data['updated_by'] = request.user.username
                Todo.objects.filter(pk=todo_id).update(**update_data)
            else:
                form.user_id = request.user.id
                form.user_name = request.user.username
                form.created_by = request.user.username
                form.updated_by = request.user.username
                Todo.objects.create(**form)
        return json_response(error=error)

    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)
        if error is None:
            Todo.objects.filter(pk=form.id).delete()
        return json_response(error=error)
