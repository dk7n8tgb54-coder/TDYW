# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.views import View
from django.utils import timezone
from libs import json_response, auth
from libs.tenant_utils import apply_tenant_filter
from libs import Argument, JsonParser
import logging

logger = logging.getLogger(__name__)


class UpgradeRecordView(View):
    """升级表单视图 - 旧版（保留备用）"""

    @auth('upgrade.upgrade.view')
    def get(self, request):
        """获取升级表单列表或详情"""
        from .models import UpgradeRecord

        # 如果指定了id，返回详情
        record_id = request.GET.get('id')
        if record_id:
            record = apply_tenant_filter(UpgradeRecord.objects.filter(pk=record_id), request.user).first()
            if not record:
                return json_response(error='升级表单不存在', status=404)

            return json_response(record.to_view())

        # 列表查询
        records = apply_tenant_filter(UpgradeRecord.objects.all(), request.user)

        # 筛选参数
        filters = request.GET.dict()
        if filters.get('status'):
            records = records.filter(status=filters['status'])
        if filters.get('system'):
            records = records.filter(system__icontains=filters['system'])
        if filters.get('upgrade_type'):
            records = records.filter(upgrade_type=filters['upgrade_type'])
        if filters.get('owner'):
            records = records.filter(owner__icontains=filters['owner'])
        if filters.get('date'):
            from datetime import datetime as _dt, timedelta as _td
            _d = _dt.strptime(filters['date'], '%Y-%m-%d')
            records = records.filter(created_at__gte=_d, created_at__lt=_d + _td(days=1))
        if filters.get('start_date') and filters.get('end_date'):
            records = records.filter(upgrade_time__gte=filters['start_date'], upgrade_time__lte=filters['end_date'])

        # 排序
        records = records.order_by('-upgrade_time', '-id')

        # 去重选项
        systems = [x['system'] for x in records.order_by('system').values('system').distinct()]
        statuses = [x['status'] for x in records.order_by('status').values('status').distinct()]
        upgrade_types = [x['upgrade_type'] for x in records.order_by('upgrade_type').values('upgrade_type').distinct()]

        return json_response({
            'systems': systems,
            'statuses': statuses,
            'upgrade_types': upgrade_types,
            'records': [x.to_view() for x in records],
        })

    @auth('upgrade.upgrade.add')
    def post(self, request):
        """创建升级表单"""
        from .models import UpgradeRecord

        form, error = JsonParser(
            Argument('system', help='请输入系统'),
            Argument('upgrade_type', help='请选择升级类型'),
            Argument('version', help='请输入版本'),
            Argument('upgrade_time', help='请选择升级时间'),
            Argument('status', help='请选择状态'),
            Argument('owner', help='请输入负责人'),
        ).parse(request.body)

        if error is None:
            # 验证状态值
            VALID_STATUSES = ['处理中', '已完成']
            if form.status not in VALID_STATUSES:
                return json_response(error='状态值无效，仅支持：处理中/已完成')

            # 创建升级表单
            tenant_id = request.user.tenant_id

            record_data = {
                'system': form.system,
                'upgrade_type': form.upgrade_type,
                'version': form.version,
                'upgrade_time': form.upgrade_time,
                'status': form.status,
                'owner': form.owner,
                'created_by': request.user,
                'tenant_id': tenant_id,
            }
            UpgradeRecord.objects.create(**record_data)

        return json_response(error=error)

    @auth('upgrade.upgrade.edit')
    def put(self, request):
        """更新升级表单"""
        from .models import UpgradeRecord

        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象'),
            Argument('system', required=False),
            Argument('upgrade_type', required=False),
            Argument('version', required=False),
            Argument('upgrade_time', required=False),
            Argument('status', required=False),
            Argument('owner', required=False),
        ).parse(request.body)

        if error is None:
            record = apply_tenant_filter(UpgradeRecord.objects.filter(pk=form.id), request.user).first()
            if not record:
                return json_response(error='无权限操作')

            # 可编辑字段
            editable_fields = ['system', 'upgrade_type', 'version', 'upgrade_time', 'status', 'owner']
            for field in editable_fields:
                if hasattr(form, field) and getattr(form, field) is not None:
                    setattr(record, field, getattr(form, field))

            # 验证状态值
            if form.status:
                VALID_STATUSES = ['处理中', '已完成']
                if form.status not in VALID_STATUSES:
                    return json_response(error='状态值无效')

            record.updated_by = request.user
            record.updated_at = timezone.now()
            record.save()

        return json_response(error=error)

    @auth('upgrade.upgrade.del')
    def delete(self, request):
        """删除升级表单"""
        from .models import UpgradeRecord

        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)

        if error is None:
            record = apply_tenant_filter(UpgradeRecord.objects.filter(pk=form.id), request.user).first()
            if not record:
                return json_response(error='无权限操作')

            record.delete()

        return json_response(error=error)
