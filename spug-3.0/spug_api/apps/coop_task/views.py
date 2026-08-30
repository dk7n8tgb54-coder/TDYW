# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""协作任务模块接口

跨科室可见性规则（视图层显式校验，附件查询统一 skip_tenant_filter 后自行鉴权）：
- 发起方：校验 task.tenant_id == user.tenant_id（超管放行）
- 交付方：校验 assignment.target_tenant_id == user.tenant_id
- 附件读：交付科室随时可读；发起科室仅材料提交后可读（待交付为草稿，已退回件保持可见）
- 材料模板（item_template）：发起科室上传/删除（任务进行中），发起科室与被分派交付科室可读可下载；删除为物理删除
- 附件写（上传/删除）：仅交付科室，且任务进行中、明细未验收；删除为物理删除

审计联动：
- 全部写操作成功后显式 record_audit_event（置 _audit_handled 防止中间件重复记录），
  action 使用审计模块标准词汇表（create/update/delete/approve），业务细节进 detail；
- 显式未覆盖的写操作（含业务失败响应）由 AuditLogMiddleware 兜底记录；
- GET 查询与附件下载遵循审计模块全局约定（非 GET 才记录）不进审计。
"""
import logging
from datetime import datetime

from django.conf import settings
from django.db import transaction
from django.db.models import Count, F, Q
from django.utils import timezone
from django.views import View

from libs import json_response, JsonParser, Argument, auth
from apps.account.models import Tenant, User
from apps.logs.audit import record_audit_event
from apps.evidence.attachment_service import (
    AttachmentService, AttachmentConfig, PREVIEWABLE_EXTENSIONS)
from apps.evidence.models import EvidenceAttachment

from .models import (
    CoopTask, CoopTaskItem, CoopTaskAssignment, CoopTaskDelivery,
    TASK_STATUS_IN_PROGRESS, TASK_STATUS_COMPLETED, TASK_STATUS_VOIDED,
    TASK_STATUS_TEXT, DELIVERY_STATUS_TEXT, ASSIGNMENT_STATUS_TEXT,
    DELIVERY_PENDING, DELIVERY_SUBMITTED, DELIVERY_ACCEPTED, DELIVERY_REJECTED,
    compute_assignment_status,
)

logger = logging.getLogger(__name__)

MODULE = 'coop_task'
PERM_VIEW = 'coop.task.view'
PERM_ADD = 'coop.task.add'
PERM_EDIT = 'coop.task.edit'
PERM_DELETE = 'coop.task.delete'
PERM_SUBMIT = 'coop.task.submit'
PERM_ACCEPT = 'coop.task.accept'

# 附件模块标识与业务对象类型（EvidenceAttachment.module / object_type）
ATTACHMENT_MODULE = 'coop_task'
ATTACHMENT_OBJECT_TYPE = 'delivery'
TEMPLATE_OBJECT_TYPE = 'item_template'

CoopTaskAttachmentConfig = AttachmentConfig(
    allowed_extensions=('.pdf', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp',
                        '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
                        '.zip', '.rar', '.7z'),
    max_size_mb=50,
)


# ==================== 通用辅助 ====================

def _parse_deadline(value):
    """解析截止时间，支持 'YYYY-MM-DD HH:mm:ss' / 'YYYY-MM-DD HH:mm' / 'YYYY-MM-DD'"""
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            dt = datetime.strptime(value, fmt)
            # 项目 USE_TZ=False，仅在使用时区时才做 aware 转换
            return timezone.make_aware(dt) if settings.USE_TZ else dt
        except (ValueError, TypeError):
            continue
    return None


def _snapshot_name(user):
    return getattr(user, 'nickname', '') or getattr(user, 'username', '')


def _get_task_for_initiator(user, pk):
    """发起方视角取任务：仅本租户创建的任务（超管放行）"""
    qs = CoopTask.objects.filter(pk=pk, is_deleted=False)
    if not user.is_supper:
        qs = qs.filter(tenant_id=user.tenant_id)
    return qs.first()


def _get_assignment_for_deliverer(user, pk):
    """交付方视角取分派：交付科室必须是本人租户（超管不特殊放行，避免误入他人待办）"""
    return CoopTaskAssignment.objects.filter(
        pk=pk,
        target_tenant_id=user.tenant_id,
        task__is_deleted=False,
    ).select_related('task').first()


def _validate_task_items(form):
    """校验材料清单，返回 (cleaned_items, None) 或 (None, error)"""
    # 注意：form 是 AttrDict(dict)，items 与 dict 方法名碰撞，必须用 [] 取值
    items = form['items'] if isinstance(form['items'], list) else []
    cleaned_items = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            return None, f'第 {index} 条材料格式不正确'
        name = str(item.get('name') or '').strip()
        if not name:
            return None, f'第 {index} 条材料名称不能为空'
        if len(name) > 200:
            return None, f'第 {index} 条材料名称过长'
        cleaned_items.append({'name': name, 'remark': str(item.get('remark') or '').strip()[:500]})
    if not cleaned_items:
        return None, '请至少填写一项材料'
    return cleaned_items, None


def _validate_task_targets(form):
    """校验交付对象，返回 (cleaned_targets, None) 或 (None, error)

    targets 支持两种形式：
    - {'user_id': 3}   新格式：按交付科室账号分发，后端映射回租户并快照账号ID/人名
    - {'tenant_id': 't_b', 'contact_user_name': '李四'}  旧格式：直接指定租户（兼容保留）
    """
    targets = form['targets'] if isinstance(form['targets'], list) else []
    raw_targets = []
    user_ids = []
    for index, target in enumerate(targets, start=1):
        if isinstance(target, dict):
            uid = target.get('user_id')
            tid = str(target.get('tenant_id') or '').strip()
            contact = str(target.get('contact_user_name') or '').strip()[:100]
        else:
            uid, tid, contact = None, str(target or '').strip(), ''
        if uid not in (None, ''):
            try:
                uid = int(uid)
            except (TypeError, ValueError):
                return None, f'第 {index} 个交付科室格式不正确'
            raw_targets.append({'user_id': uid, 'tenant_id': '', 'contact_user_name': contact})
            user_ids.append(uid)
        elif tid:
            raw_targets.append({'user_id': None, 'tenant_id': tid, 'contact_user_name': contact})
        else:
            return None, f'第 {index} 个交付科室格式不正确'

    users_by_id = {}
    if user_ids:
        users_by_id = {u.id: u for u in User.objects.filter(
            id__in=user_ids, is_active=True, deleted_at__isnull=True)}

    cleaned_targets = []
    seen_tenant_ids = set()
    for index, raw in enumerate(raw_targets, start=1):
        if raw['user_id'] is not None:
            user = users_by_id.get(raw['user_id'])
            if not user:
                return None, f'第 {index} 个交付科室账号不存在或已停用'
            tid = user.tenant_id
            contact_id = user.id
            contact = getattr(user, 'nickname', '') or getattr(user, 'username', '')
        else:
            tid = raw['tenant_id']
            contact_id = None
            contact = raw['contact_user_name']
        if tid in seen_tenant_ids:
            return None, '交付科室不能重复'
        seen_tenant_ids.add(tid)
        cleaned_targets.append({
            'tenant_id': tid, 'contact_user_id': contact_id, 'contact_user_name': contact})
    if not cleaned_targets:
        return None, '请至少选择一个交付科室'

    tenant_names = {str(tid): name for tid, name in Tenant.objects.filter(
        id__in=[t['tenant_id'] for t in cleaned_targets]
    ).values_list('id', 'name')}
    missing = [t['tenant_id'] for t in cleaned_targets if t['tenant_id'] not in tenant_names]
    if missing:
        return None, '包含不存在的交付科室'
    for target in cleaned_targets:
        target['tenant_name'] = tenant_names[target['tenant_id']]

    return cleaned_targets, None


def _validate_create_form(form):
    """校验创建/编辑表单，返回 (deadline, items, targets, None) 或 (None, None, None, error)"""
    title = (form.title or '').strip()
    if not title:
        return None, None, None, '请输入任务标题'
    if len(title) > 200:
        return None, None, None, '任务标题长度不能超过200个字符'

    deadline = _parse_deadline(form.deadline or '')
    if not deadline:
        return None, None, None, '截止时间格式错误'

    items, err = _validate_task_items(form)
    if err:
        return None, None, None, err

    targets, err = _validate_task_targets(form)
    if err:
        return None, None, None, err

    return deadline, items, targets, None


def _refresh_task_completion(task):
    """全部交付明细验收通过后自动完成任务（调用方需持有 task 行锁）"""
    agg = CoopTaskDelivery.objects.filter(assignment__task_id=task.id).aggregate(
        total=Count('id'),
        accepted=Count('id', filter=Q(status=DELIVERY_ACCEPTED)),
    )
    if agg['total'] and agg['total'] == agg['accepted'] and task.status == TASK_STATUS_IN_PROGRESS:
        task.status = TASK_STATUS_COMPLETED
        task.completed_at = timezone.now()
        task.save(update_fields=['status', 'completed_at'])


def _attachment_counts(delivery_ids):
    """批量统计交付明细附件数，返回 {delivery_id(str): count}"""
    if not delivery_ids:
        return {}
    rows = EvidenceAttachment.objects.filter(
        module=ATTACHMENT_MODULE,
        object_type=ATTACHMENT_OBJECT_TYPE,
        object_id__in=[str(x) for x in delivery_ids],
        is_deleted=False,
    ).values('object_id').annotate(total=Count('id'))
    return {row['object_id']: row['total'] for row in rows}


def _templates_by_item(item_ids):
    """批量取材料模板附件，返回 {item_id: [view...]}"""
    if not item_ids:
        return {}
    rows = EvidenceAttachment.objects.filter(
        module=ATTACHMENT_MODULE,
        object_type=TEMPLATE_OBJECT_TYPE,
        object_id__in=[str(x) for x in item_ids],
        is_deleted=False,
    ).order_by('id')
    result = {}
    for att in rows:
        result.setdefault(int(att.object_id), []).append({
            'id': att.id,
            'file_name': att.file_name,
            'file_size': att.file_size,
            'previewable': att.file_ext in PREVIEWABLE_EXTENSIONS,
        })
    return result


def _assignment_aggregates(assignment_ids):
    """批量聚合分派进度，返回 {assignment_id: {total/accepted/submitted/rejected/pending/status}}"""
    if not assignment_ids:
        return {}
    rows = CoopTaskDelivery.objects.filter(assignment_id__in=assignment_ids).values(
        'assignment_id').annotate(
        total=Count('id'),
        accepted=Count('id', filter=Q(status=DELIVERY_ACCEPTED)),
        submitted=Count('id', filter=Q(status=DELIVERY_SUBMITTED)),
        rejected=Count('id', filter=Q(status=DELIVERY_REJECTED)),
        pending=Count('id', filter=Q(status=DELIVERY_PENDING)),
    )
    result = {}
    for row in rows:
        status = compute_assignment_status(
            row['total'], row['accepted'], row['rejected'], row['pending'])
        result[row['assignment_id']] = {
            'total': row['total'],
            'accepted': row['accepted'],
            'submitted': row['submitted'],
            'rejected': row['rejected'],
            'pending': row['pending'],
            'aggregate_status': status,
            'aggregate_status_text': ASSIGNMENT_STATUS_TEXT.get(status, status),
        }
    return result


def _serialize_deliveries(deliveries, counts):
    data = []
    for delivery in deliveries:
        item = delivery.to_view()
        item['attachment_count'] = counts.get(str(delivery.id), 0)
        data.append(item)
    return data


# ==================== 科室列表 ====================

class DepartmentListView(View):
    """可选交付对象（各科室登录账号），供创建任务时选择

    实际部署为"一科室一账号、账号即经办人姓名"，因此按账号（人名）列出可选对象；
    创建任务时后端将账号映射回其租户，分发与鉴权仍以租户为边界。
    """

    @auth(PERM_VIEW)
    def get(self, request):
        users = User.objects.filter(
            is_active=True, is_supper=False, deleted_at__isnull=True).order_by('id')
        tenant_names = dict(Tenant.objects.filter(
            id__in={u.tenant_id for u in users}).values_list('id', 'name'))
        return json_response([
            {'id': u.id, 'name': u.nickname or u.username,
             'tenant_id': u.tenant_id,
             'tenant_name': tenant_names.get(u.tenant_id, u.tenant_id)}
            for u in users
        ])


# ==================== 发起方：任务 ====================

class TaskView(View):
    """我发起的任务列表 / 创建"""

    @auth(PERM_VIEW)
    def get(self, request):
        form, error = JsonParser(
            Argument('keyword', required=False),
            Argument('status', required=False),
            Argument('page', type=int, default=1),
            Argument('page_size', type=int, default=20),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        # 分页下限保护：负数会让 ORM 切片抛异常转 500
        page = max(form.page, 1)
        page_size = max(form.page_size, 0)
        qs = CoopTask.objects.filter(is_deleted=False)
        if not request.user.is_supper:
            qs = qs.filter(tenant_id=request.user.tenant_id)
        if form.status:
            qs = qs.filter(status=form.status)
        if form.keyword:
            qs = qs.filter(Q(title__contains=form.keyword) | Q(description__contains=form.keyword))
        total = qs.count()
        tasks = list(qs.order_by('-id')[(page - 1) * page_size: page * page_size])
        now = timezone.now()
        if not tasks:
            return json_response({'results': [], 'total': total})
        # 按任务聚合分派进度
        assign_rows = list(CoopTaskAssignment.objects.filter(
            task_id__in=[t.id for t in tasks]).values(
            'task_id', 'id', 'target_tenant_name', 'contact_user_id', 'contact_user_name'))
        aggregates = _assignment_aggregates([row['id'] for row in assign_rows])
        assigns_by_task = {}
        for row in assign_rows:
            assigns_by_task.setdefault(row['task_id'], []).append(row)
        results = []
        for task in tasks:
            item = task.to_view(now)
            rows = assigns_by_task.get(task.id, [])
            aggs = [aggregates.get(row['id'], {}) for row in rows]
            # 按账号分发的分派展示账号人名，旧数据回落到科室名
            item['target_tenants'] = [
                (row['contact_user_name'] if row['contact_user_id'] else '') or row['target_tenant_name']
                for row in rows
            ]
            item['progress'] = {
                'total': sum(a.get('total', 0) for a in aggs),
                'accepted': sum(a.get('accepted', 0) for a in aggs),
                'submitted': sum(a.get('submitted', 0) for a in aggs),
                'rejected': sum(a.get('rejected', 0) for a in aggs),
                'pending': sum(a.get('pending', 0) for a in aggs),
            }
            results.append(item)
        return json_response({'results': results, 'total': total})

    @transaction.atomic()
    @auth(PERM_ADD)
    def post(self, request):
        form, error = JsonParser(
            Argument('title', help='请输入任务标题'),
            Argument('description', required=False, default=''),
            Argument('deadline', help='请选择交付截止时间'),
            Argument('items', type=list, help='请至少填写一项材料'),
            Argument('targets', type=list, help='请至少选择一个交付科室'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        deadline, items, targets, err = _validate_create_form(form)
        if err:
            return json_response(error=err)

        user = request.user
        now = timezone.now()
        task = CoopTask(
            tenant_id=getattr(user, 'tenant_id', ''),
            title=(form.title or '').strip(),
            description=(form.description or '').strip()[:20000],
            deadline=deadline,
            status=TASK_STATUS_IN_PROGRESS,
            created_by_id=user.id,
            created_by_name=_snapshot_name(user),
        )
        with transaction.atomic():
            task.save()
            item_objs = [
                CoopTaskItem(task=task, name=x['name'], remark=x['remark'], sort_order=index)
                for index, x in enumerate(items)
            ]
            CoopTaskItem.objects.bulk_create(item_objs)
            for target in targets:
                assignment = CoopTaskAssignment(
                    tenant_id=task.tenant_id,
                    task=task,
                    target_tenant_id=target['tenant_id'],
                    target_tenant_name=target['tenant_name'],
                    contact_user_id=target['contact_user_id'],
                    contact_user_name=target['contact_user_name'],
                )
                assignment.save()
                CoopTaskDelivery.objects.bulk_create([
                    CoopTaskDelivery(assignment=assignment, item=item)
                    for item in item_objs
                ])
        record_audit_event(
            request, 'create', target_type=MODULE, target_id=task.id, target_name=task.title,
            detail={
                'deadline': deadline.strftime('%Y-%m-%d %H:%M:%S'),
                'items': [x['name'] for x in items],
                'target_tenants': [
                    f"{x['contact_user_name']}（{x['tenant_name']}）" if x['contact_user_id']
                    else x['tenant_name']
                    for x in targets
                ],
            })
        return json_response(task.to_view())


class TaskDetailView(View):
    """任务详情 / 编辑（标题、说明、截止时间） / 删除"""

    @auth(PERM_VIEW)
    def get(self, request, pk):
        task = _get_task_for_initiator(request.user, pk)
        if not task:
            return json_response(error='任务不存在或无权限访问')
        items = list(task.items.all())
        assignments = list(task.assignments.all().order_by('id'))
        deliveries = list(CoopTaskDelivery.objects.filter(
            assignment__task_id=task.id).order_by('id'))
        counts = _attachment_counts([d.id for d in deliveries])
        # 待交付材料是交付方草稿：发起方不可见附件，计数一并归零
        if not request.user.is_supper:
            for d in deliveries:
                if d.status == DELIVERY_PENDING:
                    counts[str(d.id)] = 0
        aggregates = _assignment_aggregates([a.id for a in assignments])

        deliveries_by_assignment = {}
        for delivery in deliveries:
            deliveries_by_assignment.setdefault(delivery.assignment_id, []).append(delivery)
        items_by_id = {item.id: item for item in items}

        now = timezone.now()
        data = task.to_view(now)
        data['description'] = task.description
        template_map = _templates_by_item([item.id for item in items])
        data['items'] = []
        for item in items:
            item_view = item.to_view()
            item_view['templates'] = template_map.get(item.id, [])
            data['items'].append(item_view)
        data['assignments'] = []
        for assignment in assignments:
            task_deliveries = deliveries_by_assignment.get(assignment.id, [])
            agg = aggregates.get(assignment.id, {})
            data['assignments'].append({
                'id': assignment.id,
                'target_tenant_id': assignment.target_tenant_id,
                'target_tenant_name': assignment.target_tenant_name,
                'contact_user_name': assignment.contact_user_name,
                'urge_count': assignment.urge_count,
                'last_urged_at': assignment.last_urged_at.strftime('%Y-%m-%d %H:%M') if assignment.last_urged_at else '',
                'aggregate_status': agg.get('aggregate_status', 'pending'),
                'aggregate_status_text': agg.get('aggregate_status_text', ASSIGNMENT_STATUS_TEXT['pending']),
                'deliveries': _serialize_deliveries(task_deliveries, counts),
            })
        # 材料名称冗余到明细，前端矩阵直接渲染
        for assignment in data['assignments']:
            for delivery in assignment['deliveries']:
                related_item = items_by_id.get(delivery['item_id'])
                delivery['item_name'] = related_item.name if related_item else ''
                delivery['item_remark'] = related_item.remark if related_item else ''
        return json_response(data)

    @auth(PERM_EDIT)
    def post(self, request, pk):
        form, error = JsonParser(
            Argument('title', help='请输入任务标题'),
            Argument('description', required=False, default=''),
            Argument('deadline', help='请选择交付截止时间'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        deadline = _parse_deadline(form.deadline or '')
        if not deadline:
            return json_response(error='截止时间格式错误')
        title = (form.title or '').strip()
        if not title:
            return json_response(error='请输入任务标题')
        if len(title) > 200:
            return json_response(error='任务标题长度不能超过200个字符')

        with transaction.atomic():
            task = CoopTask.objects.select_for_update().filter(
                pk=pk, is_deleted=False).first()
            if not task:
                return json_response(error='任务不存在')
            if not request.user.is_supper and task.tenant_id != request.user.tenant_id:
                return json_response(error='任务不存在或无权限访问')
            if task.status != TASK_STATUS_IN_PROGRESS:
                return json_response(error='仅进行中的任务可以编辑')
            before = {'title': task.title, 'deadline': task.deadline.strftime('%Y-%m-%d %H:%M')}
            user = request.user
            task.title = title
            task.description = (form.description or '').strip()[:20000]
            task.deadline = deadline
            task.updated_at = timezone.now()
            task.updated_by_id = user.id
            task.updated_by_name = _snapshot_name(user)
            task.save(update_fields=[
                'title', 'description', 'deadline', 'updated_at', 'updated_by_id', 'updated_by_name'])
        record_audit_event(
            request, 'update', target_type=MODULE, target_id=task.id, target_name=task.title,
            before_value=before,
            after_value={'title': task.title, 'deadline': deadline.strftime('%Y-%m-%d %H:%M')})
        return json_response(task.to_view())

    @auth(PERM_DELETE)
    def delete(self, request, pk):
        with transaction.atomic():
            task = CoopTask.objects.select_for_update().filter(
                pk=pk, is_deleted=False).first()
            if not task:
                return json_response(error='任务不存在')
            if not request.user.is_supper and task.tenant_id != request.user.tenant_id:
                return json_response(error='任务不存在或无权限访问')
            user = request.user
            task.is_deleted = True
            task.deleted_at = timezone.now()
            task.deleted_by_id = user.id
            task.deleted_by_name = _snapshot_name(user)
            task.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by_id', 'deleted_by_name'])
        record_audit_event(
            request, 'delete', target_type=MODULE, target_id=task.id, target_name=task.title)
        return json_response()


class TaskVoidView(View):
    """作废任务（业务终止，保留记录可查）"""

    @auth(PERM_DELETE)
    def post(self, request, pk):
        with transaction.atomic():
            task = CoopTask.objects.select_for_update().filter(
                pk=pk, is_deleted=False).first()
            if not task:
                return json_response(error='任务不存在')
            if not request.user.is_supper and task.tenant_id != request.user.tenant_id:
                return json_response(error='任务不存在或无权限访问')
            if task.status != TASK_STATUS_IN_PROGRESS:
                return json_response(error='仅进行中的任务可以作废')
            task.status = TASK_STATUS_VOIDED
            task.updated_at = timezone.now()
            task.updated_by_id = request.user.id
            task.updated_by_name = _snapshot_name(request.user)
            task.save(update_fields=['status', 'updated_at', 'updated_by_id', 'updated_by_name'])
        record_audit_event(
            request, 'update', target_type=MODULE, target_id=task.id, target_name=task.title,
            detail={'status': 'voided', 'action': 'void'})
        return json_response()


class TaskUrgeView(View):
    """催办指定科室"""

    @auth(PERM_EDIT)
    def post(self, request, pk):
        form, error = JsonParser(
            Argument('assignment_id', type=int, help='请指定催办科室'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        task = _get_task_for_initiator(request.user, pk)
        if not task:
            return json_response(error='任务不存在或无权限访问')
        assignment = task.assignments.filter(pk=form.assignment_id).first()
        if not assignment:
            return json_response(error='分派记录不存在')
        if task.status != TASK_STATUS_IN_PROGRESS:
            return json_response(error='任务已结束，无需催办')
        now = timezone.now()
        assignment.urge_count += 1
        assignment.last_urged_at = now
        assignment.save(update_fields=['urge_count', 'last_urged_at'])
        record_audit_event(
            request, 'update', target_type=MODULE, target_id=task.id, target_name=task.title,
            detail={'action': 'urge', 'target_tenant': assignment.target_tenant_name,
                    'urge_count': assignment.urge_count})
        return json_response()


# ==================== 交付方：收件箱 ====================

class InboxView(View):
    """本科室收到的任务列表（交付方视角）"""

    @auth(PERM_VIEW)
    def get(self, request):
        assignments = CoopTaskAssignment.objects.filter(
            target_tenant_id=request.user.tenant_id,
            task__is_deleted=False,
        ).exclude(task__status=TASK_STATUS_VOIDED).select_related('task').order_by('-task__id')
        aggregates = _assignment_aggregates([a.id for a in assignments])
        now = timezone.now()
        results = []
        for assignment in assignments:
            task = assignment.task
            agg = aggregates.get(assignment.id, {})
            results.append({
                'id': assignment.id,
                'task_id': task.id,
                'task_title': task.title,
                'task_description': task.description,
                'deadline': task.deadline.strftime('%Y-%m-%d %H:%M') if task.deadline else '',
                'task_status': task.status,
                'task_status_text': TASK_STATUS_TEXT.get(task.status, task.status),
                'is_overdue': task.is_overdue(now),
                'created_by_name': task.created_by_name,
                'contact_user_name': assignment.contact_user_name,
                'urge_count': assignment.urge_count,
                'last_urged_at': assignment.last_urged_at.strftime('%Y-%m-%d %H:%M') if assignment.last_urged_at else '',
                'has_unread_urge': assignment.has_unread_urge(),
                'aggregate_status': agg.get('aggregate_status', 'pending'),
                'aggregate_status_text': agg.get('aggregate_status_text', ASSIGNMENT_STATUS_TEXT['pending']),
            })
        return json_response(results)


class InboxDetailView(View):
    """交付详情（逐材料上传/提交），同时消除催办未读"""

    @auth(PERM_VIEW)
    def get(self, request, pk):
        assignment = _get_assignment_for_deliverer(request.user, pk)
        if not assignment:
            return json_response(error='任务不存在或无权限访问')
        task = assignment.task
        items = list(task.items.all())
        deliveries = list(assignment.deliveries.all().order_by('item__sort_order', 'id'))
        counts = _attachment_counts([d.id for d in deliveries])
        items_by_id = {item.id: item for item in items}
        template_map = _templates_by_item(items_by_id.keys())

        # 查看详情即视为已读催办
        if assignment.has_unread_urge():
            assignment.urge_read_at = timezone.now()
            assignment.save(update_fields=['urge_read_at'])

        now = timezone.now()
        data = task.to_view(now)
        data['assignment_id'] = assignment.id
        data['target_tenant_name'] = assignment.target_tenant_name
        data['urge_count'] = assignment.urge_count
        data['items'] = []
        for delivery in deliveries:
            item = items_by_id.get(delivery.item_id)
            view = delivery.to_view()
            view['item_name'] = item.name if item else ''
            view['item_remark'] = item.remark if item else ''
            view['attachment_count'] = counts.get(str(delivery.id), 0)
            view['templates'] = template_map.get(delivery.item_id, [])
            data['items'].append(view)
        agg = _assignment_aggregates([assignment.id]).get(assignment.id, {})
        data['aggregate_status'] = agg.get('aggregate_status', 'pending')
        data['aggregate_status_text'] = agg.get('aggregate_status_text', ASSIGNMENT_STATUS_TEXT['pending'])
        return json_response(data)


# ==================== 交付明细动作 ====================

def _get_delivery_for_deliverer(user, pk):
    """交付方视角取交付明细（上传/提交）"""
    return CoopTaskDelivery.objects.select_related('assignment__task').filter(pk=pk).first()


def _get_delivery_for_initiator(user, pk):
    """发起方视角取交付明细（验收/退回）"""
    delivery = CoopTaskDelivery.objects.select_related('assignment__task').filter(pk=pk).first()
    if not delivery:
        return None
    task = delivery.assignment.task
    if task.is_deleted:
        return None
    if not user.is_supper and task.tenant_id != user.tenant_id:
        return None
    return delivery


class DeliverySubmitView(View):
    """提交交付（rejected 状态可重新提交）"""

    @auth(PERM_SUBMIT)
    def post(self, request, pk):
        delivery = _get_delivery_for_deliverer(request.user, pk)
        if not delivery or delivery.assignment.target_tenant_id != request.user.tenant_id:
            return json_response(error='交付明细不存在或无权限访问')
        task = delivery.assignment.task
        if task.status != TASK_STATUS_IN_PROGRESS:
            return json_response(error='任务已结束，无法提交')
        if delivery.status == DELIVERY_ACCEPTED:
            return json_response(error='该材料已验收通过，无需重复提交')
        now = timezone.now()
        delivery.status = DELIVERY_SUBMITTED
        delivery.submitted_at = now
        delivery.submitter_id = request.user.id
        delivery.submitter_name = _snapshot_name(request.user)
        delivery.save(update_fields=[
            'status', 'submitted_at', 'submitter_id', 'submitter_name'])
        record_audit_event(
            request, 'update', target_type=MODULE, target_id=task.id, target_name=task.title,
            detail={'action': 'submit', 'delivery_id': delivery.id,
                    'item': delivery.item.name, 'delivery_status': DELIVERY_STATUS_TEXT[DELIVERY_SUBMITTED]})
        return json_response(delivery.to_view())


class DeliveryAcceptView(View):
    """验收通过"""

    @auth(PERM_ACCEPT)
    def post(self, request, pk):
        with transaction.atomic():
            delivery = CoopTaskDelivery.objects.select_for_update().select_related(
                'assignment__task').filter(pk=pk).first()
            if not delivery:
                return json_response(error='交付明细不存在')
            task = delivery.assignment.task
            if task.is_deleted or (
                    not request.user.is_supper and task.tenant_id != request.user.tenant_id):
                return json_response(error='交付明细不存在或无权限访问')
            if delivery.status != DELIVERY_SUBMITTED:
                return json_response(error='仅待验收状态的材料可以验收')
            now = timezone.now()
            delivery.status = DELIVERY_ACCEPTED
            delivery.accepted_at = now
            delivery.accepted_by_id = request.user.id
            delivery.accepted_by_name = _snapshot_name(request.user)
            delivery.save(update_fields=[
                'status', 'accepted_at', 'accepted_by_id', 'accepted_by_name'])
            task = CoopTask.objects.select_for_update().get(pk=task.id)
            _refresh_task_completion(task)
        record_audit_event(
            request, 'approve', target_type=MODULE, target_id=task.id, target_name=task.title,
            detail={'action': 'accept', 'delivery_id': delivery.id, 'item': delivery.item.name,
                    'result': 'accepted'})
        return json_response(delivery.to_view())


class DeliveryRejectView(View):
    """验收退回（需填写退回原因）"""

    @auth(PERM_ACCEPT)
    def post(self, request, pk):
        form, error = JsonParser(
            Argument('reason', help='请填写退回原因'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        reason = (form.reason or '').strip()
        if not reason:
            return json_response(error='请填写退回原因')
        if len(reason) > 500:
            return json_response(error='退回原因长度不能超过500个字符')
        with transaction.atomic():
            delivery = CoopTaskDelivery.objects.select_for_update().select_related(
                'assignment__task').filter(pk=pk).first()
            if not delivery:
                return json_response(error='交付明细不存在')
            task = delivery.assignment.task
            if task.is_deleted or (
                    not request.user.is_supper and task.tenant_id != request.user.tenant_id):
                return json_response(error='交付明细不存在或无权限访问')
            if delivery.status != DELIVERY_SUBMITTED:
                return json_response(error='仅待验收状态的材料可以退回')
            delivery.status = DELIVERY_REJECTED
            delivery.reject_reason = reason
            delivery.accepted_by_id = request.user.id
            delivery.accepted_by_name = _snapshot_name(request.user)
            delivery.save(update_fields=[
                'status', 'reject_reason', 'accepted_by_id', 'accepted_by_name'])
        record_audit_event(
            request, 'approve', target_type=MODULE, target_id=task.id, target_name=task.title,
            detail={'action': 'reject', 'delivery_id': delivery.id, 'item': delivery.item.name,
                    'result': 'rejected', 'reason': reason})
        return json_response(delivery.to_view())


# ==================== 角标 ====================

class BadgeView(View):
    """侧边栏角标：交付方待处理 + 发起方待验收 + 催办未读"""

    @auth(PERM_VIEW)
    def get(self, request):
        user = request.user
        accept_pending = CoopTaskDelivery.objects.filter(
            assignment__task__tenant_id=user.tenant_id,
            assignment__task__is_deleted=False,
            assignment__task__status=TASK_STATUS_IN_PROGRESS,
            status=DELIVERY_SUBMITTED,
        ).count()
        inbox_pending = CoopTaskAssignment.objects.filter(
            target_tenant_id=user.tenant_id,
            task__is_deleted=False,
            task__status=TASK_STATUS_IN_PROGRESS,
        ).filter(
            Q(deliveries__status=DELIVERY_PENDING) | Q(deliveries__status=DELIVERY_REJECTED)
        ).distinct().count()
        urge_unread = CoopTaskAssignment.objects.filter(
            target_tenant_id=user.tenant_id,
            last_urged_at__isnull=False,
            task__is_deleted=False,
        ).exclude(task__status=TASK_STATUS_VOIDED).filter(
            Q(urge_read_at__isnull=True) | Q(urge_read_at__lt=F('last_urged_at'))
        ).count()
        return json_response({
            'count': inbox_pending + accept_pending,
            'inbox_pending': inbox_pending,
            'accept_pending': accept_pending,
            'urge_unread': urge_unread,
        })


# ==================== 附件接口（转调 evidence.AttachmentService） ====================

def _check_delivery_attachment_read(user, delivery):
    """附件读可见性：交付科室（上传方）随时可读；发起科室在材料提交后可读。

    待交付（pending）视为交付方草稿，附件对发起方隐藏；
    已提交/已验收/已退回均保持可见（退回件供对照整改）。
    """
    if user.is_supper:
        return None
    task = delivery.assignment.task
    if delivery.assignment.target_tenant_id == user.tenant_id:
        return None
    if task.tenant_id == user.tenant_id:
        if delivery.status == DELIVERY_PENDING:
            return '该材料尚未提交，附件暂不可见'
        return None
    return '无权限访问该附件'


def _check_delivery_attachment_write(user, delivery):
    """附件写权限：仅交付科室，任务进行中且明细未验收"""
    if user.is_supper:
        return None
    if delivery.assignment.target_tenant_id != user.tenant_id:
        return '仅交付科室可以上传或删除附件'
    return None


def _get_delivery_for_attachment(user, pk):
    return CoopTaskDelivery.objects.select_related('assignment__task').filter(pk=pk).first()


class DeliveryAttachmentView(View):
    """交付明细附件列表 / 上传"""

    @auth(PERM_VIEW)
    def get(self, request, pk):
        delivery = _get_delivery_for_attachment(request.user, pk)
        if not delivery:
            return json_response(error='交付明细不存在')
        err = _check_delivery_attachment_read(request.user, delivery)
        if err:
            return json_response(error=err)
        data = AttachmentService.list(
            request.user, ATTACHMENT_MODULE, ATTACHMENT_OBJECT_TYPE, pk, skip_tenant_filter=True)
        return json_response(data)

    @auth(PERM_SUBMIT)
    def post(self, request, pk):
        delivery = _get_delivery_for_attachment(request.user, pk)
        if not delivery:
            return json_response(error='交付明细不存在')
        err = _check_delivery_attachment_write(request.user, delivery)
        if err:
            return json_response(error=err)
        task = delivery.assignment.task
        if task.status != TASK_STATUS_IN_PROGRESS:
            return json_response(error='任务已结束，无法上传附件')
        if delivery.status == DELIVERY_ACCEPTED:
            return json_response(error='该材料已验收通过，无法上传附件')
        file = request.FILES.get('file')
        if not file:
            return json_response(error='请选择要上传的文件')
        att, error = AttachmentService.upload(
            file=file, user=request.user,
            module=ATTACHMENT_MODULE, object_type=ATTACHMENT_OBJECT_TYPE, object_id=pk,
            config=CoopTaskAttachmentConfig,
        )
        if error:
            return json_response(error=error)
        result = att.to_view()
        result['uploaded_by_name'] = request.user.nickname
        result['created_at'] = att.uploaded_at
        result['previewable'] = att.file_ext in PREVIEWABLE_EXTENSIONS
        record_audit_event(
            request, 'create', target_type=MODULE, target_id=task.id, target_name=task.title,
            detail={'action': 'upload_attachment', 'delivery_id': delivery.id,
                    'item': delivery.item.name, 'file_name': att.file_name})
        return json_response(result)


class AttachmentDownloadView(View):
    """附件下载（鉴权），支持 ?inline=1 内联预览图片/PDF（含交付明细附件与材料模板）"""

    @auth(PERM_VIEW)
    def get(self, request, pk):
        att = EvidenceAttachment.objects.filter(
            pk=pk, module=ATTACHMENT_MODULE, is_deleted=False).first()
        if not att:
            return json_response(error='附件不存在')
        err = _resolve_attachment_read(request.user, att)
        if err:
            return json_response(error=err)
        response, error = AttachmentService.download_response(
            request.user, pk, inline=request.GET.get('inline') in ('1', 'true', 'True'),
            skip_tenant_filter=True)
        if error:
            return json_response(error=error)
        return response


class AttachmentPreviewUrlView(View):
    """获取 kkFileView 在线预览地址（含交付明细附件与材料模板）"""

    @auth(PERM_VIEW)
    def get(self, request, pk):
        att = EvidenceAttachment.objects.filter(
            pk=pk, module=ATTACHMENT_MODULE, is_deleted=False).first()
        if not att:
            return json_response(error='附件不存在')
        err = _resolve_attachment_read(request.user, att)
        if err:
            return json_response(error=err)
        preview_file_api_path = f'/api/coop-task/attachments/{pk}/preview-file/'
        # 附件归属上传方（交付科室）租户，跨租户预览须以附件真实租户绑定令牌
        data, error = AttachmentService.get_preview_url(
            request.user, pk, preview_file_api_path, skip_tenant_filter=True,
            token_tenant_id=att.tenant_id)
        if error:
            return json_response(error=error)
        return json_response(data)


class AttachmentPreviewFileView(View):
    """kkFileView 回调读取文件流（preview_token 鉴权）"""

    def get(self, request, pk):
        preview_token = request.GET.get('preview_token')
        if not preview_token:
            return json_response(error='缺少 preview_token 参数')
        response, error = AttachmentService.preview_file_response(preview_token, pk)
        if error:
            return json_response(error=error)
        return response


class AttachmentDeleteView(View):
    """附件删除（物理删除：记录与文件一并移除，仅交付科室，明细未验收且任务进行中）"""

    @auth(PERM_SUBMIT)
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定附件ID'),
            Argument('delete_reason', required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        att = EvidenceAttachment.objects.filter(
            pk=form.id, module=ATTACHMENT_MODULE, object_type=ATTACHMENT_OBJECT_TYPE,
            is_deleted=False).first()
        if not att:
            return json_response(error='附件不存在')
        delivery = _get_delivery_for_attachment(request.user, att.object_id)
        if not delivery:
            return json_response(error='附件不存在或无权限访问')
        err = _check_delivery_attachment_write(request.user, delivery)
        if err:
            return json_response(error=err)
        task = delivery.assignment.task
        if task.status != TASK_STATUS_IN_PROGRESS:
            return json_response(error='任务已结束，无法删除附件')
        if delivery.status == DELIVERY_ACCEPTED:
            return json_response(error='该材料已验收通过，无法删除附件')
        error = AttachmentService.hard_delete(att)
        if error:
            return json_response(error=error)
        record_audit_event(
            request, 'delete', target_type=MODULE, target_id=task.id, target_name=task.title,
            detail={'action': 'delete_attachment', 'delivery_id': delivery.id,
                    'item': delivery.item.name, 'file_name': att.file_name,
                    'delete_reason': form.delete_reason or ''})
        return json_response()


# ==================== 材料模板接口 ====================

def _get_item_with_task(pk):
    """取材料及其所属任务（任务未删除）"""
    return CoopTaskItem.objects.select_related('task').filter(
        pk=pk, task__is_deleted=False).first()


def _check_template_access(user, item):
    """模板可见性：发起科室 或 被分派的交付科室（超管放行）"""
    if user.is_supper:
        return None
    task = item.task
    if task.tenant_id == user.tenant_id:
        return None
    if CoopTaskAssignment.objects.filter(
            task=task, target_tenant_id=user.tenant_id).exists():
        return None
    return '无权限访问该模板'


def _check_template_manage(user, item):
    """模板管理权限：仅发起科室（超管放行）；任务是否进行中由调用方另行校验"""
    if user.is_supper:
        return None
    if item.task.tenant_id != user.tenant_id:
        return '仅发起科室可以管理材料模板'
    return None


def _resolve_attachment_read(user, att):
    """按附件类型鉴权读：交付明细附件走交付规则，材料模板走模板规则"""
    if att.object_type == TEMPLATE_OBJECT_TYPE:
        item = _get_item_with_task(att.object_id)
        if not item:
            return '附件不存在或无权限访问'
        return _check_template_access(user, item)
    delivery = _get_delivery_for_attachment(user, att.object_id)
    if not delivery:
        return '附件不存在或无权限访问'
    return _check_delivery_attachment_read(user, delivery)


class ItemTemplateView(View):
    """材料模板附件：列表 / 上传 / 删除（发起方管理，交付科室下载填写后作为交付材料上传）"""

    @auth(PERM_VIEW)
    def get(self, request, pk):
        item = _get_item_with_task(pk)
        if not item:
            return json_response(error='材料不存在')
        err = _check_template_access(request.user, item)
        if err:
            return json_response(error=err)
        data = AttachmentService.list(
            request.user, ATTACHMENT_MODULE, TEMPLATE_OBJECT_TYPE, pk, skip_tenant_filter=True)
        return json_response(data)

    @auth(PERM_EDIT)
    def post(self, request, pk):
        item = _get_item_with_task(pk)
        if not item:
            return json_response(error='材料不存在')
        err = _check_template_manage(request.user, item)
        if err:
            return json_response(error=err)
        if item.task.status != TASK_STATUS_IN_PROGRESS:
            return json_response(error='任务已结束，无法上传模板')
        file = request.FILES.get('file')
        if not file:
            return json_response(error='请选择要上传的文件')
        att, error = AttachmentService.upload(
            file=file, user=request.user,
            module=ATTACHMENT_MODULE, object_type=TEMPLATE_OBJECT_TYPE, object_id=pk,
            config=CoopTaskAttachmentConfig,
        )
        if error:
            return json_response(error=error)
        result = att.to_view()
        result['uploaded_by_name'] = request.user.nickname
        result['created_at'] = att.uploaded_at
        result['previewable'] = att.file_ext in PREVIEWABLE_EXTENSIONS
        record_audit_event(
            request, 'create', target_type=MODULE, target_id=item.task_id,
            target_name=item.task.title,
            detail={'action': 'upload_template', 'item_id': item.id, 'item': item.name,
                    'template_id': att.id, 'file_name': att.file_name})
        return json_response(result)

    @auth(PERM_EDIT)
    def delete(self, request, pk):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定模板附件ID'),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        item = _get_item_with_task(pk)
        if not item:
            return json_response(error='材料不存在')
        err = _check_template_manage(request.user, item)
        if err:
            return json_response(error=err)
        if item.task.status != TASK_STATUS_IN_PROGRESS:
            return json_response(error='任务已结束，无法删除模板')
        att = EvidenceAttachment.objects.filter(
            pk=form.id, module=ATTACHMENT_MODULE, object_type=TEMPLATE_OBJECT_TYPE,
            is_deleted=False).first()
        if not att or str(att.object_id) != str(pk):
            return json_response(error='模板不存在')
        error = AttachmentService.hard_delete(att)
        if error:
            return json_response(error=error)
        record_audit_event(
            request, 'delete', target_type=MODULE, target_id=item.task_id,
            target_name=item.task.title,
            detail={'action': 'delete_template', 'item_id': item.id, 'item': item.name,
                    'template_id': att.id, 'file_name': att.file_name})
        return json_response()
