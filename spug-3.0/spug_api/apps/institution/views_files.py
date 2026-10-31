# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""制度文件条目管理视图（多文件）：清单/新增/改名/排序/移除与文件原稿

文件级接口的第一道越权防线：所有请求先经 _file_from_request 校验
文件确属 URL 中的制度，再进入角色与业务校验。草稿/会话/编辑器契约
见 views_draft.py。
"""
import logging

from django.db import transaction
from django.views.generic import View

from apps.account.models import User
from apps.logs.audit import record_audit_event
from libs import Argument, JsonParser, auth, json_response

from . import authorization_services, revision_services, serializers, \
    services, storage
from .models import Manual, ManualAuthorization, ManualDraft, ManualFile, \
    ManualOriginal
from .views import _check_owner_or_admin, _manual_from_request
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
    """文件分工（负责人/分工说明/是否我负责）——文件清单所有可见者下发

    owner_name 优先取落库快照（账号删除后仍可读），为空时回退关联账号
    的昵称/账号名。负责人只是责任标记：is_mine 不授予任何操作权限，
    各写接口仍由视图层独立校验角色与归属。
    """
    owner_name = file_entry.owner_name
    if not owner_name and file_entry.owner:
        owner_name = (getattr(file_entry.owner, 'nickname', '') or
                      file_entry.owner.username or '')
    return {
        'owner_id': file_entry.owner_id,
        'owner_name': owner_name,
        'note': file_entry.assign_note,
        'assigned_at': file_entry.assigned_at,
        'is_mine': file_entry.owner_id == request.user.id,
    }


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
    快照或初始原稿），供草稿工作台渲染对应恢复入口，不静默回退到原稿。
    """

    @auth('institution.manual.view')
    def get(self, request, pk):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not authorization_services.can_view_manual(request.user, manual):
            return json_response(error='手册不存在或无权限访问')
        with_status = _can_view_workspace(request.user, manual)
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
                submission=(services.file_submission_state(file_entry, draft)
                            if with_status else None)))
        return json_response(data=items)


class ManualFileCreateView(View):
    """新增制度文件：multipart 上传 -> 条目+原稿+草稿（追加到清单末尾）

    可选 multipart 字段 owner_id / note：新增时即指定文件负责人与分工
    说明（不传即"未分配"，之后可经 assignment 接口改派）。被指派账号
    必须持有该手册 can_edit 编制授权。
    """

    @auth('institution.manual.upload')
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
        owner, err = _resolve_assignee(manual, request.POST.get('owner_id'))
        if err:
            return json_response(error=err)
        note = (request.POST.get('note') or '').strip()
        if len(note) > 500:
            return json_response(error='分工说明不能超过 500 字')
        file_entry, draft_err = services.create_manual_file(
            manual, request.user, upload, owner=owner, note=note)
        if file_entry is None:
            return json_response(error=draft_err)
        record_audit_event(
            request, 'create', services.AUDIT_TARGET_TYPE,
            target_id=manual.id, target_name=manual.name,
            detail={'action_kind': services.ACTION_FILE_ADD,
                    'file_id': file_entry.id, 'module': 'institution'})
        draft = ManualDraft.objects.filter(file=file_entry).first()
        data = serializers.to_manual_file_dict(
            file_entry, draft, _session_payload(file_entry, request),
            assignment=_assignment_payload(file_entry, request),
            submission=services.file_submission_state(file_entry, draft))
        # 草稿建立失败（如 .doc 转换失败）不掩盖文件创建成功：
        # 前端据 draft_error 提示，文件仍出现在清单中
        data['draft_error'] = draft_err or ''
        return json_response(data=data)


class AssignmentOwnerOptionsView(View):
    """文件分工负责人候选（仅 ID+显示名的最小清单，2026-10-30 新增）

    分工弹窗与新增文件负责人选择专用，替代直接拉账号管理列表
    /api/account/user/（该接口 GET 要求 system.account.view，持有制度
    分工权限但无账号查看权的用户打开弹窗即"权限拒绝"，候选还被前端
    catch 吞掉表现为空列表）。本接口绝不开放账号管理清单，也不放宽
    其权限：
    - 页面权限与分工写路径一致：draft_edit（单/批量分工）或 upload
      （新增文件携带负责人）任一；
    - 业务口径与写接口相同：手册所有者或制度管理员
      （_check_owner_or_admin，2026-10-31 起）；
    - 候选=持有该手册 can_edit 编制授权的启用账号（2026-10-31 起）——
      负责人独占编辑要求被指派账号具备编制资格，与
      _resolve_assignee 的校验口径一致；本模块授权按账号授权行判定、
      tenant_id 不参与归属，跨租户账号可作负责人是预期行为；
    - 只返回 id + name（昵称，空则账号名），不回传其他账号字段。
    """

    @auth('institution.manual.draft_edit|institution.manual.upload')
    def get(self, request, pk):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        deny = _check_owner_or_admin(manual, request.user)
        if deny:
            return deny
        rows = (ManualAuthorization.objects.filter(
            manual=manual, can_edit=True).select_related('account')
            .order_by('account_id'))
        return json_response(data=[
            {'id': row.account_id,
             'name': row.account.nickname or row.account.username}
            for row in rows if row.account.is_active])


