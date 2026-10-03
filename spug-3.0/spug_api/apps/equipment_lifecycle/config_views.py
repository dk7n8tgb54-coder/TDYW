# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""设备全生命周期——系统配置视图（2026-10）。

产品定位：配置不是独立一级菜单/独立页面，只在「系统详情 → 配置」页签内
使用（当前配置 + 配置变更历史两个信息区域 + 记录配置变更 Modal）。
不与运行记录、巡视维护、系统升级混淆：多步骤升级/测试/回退仍由系统升级
管理负责，本模块只管配置参数值的变更留痕。

权限域（前后端一致，后端独立校验）：
- equipment_lifecycle.config.view       当前配置/变更历史/详情/参数定义查询
- equipment_lifecycle.config.add        创建配置变更
- equipment_lifecycle.config.edit       编辑/取消草稿变更
- equipment_lifecycle.config.apply      应用变更
- equipment_lifecycle.config.verify     验证变更
- equipment_lifecycle.config.rollback   回退变更
- equipment_lifecycle.config.template   参数定义维护（新增/编辑）

设计要点：
- 创建/回退持 el_config_change_no 编号锁（non_atomic 装配，锁 → 事务提交
  → 放锁），应用/验证/取消/编辑走请求级事务 + 行锁；
- 创建幂等：client_token 命中同租户已有变更直接返回；同系统同原因窗口期
  查重；重复提交不生成重复记录；
