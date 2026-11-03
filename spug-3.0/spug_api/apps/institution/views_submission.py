# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""提交待发布核对：撤回 / 退回 / 待核对快照预览与下载（2026-11-03）

行数门禁拆分：views_files（文件条目与分工）与 views_draft（草稿/编辑器
契约）均接近/超过阈值，本组端点独立成文件；复用两处的定位与响应助手
（单向依赖：views_submission -> views_files/views_draft，勿反向）。

固定快照契约：
- 预览/下载只读 pending 提交的独立副本（submissions/），不读草稿、
  不读当前生效版本；缺少有效快照时明确业务错误；
- 权限=页面 view + 工作区可见（所有者/编制/发布授权），发布人因此
  无需 download 页面码即可核对；快照始终绑定 URL 中的制度与文件；
- 撤回=有效负责人本人；退回=can_publish（所有者或逐本发布授权，
  平台超管不因超管身份可发布，沿用既有授权口径），原因必填。
"""
import logging
import os

from django.views.generic import View

from libs import Argument, JsonParser, json_response

from . import authorization_services, serializers, services, storage
from .models import ManualDraft
from .views import _download_response, _manual_from_request, manual_auth
from .views_draft import _build_preview_url
from .views_files import (_assignment_payload, _can_view_workspace,
                          _file_from_request, _submission_state)

logger = logging.getLogger(__name__)


def _pending_snapshot(file_entry):
    """当前待核对提交及其物理文件（缺失返回 (None, 明确错误)）"""
    submission = services.get_pending_submission(file_entry)
    if not submission:
        return None, '当前没有待核对的提交快照'
    try:
        abs_path = storage.resolve_absolute_path(submission.file_path)
    except ValueError:
        return None, '提交快照路径非法，无法读取'
    if not os.path.exists(abs_path):
        return None, '提交快照文件不存在或已被清理，请负责人重新提交'
    return submission, None


class SubmissionWithdrawView(View):
    """有效负责人撤回待核对提交（解除冻结；旧快照作废但记录保留）"""

    @manual_auth('institution.manual.view')
    def post(self, request, pk, fid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        file_entry, resp = _file_from_request(request, manual, fid)
        if resp:
            return resp
        file_entry, err = services.withdraw_file_submission(
            file_entry, request.user)
        if err:
            return json_response(error=err)
        draft = ManualDraft.objects.filter(file=file_entry).first()
        return json_response(data=serializers.to_manual_file_dict(
            file_entry, draft, None,
            assignment=_assignment_payload(file_entry, request),
            submission=_submission_state(
                file_entry, draft, request, manual)))


class SubmissionReturnView(View):
    """发布权者退回待核对提交（原因必填；负责人修改后可重新提交）"""

    @manual_auth('institution.manual.publish')
    def post(self, request, pk, fid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not authorization_services.can_publish(request.user, manual):
            return json_response(error='手册不存在或无权限访问')
        file_entry, resp = _file_from_request(request, manual, fid)
        if resp:
            return resp
        form, error = JsonParser(
            Argument('reason', type=str, required=True,
                     help='请填写退回原因'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        file_entry, err = services.return_file_submission(
            file_entry, request.user, form.reason)
        if err:
            return json_response(error=err)
        draft = ManualDraft.objects.filter(file=file_entry).first()
        return json_response(data=serializers.to_manual_file_dict(
            file_entry, draft, None,
            assignment=_assignment_payload(file_entry, request),
            submission=_submission_state(
                file_entry, draft, request, manual, can_publish=True)))


class SubmissionPreviewUrlView(View):
    """待核对快照预览地址（发布人核对；只读 pending 独立副本）"""

    @manual_auth('institution.manual.view')
    def get(self, request, pk, fid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not _can_view_workspace(request.user, manual):
            return json_response(error='手册不存在或无权限访问')
        file_entry, resp = _file_from_request(request, manual, fid)
        if resp:
            return resp
        submission, err = _pending_snapshot(file_entry)
        if err:
            return json_response(error=err)
        data = _build_preview_url(
            request, manual, storage.FILE_KIND_SUBMISSION, submission,
            file_name=submission.original_name)
        if not data:
            return json_response(error='Office文档预览服务未配置，请联系管理员')
        data.update({
            'file_name': submission.original_name,
            'submission_id': submission.id,
            'submitted_by_name': submission.submitted_by_name,
            'submitted_at': submission.submitted_at,
        })
        return json_response(data=data)


class SubmissionDownloadView(View):
    """待核对快照下载（发布人核对；只读 pending 独立副本）"""

    @manual_auth('institution.manual.view')
    def get(self, request, pk, fid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not _can_view_workspace(request.user, manual):
            return json_response(error='手册不存在或无权限访问')
        file_entry, resp = _file_from_request(request, manual, fid)
        if resp:
            return resp
        submission, err = _pending_snapshot(file_entry)
        if err:
            return json_response(error=err)
        services.log_operation(
            manual, request.user, 'download', file=file_entry,
            file_name=submission.original_name, file_kind='submission',
            file_id=file_entry.id, submission_id=submission.id)
        try:
            abs_path = storage.resolve_absolute_path(submission.file_path)
        except ValueError:
            return json_response(error='提交快照路径非法，无法下载')
        return _download_response(
            request, abs_path, submission.original_name)