class ManualFileAssignmentView(View):
    """指定/改派/清空文件负责人（文件分工；分工单位=整份文件）

    请求体 owner_id 必须显式携带（null=清空为"未分配"）+ note 分工说明。
    权限=模块 draft_edit 权限 +（手册所有者或制度管理员）；被指派账号
    必须持有该手册 can_edit 编制授权，此后仅负责人可编辑该文件。
    """

    @auth('institution.manual.draft_edit')
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
            submission=services.file_submission_state(file_entry, draft)))


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
      （draft_edit + 手册所有者或制度管理员）；被指派账号必须持有
      该手册 can_edit 编制授权。
    - 事务内逐文件复用 services.assign_file_owner（负责人变化时同步
      清除"提交编制"交接记录并撤销该文件活跃编辑会话），每份文件写
      一条 file_assign 操作记录（batch=True 标记），另记一条模块审计
      事件。
    """

    @auth('institution.manual.draft_edit')
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
        for file_entry in files:
            file_entry, err = services.assign_file_owner(
                file_entry, owner, note, request.user, batch=True)
            if err:
                return json_response(error=err)
            draft = ManualDraft.objects.filter(file=file_entry).first()
            updated_rows.append(serializers.to_manual_file_dict(
                file_entry, draft, _session_payload(file_entry, request),
                assignment=_assignment_payload(file_entry, request),
                submission=services.file_submission_state(file_entry, draft)))
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
      改用初始来源或覆盖工作副本。
    """

    @auth('institution.manual.draft_edit')
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
    """提交编制（负责人完成编制后的明确交接标记）

    后端记录提交时草稿修订号与时间；草稿再次保存/重建后提交状态按
    修订号比对自动失效（计算式，见 services.file_submission_state）。
    无有效草稿或仍有活跃编辑会话时拒绝。放行口径=文件负责人 或
    手册所有者 或 制度管理员（提交是状态交接而非编辑操作；2026-10-31
    起负责人必持编制授权——分工写路径已校验，但提交本身不要求
    draft_edit 页面权限）；不新增发布阻断条件。
    """

    @auth('institution.manual.view')
    @transaction.atomic
    def post(self, request, pk, fid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        file_entry, resp = _file_from_request(request, manual, fid)
        if resp:
            return resp
        is_assignee = file_entry.owner_id == request.user.id
        if not (is_assignee or
                authorization_services.is_manual_owner(request.user, manual) or
                authorization_services.is_institution_admin(request.user)):
            return json_response(error='手册不存在或无权限访问')
        file_entry, err = services.submit_file_compilation(
            file_entry, request.user)
        if err:
            return json_response(error=err)
        record_audit_event(
            request, 'update', services.AUDIT_TARGET_TYPE,
            target_id=manual.id, target_name=manual.name,
            detail={'action_kind': services.ACTION_FILE_SUBMIT,
                    'file_id': file_entry.id,
                    'submission_revision': file_entry.submission_revision,
                    'module': 'institution'})
        draft = ManualDraft.objects.filter(file=file_entry).first()
        return json_response(data=serializers.to_manual_file_dict(
            file_entry, draft, _session_payload(file_entry, request),
            assignment=_assignment_payload(file_entry, request),
            submission=services.file_submission_state(file_entry, draft)))


class ManualFileRenameView(View):
    @auth('institution.manual.draft_edit')
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
            submission=services.file_submission_state(file_entry, draft)))


class ManualFileMoveView(View):
    @auth('institution.manual.draft_edit')
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
            submission=services.file_submission_state(file_entry, draft)))


class ManualFileRemoveView(View):
    @auth('institution.manual.draft_edit')
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


