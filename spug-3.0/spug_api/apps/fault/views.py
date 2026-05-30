# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under AGPL-3.0 License.
from django.views.generic import View
from libs import json_response, JsonParser, Argument, human_datetime, auth
from libs.tenant_utils import apply_tenant_filter, assign_tenant_id
from apps.fault.models import FaultRecord, FaultPart
import logging

logger = logging.getLogger(__name__)


class FaultRecordView(View):
    @auth('fault.faultrecord.view')
    def get(self, request):
        records = apply_tenant_filter(FaultRecord.objects.all(), request.user)
        system_names = [x['system_name'] for x in records.order_by('system_name').values('system_name').distinct()]
        return json_response({'system_names': system_names, 'records': [x.to_view() for x in records]})

    @auth('fault.faultrecord.add|fault.faultrecord.edit')
    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('system_name', help='请输入系统名称'),
            Argument('device_code', help='请输入设备编号'),
            Argument('fault_date', help='请选择日期'),
            Argument('handler', help='请输入处置人员'),
            Argument('recorder', help='请输入记录人员'),
            Argument('fault_level', help='请选择故障评级'),
            Argument('fault_phenomenon', help='请输入故障现象'),
            Argument('handling_process', help='请输入处置过程')
        ).parse(request.body)
        if error is None:
            if form.id:
                form.updated_at = human_datetime()
                form.updated_by = request.user
                if not apply_tenant_filter(FaultRecord.objects.filter(pk=form.id), request.user).exists():
                    return json_response(error='记录不存在或无权操作')
                FaultRecord.objects.filter(pk=form.pop('id')).update(**form)
            else:
                form.created_by = request.user
                assign_tenant_id(form, request.user)
                FaultRecord.objects.create(**form)
        return json_response(error=error)

    @auth('fault.faultrecord.del')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)
        if error is None:
            if not apply_tenant_filter(FaultRecord.objects.filter(pk=form.id), request.user).exists():
                return json_response(error='记录不存在或无权操作')
            FaultRecord.objects.filter(pk=form.id).delete()
        return json_response(error=error)


class FaultPartView(View):
    @auth('fault.faultpart.view')
    def get(self, request):
        records = apply_tenant_filter(FaultPart.objects.all(), request.user)
        system_names = [x['system_name'] for x in records.order_by('system_name').values('system_name').distinct()]
        return json_response({'system_names': system_names, 'records': [x.to_view() for x in records]})

    @auth('fault.faultpart.add|fault.faultpart.edit')
    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('name', help='请输入故障件名称'),
            Argument('system_name', help='请输入所属系统'),
            Argument('date', help='请选择日期'),
            Argument('fault_date', help='请选择故障日期'),
            Argument('status', help='请选择状态'),
            Argument('fault_sent_date', required=False),
            Argument('test_return_date', required=False),
            Argument('archive_date', required=False)
        ).parse(request.body)
        if error is None:
            # 根据状态自动记录日期
            if form.status == '送修' and not form.fault_sent_date:
                form.fault_sent_date = human_datetime()
            elif form.status == '运回测试' and not form.test_return_date:
                form.test_return_date = human_datetime()
            elif form.status == '正常归档' and not form.archive_date:
                form.archive_date = human_datetime()

            if form.id:
                form.updated_at = human_datetime()
                form.updated_by = request.user
                if not apply_tenant_filter(FaultPart.objects.filter(pk=form.id), request.user).exists():
                    return json_response(error='记录不存在或无权操作')
                FaultPart.objects.filter(pk=form.pop('id')).update(**form)
            else:
                form.created_by = request.user
                assign_tenant_id(form, request.user)
                FaultPart.objects.create(**form)
        return json_response(error=error)

    @auth('fault.faultpart.del')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)
        if error is None:
            if not apply_tenant_filter(FaultPart.objects.filter(pk=form.id), request.user).exists():
                return json_response(error='记录不存在或无权操作')
            FaultPart.objects.filter(pk=form.id).delete()
        return json_response(error=error)
