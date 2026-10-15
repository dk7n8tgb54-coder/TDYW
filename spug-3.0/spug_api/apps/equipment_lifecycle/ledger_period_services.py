# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——本期应填台账生成与周期分组服务（2026-10-14 自 ledger_services 迁出）。

- 生成范围：显式配置 适用系统+生成周期 的启用 Excel 模板（一模板一系统，
  同系统可多模板），生成本周/本月/本航季的应填台账并按期次分组查看；
- 期次与去重、生成物形态、日期语义与历史兼容的完整约定见下方章节注释；
- 本模块只承载周期生成与分组查询，台账通用创建/编辑/状态机仍在
  ledger_services（本文件可反向导入，不构成循环）。
"""
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
from apps.equipment_lifecycle.models import (
    ENTRY_CHANNEL_WEB,
    ITEM_RESULT_ABNORMAL,
    LEDGER_FROM_EXCEL,
    LEDGER_FROM_MANUAL,
    LEDGER_STATUS_DRAFT,
    LEDGER_STATUS_RETURNED,
    LEDGER_STATUS_REVIEWED,
    LEDGER_STATUS_SUBMITTED,
    LEDGER_STATUS_VOID,
    LEDGER_TYPE_SEASONAL,
    LEDGER_TYPE_WEEK_MONTH,
    OperationLedger,
    OperationLedgerItem,
)
from apps.equipment_lifecycle.ledger_services import (
    LedgerValidationError,
    generate_ledger_no,
    validate_ledger_type,
)

# ======================================================================
# 本期应填台账生成（2026-10-14 重构原"周期批量新增"：不再创建手工壳）
# ----------------------------------------------------------------------
# - 生成对象 = 已显式配置 适用系统 + 生成周期 的启用 Excel 模板（一模板一
#   系统，同系统可多模板；配置不从模板名称或表格内容推断；历史模板未配置
#   的标记"待配置"，不猜测、不改写历史记录）；
# - 期次键（maintenance_period，计划填写期次）：
#   · 每周模板：本周一日期 YYYY-MM-DD——周一至周日为一个自然周，跨月周只
#     算一个期次，归入周一所在月份，展示完整起止日期；
#   · 每月模板：YYYY-MM（自然月）；
#   · 季维护模板：YYYY-夏秋 / YYYY-冬春（民航航季边界）；
# - 本期 = 以当前日期为基准的当前周/当前月/当前航季，不预建未来期次；
# - 去重：同租户+模板+系统+期次仅一张台账（唯一约束 uniq_el_ledger_tpl_period，
#   MariaDB 无部分唯一索引，非生成路线 source_template 为 NULL 天然豁免；
#   含已作废——作废台账不在一键生成中悄悄重建，预览标记需人工处理）；
#   模板行锁串行化并发，发布新版本/重复点击/并发请求都不重复生成；
# - 生成物 = created_from=excel_template 的正式台账，创建即固定引用模板
#   最新已发布版本快照（OperationLedgerExcelRecord），可直接进入 Excel
#   填写；不再生成没有明细且无法补录的手工草稿；
# - 计划填写期次（maintenance_period）与实际执行日期（executed_date）是
#   不同概念：生成的应填台账 executed_date 为空，由填写人执行后录入
#   （excel_ledger_services.update_header）；台账编号以期次起始日期为基准，
#   创建后不随执行日期改变；
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
# 历史台账无期次标记时按执行日期归档的来源标注（不改写历史记录，也不凭模板名称推断周/月周期）
PERIOD_SOURCE_DERIVED_TEXT = '按实际执行日期归档'
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
    """台账行级期次展示字段（兼容历史台账，不改写历史记录）。

    - 明确期次：表头 maintenance_period 标记 → period_is_derived=False；
    - 历史归档：无标记时按实际执行日期推导（与 ledger_period_key 同口径），
      period_is_derived=True 且 period_source_text 标注来源；
    - 两者皆缺：显示"未标注期次"。
    """
    period = ledger_period_key(ledger)
    if not period:
        return {'period_label': PERIOD_UNMARKED_LABEL, 'period_is_derived': False,
                'period_source_text': '台账缺少期次标记与执行日期'}
    if ledger.maintenance_period:
        return {'period_label': maintenance_period_label(ledger.ledger_type, period),
                'period_is_derived': False, 'period_source_text': ''}
    return {'period_label': maintenance_period_label(ledger.ledger_type, period),
            'period_is_derived': True, 'period_source_text': PERIOD_SOURCE_DERIVED_TEXT}


def ledger_period_key(ledger):
    """台账归属期次：优先表头计划期次标记，历史台账按实际执行日期推导。"""
    if ledger.maintenance_period:
        return ledger.maintenance_period
    executed = ledger.executed_date
    if executed is None:
        return ''
    if ledger.ledger_type == LEDGER_TYPE_SEASONAL:
        # 按航季边界推导：夏秋=3月末周日~10月末周日；冬春=10月末周日~次年3月末周日
        return season_key_of(executed)
    return executed.strftime('%Y-%m')


def _generatable_templates(user, ledger_type, for_update=False):
    """本租户指定类型的启用模板（生成范围；含待配置模板，预览中显式标注）。"""
    query = apply_tenant_filter(
        OperationLedgerExcelTemplate.objects.filter(is_active=True), user,
    ).filter(ledger_type=ledger_type).select_related('system')
    if for_update:
        query = query.select_for_update()
    return query.order_by('id')


def _latest_versions(template_ids):
    """模板 → 最新已发布版本（无发布版本的模板不出现）。

    template_ids 来自已按租户过滤的模板集合，版本随模板租户归属。
    """
    latest = {}
    if not template_ids:
        return latest
    rows = OperationLedgerExcelTemplateVersion.objects.filter(
        template_id__in=template_ids).order_by('template_id', '-version_no')
    for version in rows:
        latest.setdefault(version.template_id, version)
    return latest


def _generation_slot_ledgers(user, ledger_type, slots):
    """批量查询各 (模板, 系统, 期次) 槽位的现有台账（含已作废，用于分类判定）。

    返回 {(template_id, system_id, period): [ledger, ...]}；同时把旧批量
    新增的手工壳（created_from=manual、无模板、同系统同期次）并入同槽位，
    一并占位（不自动改写历史记录，由预览显式标注需人工处理）。
    """
    if not slots:
        return {}
    template_q = Q()
    shell_q = Q()
    for template_id, system_id, period in slots:
        template_q |= Q(source_template_id=template_id, system_id=system_id,
                        maintenance_period=period)
        shell_q |= Q(created_from=LEDGER_FROM_MANUAL, source_template__isnull=True,
                     system_id=system_id, maintenance_period=period)
    rows = apply_tenant_filter(OperationLedger.objects.all(), user).filter(
        Q(ledger_type=ledger_type) & (template_q | shell_q),
    ).select_related('source_template')
    grouped = {}
    for ledger in rows:
        key = (ledger.source_template_id, ledger.system_id, ledger.maintenance_period)
        grouped.setdefault(key, []).append(ledger)
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


def _classify_slot(template, slot_ledgers, period):
    """槽位分类：返回 (status, reason, existing_ledger)。

    判定顺序：本模板有效台账已存在（跳过）→ 历史手工壳占用（需人工处理）
    → 已作废占用（需人工处理，不悄悄重建）→ 可新建。
    手工壳（无模板）以 (None, 系统, 期次) 落桶，与模板槽位合并判定；
    本模板槽位受唯一约束（含已作废），不会同时存在有效与作废两张。
    """
    ledgers = list(slot_ledgers.get((template.id, template.system_id, period)) or [])
    ledgers += slot_ledgers.get((None, template.system_id, period)) or []
    template_valid = [x for x in ledgers
                      if x.source_template_id is not None
                      and x.status != LEDGER_STATUS_VOID]
    if template_valid:
        ledger = sorted(template_valid, key=lambda x: -x.id)[0]
        return GENERATE_EXISTS, '', ledger
    shells = [x for x in ledgers
              if x.source_template_id is None and x.status != LEDGER_STATUS_VOID]
    if shells:
        ledger = sorted(shells, key=lambda x: -x.id)[0]
        return (GENERATE_MANUAL_NEEDED,
                '该系统本期已存在历史草稿台账 %s，请先作废或处理后生成' % ledger.ledger_no,
                ledger)
    voided = [x for x in ledgers if x.status == LEDGER_STATUS_VOID]
    if voided:
        ledger = sorted(voided, key=lambda x: -x.id)[0]
        return (GENERATE_MANUAL_NEEDED,
                '该期次已存在已作废台账 %s，不在一键生成中重建，请通过受控操作处理' % ledger.ledger_no,
                ledger)
    return GENERATE_CREATE, '', None


def _generation_entry(user, template, ledger_type, today, latest, slot_ledgers):
    """单模板本期生成判定（预览与生成共用同一口径）。"""
    entry = {
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
    status, reason, existing = _classify_slot(template, slot_ledgers, period)
    entry['status'] = status
    entry['reason'] = reason
    if existing is not None:
        entry['existing_ledger'] = {
            'id': existing.id, 'ledger_no': existing.ledger_no, 'status': existing.status}
    return entry


def period_generate_preview(user, ledger_type):
    """本期应填台账预览（只读）：逐模板给出当前期次与可生成性判定。

    返回 (result, None) 或 (None, error)。条目状态：create 将新建 /
    exists 已存在跳过 / no_version 缺少可用版本 / manual_needed 需人工处理。
    """
    try:
        validate_ledger_type(ledger_type)
    except LedgerValidationError as e:
        return None, str(e)
    today = timezone.now().date()
    templates = list(_generatable_templates(user, ledger_type))
    slots = []
    for template in templates:
        period, start, _ = _template_slot(template, ledger_type, today)
        if period is not None:
            slots.append((template.id, template.system_id, period))
    latest = _latest_versions([t.id for t in templates])
    slot_ledgers = _generation_slot_ledgers(user, ledger_type, slots)
    entries = [
        _generation_entry(user, t, ledger_type, today, latest, slot_ledgers)
        for t in templates
    ]
    summary = {status: 0 for status in GENERATE_STATUS_VALUES}
    for entry in entries:
        summary[entry['status']] += 1
    return {
        'ledger_type': ledger_type,
        'base_date': today.strftime('%Y-%m-%d'),
        'entries': entries,
        'summary': summary,
    }, None


@transaction.atomic
def period_generate(user, ledger_type):
    """生成缺项（确认后执行）：按预览同口径重新计算并创建，返回实际结果。

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
    today = timezone.now().date()
    templates = list(_generatable_templates(user, ledger_type, for_update=True))
    slots = []
    for template in templates:
        period, start, _ = _template_slot(template, ledger_type, today)
        if period is not None:
            slots.append((template.id, template.system_id, period))
    latest = _latest_versions([t.id for t in templates])
    slot_ledgers = _generation_slot_ledgers(user, ledger_type, slots)
    created, skipped, failed = [], [], []
    for template in templates:
        entry = _generation_entry(user, template, ledger_type, today, latest, slot_ledgers)
        if entry['status'] == GENERATE_EXISTS:
            skipped.append({
                'template_id': template.id, 'template_name': template.name,
                'system_name': entry['system_name'],
                'maintenance_period': entry['maintenance_period'],
                'period_text': entry['period_text'],
                'ledger': entry['existing_ledger'],
            })
            continue
        if entry['status'] != GENERATE_CREATE:
            failed.append({
                'template_id': template.id, 'template_name': template.name,
                'system_name': entry['system_name'],
                'status': entry['status'],
                'reason': entry['reason'],
            })
            continue
        try:
            ledger = _create_generated_ledger(user, template, latest[template.id], entry)
        except LedgerValidationError as e:
            failed.append({
                'template_id': template.id, 'template_name': template.name,
                'system_name': entry['system_name'],
                'status': GENERATE_MANUAL_NEEDED, 'reason': str(e)})
            continue
        row = {
            'id': ledger.id, 'ledger_no': ledger.ledger_no,
            'template_id': template.id, 'template_name': template.name,
            'system_id': ledger.system_id, 'system_name': entry['system_name'],
            'maintenance_period': entry['maintenance_period'],
            'period_text': entry['period_text'],
            'version_no': entry['version_no'],
        }
        created.append(row)
        slot_ledgers.setdefault(
            (template.id, template.system_id, entry['maintenance_period']), []
        ).append(ledger)
    return {
        'ledger_type': ledger_type,
        'created': created,
        'skipped': skipped,
        'failed': failed,
    }, None


