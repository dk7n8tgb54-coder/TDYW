# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under AGPL-3.0 License.
from django.views.generic import View
from django.utils import timezone
from libs import json_response, JsonParser, Argument, auth
from libs.tenant_utils import apply_tenant_filter, assign_tenant_id
from libs.pagination import paginate, paginate_response
from apps.fault.models import FaultRecord, FaultPart
from apps.logs.audit import record_audit_event
import logging

logger = logging.getLogger(__name__)


class FaultRecordView(View):
    @auth('fault.faultrecord.view')
    def get(self, request):
        records = apply_tenant_filter(FaultRecord.objects.all(), request.user).select_related('created_by', 'updated_by')
        system_names = [x['system_name'] for x in records.order_by('system_name').values('system_name').distinct()]

        page, page_size = paginate(request)
        data = paginate_response(records, page, page_size, serialize_fn=lambda x: x.to_view(), items_key='records')
        data['system_names'] = system_names
        return json_response(data)

    @auth('fault.faultrecord.add|fault.faultrecord.edit')
    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('system_name', required=False),
            Argument('device_code', required=False),
            Argument('fault_date', required=False),
            Argument('handler', required=False),
            Argument('recorder', required=False),
            Argument('fault_level', required=False),
            Argument('fault_phenomenon', required=False),
            Argument('handling_process', required=False)
        ).parse(request.body)
        if error is None:
            if form.id:
                # 编辑：只更新传入的非 None 字段
                if not request.user.has_perms({'fault.faultrecord.edit'}):
                    return json_response(error='权限拒绝：缺少编辑故障记录权限')
                if not apply_tenant_filter(FaultRecord.objects.filter(pk=form.id), request.user).exists():
                    return json_response(error='记录不存在或无权操作')
                form.updated_at = timezone.now()
                form.updated_by = request.user
                update_data = {k: v for k, v in form.items() if v is not None and k != 'id'}
                FaultRecord.objects.filter(pk=form.pop('id')).update(**update_data)
            else:
                # 创建：校验必填字段
                if not request.user.has_perms({'fault.faultrecord.add'}):
                    return json_response(error='权限拒绝：缺少新增故障记录权限')
                required = {
                    'system_name': '系统名称', 'device_code': '设备编号',
                    'fault_date': '日期', 'handler': '处置人员',
                    'recorder': '记录人员', 'fault_level': '故障评级',
                    'fault_phenomenon': '故障现象', 'handling_process': '处置过程'
                }
                for field, label in required.items():
                    if not form.get(field):
                        return json_response(error=f'请输入{label}')
                form.created_by = request.user
                assign_tenant_id(form, request.user)
                create_data = {k: v for k, v in form.items() if v is not None}
                FaultRecord.objects.create(**create_data)
        return json_response(error=error)

    @auth('fault.faultrecord.del')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)
        if error is None:
            record = apply_tenant_filter(
                FaultRecord.objects.all(), request.user
            ).filter(pk=form.id).first()
            if not record:
                return json_response(error='记录不存在或无权操作')
            record_audit_event(
                request, 'delete', 'fault',
                target_id=record.id, target_name=record.system_name,
                detail={'device_code': record.device_code, 'fault_level': record.fault_level},
            )
            record.delete()
        return json_response(error=error)


class FaultPartView(View):
    @auth('fault.faultpart.view')
    def get(self, request):
        records = apply_tenant_filter(FaultPart.objects.all(), request.user).select_related('created_by', 'updated_by')
        system_names = [x['system_name'] for x in records.order_by('system_name').values('system_name').distinct()]

        page, page_size = paginate(request)
        data = paginate_response(records, page, page_size, serialize_fn=lambda x: x.to_view(), items_key='records')
        data['system_names'] = system_names
        return json_response(data)

    @auth('fault.faultpart.add|fault.faultpart.edit')
    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('name', required=False),
            Argument('system_name', required=False),
            Argument('date', required=False),
            Argument('fault_date', required=False),
            Argument('status', required=False),
            Argument('fault_sent_date', required=False),
            Argument('test_return_date', required=False),
            Argument('archive_date', required=False)
        ).parse(request.body)
        if error is None:
            # 根据状态自动记录日期
            if form.status == '送修' and not form.fault_sent_date:
                form.fault_sent_date = timezone.now()
            elif form.status == '运回测试' and not form.test_return_date:
                form.test_return_date = timezone.now()
            elif form.status == '正常归档' and not form.archive_date:
                form.archive_date = timezone.now()

            if form.id:
                # 编辑：只更新传入的非 None 字段
                if not request.user.has_perms({'fault.faultpart.edit'}):
                    return json_response(error='权限拒绝：缺少编辑故障件权限')
                if not apply_tenant_filter(FaultPart.objects.filter(pk=form.id), request.user).exists():
                    return json_response(error='记录不存在或无权操作')
                form.updated_at = timezone.now()
                form.updated_by = request.user
                update_data = {k: v for k, v in form.items() if v is not None and k != 'id'}
                FaultPart.objects.filter(pk=form.pop('id')).update(**update_data)
            else:
                # 创建：校验必填字段
                if not request.user.has_perms({'fault.faultpart.add'}):
                    return json_response(error='权限拒绝：缺少新增故障件权限')
                required = {
                    'name': '故障件名称', 'system_name': '所属系统',
                    'date': '日期', 'fault_date': '故障日期', 'status': '状态'
                }
                for field, label in required.items():
                    if not form.get(field):
                        return json_response(error=f'请输入{label}')
                form.created_by = request.user
                assign_tenant_id(form, request.user)
                create_data = {k: v for k, v in form.items() if v is not None}
                FaultPart.objects.create(**create_data)
        return json_response(error=error)

    @auth('fault.faultpart.del')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)
        if error is None:
            record = apply_tenant_filter(
                FaultPart.objects.all(), request.user
            ).filter(pk=form.id).first()
            if not record:
                return json_response(error='记录不存在或无权操作')
            record_audit_event(
                request, 'delete', 'fault',
                target_id=record.id, target_name=record.name,
                detail={'system_name': record.system_name, 'status': record.status},
            )
            record.delete()
        return json_response(error=error)
