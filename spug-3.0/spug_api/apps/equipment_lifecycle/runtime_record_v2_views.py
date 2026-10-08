# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""设备全生命周期——运行记录第二版视图（2026-10）：待办与统计。

定位：用户先快速记录运行情况（新建成功即"已记录"，可长期保留，不作为待办）；
第四版（2026-10-05）研判不再是必经步骤：跟进由"追加首条处理进展"触发
（第一版 progress 端点），转故障由独立 convert-to-fault 端点完成；
不把运行记录扩展为第二套故障处置系统（正式处置以 SystemFault 为准）。

本文件承载第二版能力（与第一版 runtime_record_views 单向依赖，复用其取数/
校验助手；fault_views._parse_dt 沿用第一版引入）：
- 待办列表：只含跟进中记录（最近更新优先排序），完成跟进或转故障
  自然移出；
- 统计查询：只读，仅使用运行记录数据（巡视/维护/配置变更/升级不混入）。

旧端点（2026-10-06 随状态归一/重复功能退役整体删除，路由同步移除）：
- 研判（triage）：研判不再是必经步骤，历史研判字段仅作快照保留；
- 重复问题（similar/duplicate-links/mark-repeated）：前端入口已下线，
  模型与字段随迁移 0008 删除。

权限（后端独立校验，前端仅控制展示）：
- equipment_lifecycle.runtime_record.view：待办与统计读取
"""
from datetime import timedelta

from django.utils import timezone
from django.views.generic import View

from libs import JsonParser, Argument, json_response, auth
from libs.tenant_utils import apply_tenant_filter

from apps.equipment_lifecycle import runtime_record_services
from apps.equipment_lifecycle.models import (
    RUNTIME_RECORD_STATUS_FOLLOWING_UP,
    SystemRuntimeRecord,
)
from apps.equipment_lifecycle.fault_views import _parse_dt
from apps.equipment_lifecycle.runtime_record_views import _validate_record_type

# 待办列表单次返回上限（跟进中记录量级小，超出说明积压，应先处置再查看）
TODO_LIST_LIMIT = 200


class RuntimeRecordTodoView(View):
    """运行记录待办列表：只含"跟进中"记录，完成跟进或转故障后自然移出。

    - 不为普通记录发送提醒，也不做周期轮询；本端点只做条件查询，
      由前端进入待办页签时触发；
    - 按最近更新优先排序（updated_at/created_at 降序；2026-10-06 跟进计划
      删除后不再有计划处理时间/超期/跟进人维度）。
    """

    @auth('equipment_lifecycle.runtime_record.view')
    def get(self, request):
        query = apply_tenant_filter(
            SystemRuntimeRecord.objects.all(), request.user
        ).filter(status=RUNTIME_RECORD_STATUS_FOLLOWING_UP)
        rows = list(query[:TODO_LIST_LIMIT])
        rows.sort(key=lambda r: (r.updated_at or r.created_at or '', r.id), reverse=True)
        return json_response({
            'data': [r.to_view() for r in rows],
            'total': len(rows),
        })


class RuntimeRecordStatisticsView(View):
    """运行记录只读统计（默认近 30 天，时间范围 __gte/__lt）。

    record_type 统计口径筛选：未传时默认 abnormal——原有异常统计口径保持
    不变；routine 统计日常运行记录；只使用运行记录数据（巡视/维护/配置
    变更/升级不混入）。
    """

    @auth('equipment_lifecycle.runtime_record.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('occurred_from', type=str, required=False, default=''),
            Argument('occurred_to', type=str, required=False, default=''),
            Argument('record_type', type=str, required=False, default='',
                     help='记录类型筛选（routine日常运行/abnormal异常事件；'
                          '未传默认abnormal）'),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        record_type, err = _validate_record_type(form.record_type)
        if err:
            return json_response(error=err)
        now = timezone.now()
        occurred_to = now + timedelta(days=1)
        occurred_from = now - timedelta(days=30)
        if form.occurred_from:
            occurred_from = _parse_dt(form.occurred_from)
            if not occurred_from:
                return json_response(error='发生时间起始格式不正确')
        if form.occurred_to:
            occurred_to = _parse_dt(form.occurred_to)
            if not occurred_to:
                return json_response(error='发生时间截止格式不正确')
        if occurred_from >= occurred_to:
            return json_response(error='统计开始时间必须早于截止时间')
        stats = runtime_record_services.compute_runtime_statistics(
            request.user.tenant_id, occurred_from, occurred_to,
            record_type=record_type)
        stats['occurred_from'] = occurred_from
        stats['occurred_to'] = occurred_to
        stats['record_type'] = record_type
        stats['stale_days'] = runtime_record_services.RUNTIME_RECORD_STALE_DAYS
        return json_response(stats)
