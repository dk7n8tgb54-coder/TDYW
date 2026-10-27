# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""系统档案关联视图（升级管理挂接系统档案）。

- UpgradeCandidateSystemsView：GET /api/upgrade/candidate-systems/
  升级表单/方案系统候选项（本租户可用系统，请求只提交系统 ID）；
- SystemUpgradeRecordsView：GET /api/equipment-lifecycle/systems/<pk>/upgrade-records/
  按系统查询升级记录（系统详情"升级记录"页签），路由注册在
  equipment_lifecycle/urls.py，视图落在本 app 以保持 upgrade→el 单向依赖。
"""
from django.views import View
from libs import json_response, auth
from libs.pagination import paginate
from libs.tenant_utils import apply_tenant_filter

from apps.upgrade.models import UpgradeRecord
from apps.upgrade.serializers import UpgradeRecordSerializer


class UpgradeCandidateSystemsView(View):
    """升级表单系统候选项：本租户可用（未停用）系统。"""

    @auth('upgrade.upgrade.view')
    def get(self, request):
        # 函数内导入：RELEASE_PENDING_APPS 门控摘除 equipment_lifecycle 时，
        # upgrade 仍须可安装，模块级导入会导致启动崩溃。
        from apps.equipment_lifecycle.models import LifecycleSystem

        systems = apply_tenant_filter(
            LifecycleSystem.objects.all(), request.user
        ).filter(is_active=True).order_by('system_code')
        return json_response({'data': [{
            'id': s.id,
            'system_code': s.system_code,
            'name': s.name,
            'install_location': s.install_location,
        } for s in systems]})


class SystemUpgradeRecordsView(View):
    """按系统查询升级记录（系统详情"升级记录"页签）。"""

    @auth('upgrade.upgrade.view')
    def get(self, request, pk):
        from apps.equipment_lifecycle.models import LifecycleSystem

        system = apply_tenant_filter(
            LifecycleSystem.objects.all(), request.user
        ).filter(pk=pk).first()
        if not system:
            return json_response(error='系统不存在或无权限')
        query = apply_tenant_filter(
            UpgradeRecord.objects.filter(is_deleted=False), request.user
        ).filter(system=system).order_by('-upgrade_time', '-id')
        page, page_size = paginate(request)
        total = query.count()
        records = query[(page - 1) * page_size: page * page_size]
        return json_response({
            'data': [UpgradeRecordSerializer.to_list_view(r) for r in records],
            'total': total, 'page': page, 'page_size': page_size,
        })
