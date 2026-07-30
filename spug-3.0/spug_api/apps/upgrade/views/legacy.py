# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
兼容旧接口 - 前端迁移完成后移除

旧接口路径：
- GET  /api/upgrade/upgrade/          → 列表/详情
- POST /api/upgrade/upgrade/          → 创建
- PUT  /api/upgrade/upgrade/          → 更新
- DELETE /api/upgrade/upgrade/        → 删除
"""
import logging
from django.views import View
from libs import json_response, auth, Argument, JsonParser
from libs.tenant_utils import apply_tenant_filter

logger = logging.getLogger(__name__)


class LegacyUpgradeView(View):
    """兼容旧升级表单接口"""

    @auth('upgrade.upgrade.view')
    def get(self, request):
        """获取升级表单列表或详情（兼容旧前端）"""
        from apps.upgrade.models import UpgradeRecord
        from apps.upgrade.serializers import UpgradeRecordSerializer

        record_id = request.GET.get('id')
        if record_id:
            # 详情模式
            from apps.upgrade.services.record_service import RecordService
            data, error = RecordService.get_detail(int(record_id), request.user)
            if error:
                return json_response(error=error, status=404)
            return json_response(data)

        # 列表模式（旧前端不带分页，全量返回）
        records_qs = apply_tenant_filter(UpgradeRecord.objects.all(), request.user)

        # 筛选
        filters = request.GET.dict()
        if filters.get('status'):
            records_qs = records_qs.filter(status=filters['status'])
        if filters.get('system'):
            records_qs = records_qs.filter(system__icontains=filters['system'])
        if filters.get('upgrade_type'):
            records_qs = records_qs.filter(upgrade_type=filters['upgrade_type'])
        if filters.get('owner'):
            records_qs = records_qs.filter(owner__icontains=filters['owner'])
        if filters.get('start_date') and filters.get('end_date'):
            records_qs = records_qs.filter(
                upgrade_time__gte=filters['start_date'],
                upgrade_time__lte=filters['end_date'],
            )

        records_qs = records_qs.order_by('-upgrade_time', '-id')

        # 去重选项
        systems = list(records_qs.order_by('system').values_list('system', flat=True).distinct())
        statuses = list(records_qs.order_by('status').values_list('status', flat=True).distinct())
        upgrade_types = list(records_qs.order_by('upgrade_type').values_list('upgrade_type', flat=True).distinct())

        # 序列化
        records_data = [UpgradeRecordSerializer.to_list_view(r) for r in records_qs]

        return json_response({
            'systems': systems,
            'statuses': statuses,
            'upgrade_types': upgrade_types,
            'records': records_data,
        })

    @auth('upgrade.upgrade.add')
    def post(self, request):
        """创建升级表单（兼容旧前端）"""
        from apps.upgrade.services.record_service import RecordService

        form, error = JsonParser(
            Argument('system', help='请输入系统'),
            Argument('upgrade_type', help='请选择升级类型'),
            Argument('version', help='请输入版本'),
            Argument('upgrade_time', help='请选择升级时间'),
            Argument('status', help='请选择状态'),
            Argument('owner', help='请输入负责人'),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        record, error = RecordService.create_record(
            user=request.user,
            record_data=form,
        )

        if error:
            return json_response(error=error)

        return json_response()

    @auth('upgrade.upgrade.edit')
    def put(self, request):
        """更新升级表单（兼容旧前端）"""
        from apps.upgrade.services.record_service import RecordService

        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象'),
            Argument('system', required=False),
            Argument('upgrade_type', required=False),
            Argument('version', required=False),
            Argument('upgrade_time', required=False),
            Argument('status', required=False),
            Argument('owner', required=False),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        record, error = RecordService.update_record(
            record_id=form.id,
            user=request.user,
            data=form,
        )

        if error:
            return json_response(error=error)

        return json_response()

    @auth('upgrade.upgrade.del')
    def delete(self, request):
        """删除升级表单（兼容旧前端）"""
        from apps.upgrade.services.record_service import RecordService

        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)

        if error:
            return json_response(error=error)

        error = RecordService.delete_record(form.id, request)
        if error:
            return json_response(error=error)

        return json_response()