class OriginalsOverviewView(View):
    """初始来源聚合清单（"初始来源"页签数据源，2026-10-29 改版）

    一次请求返回全部制度文件（含已移除条目）每份一行：文件名、最初
    原稿（该文件最早一条上传记录）的上传人与时间、原稿记录数与完整
    历史（含已按保留策略清理的记录——元数据保留、is_cleaned=True）、
    该文件首次进入的发布版本（原稿保护边界展示用）。文件较多时避免
    为每一行单独发请求；文件级归属校验沿用本模块统一口径（数据全部
    以 manual 为范围查询，不接外部 ID）。草稿来源信息仅对有工作区
    可见权的调用方附加（与 files/ 清单口径一致，后端仍独立校验）。
    """

    @auth('institution.manual.view')
    def get(self, request, pk):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not authorization_services.can_view_manual(request.user, manual):
            return json_response(error='手册不存在或无权限访问')
        rows = serializers.to_originals_overview(manual)
        if _can_view_workspace(request.user, manual):
            drafts = {d.file_id: d for d in
                      ManualDraft.objects.filter(manual=manual)}
            for row in rows:
                draft = drafts.get(row['file_id'])
                row['draft'] = {
                    'has_draft': bool(draft and draft.file_path),
                    'revision': draft.revision if draft else 0,
                    'source_original_id': draft.source_original_id if draft else None,
                }
        else:
            for row in rows:
                row['draft'] = None
        return json_response(data={'files': rows})


class FileOriginalListView(View):
    @auth('institution.manual.view')
    def get(self, request, pk, fid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        file_entry, resp = _file_from_request(request, manual, fid)
        if resp:
            return resp
        originals = file_entry.originals.select_related('uploaded_by').all()
        return json_response(data=[
            serializers.to_original_dict(x) for x in originals])


class FileOriginalUploadView(View):
    """为已有文件更换来源：上传新的原稿记录（受控操作，目标文件明确）

    语义与"新增制度文件"（files/create，每个上传文件各建一份条目）
    严格区分：本接口只向 URL 指定的目标文件追加一条原稿记录，作为
    该文件后续"从原始上传文件重建草稿"的候选来源；绝不改动或覆盖
    当前草稿（草稿替换只能经 draft/create 的显式重建，含确认与密码
    防线），原稿记录本身也永不覆盖。
    """

    @auth('institution.manual.upload')
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
        upload = request.FILES.get('file')
        if not upload:
            return json_response(error='请选择要上传的文件')
        ext = storage.extract_extension(upload.name)
        if ext not in storage.ALLOWED_EXTENSIONS:
            return json_response(error='仅支持 .doc / .docx 文件')
        if upload.size > storage.MAX_FILE_SIZE:
            return json_response(error='文件大小超过限制（100MB）')
        stored_name = storage.build_stored_name(upload.name)
        rel_path = storage.build_relative_path(
            storage.FILE_KIND_ORIGINAL, manual.id, stored_name)
        abs_path = storage.resolve_absolute_path(rel_path)
        file_hash = storage.save_upload_file(upload, abs_path)
        try:
            with transaction.atomic():
                original = ManualOriginal.objects.create(
                    manual=manual, file=file_entry, file_path=rel_path,
                    original_name=storage.display_name(upload.name), ext=ext,
                    file_size=upload.size, file_hash=file_hash,
                    uploaded_by=request.user)
                services.log_operation(
                    manual, request.user, services.ACTION_UPLOAD_ORIGINAL,
                    file=file_entry, file_id=file_entry.id,
                    original_id=original.id, file_name=upload.name)
                record_audit_event(
                    request, 'create', services.AUDIT_TARGET_TYPE,
                    target_id=manual.id, target_name=manual.name,
                    detail={'action_kind': services.ACTION_UPLOAD_ORIGINAL,
                            'file_id': file_entry.id, 'file_name': upload.name,
                            'module': 'institution'})
        except Exception:
            storage.safe_delete_file(abs_path)
            raise
        return json_response(data=serializers.to_original_dict(original))


class FileOriginalDownloadView(View):
    @auth('institution.manual.download')
    def get(self, request, pk, fid, oid):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        file_entry, resp = _file_from_request(request, manual, fid)
        if resp:
            return resp
        original = ManualOriginal.objects.filter(
            pk=oid, manual=manual, file=file_entry).first()
        if not original:
            return json_response(error='原稿不存在或无权限访问')
        if original.cleaned_at:
            return json_response(error=storage.ORIGINAL_CLEANED_ERROR)
        services.log_operation(
            manual, request.user, 'download', file=file_entry,
            file_name=original.original_name, file_kind='original')
        try:
            abs_path = storage.resolve_absolute_path(original.file_path)
        except ValueError:
            return json_response(error='文件路径非法')
        return _download_response(request, abs_path, original.original_name)
