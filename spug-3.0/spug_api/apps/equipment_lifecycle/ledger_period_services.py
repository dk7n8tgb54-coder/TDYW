# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——本期应填台账生成与周期分组服务（2026-10-14 自 ledger_services 迁出）。

- 生成范围：显式配置 适用系统+生成周期 的启用 Excel 模板（一模板一系统，
  同系统可多模板），生成本周/本月/本航季的应填台账并按期次分组查看；
- 期次与去重、生成物形态、日期语义与历史兼容的完整约定见下方章节注释；
- 本模块只承载周期生成与分组查询，台账通用创建/编辑/状态机仍在
  ledger_services（本文件可反向导入，不构成循环）。
"""
import logging
import re
from datetime import date, datetime, timedelta

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from libs.tenant_utils import apply_tenant_filter

from apps.equipment_lifecycle.excel_models import (
    TEMPLATE_PERIOD_MONTHLY,
    TEMPLATE_PERIOD_TEXT,
    TEMPLATE_PERIOD_WEEKLY,
    OperationLedgerExcelRecord,
    OperationLedgerExcelTemplate,
    OperationLedgerExcelTemplateVersion,
)
from apps.equipment_lifecycle.form_models import (
    OperationLedgerFormRecord,
    OperationLedgerFormTemplate,
    OperationLedgerFormTemplateVersion,
)
from apps.equipment_lifecycle.models import (
    ENTRY_CHANNEL_WEB,
    ITEM_RESULT_ABNORMAL,
    LEDGER_FROM_EXCEL,
    LEDGER_FROM_FORM,
    LEDGER_FROM_MANUAL,
    LEDGER_STATUS_COMPLETED,
    LEDGER_STATUS_DRAFT,
    LEDGER_STATUS_VOID,
    LEDGER_TYPE_SEASONAL,
    LEDGER_TYPE_WEEK_MONTH,
    OperationLedger,
    OperationLedgerItem,
)
from apps.equipment_lifecycle.ledger_services import (
    LedgerValidationError,
    apply_ledger_status_filter,
    generate_ledger_no,
    validate_ledger_type,
)

logger = logging.getLogger(__name__)

# ======================================================================
# 本期应填台账生成（2026-10-14 重构原"周期批量新增"：不再创建手工壳）
# ----------------------------------------------------------------------
# - 生成对象 = 已显式配置 适用系统 + 生成周期 的启用模板（一模板一系统，
#   同系统可多模板；配置不从模板名称或表格内容推断；历史模板未配置
#   的标记"待配置"，不猜测、不改写历史记录）。2026-10-21 起同时覆盖
#   两条路线：Excel 模板（excel_template）与数字表单模板（form_template），
#   槽位与期次语义完全一致，条目以 template_kind 区分（excel/form）；
# - 期次键（maintenance_period，计划填写期次）：
#   · 每周模板：本周一日期 YYYY-MM-DD——周一至周日为一个自然周，跨月周只
#     算一个期次，归入周一所在月份，展示完整起止日期；
#   · 每月模板：YYYY-MM（自然月）；
#   · 季维护模板：YYYY-夏秋 / YYYY-冬春（民航航季边界）；
#   期次归属只看该表头标记（2026-10-19 删除 executed_date，历史台账已在
#   迁移 0024 按当时推导口径回填标记）；
# - 本期 = 以当前日期为基准的当前周/当前月/当前航季，不预建未来期次；
# - 去重：同租户+路线模板+系统+期次仅一张有效台账（Excel 路线唯一约束
#   uniq_el_ledger_tpl_period、数字表单路线 uniq_el_ledger_form_tpl_period，
#   均以 slot_active 参与：非作废=True、作废=NULL 豁免；作废台账不在一键
#   生成中悄悄重建，预览标记需人工处理，确需重做走明确补建
#   period_generate_rebuild）；模板行锁串行化并发，发布新版本/重复点击/
#   并发请求都不重复生成；
# - 生成物 = created_from=excel_template / form_template 的正式台账，创建
#   即固定引用模板最新已发布版本快照（Excel: OperationLedgerExcelRecord，
#   数字表单：OperationLedgerFormRecord），可直接进入对应填写界面；不再
#   生成没有明细且无法补录的手工草稿；
# - 历史兼容：旧批量新增的手工壳（created_from=manual 且带期次标记）不
#   改写，同系统同期次存在未作废手工壳时该模板标记需人工处理，不自动生成。
# ======================================================================

PERIOD_WEEK_RE = re.compile(r'^(\d{4})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$')
PERIOD_MONTH_RE = re.compile(r'^(\d{4})-(0[1-9]|1[0-2])$')
PERIOD_SEASON_RE = re.compile(r'^(\d{4})-(夏秋|冬春)$')


def _last_weekday_of_month(year, month, weekday):
    """某月最后一个指定星期几（weekday: 周一=0 … 周日=6）。"""
    if month == 12:
        last_day = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)
    return last_day - timedelta(days=(last_day.weekday() - weekday) % 7)

# 预览/生成条目状态
GENERATE_CREATE = 'create'          # 将新建
GENERATE_EXISTS = 'exists'          # 已存在有效台账，跳过
GENERATE_NO_VERSION = 'no_version'  # 缺少可用版本（未发布任何版本）
GENERATE_MANUAL_NEEDED = 'manual_needed'  # 需人工处理（待配置/停用/作废或历史草稿占用）
GENERATE_STATUS_VALUES = [
    GENERATE_CREATE, GENERATE_EXISTS, GENERATE_NO_VERSION, GENERATE_MANUAL_NEEDED,
]
GENERATE_STATUS_TEXT = {
    GENERATE_CREATE: '将新建',
    GENERATE_EXISTS: '已存在跳过',
    GENERATE_NO_VERSION: '缺少可用版本',
    GENERATE_MANUAL_NEEDED: '需人工处理',
}


def week_start(day):
    """所在自然周的周一（每周从周一开始，到周日结束）。"""
    return day - timedelta(days=day.weekday())


def week_period_key(day):
    """周期生成用每周期次键：该周周一日期 YYYY-MM-DD。"""
    return week_start(day).strftime('%Y-%m-%d')


def parse_maintenance_period(ledger_type, period):
    """校验并解析计划期次，返回 (period, start_date, end_date_exclusive)。

    周月维护接受两种期次键：每周键 YYYY-MM-DD（须为周一日期，周一~周日）
    与每月键 YYYY-MM；季维护为航季 YYYY-夏秋 / YYYY-冬春。
    """
    validate_ledger_type(ledger_type)
    period = str(period or '').strip()
    if ledger_type == LEDGER_TYPE_WEEK_MONTH:
        if PERIOD_WEEK_RE.match(period):
            try:
                start = datetime.strptime(period, '%Y-%m-%d').date()
            except ValueError:
                raise LedgerValidationError('周期格式不正确：%s' % period)
            if start.weekday() != 0:
                raise LedgerValidationError('每周期次键应为周一日期：%s' % period)
            return period, start, start + timedelta(days=7)
        matched = PERIOD_MONTH_RE.match(period)
        if not matched:
            raise LedgerValidationError('周月维护周期格式应为 YYYY-MM 或周一日期 YYYY-MM-DD')
        year, month = int(matched.group(1)), int(matched.group(2))
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    else:
        matched = PERIOD_SEASON_RE.match(period)
        if not matched:
            raise LedgerValidationError('季维护周期应为航季：YYYY-夏秋 或 YYYY-冬春，如 2026-夏秋')
        year, season = int(matched.group(1)), matched.group(2)
        if season == '夏秋':
            start = _last_weekday_of_month(year, 3, 6)      # 夏秋航季开始（3月末周日）
            end = _last_weekday_of_month(year, 10, 6)       # 冬春航季开始（10月末周日，开区间）
        else:
            start = _last_weekday_of_month(year, 10, 6)     # 冬春航季开始（10月末周日）
            end = _last_weekday_of_month(year + 1, 3, 6)    # 次年夏秋开始（次年3月末周日，开区间）
    return period, start, end


SEASON_TEXT_MAP = {'夏秋': '夏秋季', '冬春': '冬春季'}


def season_key_of(day):
    """日期所属航季期次键（夏秋=3月末周日~10月末周日；冬春=10月末周日~次年3月末周日）。"""
    summer_start = _last_weekday_of_month(day.year, 3, 6)
    winter_start = _last_weekday_of_month(day.year, 10, 6)
    if summer_start <= day < winter_start:
        return '%04d-夏秋' % day.year
    if day >= winter_start:
        return '%04d-冬春' % day.year
    # 1~3月中属于上一年10月末开始的冬春航季
    return '%04d-冬春' % (day.year - 1)


def current_period_key(ledger_type, generation_period, today=None):
    """模板生成周期 → 本期期次键（以当前日期为基准，不预建未来期次）。"""
    today = today or timezone.now().date()
    if ledger_type == LEDGER_TYPE_SEASONAL:
        return season_key_of(today)
    if generation_period == TEMPLATE_PERIOD_WEEKLY:
        return week_period_key(today)
    return today.strftime('%Y-%m')


def maintenance_period_text(ledger_type, period):
    """期次展示文本：每周键显示完整起止日期；YYYY-MM → 2026年10月；航季 → 2026年夏秋季。"""
    if ledger_type == LEDGER_TYPE_SEASONAL:
        year, season = period.split('-')
        return '%s年%s' % (year, SEASON_TEXT_MAP.get(season, season))
    if PERIOD_WEEK_RE.match(period):
        start = datetime.strptime(period, '%Y-%m-%d').date()
        return '%s ~ %s' % (period, (start + timedelta(days=6)).strftime('%Y-%m-%d'))
    year, month = period.split('-')
    return '%s年%d月' % (year, int(month))


# 期次完整标签前缀：填写列表行/分组标题用，一个月多张周台账时可直接辨认每张
# 对应哪一周（每周｜周一日期—周日日期）/ 哪个月（每月｜YYYY年M月）
PERIOD_LABEL_WEEK_PREFIX = '每周｜'
PERIOD_LABEL_MONTH_PREFIX = '每月｜'
PERIOD_UNMARKED_LABEL = '未标注期次'


def maintenance_period_label(ledger_type, period):
    """期次完整展示标签：每周｜周一—周日 / 每月｜YYYY年M月 / 航季名称含起止日期。

    空/无法解析的期次返回"未标注期次"或原样键值，不猜测、不改写。
    """
    period = str(period or '').strip()
    if not period:
        return PERIOD_UNMARKED_LABEL
    if ledger_type == LEDGER_TYPE_SEASONAL:
        try:
            _, start, end = parse_maintenance_period(ledger_type, period)
        except LedgerValidationError:
            return period
        year, season = period.split('-')
        return '%s年%s（%s ~ %s）' % (
            year, SEASON_TEXT_MAP.get(season, season),
            start.strftime('%Y-%m-%d'), (end - timedelta(days=1)).strftime('%Y-%m-%d'))
    if PERIOD_WEEK_RE.match(period):
        try:
            start = datetime.strptime(period, '%Y-%m-%d').date()
        except ValueError:
            return period
        return '%s%s ~ %s' % (PERIOD_LABEL_WEEK_PREFIX, period,
                              (start + timedelta(days=6)).strftime('%Y-%m-%d'))
    matched = PERIOD_MONTH_RE.match(period)
    if matched:
        return '%s%s年%d月' % (PERIOD_LABEL_MONTH_PREFIX, matched.group(1), int(matched.group(2)))
    return period


def period_current_keys(ledger_type, today=None):
    """本期期次键集合：周月维护为 本周（周一键）+ 本月；季维护为当前航季。"""
    today = today or timezone.now().date()
    if ledger_type == LEDGER_TYPE_SEASONAL:
        return {season_key_of(today)}
    return {week_period_key(today), today.strftime('%Y-%m')}


def ledger_period_display(ledger):
    """台账行级期次展示字段（期次归属只看表头标记，2026-10-19 起）。

    - 明确期次：表头 maintenance_period 标记；
    - 无标记：显示"未标注期次"（历史无标记台账已在迁移 0024 按当时推导
      口径回填标记，此处不再读时推导）。
    """
    period = ledger_period_key(ledger)
    if not period:
        return {'period_label': PERIOD_UNMARKED_LABEL, 'period_is_derived': False,
                'period_source_text': '台账缺少期次标记'}
    return {'period_label': maintenance_period_label(ledger.ledger_type, period),
            'period_is_derived': False, 'period_source_text': ''}


def ledger_period_key(ledger):
    """台账归属期次：表头计划期次标记（无标记返回空串）。"""
    return ledger.maintenance_period or ''


def _generatable_templates(user, ledger_type, kind='excel', for_update=False):
    """本租户指定类型、指定路线的启用模板（生成范围；含待配置模板，预览中
    显式标注）。kind='excel' 查 Excel 模板表，kind='form' 查数字表单模板表；
    两类模板同名字段（system/generation_period/ledger_type/is_active）同义。"""
    model = OperationLedgerFormTemplate if kind == 'form' else OperationLedgerExcelTemplate
    query = apply_tenant_filter(
        model.objects.filter(is_active=True), user,
    ).filter(ledger_type=ledger_type).select_related('system')
    if for_update:
        query = query.select_for_update()
    return query.order_by('id')


def _latest_versions(template_ids, kind='excel'):
    """模板 → 最新已发布版本（无发布版本的模板不出现）。

    template_ids 来自已按租户过滤的模板集合，版本随模板租户归属；
    两张版本表主键独立，结果以 kind 分开使用，不跨表合并。
    """
    model = (OperationLedgerFormTemplateVersion if kind == 'form'
             else OperationLedgerExcelTemplateVersion)
    latest = {}
    if not template_ids:
        return latest
    rows = model.objects.filter(
        template_id__in=template_ids).order_by('template_id', '-version_no')
    for version in rows:
        latest.setdefault(version.template_id, version)
    return latest


def _generation_slot_ledgers(user, ledger_type, slots):
    """批量查询各 (路线, 模板, 系统, 期次) 槽位的现有台账（含已作废，用于分类判定）。

    slots 为 (kind, template_id, system_id, period)；返回 {'excel': 桶,
    'form': 桶}，桶键为 (kind, template_id, system_id, period)——两条路线
    的模板主键分属不同表、互不比较，必须带 kind 分桶。旧批量新增的手工壳
    （created_from=manual、无路线模板、同系统同期次）同时并入两条路线的
    (kind, None, 系统, 期次) 桶，一并占位（不自动改写历史记录，由预览
    显式标注需人工处理）。
    """
    if not slots:
        return {'excel': {}, 'form': {}}
    template_q = Q()
    form_q = Q()
    shell_q = Q()
    for kind, template_id, system_id, period in slots:
        if kind == 'form':
            form_q |= Q(source_form_template_id=template_id, system_id=system_id,
                        maintenance_period=period)
        else:
            template_q |= Q(source_template_id=template_id, system_id=system_id,
                            maintenance_period=period)
        shell_q |= Q(created_from=LEDGER_FROM_MANUAL, source_template__isnull=True,
                     source_form_template__isnull=True,
                     system_id=system_id, maintenance_period=period)
    rows = apply_tenant_filter(OperationLedger.objects.all(), user).filter(
        Q(ledger_type=ledger_type) & (template_q | form_q | shell_q),
    )
    grouped = {'excel': {}, 'form': {}}
    for ledger in rows:
        kind = 'form' if ledger.created_from == LEDGER_FROM_FORM else 'excel'
        template_id = (ledger.source_form_template_id if kind == 'form'
                       else ledger.source_template_id)
        if template_id is None:
            # 手工壳（无路线模板）：对两条路线的槽位判定同时占位
            for bucket_kind in ('excel', 'form'):
                grouped[bucket_kind].setdefault(
                    (bucket_kind, None, ledger.system_id, ledger.maintenance_period),
                    []).append(ledger)
            continue
        grouped[kind].setdefault(
            (kind, template_id, ledger.system_id, ledger.maintenance_period),
            []).append(ledger)
    return grouped


def _template_slot(template, ledger_type, today):
    """模板本期槽位：返回 (period, start, end) 或 (None, None, None)（待配置）。"""
    if template.system_id is None or not template.generation_period:
        return None, None, None
    if ledger_type == LEDGER_TYPE_WEEK_MONTH and template.generation_period \
            not in (TEMPLATE_PERIOD_WEEKLY, TEMPLATE_PERIOD_MONTHLY):
        return None, None, None
    period = current_period_key(ledger_type, template.generation_period, today)
    _, start, end = parse_maintenance_period(ledger_type, period)
    return period, start, end


def _classify_slot(template, kind, slot_ledgers, period):
    """槽位分类：返回 (status, reason, existing_ledger)。

    判定顺序：本模板有效台账已存在（跳过）→ 历史手工壳占用（需人工处理）
    → 已作废占用（需人工处理，不悄悄重建）→ 可新建。
    手工壳（无路线模板）以 (kind, None, 系统, 期次) 落桶，与模板槽位合并
    判定；本模板槽位受唯一约束（含已作废），不会同时存在有效与作废两张。
    """
    ledgers = list(slot_ledgers.get(
        (kind, template.id, template.system_id, period)) or [])
    ledgers += slot_ledgers.get((kind, None, template.system_id, period)) or []
    own_field = 'source_form_template_id' if kind == 'form' else 'source_template_id'
    template_valid = [x for x in ledgers
                      if getattr(x, own_field) is not None
                      and x.status != LEDGER_STATUS_VOID]
    if template_valid:
        ledger = sorted(template_valid, key=lambda x: -x.id)[0]
        return GENERATE_EXISTS, '', ledger
    shells = [x for x in ledgers
              if getattr(x, own_field) is None and x.status != LEDGER_STATUS_VOID]
    if shells:
        ledger = sorted(shells, key=lambda x: -x.id)[0]
        return (GENERATE_MANUAL_NEEDED,
                '该系统本期已存在历史草稿台账 %s，请先作废或处理后生成' % ledger.ledger_no,
                ledger)
    voided = [x for x in ledgers if x.status == LEDGER_STATUS_VOID]
    if voided:
        ledger = sorted(voided, key=lambda x: -x.id)[0]
        return (GENERATE_MANUAL_NEEDED,
                '该期次已存在已作废台账 %s，不在一键生成中重建；确需重做请使用补建操作' % ledger.ledger_no,
                ledger)
    return GENERATE_CREATE, '', None


def _generation_entry(user, template, ledger_type, today, latest, slot_ledgers,
                      kind='excel'):
    """单模板本期生成判定（预览与生成共用同一口径；kind 标识路线）。"""
    entry = {
        'template_kind': kind,
        'template_id': template.id,
        'template_name': template.name,
        'system_id': template.system_id,
        'system_name': template.system.name if template.system_id else '',
        'system_code': template.system.system_code if template.system_id else '',
        'generation_period': template.generation_period,
        'generation_period_text': TEMPLATE_PERIOD_TEXT.get(
            template.generation_period, template.generation_period or ''),
        'maintenance_period': '',
        'period_text': '',
        'period_start': None,
        'period_end': None,
        'version_id': None,
        'version_no': None,
        'status': GENERATE_MANUAL_NEEDED,
        'reason': '',
        'existing_ledger': None,
    }
    if not template.is_active:
        entry['reason'] = '模板已停用，不能用于新台账'
        return entry
    period, start, end = _template_slot(template, ledger_type, today)
    if period is None:
        missing = []
        if template.system_id is None:
            missing.append('适用系统')
        if not template.generation_period:
            missing.append('生成周期')
        entry['reason'] = '模板待配置：%s（历史模板不自动推断，请在模板管理中配置）' % '、'.join(missing)
        return entry
    entry['maintenance_period'] = period
    entry['period_text'] = maintenance_period_text(ledger_type, period)
    entry['period_start'] = start
    entry['period_end'] = end - timedelta(days=1)
    version = latest.get(template.id)
    if version is None:
        entry['status'] = GENERATE_NO_VERSION
        entry['reason'] = '缺少可用版本：模板尚未发布任何版本'
        return entry
    entry['version_id'] = version.id
    entry['version_no'] = version.version_no
    if template.system_id and not template.system.is_active:
        entry['status'] = GENERATE_MANUAL_NEEDED
        entry['reason'] = '适用系统已停用，不能用于新台账'
        return entry
    status, reason, existing = _classify_slot(template, kind, slot_ledgers, period)
    entry['status'] = status
    entry['reason'] = reason
    if existing is not None:
        entry['existing_ledger'] = {
            'id': existing.id, 'ledger_no': existing.ledger_no, 'status': existing.status}
    # 作废占用的槽位提供明确补建入口（前端在预览行内展示"补建"按钮）
    entry['rebuildable'] = bool(
        status == GENERATE_MANUAL_NEEDED and existing is not None
        and existing.status == LEDGER_STATUS_VOID)
    return entry


def _validate_maintenance_cycles(ledger_type, maintenance_cycles, required=False):
    """校验本次选择的维护周期；季维护固定为 seasonal。"""
    allowed = {'seasonal'} if ledger_type == LEDGER_TYPE_SEASONAL else {'weekly', 'monthly'}
    if maintenance_cycles is None:
        if required:
            return None, '请选择维护周期'
        return allowed, None
    if not isinstance(maintenance_cycles, (list, tuple)) or not maintenance_cycles:
        return None, '至少选择一个维护周期'
    if any(not isinstance(value, str) or value not in allowed
           for value in maintenance_cycles):
        return None, '维护周期参数与台账类型不匹配'
    selected = set(maintenance_cycles)
    return selected, None


def _selected_entry_cycles(entry):
    return 'seasonal' if entry.get('generation_period') == 'seasonal' \
        else entry.get('generation_period')


def _collect_generation_slots(user, ledger_type, today):
    """两条路线启用模板的本期槽位统一收集（预览/生成/概览共用）。

    返回 (excel_templates, form_templates, latest, slot_maps)：
    - latest 为 {kind: {template_id: 最新版本}}；
    - slot_maps 为 _generation_slot_ledgers 结果（桶键带 kind）。
    """
    excel_templates = list(_generatable_templates(user, ledger_type, kind='excel'))
    form_templates = list(_generatable_templates(user, ledger_type, kind='form'))
    slots = []
    for kind, templates in (('excel', excel_templates), ('form', form_templates)):
        for template in templates:
            period, _, _ = _template_slot(template, ledger_type, today)
            if period is not None:
                slots.append((kind, template.id, template.system_id, period))
    latest = {
        'excel': _latest_versions([t.id for t in excel_templates], kind='excel'),
        'form': _latest_versions([t.id for t in form_templates], kind='form'),
    }
    slot_maps = _generation_slot_ledgers(user, ledger_type, slots)
    return excel_templates, form_templates, latest, slot_maps


def _merged_generation_entries(user, ledger_type, today, excel_templates,
                               form_templates, latest, slot_maps):
    """两条路线生成条目合并（Excel 路线在前，路线内按模板 id 升序）。"""
    entries = [
        _generation_entry(user, t, ledger_type, today, latest['excel'],
                          slot_maps['excel'], kind='excel')
        for t in excel_templates
    ]
    entries += [
        _generation_entry(user, t, ledger_type, today, latest['form'],
                          slot_maps['form'], kind='form')
        for t in form_templates
    ]
    return entries


def period_generate_preview(user, ledger_type, maintenance_cycles=None):
    """本期应填台账预览（只读）：逐模板给出当前期次与可生成性判定。

    返回 (result, None) 或 (None, error)。条目状态：create 将新建 /
    exists 已存在跳过 / no_version 缺少可用版本 / manual_needed 需人工处理；
    条目含 template_kind（excel/form）区分模板路线。
    """
    try:
        validate_ledger_type(ledger_type)
    except LedgerValidationError as e:
        return None, str(e)
    selected_cycles, error = _validate_maintenance_cycles(
        ledger_type, maintenance_cycles)
    if error:
        return None, error
    today = timezone.now().date()
    excel_templates, form_templates, latest, slot_maps = _collect_generation_slots(
        user, ledger_type, today)
    entries = _merged_generation_entries(
        user, ledger_type, today, excel_templates, form_templates, latest, slot_maps)
    entries = [entry for entry in entries
               if not _selected_entry_cycles(entry)
               or _selected_entry_cycles(entry) in selected_cycles]
    summary = {status: 0 for status in GENERATE_STATUS_VALUES}
    for entry in entries:
        summary[entry['status']] += 1
    return {
        'ledger_type': ledger_type,
        'base_date': today.strftime('%Y-%m-%d'),
        'maintenance_cycles': sorted(selected_cycles),
        'period_labels': {
            'weekly': '%s ~ %s' % (week_start(today).strftime('%Y-%m-%d'),
                                   (week_start(today) + timedelta(days=6)).strftime('%Y-%m-%d')),
            'monthly': '%s年%s月' % (today.year, today.month),
            'seasonal': maintenance_period_text(LEDGER_TYPE_SEASONAL,
                                                current_period_key(LEDGER_TYPE_SEASONAL, 'seasonal', today)),
        },
        'entries': entries,
        'summary': summary,
    }, None


def _validate_template_ids(template_ids):
    """校验模板 ID 清单：非空、全为数字（不去重——Excel 与数字表单两条路线
    的模板主键分属不同表、可能撞号，去重按 (kind, id) 在路线校验后进行）。"""
    if not isinstance(template_ids, (list, tuple)) or not template_ids:
        return None, '至少选择一个可生成模板'
    if any(not str(value).isdigit() for value in template_ids):
        return None, '模板选择参数不合法'
    return [int(value) for value in template_ids], None


# 模板路线（生成确认可按路线选择；缺省全按 Excel 路线，兼容旧调用）
GENERATION_KIND_VALUES = ['excel', 'form']


def _validate_template_kinds(template_kinds, template_ids):
    """校验 template_ids 对应的路线标记（平行数组，缺省补 'excel'）。

    去重按 (kind, id)：两条路线主键空间独立，同号分属不同模板均合法。"""
    if template_kinds is None:
        kinds = ['excel'] * len(template_ids)
    elif isinstance(template_kinds, (list, tuple)) \
            and len(template_kinds) == len(template_ids):
        kinds = []
        for value in template_kinds:
            if value not in GENERATION_KIND_VALUES:
                return None, '模板路线参数不合法：%s' % value
            kinds.append(value)
    else:
        return None, '模板路线参数与模板选择不一致'
    pairs = list(zip(kinds, template_ids))
    if len(set(pairs)) != len(pairs):
        return None, '模板选择参数重复'
    return kinds, None


def _locked_generation_templates(user, ledger_type, selected_ids, selected_kinds):
    """按 (kind, id) 行锁取所选模板，返回 (templates, kinds) 或 (None, None)。

    行锁（select_for_update）串行化同模板并发请求；任一模板不存在/类型
    不匹配/跨租户时整体拒绝。"""
    template_map = {}
    for kind in ('excel', 'form'):
        ids = [tid for tid, k in zip(selected_ids, selected_kinds) if k == kind]
        if not ids:
            continue
        model = (OperationLedgerFormTemplate if kind == 'form'
                 else OperationLedgerExcelTemplate)
        for template in apply_tenant_filter(
                model.objects.filter(pk__in=ids), user
        ).filter(ledger_type=ledger_type).select_related('system') \
                .select_for_update().order_by('id'):
            template_map[(kind, template.id)] = template
    if len(template_map) != len(selected_ids):
        return None, None
    return ([template_map[(kind, tid)]
             for kind, tid in zip(selected_kinds, selected_ids)],
            selected_kinds)


def _collect_generation_context(user, ledger_type, templates, kinds, today):
    """所选模板的槽位/版本/台账占用（生成执行用，与预览同口径）。"""
    slots = []
    for template, kind in zip(templates, kinds):
        period, _, _ = _template_slot(template, ledger_type, today)
        if period is not None:
            slots.append((kind, template.id, template.system_id, period))
    latest = {
        'excel': _latest_versions(
            [t.id for t, k in zip(templates, kinds) if k == 'excel'], kind='excel'),
        'form': _latest_versions(
            [t.id for t, k in zip(templates, kinds) if k == 'form'], kind='form'),
    }
    return latest, _generation_slot_ledgers(user, ledger_type, slots)


def _dispatch_generation_entry(user, template, kind, ledger_type, today, latest,
                               slot_maps, selected_cycles, created, skipped,
                               failed):
    """单模板生成判定与落桶（created/skipped/failed 之一）。"""
    entry = _generation_entry(user, template, ledger_type, today,
                              latest[kind], slot_maps[kind], kind=kind)
    base = {
        'template_kind': kind,
        'template_id': template.id, 'template_name': template.name,
        'system_name': entry['system_name'],
    }
    entry_cycle = _selected_entry_cycles(entry)
    if entry_cycle and entry_cycle not in selected_cycles:
        failed.append({**base, 'status': GENERATE_MANUAL_NEEDED,
                       'reason': '模板维护周期已变化，不属于本次选择的维护周期'})
        return
    if entry['status'] == GENERATE_EXISTS:
        skipped.append({**base,
                        'maintenance_period': entry['maintenance_period'],
                        'period_text': entry['period_text'],
                        'ledger': entry['existing_ledger']})
        return
    if entry['status'] != GENERATE_CREATE:
        failed.append({**base, 'status': entry['status'],
                       'reason': entry['reason']})
        return
    try:
        ledger = _create_generated_ledger(
            user, template, latest[kind][template.id], entry, kind=kind)
    except LedgerValidationError as e:
        failed.append({**base, 'status': GENERATE_MANUAL_NEEDED, 'reason': str(e)})
        return
    created.append({
        **base,
        'id': ledger.id, 'ledger_no': ledger.ledger_no,
        'system_id': ledger.system_id,
        'maintenance_period': entry['maintenance_period'],
        'period_text': entry['period_text'],
        'version_no': entry['version_no'],
    })
    slot_maps[kind].setdefault(
        (kind, template.id, template.system_id, entry['maintenance_period']),
        []).append(ledger)


@transaction.atomic
def period_generate(user, ledger_type, maintenance_cycles=None, template_ids=None,
                    template_kinds=None):
    """生成缺项（确认后执行）：按预览同口径重新计算并创建，返回实际结果。

    - template_ids 为所选模板主键；template_kinds 为对应路线标记平行数组
      （excel/form，缺省全按 excel 兼容旧调用）；
    - 模板行锁（select_for_update）串行化同模板并发请求，锁内重算判定，
      重复点击/并发只能创建一次（唯一约束兜底）；
    - 每条创建走独立保存点，编号冲突（IntegrityError）重算序号重试，
      单条失败不影响其他模板；
    - 结果如实返回 created/skipped/failed，不以预览数量冒充实际结果。
    """
    try:
        validate_ledger_type(ledger_type)
    except LedgerValidationError as e:
        return None, str(e)
    selected_cycles, error = _validate_maintenance_cycles(
        ledger_type, maintenance_cycles, required=True)
    if error:
        return None, error
    selected_ids, error = _validate_template_ids(template_ids)
    if error:
        return None, error
    selected_kinds, error = _validate_template_kinds(template_kinds, selected_ids)
    if error:
        return None, error
    templates, kinds = _locked_generation_templates(
        user, ledger_type, selected_ids, selected_kinds)
    if templates is None:
        return None, '所选模板不存在、类型不匹配或无权访问'
    today = timezone.now().date()
    latest, slot_maps = _collect_generation_context(
        user, ledger_type, templates, kinds, today)
    created, skipped, failed = [], [], []
    for template, kind in zip(templates, kinds):
        _dispatch_generation_entry(
            user, template, kind, ledger_type, today, latest, slot_maps,
            selected_cycles, created, skipped, failed)
    return {
        'ledger_type': ledger_type,
        'created': created,
        'skipped': skipped,
        'failed': failed,
    }, None


@transaction.atomic
def period_generate_rebuild(user, template_id, template_kind='excel'):
    """明确补建（2026-10-16）：为"已作废占用"的本期槽位重新生成应填台账。

    - 仅处理当期（本期）槽位：模板行锁内重算判定；本期已存在有效台账
      （草稿/已完成/旧流程状态）时拒绝；已作废占用或槽位为空时创建；
    - template_kind 选择模板路线（excel/form，缺省 excel 兼容旧调用）；
    - 作废台账保留不动（不删除、不改写），新旧台账并存；
    - 槽位唯一约束以 slot_active 豁免作废行，补建不再被作废记录阻塞。
    返回 (created_row, None) 或 (None, error_message)。
    """
    if not str(template_id or '').isdigit():
        return None, '模板参数不合法'
    if template_kind not in GENERATION_KIND_VALUES:
        return None, '模板路线参数不合法'
    model = (OperationLedgerFormTemplate if template_kind == 'form'
             else OperationLedgerExcelTemplate)
    today = timezone.now().date()
    template = apply_tenant_filter(
        model.objects.filter(is_active=True, pk=int(template_id)), user
    ).select_related('system').select_for_update().first()
    if template is None:
        return None, '模板不存在或已停用'
    period, start, _ = _template_slot(template, template.ledger_type, today)
    if period is None:
        return None, '模板待配置适用系统/生成周期，请先在模板管理中配置'
    latest = _latest_versions([template.id], kind=template_kind)
    version = latest.get(template.id)
    if version is None:
        return None, '缺少可用版本：模板尚未发布任何版本'
    if template.system_id and not template.system.is_active:
        return None, '适用系统已停用，不能用于新台账'
    slot_maps = _generation_slot_ledgers(user, template.ledger_type, [
        (template_kind, template.id, template.system_id, period)])
    status, _, existing = _classify_slot(
        template, template_kind, slot_maps[template_kind], period)
    if status == GENERATE_EXISTS:
        return None, '本期已存在有效台账 %s，无需补建' % existing.ledger_no
    try:
        ledger = _create_generated_ledger(user, template, version, {
            'period_start': start,
            'maintenance_period': period,
        }, kind=template_kind)
    except LedgerValidationError as e:
        return None, str(e)
    return {
        'template_kind': template_kind,
        'id': ledger.id, 'ledger_no': ledger.ledger_no,
        'template_id': template.id, 'template_name': template.name,
        'system_id': ledger.system_id, 'system_name': template.system.name if template.system_id else '',
        'maintenance_period': period,
        'period_text': maintenance_period_text(template.ledger_type, period),
        'version_no': version.version_no,
    }, None


def _type_of_kind_for_query():
    """补建查询按模板自身 ledger_type 过滤（行锁查询内已限定租户与启用状态）。"""
    from apps.equipment_lifecycle.models import (
        LEDGER_TYPE_SEASONAL, LEDGER_TYPE_WEEK_MONTH)
    return LEDGER_TYPE_WEEK_MONTH


def _create_generated_ledger(user, template, version, entry, kind='excel'):
    """创建一张周期生成的应填台账（表头 + 填写记录，固定版本快照）。

    - kind 选择路线：excel 创建 OperationLedgerExcelRecord（含默认值骨架），
      form 创建 OperationLedgerFormRecord（空填写值，直接进入表单填写）；
    - 期次归属由 maintenance_period 标记承载；
    - 台账编号以期次起始日期为基准，创建后不变；
    - 编号序列冲突（同基准日期并发）时重算序号重试（有界）。
    """
    # excel_template_manage / excel_ledger_services 反向依赖本模块，函数内延迟导入
    from apps.equipment_lifecycle.excel_ledger_services import _canonical
    from apps.equipment_lifecycle.excel_template_manage import default_prefill
    base_date = entry['period_start']
    last_error = None
    for _ in range(3):
        try:
            with transaction.atomic():
                common = dict(
                    tenant_id=user.tenant_id,
                    ledger_no=generate_ledger_no(
                        user.tenant_id, template.ledger_type, base_date),
                    ledger_type=template.ledger_type,
                    status=LEDGER_STATUS_DRAFT,
                    entry_channel=ENTRY_CHANNEL_WEB,
                    system=template.system,
                    maintenance_period=entry['maintenance_period'],
                    created_by=user,
                )
                if kind == 'form':
                    ledger = OperationLedger(
                        created_from=LEDGER_FROM_FORM,
                        source_form_template=template, **common)
                    ledger.save()
                    OperationLedgerFormRecord.objects.create(
                        tenant_id=user.tenant_id,
                        ledger=ledger,
                        version=version,
                        values=_canonical({}),
                    )
                else:
                    ledger = OperationLedger(
                        created_from=LEDGER_FROM_EXCEL,
                        source_template=template, **common)
                    ledger.save()
                    OperationLedgerExcelRecord.objects.create(
                        tenant_id=user.tenant_id,
                        ledger=ledger,
                        version=version,
                        values=_canonical(default_prefill(version.get_bindings())),
                    )
                return ledger
        except IntegrityError as e:
            last_error = e
    # 与 ledger_services.create_ledger_row_with_no_retry 同口径：约束细节
    # 只进日志（此为既有文案的历史泄漏，2026-10-26 复核一并净化）
    logger.warning('台账编号唯一约束冲突重试耗尽：%s', last_error)
    raise LedgerValidationError('台账编号生成冲突，请重试')


def _filtered_period_ledger_query(user, ledger_type, status='', system_id=None, keyword=''):
    """周期分组基础查询：租户 + 类型 + 状态/系统/编号筛选。

    状态口径与统一列表一致（apply_ledger_status_filter）：默认视图不含
    已作废，组内统计与可见行保持一致。
    """
    query = apply_tenant_filter(OperationLedger.objects.all(), user).filter(
        ledger_type=ledger_type).select_related(
        'system', 'excel_record__version', 'form_record__version')
    query = apply_ledger_status_filter(query, status)
    if system_id and str(system_id).isdigit():
        query = query.filter(
            Q(items__system_id=system_id) | Q(system_id=system_id)).distinct()
    if keyword:
        query = query.filter(ledger_no__icontains=keyword)
    return query


def _grouped_ledger_views(ledgers, row_serializer):
    """台账行视图按期次分组（组内行含明细计数、期次展示与来源附加字段）。"""
    count_map = {
        row['ledger_id']: row for row in OperationLedgerItem.objects.filter(
            ledger_id__in=[item.id for item in ledgers],
        ).values('ledger_id').annotate(
            items_count=Count('id'),
            abnormal_count=Count('id', filter=Q(result=ITEM_RESULT_ABNORMAL)),
        )
    } if ledgers else {}
    grouped = {}
    for ledger in ledgers:
        view = ledger.to_view()
        count = count_map.get(ledger.id)
        view['items_count'] = count['items_count'] if count else 0
        view['abnormal_count'] = count['abnormal_count'] if count else 0
        view.update(ledger_period_display(ledger))
        if row_serializer is not None:
            view.update(row_serializer(ledger))
        grouped.setdefault(ledger_period_key(ledger), []).append(view)
    return grouped


def _period_group_sort_key(ledger_type, key):
    """组排序键：期次起始日期（无法解析的组键排最后）。"""
    try:
        _, start, _ = parse_maintenance_period(ledger_type, key)
        return start, key
    except LedgerValidationError:
        return date.min, key


def _period_group_entry(ledger_type, key, rows, current_keys):
    """单期次组条目：完整期次标签 + 本期标记 + 状态统计（与可见行一致）。"""
    rows.sort(key=lambda r: (not r['system_name'], r['system_name'], r['id']))
    return {
        'maintenance_period': key,
        'period_text': maintenance_period_label(ledger_type, key),
        'is_current': key in current_keys,
        'total': len(rows),
        'draft': sum(1 for r in rows if r['status'] == LEDGER_STATUS_DRAFT),
        'completed': sum(1 for r in rows if r['status'] == LEDGER_STATUS_COMPLETED),
        'void': sum(1 for r in rows if r['status'] == LEDGER_STATUS_VOID),
        'ledgers': rows,
    }


def list_period_groups(user, ledger_type, status='', system_id=None, keyword='',
                       page=1, page_size=20, row_serializer=None):
    """按周期分组返回台账列表（组内含各系统台账与填写状态，分页按期次组切片）。

    - 分组键 = 维护类型 + 期次标记（maintenance_period，无标记归"未标注期次"）；
    - status/system/keyword 支持筛选：keyword 按台账编号模糊匹配（命中台账
      所在的期次组保留，组内数量与可见行一致）；system 命中表头级系统或明细
      系统；
    - row_serializer(ledger) 由视图层注入（来源字段等展示附加信息）；
    - 组按期次起始日期倒序（无法解析的组键排最后），组内按系统名（空系统
      靠后）+ID 排序；
    - is_current 标记本期组（本周/本月或当前航季），前端默认只展开本期；
    - 组内统计区分 草稿/已完成/已作废 三状态，
      period_text 为完整期次标签（每周｜… / 每月｜… / 航季含起止日期）。
    """
    validate_ledger_type(ledger_type)
    ledgers = list(_filtered_period_ledger_query(
        user, ledger_type, status=status, system_id=system_id, keyword=keyword))
    grouped = _grouped_ledger_views(ledgers, row_serializer)
    current_keys = period_current_keys(ledger_type)
    keys = sorted(
        grouped, key=lambda k: _period_group_sort_key(ledger_type, k), reverse=True)
    data = [
        _period_group_entry(ledger_type, key, grouped[key], current_keys)
        for key in keys
    ]
    page = max(int(page or 1), 1)
    page_size = min(max(int(page_size or 20), 1), 200)
    start = (page - 1) * page_size
    return {
        'data': data[start: start + page_size],
        'total': len(data), 'page': page, 'page_size': page_size,
    }


def _period_ledger_counts(user, ledger_type, period, start, end):
    """指定期次的台账状态统计（与周期分组同口径）。

    期次归属只看表头标记（历史无标记台账已在迁移 0024 回填）。
    """
    query = apply_tenant_filter(OperationLedger.objects.all(), user).filter(
        ledger_type=ledger_type, maintenance_period=period)
    return query.aggregate(
        draft=Count('id', filter=Q(status=LEDGER_STATUS_DRAFT)),
        completed=Count('id', filter=Q(status=LEDGER_STATUS_COMPLETED)),
        void=Count('id', filter=Q(status=LEDGER_STATUS_VOID)),
    )


def period_overview(user, ledger_type):
    """本期工作概览（只读）：周月维护给 本周+本月 两块，季维护给 本航季 一块。

    数量口径（真实数据，不以已有台账冒充应填）：
    - expected 应填 = 本期已配置（适用系统启用且已有发布版本）的模板槽位数，
      即 可自动生成 + 已存在台账 的槽位之和；
    - to_generate 待生成 = 其中尚未生成且可自动生成的槽位（依据模板生成
      规则计算，与 period_generate_preview 同口径）；
    - drafting/completed/void = 本期已有台账的真实状态数量
      （与周期分组同口径，含历史归档台账）；
    - attention 需处理 = 缺少版本/系统停用/作废或历史草稿占用的槽位数；
    - unconfigured_templates = 适用系统或生成周期待配置的模板数。
    """
    try:
        validate_ledger_type(ledger_type)
    except LedgerValidationError as e:
        return None, str(e)
    today = timezone.now().date()
    slots = []
    unconfigured = 0
    latest = {'excel': {}, 'form': {}}
    for kind in ('excel', 'form'):
        templates = list(_generatable_templates(user, ledger_type, kind=kind))
        for template in templates:
            period, start, end = _template_slot(template, ledger_type, today)
            if period is None:
                unconfigured += 1
                continue
            slots.append({'template': template, 'kind': kind, 'period': period,
                          'start': start, 'end': end})
        latest[kind] = _latest_versions(
            [s['template'].id for s in slots if s['kind'] == kind], kind=kind)
    slot_maps = _generation_slot_ledgers(user, ledger_type, [
        (s['kind'], s['template'].id, s['template'].system_id, s['period'])
        for s in slots])
    statuses = {}
    for slot in slots:
        # 复用预览条目判定：包含 缺少版本/系统停用 的槽位状态（与生成口径一致）
        entry = _generation_entry(
            user, slot['template'], ledger_type, today, latest[slot['kind']],
            slot_maps[slot['kind']], kind=slot['kind'])
        statuses.setdefault(slot['period'], []).append(entry['status'])
    if ledger_type == LEDGER_TYPE_SEASONAL:
        block_defs = [('season', '本航季', season_key_of(today))]
    else:
        block_defs = [
            ('week', '本周', week_period_key(today)),
            ('month', '本月', today.strftime('%Y-%m')),
        ]
    blocks = []
    for key, title, period in block_defs:
        _, start, end = parse_maintenance_period(ledger_type, period)
        slot_statuses = statuses.get(period, [])
        counts = _period_ledger_counts(user, ledger_type, period, start, end)
        blocks.append({
            'key': key,
            'title': title,
            'maintenance_period': period,
            'period_label': maintenance_period_label(ledger_type, period),
            'period_start': start.strftime('%Y-%m-%d'),
            'period_end': (end - timedelta(days=1)).strftime('%Y-%m-%d'),
            'expected': sum(1 for s in slot_statuses
                            if s in (GENERATE_CREATE, GENERATE_EXISTS)),
            'to_generate': sum(1 for s in slot_statuses if s == GENERATE_CREATE),
            'drafting': counts['draft'],
            'completed': counts['completed'],
            'voided': counts['void'],
            'attention': sum(1 for s in slot_statuses
                             if s in (GENERATE_NO_VERSION, GENERATE_MANUAL_NEEDED)),
        })
    return {
        'ledger_type': ledger_type,
        'base_date': today.strftime('%Y-%m-%d'),
        'blocks': blocks,
        'unconfigured_templates': unconfigured,
    }, None
