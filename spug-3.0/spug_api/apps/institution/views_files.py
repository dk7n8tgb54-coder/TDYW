# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""制度文件条目管理视图（多文件）：清单/新增/改名/排序/移除

新增文件由上传文件直接建立当前草稿（见 services.create_manual_file），
不再保存额外副本。文件级接口的第一道越权防线：所有请求先经
_file_from_request 校验文件确属 URL 中的制度，再进入角色与业务校验。
草稿/会话/编辑器契约见 views_draft.py。
"""
import logging

from django.db import transaction
from django.views.generic import View

from apps.account.models import User
from apps.logs.audit import record_audit_event
from libs import Argument, JsonParser, json_response

from . import authorization_services, revision_services, serializers, \
    services
from .models import Manual, ManualAuthorization, ManualDraft, ManualFile
from .views import _check_owner_or_admin, _manual_from_request, manual_auth
logger = logging.getLogger(__name__)


def _file_from_request(request, manual, fid):
    """取制度文件条目并校验确属当前制度；失败返回 (None, 响应)"""
    file_entry, err = services.get_manual_file(manual, fid)
    if err:
        return None, json_response(error=err)
    return file_entry, None


def _can_view_workspace(user, manual):
    """草稿工作区/待发布清单可见：管理员/所有者/编制或发布授权"""
    return authorization_services.can_view_workspace(user, manual)


def _session_payload(file_entry, request):
    """文件的活跃会话占用信息（文件清单与草稿详情共用）"""
    active = services.get_active_session_for_file(file_entry)
    if not active:
        return None
    return {
        'is_mine': active.user_id == request.user.id,
        'user_name': active.user.username,
        'expires_at': active.expires_at,
    }


def _assignment_payload(file_entry, request):
    """文件分工（负责人/分工说明/是否我负责/有效负责人）——所有可见者下发

    owner_id/owner_name/is_mine 保持显式分工原值；effective_owner_* 是
    有效负责人（显式负责人优先，owner 为空时回退手册所有者），发布交接、
    提交/撤回权限与界面展示均以有效负责人为准。owner_assigned=false
    表示该文件未单独指定负责人（显示默认负责人）。
    负责人只是责任标记：is_mine 不授予任何操作权限，各写接口仍由视图层
    独立校验角色与归属。
    """
    owner_name = file_entry.owner_name
    if not owner_name and file_entry.owner:
        owner_name = (getattr(file_entry.owner, 'nickname', '') or
                      file_entry.owner.username or '')
    effective_owner = services.effective_owner(file_entry)
    effective_owner_id = effective_owner.pk if effective_owner else None
    effective_owner_name = ''
    if effective_owner_id:
        if file_entry.owner_id == effective_owner_id:
            effective_owner_name = owner_name
        else:
            effective_owner_name = services._account_display(effective_owner)
    return {
        'owner_id': file_entry.owner_id,
        'owner_name': owner_name,
        'note': file_entry.assign_note,
        'assigned_at': file_entry.assigned_at,
        'is_mine': file_entry.owner_id == request.user.id,
        'effective_owner_id': effective_owner_id,
        'effective_owner_name': effective_owner_name,
        'is_effective_owner': bool(
            effective_owner_id and effective_owner_id == request.user.id),
        'owner_assigned': bool(file_entry.owner_id or file_entry.owner_name),
    }


def _submission_state(file_entry, draft, request, manual, can_publish=None):
    """文件提交待发布核对状态（统一带当前请求者与发布权口径）

    有效提交、冻结、撤回/退回权限都在服务层计算；视图只传当前账号与
    该手册的 can_publish 资格，不自行推断。
    """
    if can_publish is None:
        can_publish = authorization_services.can_publish(request.user, manual)
    return services.file_submission_state(
        file_entry, draft, request.user, can_publish=can_publish)


def _resolve_owner(owner_id):
    """校验负责人账号存在且启用；未传返回 (None, None)"""
    if not owner_id:
        return None, None
    owner = User.objects.filter(pk=owner_id, is_active=True).first()
    if not owner:
        return None, '负责人账号不存在'
    return owner, None


def _resolve_assignee(manual, owner_id):
    """解析分工负责人并校验其持有该手册编制授权（can_edit）

    分工写路径（新增文件携带负责人 / 单与批量分工）统一入口：
    被指派账号必须持有该手册 can_edit 授权（负责人独占编辑的资格
    前提）；未传 owner_id（清空/不指定）直接通过。
    """
    owner, err = _resolve_owner(owner_id)
    if err:
        return None, err
    err = authorization_services.validate_assignee_for_manual(manual, owner)
    if err:
        return None, err
    return owner, None


# ---------------------------------------------------------------------------
# 制度文件条目（多文件）


class ManualFileListView(View):
    """待发布文件清单：有序文件 + 各自草稿状态与编辑占用 + 文件分工

    仅查看授权即可见文件结构（详情页展示发布版清单的入口）与文件分工
    （负责人/分工说明）；草稿修订号、编辑占用与"提交编制"状态属草稿
    域信息，仅对工作区可见（管理员/所有者/编制或发布授权）者填充。
    草稿缺失的文件行附带 draft_recovery（恢复途径提示：当前生效版本
    快照或提示重新上传制度文件），供草稿工作台渲染对应恢复提示，绝不
    静默回退到任何上传副本。
    """

    @manual_auth('institution.manual.view')
    def get(self, request, pk):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not authorization_services.can_view_manual(request.user, manual):
            return json_response(error='手册不存在或无权限访问')
        with_status = _can_view_workspace(request.user, manual)
        can_publish = (authorization_services.can_publish(request.user, manual)
                       if with_status else False)
        items = []
        for file_entry in services.list_active_files(manual):
            recovery = None
            draft = None
            session = None
            if with_status:
                draft = ManualDraft.objects.filter(file=file_entry).first()
                session = _session_payload(file_entry, request)
                if not draft or not draft.file_path:
                    recovery = services.build_draft_recovery_hint(file_entry)
            items.append(serializers.to_manual_file_dict(
                file_entry, draft, session, draft_recovery=recovery,
                assignment=_assignment_payload(file_entry, request),
                submission=(_submission_state(
                    file_entry, draft, request, manual, can_publish)
                    if with_status else None)))
        return json_response(data=items)


class ManualFileCreateView(View):
    """新增制度文件：multipart 上传 -> 条目+当前草稿（追加到清单末尾）

    上传文件直接用于建立当前草稿（.docx 直落草稿存储；.doc 先转换），
    每个上传文件各建一条独立条目与独立草稿，不再额外保存副本。转换/
    写入/建库任一失败均由服务层补偿清理并返回明确业务错误，数据库
    不留半成品条目、磁盘不留孤儿文件。

    可选 multipart 字段 owner_id / note：新增时即指定文件负责人与分工
    说明。**不携带 owner_id 字段 = 默认手册所有者**（新增文件默认由
    所有者负责，避免新文件无人提交编制而阻断发布）；显式携带空串 =
    明确不分配（保持手工分工）。被指派账号必须持有该手册 can_edit
    编制授权（所有者本人按对象范围自动具备资格）。
    """

    @manual_auth('institution.manual.upload')
    def post(self, request, pk):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        deny = _check_owner_or_admin(manual, request.user)
        if deny:
            return deny
        upload = request.FILES.get('file')
        if not upload:
            return json_response(error='请选择要上传的文件')
        if manual.status != Manual.STATUS_ACTIVE:
            return json_response(error='手册已归档，不能新增文件')
        if 'owner_id' not in request.POST:
            # 字段缺失 = 默认手册所有者（手册无所有者时仍为未分配）
            owner = manual.owner
        else:
            # 字段存在（含空串）= 显式语义：空串=未分配
            owner, err = _resolve_assignee(
                manual, request.POST.get('owner_id'))
            if err:
                return json_response(error=err)
        note = (request.POST.get('note') or '').strip()
        if len(note) > 500:
            return json_response(error='分工说明不能超过 500 字')
        file_entry, err = services.create_manual_file(
            manual, request.user, upload, owner=owner, note=note)
        if err:
            return json_response(error=err)
        record_audit_event(
            request, 'create', services.AUDIT_TARGET_TYPE,
            target_id=manual.id, target_name=manual.name,
            detail={'action_kind': services.ACTION_FILE_ADD,
                    'file_id': file_entry.id, 'module': 'institution'})
        draft = ManualDraft.objects.filter(file=file_entry).first()
        return json_response(data=serializers.to_manual_file_dict(
            file_entry, draft, _session_payload(file_entry, request),
            assignment=_assignment_payload(file_entry, request),
            submission=_submission_state(
                file_entry, draft, request, manual)))


class AssignmentOwnerOptionsView(View):
    """文件分工负责人候选（仅 ID+显示名的最小清单，2026-10-30 新增）

    分工弹窗与新增文件负责人选择专用，替代直接拉账号管理列表
    /api/account/user/（该接口 GET 要求 system.account.view，持有制度
    分工权限但无账号查看权的用户打开弹窗即"权限拒绝"，候选还被前端
    catch 吞掉表现为空列表）。本接口绝不开放账号管理清单，也不放宽
    其权限：
    - 页面权限与分工写路径一致：draft_edit（单/批量分工）或 upload
      （新增文件携带负责人）任一；
    - 业务口径与写接口相同：手册所有者或平台超管
      （_check_owner_or_admin，2026-10-31 起）；
    - 候选=手册所有者（即使没有 can_edit 授权行，所有者按对象范围
      自动具备编辑资格）+ 持有该手册 can_edit 编制授权的启用账号
      （2026-11-01 起补入所有者）——负责人独占编辑要求被指派账号具备
      编制资格，与 _resolve_assignee 的校验口径一致；本模块授权按账号
      授权行判定、tenant_id 不参与归属，跨租户账号可作负责人是预期行为；
    - 按账号 id 去重，只返回 id + name（昵称，空则账号名），不回传
      其他账号字段。
    """

    @manual_auth('institution.manual.draft_edit|institution.manual.upload')
    def get(self, request, pk):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        deny = _check_owner_or_admin(manual, request.user)
        if deny:
            return deny
        candidates = {}
        if manual.owner_id:
            owner = manual.owner
            candidates[owner.id] = {
                'id': owner.id,
                'name': owner.nickname or owner.username}
        rows = (ManualAuthorization.objects.filter(
            manual=manual, can_edit=True).select_related('account')
            .order_by('account_id'))
        for row in rows:
            if not row.account.is_active:
                continue
            candidates.setdefault(row.account_id, {
                'id': row.account_id,
                'name': row.account.nickname or row.account.username})
        return json_response(
            data=[candidates[key] for key in sorted(candidates)])


class ManualFileAssignmentView(View):
    """指定/改派/清空文件负责人（文件分工；分工单位=整份文件）

    请求体 owner_id 必须显式携带（null=清空为"未分配"）+ note 分工说明。
    权限=模块 draft_edit 权限 +（手册所有者或平台超管）；被指派账号
    必须持有该手册 can_edit 编制授权，此后仅负责人可编辑该文件。
    """

    @manual_auth('institution.manual.draft_edit')
    @transaction.atomic
    def post(self, request, pk, fid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        deny = _check_owner_or_admin(manual, request.user)
        if deny:
            return deny
        file_entry, resp = _file_from_request(request, manual, fid)
        if resp:
            return resp
        form, error = JsonParser(
            Argument('owner_id', type=int, required=False, default=None),
            Argument('note', type=str, required=False, default=''),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        owner, err = _resolve_assignee(manual, form.owner_id)
        if err:
            return json_response(error=err)
        note = (form.note or '').strip()
        if len(note) > 500:
            return json_response(error='分工说明不能超过 500 字')
        file_entry, err = services.assign_file_owner(
            file_entry, owner, note, request.user)
        if err:
            return json_response(error=err)
        record_audit_event(
            request, 'update', services.AUDIT_TARGET_TYPE,
            target_id=manual.id, target_name=manual.name,
            detail={'action_kind': services.ACTION_FILE_ASSIGN,
                    'file_id': file_entry.id, 'owner_id': file_entry.owner_id,
                    'module': 'institution'})
        draft = ManualDraft.objects.filter(file=file_entry).first()
        return json_response(data=serializers.to_manual_file_dict(
            file_entry, draft, _session_payload(file_entry, request),
            assignment=_assignment_payload(file_entry, request),
            submission=_submission_state(
                file_entry, draft, request, manual)))


def _validate_batch_assignment(manual, form):
    """批量分工请求体校验（逐文件校验归属，任一失败整批拒绝）

    Returns:
        tuple: (files, owner, note, error_response 或 None)。
    """
    file_ids = form.file_ids
    if not file_ids or any(
            not isinstance(x, int) or isinstance(x, bool)
            for x in file_ids):
        return None, None, None, json_response(error='文件参数格式错误')
    unique_ids = sorted(set(file_ids))
    files = list(ManualFile.objects.filter(
        manual=manual, id__in=unique_ids))
    found_ids = {f.id for f in files}
    missing = [fid for fid in unique_ids if fid not in found_ids]
    if missing:
        return None, None, None, json_response(
            error='所选文件不存在或不属于当前制度')
    owner, err = _resolve_assignee(manual, form.owner_id)
    if err:
        return None, None, None, json_response(error=err)
    note = (form.note or '').strip()
    if len(note) > 500:
        return None, None, None, json_response(error='分工说明不能超过 500 字')
    return files, owner, note, None


class ManualFileBatchAssignmentView(View):
    """批量文件分工：勾选多份文件统一指定/清空负责人并填写分工说明

    - 请求体 file_ids（非空整数列表，去重）+ owner_id（显式携带，
      null=清空）+ note（≤500 字，统一应用到所选文件）。
    - 逐文件校验归属：任一文件不存在或不属于 URL 中的制度，整批拒绝
      （全成功或全失败，绝不部分生效）；权限与单文件分工同口径
      （draft_edit + 手册所有者或平台超管）；被指派账号必须持有
      该手册 can_edit 编制授权。
    - 事务内逐文件复用 services.assign_file_owner（负责人变化时同步
      清除"提交编制"交接记录并撤销该文件活跃编辑会话），每份文件写
      一条 file_assign 操作记录（batch=True 标记），另记一条模块审计
      事件。
    """

    @manual_auth('institution.manual.draft_edit')
    @transaction.atomic
    def post(self, request, pk):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        deny = _check_owner_or_admin(manual, request.user)
        if deny:
            return deny
        form, error = JsonParser(
            Argument('file_ids', type=list, required=True,
                     help='请选择要分工的文件'),
            Argument('owner_id', type=int, required=False, default=None),
            Argument('note', type=str, required=False, default=''),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        files, owner, note, err_resp = _validate_batch_assignment(
            manual, form)
        if err_resp:
            return err_resp
        updated_rows = []
        can_publish = authorization_services.can_publish(request.user, manual)
        for file_entry in files:
            file_entry, err = services.assign_file_owner(
                file_entry, owner, note, request.user, batch=True)
            if err:
                return json_response(error=err)
            draft = ManualDraft.objects.filter(file=file_entry).first()
            updated_rows.append(serializers.to_manual_file_dict(
                file_entry, draft, _session_payload(file_entry, request),
                assignment=_assignment_payload(file_entry, request),
                submission=_submission_state(
                    file_entry, draft, request, manual, can_publish)))
        record_audit_event(
            request, 'update', services.AUDIT_TARGET_TYPE,
            target_id=manual.id, target_name=manual.name,
            detail={'action_kind': services.ACTION_FILE_ASSIGN,
                    'batch': True,
                    'file_ids': sorted(f.id for f in files),
                    'owner_id': owner.id if owner else None,
                    'module': 'institution'})
        return json_response(data={
            'count': len(updated_rows), 'files': updated_rows})


class FileRevisionStartView(View):
    """开始修订（已发布文件的真实状态动作，不是页面文案切换）

    权限=模块 draft_edit + 负责人独占编辑（can_edit_file：编制授权 +
    该文件负责人；修订由负责人开启，发布者从详情待发布状态与核对入口
    发布，不需要开启修订或编辑会话）。
    语义见 revision_services.start_file_revision：
    - 修订已在进行中：幂等返回 resumed（前端显示"继续编辑"直接复用）；
    - 工作副本健康：开启修订并原样复用，不复制新快照；
    - 工作副本缺失/损坏/与生效基线不一致：返回 needs_repair（HTTP 200
      携带 reason/message/draft_recovery），调用方明确提示后携带
      confirm_repair=true 再次调用，从当前生效版本快照修复，绝不静默
      改用其它来源或覆盖工作副本。
    """

    @manual_auth('institution.manual.draft_edit')
    def post(self, request, pk, fid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        file_entry, resp = _file_from_request(request, manual, fid)
        if resp:
            return resp
        if not authorization_services.can_edit_file(request.user, manual, file_entry):
            return json_response(error='手册不存在或无权限访问')
        form, error = JsonParser(
            Argument('confirm_repair', type=bool, required=False,
                     default=False),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        data, err = revision_services.start_file_revision(
            file_entry, request.user, confirm_repair=form.confirm_repair)
        if err:
            return json_response(error=err)
        if data.get('started') or data.get('repaired'):
            record_audit_event(
                request, 'update', services.AUDIT_TARGET_TYPE,
                target_id=manual.id, target_name=manual.name,
                detail={'action_kind': services.ACTION_REVISION_START,
                        'file_id': file_entry.id, 'repaired': data.get('repaired'),
                        'module': 'institution'})
        if data.get('needs_repair'):
            # 修复需明确确认：返回 200 + needs_repair（非业务错误），
            # 前端展示原因与恢复途径后携带 confirm_repair 重试
            return json_response(data=data)
        return json_response(data=data)


class ManualFileSubmitView(View):
    """提交待发布核对（有效负责人完成编制后的固定快照交接，2026-11-03）

    后端复制当前草稿为独立不可变快照并冻结内容写路径；发布人预览/
    下载/最终发布都读取同一快照（见 services.submit_file_compilation）。
    无有效草稿或仍有活跃编辑会话时拒绝；**放行口径=仅有效负责人本人**
    （显式负责人优先，owner 为空时回退手册所有者；未分配且手册无所有者
    明确拒绝），手册所有者/平台超管不得代提交。页面权限门仍为 view
    （负责人可能仅持查看权限），身份校验由服务层唯一判定；已有 pending
    提交拒绝且状态不变。
    """

    @manual_auth('institution.manual.view')
    def post(self, request, pk, fid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        file_entry, resp = _file_from_request(request, manual, fid)
        if resp:
            return resp
        file_entry, err = services.submit_file_compilation(
            file_entry, request.user)
        if err:
            return json_response(error=err)
        submission = services.get_pending_submission(file_entry)
        record_audit_event(
            request, 'update', services.AUDIT_TARGET_TYPE,
            target_id=manual.id, target_name=manual.name,
            detail={'action_kind': services.ACTION_FILE_SUBMIT,
                    'file_id': file_entry.id,
                    'submission_id': submission.id if submission else None,
                    'module': 'institution'})
        draft = ManualDraft.objects.filter(file=file_entry).first()
        return json_response(data=serializers.to_manual_file_dict(
            file_entry, draft, _session_payload(file_entry, request),
            assignment=_assignment_payload(file_entry, request),
            submission=_submission_state(
                file_entry, draft, request, manual)))


class ManualFileRenameView(View):
    @manual_auth('institution.manual.draft_edit')
    def post(self, request, pk, fid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        deny = _check_owner_or_admin(manual, request.user)
        if deny:
            return deny
        file_entry, resp = _file_from_request(request, manual, fid)
        if resp:
            return resp
        form, error = JsonParser(
            Argument('name', type=str, required=True, help='文件名不能为空'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        file_entry, err = services.rename_manual_file(
            file_entry, form.name, request.user)
        if err:
            return json_response(error=err)
        draft = ManualDraft.objects.filter(file=file_entry).first()
        return json_response(data=serializers.to_manual_file_dict(
            file_entry, draft, _session_payload(file_entry, request),
            assignment=_assignment_payload(file_entry, request),
            submission=_submission_state(
                file_entry, draft, request, manual)))


class ManualFileMoveView(View):
    @manual_auth('institution.manual.draft_edit')
    def post(self, request, pk, fid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        deny = _check_owner_or_admin(manual, request.user)
        if deny:
            return deny
        file_entry, resp = _file_from_request(request, manual, fid)
        if resp:
            return resp
        form, error = JsonParser(
            Argument('position', type=int, required=True, help='请提供目标序位'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        file_entry, err = services.move_manual_file(
            manual, file_entry, form.position, request.user)
        if err:
            return json_response(error=err)
        draft = ManualDraft.objects.filter(file=file_entry).first()
        return json_response(data=serializers.to_manual_file_dict(
            file_entry, draft, _session_payload(file_entry, request),
            assignment=_assignment_payload(file_entry, request),
            submission=_submission_state(
                file_entry, draft, request, manual)))


class ManualFileRemoveView(View):
    @manual_auth('institution.manual.draft_edit')
    def post(self, request, pk, fid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        deny = _check_owner_or_admin(manual, request.user)
        if deny:
            return deny
        file_entry, resp = _file_from_request(request, manual, fid)
        if resp:
            return resp
        file_entry, err = services.remove_manual_file(file_entry, request.user)
        if err:
            return json_response(error=err)
        record_audit_event(
            request, 'update', services.AUDIT_TARGET_TYPE,
            target_id=manual.id, target_name=manual.name,
            detail={'action_kind': services.ACTION_FILE_REMOVE,
                    'file_id': file_entry.id, 'module': 'institution'})
        return json_response()