def _create_generated_ledger(user, template, version, entry):
    """创建一张周期生成的 Excel 应填台账（表头 + 填写记录，固定版本快照）。

    - executed_date 留空（计划填写期次 ≠ 实际执行日期，执行后由填写人录入）；
    - 台账编号以期次起始日期为基准，创建后不随执行日期改变；
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
                ledger = OperationLedger(
                    tenant_id=user.tenant_id,
                    ledger_no=generate_ledger_no(
                        user.tenant_id, template.ledger_type, base_date),
                    ledger_type=template.ledger_type,
                    executed_date=None,
                    status=LEDGER_STATUS_DRAFT,
                    entry_channel=ENTRY_CHANNEL_WEB,
                    created_from=LEDGER_FROM_EXCEL,
                    system=template.system,
                    source_template=template,
                    maintenance_period=entry['maintenance_period'],
                    created_by=user,
                )
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
    raise LedgerValidationError('台账编号生成冲突，请重试（%s）' % last_error)


def _filtered_period_ledger_query(user, ledger_type, status='', system_id=None, keyword=''):
    """周期分组基础查询：租户 + 类型 + 状态/系统/编号筛选。"""
    query = apply_tenant_filter(OperationLedger.objects.all(), user).filter(
        ledger_type=ledger_type).select_related('system', 'excel_record__version')
    if status:
        query = query.filter(status=status)
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
    """单期次组条目：完整期次标签 + 本期标记 + 五状态统计（与可见行一致）。"""
    rows.sort(key=lambda r: (not r['system_name'], r['system_name'], r['id']))
    return {
        'maintenance_period': key,
        'period_text': maintenance_period_label(ledger_type, key),
        'is_current': key in current_keys,
        'total': len(rows),
        'draft': sum(1 for r in rows if r['status'] == LEDGER_STATUS_DRAFT),
        'returned': sum(1 for r in rows if r['status'] == LEDGER_STATUS_RETURNED),
        'submitted': sum(1 for r in rows if r['status'] == LEDGER_STATUS_SUBMITTED),
        'reviewed': sum(1 for r in rows if r['status'] == LEDGER_STATUS_REVIEWED),
        'void': sum(1 for r in rows if r['status'] == LEDGER_STATUS_VOID),
        'ledgers': rows,
    }


def list_period_groups(user, ledger_type, status='', system_id=None, keyword='',
                       page=1, page_size=20, row_serializer=None):
    """按周期分组返回台账列表（组内含各系统台账与填写状态，分页按期次组切片）。

    - 分组键 = 维护类型 + 周期（周期优先取表头标记，历史台账按执行日期推导）；
    - status/system/keyword 支持筛选：keyword 按台账编号模糊匹配（命中台账
      所在的期次组保留，组内数量与可见行一致）；system 命中表头级系统或明细
      系统；
    - row_serializer(ledger) 由视图层注入（来源字段等展示附加信息）；
    - 组按期次起始日期倒序（无法解析的组键排最后），组内按系统名（空系统
      靠后）+ID 排序；
    - is_current 标记本期组（本周/本月或当前航季），前端默认只展开本期；
    - 组内统计区分 草稿/已退回/已提交/已复核/已作废 五状态，
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
    """指定期次的台账状态统计（与周期分组同口径，历史台账兼容）。

    显式期次标记直接命中；无标记的历史台账按执行日期落在 [start, end)
    归档（与 ledger_period_key 推导一致）；每周键无执行日期推导路径，
    仅按标记命中（与分组展示一致）。
    """
    query = apply_tenant_filter(OperationLedger.objects.all(), user).filter(
        ledger_type=ledger_type)
    if PERIOD_WEEK_RE.match(period):
        query = query.filter(maintenance_period=period)
    else:
        query = query.filter(
            Q(maintenance_period=period) |
            (Q(maintenance_period='') & Q(executed_date__gte=start)
             & Q(executed_date__lt=end)))
    return query.aggregate(
        draft=Count('id', filter=Q(status=LEDGER_STATUS_DRAFT)),
        returned=Count('id', filter=Q(status=LEDGER_STATUS_RETURNED)),
        submitted=Count('id', filter=Q(status=LEDGER_STATUS_SUBMITTED)),
        reviewed=Count('id', filter=Q(status=LEDGER_STATUS_REVIEWED)),
        void=Count('id', filter=Q(status=LEDGER_STATUS_VOID)),
    )


