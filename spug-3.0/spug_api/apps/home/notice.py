# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.views.generic import View
from libs import json_response, JsonParser, Argument, auth
from libs.idempotency import check_recent_duplicate
from apps.home.models import Notice
from apps.logs.audit import record_audit_event
import json


class NoticeView(View):
    @auth('home.notice.view')
    def get(self, request):
        notices = Notice.objects.filter(is_deleted=False)
        return json_response([x.to_view() for x in notices])

    @auth('home.notice.add|home.notice.edit')
    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('title', required=False),
            Argument('content', required=False),
            Argument('is_stress', type=bool, required=False, default=False),
        ).parse(request.body)
        if error is None:
            if form.is_stress:
                Notice.objects.filter(is_stress=True).update(is_stress=False)
            if form.id:
                # 编辑：只更新传入的非 None 字段，pop id 避免覆盖主键
                record_id = form.pop('id')
                update_data = {k: v for k, v in form.items() if v is not None}
                Notice.objects.filter(pk=record_id).update(**update_data)
            else:
                # 创建：校验必填字段
                if not form.get('title'):
                    return json_response(error='请输入标题')
                if not form.get('content'):
                    return json_response(error='请输入内容')
                if check_recent_duplicate(Notice, {
                    'title': form.get('title'),
                    'content': form.get('content'),
                }):
                    return json_response(error='检测到重复提交，请勿重复操作')
                notice = Notice.objects.create(**form)
                notice.sort_id = notice.id
                notice.save()
        return json_response(error=error)

    @auth('home.notice.edit')
    def patch(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('sort', filter=lambda x: x in ('up', 'down'), required=False),
            Argument('read', required=False)
        ).parse(request.body)
        if error is None:
            notice = Notice.objects.filter(is_deleted=False, pk=form.id).first()
            if not notice:
                return json_response(error='未找到指定记录')
            if form.sort:
                if form.sort == 'up':
                    tmp = Notice.objects.filter(is_deleted=False, sort_id__gt=notice.sort_id).last()
                else:
                    tmp = Notice.objects.filter(is_deleted=False, sort_id__lt=notice.sort_id).first()
                if tmp:
                    tmp.sort_id, notice.sort_id = notice.sort_id, tmp.sort_id
                    tmp.save()
            if form.read:
                read_ids = json.loads(notice.read_ids)
                read_ids.append(str(request.user.id))
                notice.read_ids = json.dumps(read_ids)
            notice.save()
        return json_response(error=error)

    @auth('home.notice.del')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误')
        ).parse(request.GET)
        if error is None:
            notice = Notice.objects.filter(is_deleted=False, pk=form.id).first()
            if notice:
                record_audit_event(
                    request, 'delete', 'notice',
                    target_id=str(notice.id),
                    target_name=notice.title,
                    detail={'title': notice.title}
                )
                from django.utils import timezone
                notice.is_deleted = True
                notice.deleted_at = timezone.now()
                notice.save()
        return json_response(error=error)