- 应用在事务内锁系统行与当前值行，校验变更前值未被并发覆盖后写当前值；
- 履历（SystemEvent）只由服务层对重要变更生成（须填原因），普通变更不写；
- 参数定义只新增/编辑/停用，无删除接口，历史记录全部保留；
- 写操作记录业务审计（record_audit_event）。
"""
import json

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.views.generic import View

from libs import json_response, auth
from libs.idempotency import check_recent_duplicate
from libs.pagination import paginate, paginate_response
from libs.tenant_utils import apply_tenant_filter

from apps.logs.audit import record_audit_event

from apps.equipment_lifecycle import config_services
from apps.equipment_lifecycle.config_models import (
    CONFIG_CHANGE_APPLIED,
    CONFIG_CHANGE_DRAFT,
    CONFIG_CHANGE_STATUS_TEXT_MAP,
    CONFIG_CHANGE_STATUS_VALUES,
    PARAM_SCOPE_ALL,
    PARAM_SCOPE_SPECIFIC,
    PARAM_TYPE_VALUES,
    ConfigChangeRecord,
    ConfigParamDefinition,
    ConfigParamSystemScope,
)
from apps.equipment_lifecycle.models import LifecycleSystem
from apps.equipment_lifecycle.fault_views import _parse_dt, _read_json_body

AUDIT_TARGET_CONFIG_CHANGE = 'el_config_change'
AUDIT_TARGET_CONFIG_PARAM = 'el_config_param'
IDEMPOTENCY_WINDOW_SECONDS = 30


def _get_system_for_user(pk, user, for_update=False):
    """取本租户系统（当前配置/历史查询不要求系统可用，停用系统历史可查）。"""
    qs = apply_tenant_filter(LifecycleSystem.objects.all(), user)
    if for_update:
        qs = qs.select_for_update()
    return qs.filter(pk=pk).first()


def _get_active_system_for_user(pk, user):
    """取本租户可用（未停用）系统：创建配置变更只允许选择可用系统。"""
    return apply_tenant_filter(LifecycleSystem.objects.all(), user).filter(
        pk=pk, is_active=True).first()


def _get_change_for_user(pk, user, for_update=False):
    qs = apply_tenant_filter(
        ConfigChangeRecord.objects.select_related('system'), user)
    if for_update:
        qs = qs.select_for_update()
    return qs.filter(pk=pk).first()


def _get_param_for_user(pk, user):
    return apply_tenant_filter(ConfigParamDefinition.objects.all(), user).filter(
        pk=pk).first()


def _audit_summary(change):
    return {
        'change_no': change.change_no,
        'system': change.system_name,
        'status': change.status,
        'include_in_history': change.include_in_history,
    }


class SystemConfigView(View):
    """系统当前配置（系统详情 → 配置页签 · 当前配置区域）。

    只返回适用（scope 命中）且启用的参数；未设置的参数同样返回（值为空），
    兼作记录配置变更的参数候选来源。
    """

    @auth('equipment_lifecycle.config.view')
    def get(self, request, pk):
        system = _get_system_for_user(pk, request.user)
        if not system:
            return json_response(error='系统不存在')
        return json_response(config_services.get_system_config_view(system))


class SystemConfigParamOptionsView(View):
    """配置变更参数候选（当前配置接口已含全部适用参数，本接口按需裁剪字段，
    供记录变更 Modal 独立刷新使用）。"""

    @auth('equipment_lifecycle.config.view')
    def get(self, request, pk):
        system = _get_system_for_user(pk, request.user)
        if not system:
            return json_response(error='系统不存在')
        params = config_services.get_param_candidates_for_system(system).distinct().order_by('param_code')
        items = []
        for param in params:
            current_text = config_services.get_current_value_text(system, param)
            items.append({
                'param': param.id,
                'param_code': param.param_code,
                'param_name': param.param_name,
                'data_type': param.data_type,
                'unit': param.unit,
                'is_required': param.is_required,
                'options': param.get_options(),
                'current_value': current_text,
            })
        return json_response({'items': items})


class SystemConfigChangeListView(View):
    """系统配置变更历史（系统详情 → 配置页签 · 变更历史区域）。

    支持按参数、状态、时间范围筛选（时间用 __gte/__lt）。
    """

    @auth('equipment_lifecycle.config.view')
    def get(self, request, pk):
        system = _get_system_for_user(pk, request.user)
        if not system:
            return json_response(error='系统不存在')
        query = apply_tenant_filter(ConfigChangeRecord.objects.all(), request.user).filter(
            system=system)
        param_id = request.GET.get('param', '').strip()
        if param_id.isdigit():
            query = query.filter(items__param_id=int(param_id)).distinct()
        status = request.GET.get('status', '').strip()
        if status:
            if status not in CONFIG_CHANGE_STATUS_VALUES:
                return json_response(error='变更状态筛选值不正确')
            query = query.filter(status=status)
        created_from = _parse_dt(request.GET.get('created_from')) if request.GET.get('created_from') else None
        created_to = _parse_dt(request.GET.get('created_to')) if request.GET.get('created_to') else None
        if request.GET.get('created_from') and not created_from:
            return json_response(error='开始时间格式不正确')
        if request.GET.get('created_to') and not created_to:
            return json_response(error='结束时间格式不正确')
        if created_from:
            query = query.filter(created_at__gte=created_from)
        if created_to:
            query = query.filter(created_at__lt=created_to)
        page, page_size = paginate(request)
        data = paginate_response(query, page, page_size, serialize_fn=lambda x: x.to_view())
        return json_response(data)


def _validate_history_flags(include_in_history, history_reason):
    if include_in_history and not history_reason:
        return '纳入系统履历的重要变更必须填写纳入原因'
    return None


def _extract_change_payload(body, request):
    """创建/编辑配置变更的入参提取与校验。

    返回 (fields, error)：fields 为 dict，error 非 None 时无效。
    """
    system = _get_active_system_for_user(body.get('system'), request.user)
    if not system:
        return None, '系统不存在或已停用'
    reason = (body.get('reason') or '').strip()
    if not reason:
        return None, '请填写变更原因'
    items = body.get('items')
    if not isinstance(items, list) or not items:
        return None, '至少选择一个配置参数'
    include_in_history = bool(body.get('include_in_history'))
    history_reason = (body.get('history_reason') or '').strip()
    error = _validate_history_flags(include_in_history, history_reason)
    if error:
        return None, error
    fields = {
        'system': system,
        'reason': reason,
        'items': items,
        'include_in_history': include_in_history,
        'history_reason': history_reason,
        'verify_note': (body.get('verify_note') or '').strip(),
        'client_token': (body.get('client_token') or '').strip(),
    }
    return fields, None


def _normalize_scope_system_ids(scope_type, system_ids):
    """适用系统清单归一化：specific 时必须是非空数组，all 时清空。"""
    system_ids = system_ids or []
    if scope_type == PARAM_SCOPE_SPECIFIC:
        if not isinstance(system_ids, list) or not system_ids:
            return None, '指定系统范围时必须选择至少一个适用系统'
        return system_ids, None
    return [], None


def _pick_field(body, key, current=None):
    """维护入参读取：body 未提交（None）时编辑场景回落参数现值。"""
    value = body.get(key)
    if value is None and current is not None:
        return getattr(current, key)
    return value


def _extract_param_payload(body, current=None):
    """参数定义维护入参提取与校验（POST/PUT 共用）。

    返回 (fields, system_ids, error)；current 传入编辑场景的既有参数
    （编码不可改，data_type/scope_type 未提交时保留原值）。
    """
    param_code = (_pick_field(body, 'param_code', current) or '').strip()
    param_name = (body.get('param_name') or '').strip()
    data_type = (_pick_field(body, 'data_type', current) or '').strip()
    scope_type = (_pick_field(body, 'scope_type', current) or '').strip()
    if data_type not in PARAM_TYPE_VALUES:
        return None, None, '数据类型不正确'
    if scope_type not in (PARAM_SCOPE_ALL, PARAM_SCOPE_SPECIFIC):
        return None, None, '适用范围不正确'
    options = config_services.load_json_options(body.get('enum_options'))
    system_ids, error = _normalize_scope_system_ids(scope_type, body.get('system_ids'))
    if error:
        return None, None, error
    error = config_services.validate_param_definition(
        param_code=param_code, param_name=param_name, data_type=data_type,
        scope_type=scope_type, options=options,
        validation_regex=(body.get('validation_regex') or '').strip())
    if error:
        return None, None, error
    fields = {
        'param_code': param_code,
        'param_name': param_name,
        'data_type': data_type,
        'scope_type': scope_type,
        'unit': (body.get('unit') or '').strip()[:20],
        'is_required': bool(body.get('is_required')),
        'enum_options': json.dumps(options, ensure_ascii=False) if options else '',
        'validation_regex': (body.get('validation_regex') or '').strip()[:200],
        'is_enabled': bool(body.get('is_enabled', True)),
        'remark': (body.get('remark') or '').strip()[:200],
    }
    return fields, system_ids, None


def _apply_param_scopes(param, system_ids, user):
    """按入参重建参数适用系统清单（scope_type=specific 时生效）。"""
    param.system_scopes.all().delete()
    if system_ids:
        systems = apply_tenant_filter(
            LifecycleSystem.objects.all(), user).filter(
            pk__in=[int(x) for x in system_ids if str(x).isdigit()])
        ConfigParamSystemScope.objects.bulk_create([
            ConfigParamSystemScope(tenant_id=param.tenant_id,
                                   param=param, system=system)
            for system in systems
        ])


class ConfigChangeView(View):
    """配置变更创建（POST /config-changes/，body 携带 system）。

    编号锁内生成变更编号并创建草稿（non_atomic 装配）。
    """

    @auth('equipment_lifecycle.config.add')
    def post(self, request):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        fields, error = _extract_change_payload(body, request)
        if error:
            return json_response(error=error)
        # 幂等：client_token 命中同租户已有变更直接返回，不生成重复记录
        if fields['client_token']:
            existing = apply_tenant_filter(
                ConfigChangeRecord.objects.all(), request.user
            ).filter(client_token=fields['client_token']).first()
            if existing:
                return json_response(existing.to_detail_view())
        if check_recent_duplicate(
                ConfigChangeRecord,
                {'system': fields['system'], 'reason': fields['reason'][:500]},
                window_seconds=IDEMPOTENCY_WINDOW_SECONDS):
            return json_response(error='相同的配置变更刚刚已提交，请勿重复操作')
        try:
            with config_services.config_change_no_lock():
                with transaction.atomic():
                    change = config_services.create_config_change(
                        tenant_id=request.user.tenant_id,
                        created_by=request.user,
                        **fields,
                    )
                    record_audit_event(
                        request, 'create', AUDIT_TARGET_CONFIG_CHANGE,
                        change.id, change.change_no,
                        after_value={
                            'action': 'create_draft',
                            'items_count': change.items.count(),
                            'include_in_history': change.include_in_history,
                            **_audit_summary(change),
                        })
        except config_services.ConfigChangeLockTimeout as exc:
            return json_response(error=str(exc))
        except config_services.ConfigChangeNoExhausted as exc:
            return json_response(error=str(exc))
        except (config_services.ConfigValueError,
                config_services.ConfigChangeError) as exc:
            return json_response(error=str(exc))
        change.refresh_from_db()
        return json_response(change.to_detail_view())


class ConfigChangeDetailView(View):
    """配置变更详情 / 草稿编辑。

    GET：主表 + 明细（前后值快照）+ 回退记录关联；
    PUT：仅草稿可编辑（已生效变更不被普通编辑静默覆盖）。
    """

    @auth('equipment_lifecycle.config.view')
    def get(self, request, pk):
        change = _get_change_for_user(pk, request.user)
        if not change:
            return json_response(error='配置变更不存在')
        data = change.to_detail_view()
        data['items'] = [item.to_view() for item in change.items.select_related('param')]
        data['rollback_changes'] = [
            {
                'id': item.id,
                'change_no': item.change_no,
                'status_text': CONFIG_CHANGE_STATUS_TEXT_MAP.get(item.status, item.status),
                'created_at': item.created_at,
            }
            for item in change.rollback_changes.all()
        ]
        return json_response(data)

    @auth('equipment_lifecycle.config.edit')
    def put(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        with transaction.atomic():
            change = _get_change_for_user(pk, request.user, for_update=True)
            if not change:
                return json_response(error='配置变更不存在')
            reason = (body.get('reason') or '').strip()
            if not reason:
                return json_response(error='请填写变更原因')
            items = body.get('items')
            if not isinstance(items, list) or not items:
                return json_response(error='至少选择一个配置参数')
            try:
                change = config_services.update_draft_change(
                    change=change,
                    updated_by=request.user,
                    reason=reason,
                    items=items,
                    include_in_history=body.get('include_in_history'),
                    history_reason=body.get('history_reason'),
                    verify_note=body.get('verify_note'),
                )
            except (config_services.ConfigValueError,
                    config_services.ConfigChangeError) as exc:
                return json_response(error=str(exc))
            record_audit_event(
                request, 'update', AUDIT_TARGET_CONFIG_CHANGE,
                change.id, change.change_no,
                before_value=_audit_summary(change),
                after_value={'action': 'edit_draft',
                             'items_count': change.items.count(),
                             **_audit_summary(change)})
        return json_response(change.to_detail_view())


class ConfigChangeApplyView(View):
    """应用配置变更（草稿 → 已生效，事务内锁行防并发覆盖并写当前值）。"""

    @auth('equipment_lifecycle.config.apply')
    def post(self, request, pk):
        with transaction.atomic():
            change = _get_change_for_user(pk, request.user, for_update=True)
            if not change:
                return json_response(error='配置变更不存在')
            try:
                change = config_services.apply_config_change(
                    change=change, applied_by=request.user, request=request)
            except (config_services.ConfigValueError,
                    config_services.ConfigChangeError) as exc:
                return json_response(error=str(exc))
            record_audit_event(
                request, 'update', AUDIT_TARGET_CONFIG_CHANGE,
                change.id, change.change_no,
                after_value={'action': 'apply', **_audit_summary(change)})
        return json_response(change.to_detail_view())


class ConfigChangeVerifyView(View):
    """验证配置变更（已生效 → 已验证；不通过保持已生效可补验）。"""

    @auth('equipment_lifecycle.config.verify')
    def post(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        with transaction.atomic():
            change = _get_change_for_user(pk, request.user, for_update=True)
            if not change:
                return json_response(error='配置变更不存在')
            try:
                change = config_services.verify_config_change(
                    change=change,
                    verify_status=body.get('verify_status'),
                    verify_note=body.get('verify_note'),
                    verified_by=request.user,
                    request=request,
                )
            except (config_services.ConfigValueError,
                    config_services.ConfigChangeError) as exc:
                return json_response(error=str(exc))
            record_audit_event(
                request, 'update', AUDIT_TARGET_CONFIG_CHANGE,
                change.id, change.change_no,
                after_value={'action': 'verify',
                             'verify_status': change.verify_status,
                             **_audit_summary(change)})
        return json_response(change.to_detail_view())


class ConfigChangeRollbackView(View):
    """回退配置变更：生成一条新的反向变更，原记录只流转状态（编号锁内）。"""

    @auth('equipment_lifecycle.config.rollback')
    def post(self, request, pk):
        try:
            with config_services.config_change_no_lock():
                with transaction.atomic():
                    change = _get_change_for_user(pk, request.user, for_update=True)
                    if not change:
                        return json_response(error='配置变更不存在')
                    try:
                        rollback_change = config_services.rollback_config_change(
                            change=change, created_by=request.user)
                    except (config_services.ConfigValueError,
                            config_services.ConfigChangeError) as exc:
                        return json_response(error=str(exc))
                    record_audit_event(
                        request, 'update', AUDIT_TARGET_CONFIG_CHANGE,
                        change.id, change.change_no,
                        after_value={'action': 'rollback',
                                     'rollback_change_no': rollback_change.change_no,
                                     **_audit_summary(change)})
        except config_services.ConfigChangeLockTimeout as exc:
            return json_response(error=str(exc))
        except config_services.ConfigChangeNoExhausted as exc:
            return json_response(error=str(exc))
        return json_response(rollback_change.to_detail_view())


class ConfigChangeCancelView(View):
    """取消草稿配置变更（已生效变更只能走回退流程）。"""

    @auth('equipment_lifecycle.config.edit')
    def post(self, request, pk):
        with transaction.atomic():
            change = _get_change_for_user(pk, request.user, for_update=True)
            if not change:
                return json_response(error='配置变更不存在')
            try:
                change = config_services.cancel_config_change(
                    change=change, cancelled_by=request.user, request=request)
            except (config_services.ConfigValueError,
                    config_services.ConfigChangeError) as exc:
                return json_response(error=str(exc))
            record_audit_event(
                request, 'update', AUDIT_TARGET_CONFIG_CHANGE,
                change.id, change.change_no,
                after_value={'action': 'cancel', **_audit_summary(change)})
        return json_response(change.to_detail_view())


class ConfigParamView(View):
    """配置参数定义：查询（view）与新增（template）。"""

    @auth('equipment_lifecycle.config.view')
    def get(self, request):
        query = apply_tenant_filter(ConfigParamDefinition.objects.all(), request.user)
        system_id = request.GET.get('system', '').strip()
        if system_id.isdigit():
            system = _get_system_for_user(int(system_id), request.user)
            if not system:
                return json_response(error='系统不存在')
            query = query.filter(
                Q(scope_type=PARAM_SCOPE_ALL)
                | Q(scope_type=PARAM_SCOPE_SPECIFIC, system_scopes__system_id=system.id),
            )
        query = query.distinct().order_by('param_code')
        page, page_size = paginate(request)
        data = paginate_response(query, page, page_size, serialize_fn=lambda x: x.to_view())
        return json_response(data)

    @auth('equipment_lifecycle.config.template')
    def post(self, request):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        fields, system_ids, error = _extract_param_payload(body)
        if error:
            return json_response(error=error)
        with transaction.atomic():
            if ConfigParamDefinition.objects.filter(
                    tenant_id=request.user.tenant_id,
                    param_code=fields['param_code']).exists():
                return json_response(error='参数编码已存在')
            param = ConfigParamDefinition.objects.create(
                tenant_id=request.user.tenant_id,
                created_by=request.user,
                **fields,
            )
            if fields['scope_type'] == PARAM_SCOPE_SPECIFIC:
                _apply_param_scopes(param, system_ids, request.user)
            record_audit_event(
                request, 'create', AUDIT_TARGET_CONFIG_PARAM,
                param.id, param.param_code,
                after_value={'param_name': param.param_name,
                             'data_type': param.data_type,
                             'scope_type': param.scope_type})
        return json_response(param.to_view())


class ConfigParamDetailView(View):
    """配置参数定义编辑（编码不可修改；停用保留全部历史记录）。"""

    @auth('equipment_lifecycle.config.template')
    def put(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        with transaction.atomic():
            param = _get_param_for_user(pk, request.user)
            if not param:
                return json_response(error='参数定义不存在')
            fields, system_ids, error = _extract_param_payload(body, current=param)
            if error:
                return json_response(error=error)
            for attr, value in fields.items():
                setattr(param, attr, value)
            param.updated_at = timezone.now()
            param.updated_by = request.user
            param.save()
            _apply_param_scopes(param, system_ids, request.user)
            record_audit_event(
                request, 'update', AUDIT_TARGET_CONFIG_PARAM,
                param.id, param.param_code,
                after_value={'param_name': param.param_name,
                             'is_enabled': param.is_enabled,
                             'scope_type': param.scope_type})
        return json_response(param.to_view())