def period_overview(user, ledger_type):
    """本期工作概览（只读）：周月维护给 本周+本月 两块，季维护给 本航季 一块。

    数量口径（真实数据，不以已有台账冒充应填）：
    - expected 应填 = 本期已配置（适用系统启用且已有发布版本）的模板槽位数，
      即 可自动生成 + 已存在台账 的槽位之和；
    - to_generate 待生成 = 其中尚未生成且可自动生成的槽位（依据模板生成
      规则计算，与 period_generate_preview 同口径）；
    - drafting/returned/completed/void = 本期已有台账的真实状态数量
      （completed = 已提交 + 已复核；与周期分组同口径，含历史归档台账）；
    - attention 需处理 = 缺少版本/系统停用/作废或历史草稿占用的槽位数；
    - unconfigured_templates = 适用系统或生成周期待配置的模板数。
    """
    try:
        validate_ledger_type(ledger_type)
    except LedgerValidationError as e:
        return None, str(e)
    today = timezone.now().date()
    templates = list(_generatable_templates(user, ledger_type))
    slots = []
    unconfigured = 0
    for template in templates:
        period, start, end = _template_slot(template, ledger_type, today)
        if period is None:
            unconfigured += 1
            continue
        slots.append({'template': template, 'period': period,
                      'start': start, 'end': end})
    latest = _latest_versions([s['template'].id for s in slots])
    slot_ledgers = _generation_slot_ledgers(user, ledger_type, [
        (s['template'].id, s['template'].system_id, s['period']) for s in slots])
    statuses = {}
    for slot in slots:
        # 复用预览条目判定：包含 缺少版本/系统停用 的槽位状态（与生成口径一致）
        entry = _generation_entry(
            user, slot['template'], ledger_type, today, latest, slot_ledgers)
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
            'returned': counts['returned'],
            'completed': counts['submitted'] + counts['reviewed'],
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
