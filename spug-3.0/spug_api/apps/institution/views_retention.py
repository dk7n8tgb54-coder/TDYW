# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""制度文件生命周期保留策略视图：只读预检、可控幂等执行、长期保留标记

接口约定（nginx 对外前缀 /api/institution/）：
  GET  /cleanup/preview/                        清理预检（完全只读）
  POST /cleanup/execute/                        清理执行（可控幂等）
  POST /manuals/<pk>/versions/<vid>/protect/    版本长期保留标记

权限：预检/执行属模块级运维操作，门控 institution.manual.config（不新增
权限码）；长期保留标记属发布域操作，门控 institution.manual.publish +
手册 can_publish。预检不写数据库、不触碰磁盘；执行逐项重新核对配置、
归属、期限、引用与物理路径，失败项保留可重试状态，不伪装成功。本模块
不含任何定时任务——未配置保留期限时执行整体拒绝，自动物理清理不启用。
"""
import logging

from django.db import transaction
from django.views.generic import View

from apps.logs.audit import record_audit_event
from libs import Argument, JsonParser, auth, json_response

from . import authorization_services, retention_services, serializers, services
from .models import ManualVersion
from .views import _manual_from_request, manual_auth

logger = logging.getLogger(__name__)


class CleanupPreviewView(View):
    """保留策略清理预检（只读）：候选制度/版本/文件/大小/原因/阻止条件

    预检不是执行凭证：执行前会对每个候选重新评估（期限、保护标记、
    当前版本、业务引用、共享路径与物理文件存在性均以执行时点为准）。
    """

    @auth('institution.manual.config')
    def get(self, request):
        return json_response(data=retention_services.build_cleanup_preview())


class CleanupExecuteView(View):
    """保留策略清理执行（可控幂等）

    body 可选 {"manual_id": <pk>} 限定单本制度；未配置保留期限时业务
    错误拒绝。失败项保留候选状态与失败说明可重试；结果按版本/原稿
    逐项返回成功/失败，绝不把失败伪装成成功。
    """

    @auth('institution.manual.config')
    def post(self, request):
        form, error = JsonParser(
            Argument('manual_id', type=int, required=False, default=None),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        result, err = retention_services.execute_cleanup(
            request.user, form.manual_id)
        if err:
            return json_response(error=err)
        record_audit_event(
            request, 'delete', services.AUDIT_TARGET_TYPE,
            target_id=form.manual_id or 0,
            target_name='制度保留策略清理' + (
                f'（手册 {form.manual_id}）' if form.manual_id else ''),
            detail={'action_kind': retention_services.ACTION_RETENTION_CLEANUP,
                    'summary': result['summary'], 'module': 'institution'})
        return json_response(data=result)


class VersionProtectView(View):
    """设置/取消发布版本的长期保留标记（受保护版本不成为清理候选）"""

    @manual_auth('institution.manual.publish')
    @transaction.atomic
    def post(self, request, pk, vid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not authorization_services.can_publish(request.user, manual):
            return json_response(error='手册不存在或无权限访问')
        version = ManualVersion.objects.filter(pk=vid, manual=manual).first()
        if not version:
            return json_response(error='版本不存在或无权限访问')
        form, error = JsonParser(
            Argument('long_term_protected', type=bool, required=True,
                     help='请提供 long_term_protected 取值'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        before = version.long_term_protected
        if before != form.long_term_protected:
            version.long_term_protected = form.long_term_protected
            version.save(update_fields=['long_term_protected'])
        services.log_operation(
            manual, request.user, retention_services.ACTION_VERSION_PROTECT,
            version=version, version_no=version.version_no,
            before=before, after=form.long_term_protected)
        record_audit_event(
            request, 'update', services.AUDIT_TARGET_TYPE,
            target_id=manual.id, target_name=manual.name,
            detail={'action_kind': retention_services.ACTION_VERSION_PROTECT,
                    'version_no': version.version_no,
                    'long_term_protected': form.long_term_protected,
                    'module': 'institution'})
        return json_response(data=serializers.to_version_dict(version, manual))
