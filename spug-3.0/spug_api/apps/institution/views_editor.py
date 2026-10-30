# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""制度管理 ONLYOFFICE 编辑确认端点

独立成文件的原因：views_draft.py 已超新文件行数门禁（增量治理只能保持或
减少），新增的"保存并结束编辑"落盘确认端点放在此处；复用 views_draft 的
草稿/文件定位助手（单向依赖，勿反向）。

  POST /manuals/<pk>/files/<fid>/draft/forcesave/
      请求文档服务（DS Command Service）对当前编辑文档立即 forcesave。
      前端"保存并结束编辑"以此为落盘确认起点：DS 受理（requested）后经
      既有回调链路落盘并推进修订号，前端轮询修订号确认；DS 报告无修改
      （no_changes）时可安全结束会话。撤销会话永远发生在确认之后。
"""
from django.db import transaction
from django.views.generic import View

from libs import Argument, JsonParser, auth, json_response

from . import editor_services, services
from .models import Manual
from .views import _manual_from_request
from .views_draft import _draft_or_error
from .views_files import _file_from_request


class FileDraftForcesaveView(View):
    """请求文档服务立即保存当前编辑文档（落盘确认入口，不直接落盘）

    权限与会话校验与 editor-config / multipart save 同口径：模块
    draft_edit + 手册编制角色 + 该文件有效编辑会话。响应携带请求时刻的
    草稿修订号作为轮询基线（回调落盘后修订号单调递增）。
    """

    @auth('institution.manual.draft_edit')
    def post(self, request, pk, fid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not services.can_edit_draft(request.user, manual):
            return json_response(error='手册不存在或无权限访问')
        if manual.status != Manual.STATUS_ACTIVE:
            return json_response(error='手册已归档，不能编辑')
        file_entry, resp = _file_from_request(request, manual, fid)
        if resp:
            return resp
        draft, err = _draft_or_error(file_entry)
        if err:
            return err
        form, error = JsonParser(
            Argument('session_key', type=str, required=True,
                     help='缺少编辑会话'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        session, err = services.get_active_session(
            file_entry, request.user, form.session_key)
        if err:
            return json_response(error=err)
        if not editor_services.is_editor_configured():
            return json_response(error='在线编辑服务未配置，无需保存确认')
        result, err = editor_services.request_forcesave(session)
        if err:
            return json_response(error=err)
        result['revision'] = draft.revision
        return json_response(data=result)


# 路由注册（urls.py）经 transaction.non_atomic_requests 包装：本视图在
# 事务内发起对 DS 的出站 HTTP 调用（超时 10s），不得占用 ATOMIC_REQUESTS。
_non_atomic_forcesave = transaction.non_atomic_requests(
    FileDraftForcesaveView.as_view())
