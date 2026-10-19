# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""系统初始配置建档服务层（2026-10-19）。

职责：
- get_baseline_state：建档状态查询（建档内容 + 是否可建档 + 拦截原因），
  供维护入口与系统档案配置页签共同使用；
- establish_baseline：建立初始配置（校验 + 建档主表/明细 + 当前配置值写入），
  须在事务内、由调用方持系统行锁调用；
- get_baseline_detail：建档详情（明细含规范化值文本与参数分类）。

约定：
- 每系统至多一份建档；建档后参数修改一律走配置变更流程（建档身份独立，
  不伪装成普通配置变更）；
- 只有"干净"系统允许建档：无建档、无当前配置值、无非草稿配置变更——
  已有配置数据的老系统保留原记录，不补建、不凭空推断历史基线；
- 建档写入的当前值 last_change 为空、baseline 指向建档行，当前值展示
  据此区分"初始建档"与"配置变更"来源；
- 值校验与规范化复用 config_services（normalize_param_value /
  canonical_value_text），建档值不允许为空（空值参数不纳入建档）；
- 草稿变更不占用建档资格：草稿未写当前值，建档后其应用会被
  "变更前值已被修改"护栏拦截，需取消后重新登记，符合 fail-closed。
"""
from django.utils import timezone

from apps.equipment_lifecycle.config_models import (
    CONFIG_CHANGE_APPLIED,
    CONFIG_CHANGE_ROLLED_BACK,
    CONFIG_CHANGE_VERIFIED,
    PARAM_CATEGORY_CHOICES,
    PARAM_TYPE_TEXT_MAP,
    ConfigChangeRecord,
    ConfigParamDefinition,
    SystemConfigBaseline,
    SystemConfigBaselineItem,
    SystemParamValue,
)
from apps.equipment_lifecycle.config_services import (
    canonical_value_text,
    normalize_param_value,
)


class ConfigBaselineError(Exception):
    """初始建档业务校验失败（由调用方转为业务错误提示）。"""


def get_baseline_block_reason(system):
    """系统不可建档的原因文案；None 表示可以建档（建档存在性一并校验）。"""
    if SystemConfigBaseline.objects.filter(
            tenant_id=system.tenant_id, system=system).exists():
        return '该系统已建立初始配置'
    if SystemParamValue.objects.filter(
            tenant_id=system.tenant_id, system=system).exists():
        return '该系统已有配置值（来自历史配置变更），保留原记录，不再补建初始配置'
    if ConfigChangeRecord.objects.filter(
            tenant_id=system.tenant_id, system=system,
            status__in=[CONFIG_CHANGE_APPLIED, CONFIG_CHANGE_VERIFIED,
                        CONFIG_CHANGE_ROLLED_BACK]).exists():
        return '该系统已有已生效的配置变更历史，保留原记录，不再补建初始配置'
    return None


def get_baseline_detail(baseline):
    """建档详情：主表视图 + 明细（规范化值文本 + 参数分类读自参数定义）。"""
    data = baseline.to_view()
    items = []
    for item in baseline.items.select_related('param').order_by('id'):
        fields = {
            'value_text': item.value_text,
            'value_number': item.value_number,
            'value_bool': item.value_bool,
            'value_date': item.value_date,
            'value_choice': item.value_choice,
        }
        items.append({
            'id': item.id,
            'param': item.param_id,
            'param_code': item.param_code,
            'param_name': item.param_name,
            'data_type': item.param_data_type,
            'data_type_text': PARAM_TYPE_TEXT_MAP.get(item.param_data_type, item.param_data_type),
            'category': item.param.category,
            'category_text': dict(PARAM_CATEGORY_CHOICES).get(item.param.category, item.param.category),
            'unit': item.unit,
            'display_value': canonical_value_text(item.param_data_type, fields),
        })
    data['items'] = items
    return data


def get_baseline_state(system):
    """建档状态：建档内容（含明细）+ 是否可建档 + 拦截原因。"""
    baseline = SystemConfigBaseline.objects.filter(
        tenant_id=system.tenant_id, system=system,
    ).select_related('established_by').first()
    block_reason = get_baseline_block_reason(system)
    return {
        'baseline': get_baseline_detail(baseline) if baseline else None,
        'can_establish': baseline is None and block_reason is None,
        'block_reason': block_reason or '',
    }


def _build_baseline_items(system, raw_items):
    """从原始明细构建建档明细实例（未保存）。

    - 后端重新查询参数定义，不信任前端传入的参数名称/类型；
    - 参数必须启用且适用当前系统，同一参数不允许重复建档；
    - 建档值不允许为空（空值参数不纳入建档，保持"未设置"）。
    """
    if not isinstance(raw_items, list) or not raw_items:
        raise ConfigBaselineError('至少为一个配置参数建立基线值')
    seen_param_ids = set()
    items = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise ConfigBaselineError('建档明细格式不正确')
        param_id = raw.get('param')
        if not param_id or str(param_id).isdigit() is False:
            raise ConfigBaselineError('建档明细缺少参数')
        param_id = int(param_id)
        if param_id in seen_param_ids:
            raise ConfigBaselineError('同一参数不能重复建档')
        seen_param_ids.add(param_id)
        param = ConfigParamDefinition.objects.filter(
            pk=param_id, tenant_id=system.tenant_id).first()
        if not param:
            raise ConfigBaselineError('配置参数不存在或无权限访问')
        if not param.is_enabled:
            raise ConfigBaselineError(f'参数「{param.param_name}」已停用，不能建档')
        if not param.applies_to_system(system.id):
            raise ConfigBaselineError(f'参数「{param.param_name}」不适用于当前系统')
        fields = normalize_param_value(param, raw.get('value'))
        value_text = canonical_value_text(param.data_type, fields)
        if not value_text:
            raise ConfigBaselineError(
                f'参数「{param.param_name}」的基线值不能为空；不需要建档的参数请勿勾选')
        items.append(SystemConfigBaselineItem(
            tenant_id=system.tenant_id,
            param=param,
            param_code=param.param_code,
            param_name=param.param_name,
            param_data_type=param.data_type,
            unit=param.unit,
            **fields,
        ))
    return items


def establish_baseline(*, system, established_by, source, remark, items):
    """建立初始配置（视图层在 transaction.atomic 内、持系统行锁调用）。

    - 建档前在锁内复核建档资格（防并发：同一时刻另一请求已建档或已应用
      变更时 fail-closed）；
    - 写入建档主表/明细，并为每个建档参数创建当前配置值行（last_change
      为空、baseline 指向建档、生效时间=建档时间）；
    - 建档不生成变更编号、不产生配置变更记录，身份由建档行承载。
    """
    block_reason = get_baseline_block_reason(system)
    if block_reason:
        raise ConfigBaselineError(block_reason + '，不能建立初始配置')
    source_text = (source or '').strip()
    if not source_text:
        raise ConfigBaselineError('请填写建档来源（如验收文档、出厂技术资料）')
    baseline_items = _build_baseline_items(system, items)
    established_at = timezone.now()
    baseline = SystemConfigBaseline.objects.create(
        tenant_id=system.tenant_id,
        system=system,
        system_code=system.system_code,
        system_name=system.name,
        source=source_text[:200],
        remark=(remark or '').strip()[:200],
        established_at=established_at,
        established_by=established_by,
    )
    for item in baseline_items:
        item.baseline = baseline
    SystemConfigBaselineItem.objects.bulk_create(baseline_items)
    for item in baseline_items:
        SystemParamValue.objects.create(
            tenant_id=system.tenant_id,
            system=system,
            param=item.param,
            value_text=item.value_text,
            value_number=item.value_number,
            value_bool=item.value_bool,
            value_date=item.value_date,
            value_choice=item.value_choice,
            effective_at=established_at,
            last_change=None,
            baseline=baseline,
            last_changed_by=established_by,
            created_by=established_by,
        )
    return baseline
