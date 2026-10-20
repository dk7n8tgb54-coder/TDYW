# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——Excel 模板管理服务（上传/草稿/绑定/发布/版本，2026-09-28）。

- 上传即解析：不支持的文件特性（公式/图表/图片/外部链接/透视表）显式
  拒绝并逐项列出，绝不静默丢失后提示导入成功；仅支持固定行列、固定
  填写位置的 .xlsx（动态增行/公式/宏/图表/Word 模板不支持）；
- 草稿：源文件落盘（excel_template_storage）+ 布局 meta 落库；重新上传
  源文件后布局重建、原绑定清空（坐标可能已失效，不允许残留）；
- 绑定：validate_bindings 全量校验后整体替换落库；
- 发布：发布级校验（源文件哈希一致 + 绑定 ≥1）→ 草稿文件复制为版本
  文件 → 快照落库；version_no 模板内 select_for_update 串行递增，
  (template, version_no) 唯一约束兜底；版本文件与绑定不可变（无修改/
  删除路径）；孤儿版本文件（写文件成功后事务回滚）以「同号同哈希幂等
  复用」消化，不阻塞重试发布；
- 停用/删除（2026-10-16 拆分）：停用=逻辑停用（is_active=False），不删
  任何记录与文件，可用模板接口不再返回、新台账拒绝使用，历史版本与
  历史台账全部保留（幂等）；删除=物理删除（未发布模板、已发布且所有
  版本均未被台账引用的模板），删除时在行锁内重新检查引用关系，版本
  文件随行删除；被引用（含已作废台账引用）的模板只能停用；
- 重新启用（2026-10-19）：停用的逆操作（is_active=True，幂等），恢复
  可用模板接口返回与本期应填台账自动生成参与资格；停用期间版本、
  草稿与历史台账原样保留，启用不改动任何数据；
- 草稿 PDF 预览：以草稿源文件为事实生成空白预览（未填写字段留空），
  只读不改草稿、不创建版本；LibreOffice 不可用时明确业务错误；
- 预览反馈（2026-10-19）：preview_template_pdf 支持未保存打印参数与
  临时样例值（均只作用于本次预览副本），返回真实页数/纸张尺寸
  （pypdf 读取生成 PDF）与版式预检提示，供"应用当前设置并预览"；
- 兼容性检查：模板详情返回草稿文件/哈希/不支持特性/打印区域/LibreOffice
  环境的检查结果（status: ok/warning/error），error 对齐发布自身会拒绝
  的条件，不新增阻断口径；
- PDF 打印参数（2026-09-30）：模板级参数保存在草稿布局 JSON 的
  pdf_params 键（零迁移），发布随版本快照固定，历史台账导出继续使用
  创建时版本参数；导出接口可显式传入覆盖参数（仅当次生效）；
- 模板四态（2026-09-30）：draft/published/used/deleted 由
  is_active + 已发布版本 + 引用台账数推导，列表与详情统一返回；
- 生成配置（2026-10-14）：适用系统（一模板一系统）+ 生成周期（按台账
  类型收敛）整体校验后落库；空值显式清空回"待配置"，不做自动推断；
  配置只影响本期应填台账自动生成（ledger_period_services），不影响
  手工创建，已生成台账不回溯；
- 历史台账经 OperationLedgerExcelRecord 继续引用创建时版本。

业务错误统一抛 ExcelTemplateError，View 层转 json_response(error=...)。
"""
import hashlib
import json
import os

from django.db import transaction
from django.db.models import Count, Max
from django.utils import timezone

from libs.tenant_utils import apply_tenant_filter

from apps.equipment_lifecycle import excel_pdf_service, excel_template_storage
from apps.equipment_lifecycle.excel_models import (
    TEMPLATE_PERIOD_BY_LEDGER_TYPE,
    TEMPLATE_PERIOD_MONTHLY,
    TEMPLATE_PERIOD_SEASONAL,
    TEMPLATE_PERIOD_TEXT,
    TEMPLATE_PERIOD_WEEKLY,
    OperationLedgerExcelTemplate,
    OperationLedgerExcelTemplateVersion,
)
from apps.equipment_lifecycle.excel_pdf_params import (
    estimate_pdf_warnings,
    validate_pdf_params,
)
from apps.equipment_lifecycle.excel_template_services import (
    ExcelLayoutError,
    assess_compatibility,
    collect_unsupported_features,
    describe_unsupported_features,
    main_sheet_size,
    parse_workbook,
    preview_blank_pdf,
    preview_pdf,
    refresh_column_layout,
    validate_bindings,
    validate_values,
)
from apps.equipment_lifecycle.ledger_services import (
    LedgerValidationError,
    validate_ledger_type,
)

PROTOCOL_VERSION = 1


class ExcelTemplateError(Exception):
    """Excel 模板业务校验错误（View 层转业务错误响应）。"""


def _fail(message):
    raise ExcelTemplateError(message)


def _canonical(data):
    return json.dumps(data, ensure_ascii=False, separators=(',', ':'))


def _layout_part(meta):
    """布局 meta 中需落库的部分（文件名/哈希单独存列，绑定独立变更）。"""
    return {
        'sheet_name': meta['sheet_name'],
        'layout': meta['layout'],
        'pdf_params': meta.get('pdf_params') or {},
        'protocol_version': meta['protocol_version'],
    }


def get_excel_template(pk, user, for_update=False):
    """按租户取模板；不存在返回 None（跨租户与不存在不区分，避免探测）。"""
    query = apply_tenant_filter(OperationLedgerExcelTemplate.objects.all(), user)
    if for_update:
        query = query.select_for_update()
    return query.filter(pk=pk).first()


def get_version(version_id, user):
    """按租户取已发布版本；不存在返回 None。"""
    query = apply_tenant_filter(OperationLedgerExcelTemplateVersion.objects.all(), user)
    return query.select_related('template').filter(pk=version_id).first()


def _validate_template_meta(body):
    name = str(body.get('name') or '').strip()
    if not name:
        _fail('模板名称不能为空')
    if len(name) > 100:
        _fail('模板名称超过长度限制')
    ledger_type = body.get('ledger_type')
    try:
        validate_ledger_type(ledger_type)
    except LedgerValidationError as e:
        _fail(str(e))
    description = str(body.get('description') or '').strip()
    if len(description) > 500:
        _fail('模板说明超过长度限制')
    return name, ledger_type, description


def _check_unsupported(filename, data):
    if not filename or not filename.lower().endswith('.xlsx'):
        _fail('仅支持 .xlsx 文件（暂不支持 .xls、.doc/.docx 与 WPS 私有格式）')
    if len(data) > 10 * 1024 * 1024:
        _fail('文件超过 10MB 限制')
    features = collect_unsupported_features(data)
    if features:
        _fail('模板包含平台暂不支持的特性：%s（请改为固定值或删除后重新上传）'
              % describe_unsupported_features(features))


def _parse_or_fail(filename, data):
    try:
        return parse_workbook(filename, data)
    except ExcelLayoutError as e:
        _fail(str(e))


def create_template(user, filename, data, body):
    """上传 .xlsx 创建模板：特性检测 → 解析 → 草稿文件落盘 → 模板落库。"""
    name, ledger_type, description = _validate_template_meta(body)
    _check_unsupported(filename, data)
    meta = _parse_or_fail(filename, data)
    with transaction.atomic():
        template = OperationLedgerExcelTemplate.objects.create(
            tenant_id=user.tenant_id,
            name=name,
            ledger_type=ledger_type,
            description=description,
            draft_source_filename=meta['source_filename'],
            draft_source_hash=meta['source_file_hash'],
            draft_layout=_canonical(_layout_part(meta)),
            draft_bindings='',
            draft_updated_at=timezone.now(),
            draft_updated_by=user,
            created_by=user,
        )
        excel_template_storage.write_draft(template.pk, data)
    return template


def replace_draft_file(user, template, filename, data):
    """重新上传草稿源文件：布局重建，原绑定清空（坐标可能已失效）。"""
    if not template.is_active:
        _fail('模板已删除（停用），不能重新上传源文件')
    _check_unsupported(filename, data)
    meta = _parse_or_fail(filename, data)
    with transaction.atomic():
        excel_template_storage.write_draft(template.pk, data)
        template.draft_source_filename = meta['source_filename']
        template.draft_source_hash = meta['source_file_hash']
        template.draft_layout = _canonical(_layout_part(meta))
        template.draft_bindings = ''
        template.draft_updated_at = timezone.now()
        template.draft_updated_by = user
        template.updated_at = timezone.now()
        template.updated_by = user
        template.save(update_fields=[
            'draft_source_filename', 'draft_source_hash', 'draft_layout',
            'draft_bindings', 'draft_updated_at', 'draft_updated_by',
            'updated_at', 'updated_by'])
    return template


def save_bindings(user, template, bindings):
    """保存字段绑定（整体替换，全量校验通过才落库）。"""
    if not template.is_active:
        _fail('模板已删除（停用），不能修改字段绑定')
    if template.draft_layout:
        meta = _draft_meta(template)
    else:
        _fail('模板尚无源文件草稿，请先上传 .xlsx')
    try:
        normalized = validate_bindings(meta, bindings)
    except ExcelLayoutError as e:
        _fail(str(e))
    with transaction.atomic():
        template.draft_bindings = _canonical(normalized)
        template.draft_updated_at = timezone.now()
        template.draft_updated_by = user
        template.updated_at = timezone.now()
        template.updated_by = user
        template.save(update_fields=[
            'draft_bindings', 'draft_updated_at', 'draft_updated_by',
            'updated_at', 'updated_by'])
    return template


def save_pdf_params(user, template, raw_params):
    """保存模板级 PDF 打印参数（草稿级，发布时随版本快照固定）。

    校验通过后整体替换 draft_layout 内的 pdf_params 键（布局/绑定不变）；
    重复表头行、手动分页行与打印区域按主工作表尺寸校验越界。
    """
    if not template.is_active:
        _fail('模板已删除（停用），不能修改 PDF 参数')
    if not template.draft_layout:
        _fail('模板尚无源文件草稿，请先上传 .xlsx')
    meta = _draft_meta(template)
    max_row, max_column = _draft_main_sheet_size(meta)
    try:
        params = validate_pdf_params(raw_params, max_row=max_row,
                                     max_column=max_column)
    except ExcelLayoutError as e:
        _fail(str(e))
    with transaction.atomic():
        part = json.loads(template.draft_layout)
        part['pdf_params'] = params
        template.draft_layout = _canonical(part)
        template.draft_updated_at = timezone.now()
        template.draft_updated_by = user
        template.updated_at = timezone.now()
        template.updated_by = user
        template.save(update_fields=[
            'draft_layout', 'draft_updated_at', 'draft_updated_by',
            'updated_at', 'updated_by'])
    return template


def _draft_main_sheet_size(meta):
    """主工作表 (行数, 列数)（PDF 分页/打印区域越界校验；缺失返回 None 不校验）。"""
    return main_sheet_size(meta)


def _draft_meta(template):
    """草稿布局 meta（含文件名/哈希，供绑定校验与导出组装）。"""
    try:
        part = json.loads(template.draft_layout)
    except (ValueError, TypeError):
        _fail('模板草稿内容损坏，请重新上传源文件')
    if not isinstance(part, dict) or 'layout' not in part:
        _fail('模板草稿内容损坏，请重新上传源文件')
    return {
        'source_filename': template.draft_source_filename,
        'source_file_hash': template.draft_source_hash,
        'sheet_name': part.get('sheet_name'),
        'layout': part.get('layout'),
        'field_bindings': [],
        'sample_values': {},
        'pdf_params': part.get('pdf_params') or {},
        'protocol_version': part.get('protocol_version', PROTOCOL_VERSION),
    }


def _ensure_version_file(template_id, version_no, expected_hash):
    """版本文件就位：不存在则从草稿复制；已存在（孤儿文件）须哈希一致。"""
    target = excel_template_storage.version_path(template_id, version_no)
    if os.path.exists(target):
        with open(target, 'rb') as f:
            if hashlib.sha256(f.read()).hexdigest() != expected_hash:
                _fail('模板版本文件冲突，请重试发布')
        return target
    try:
        return excel_template_storage.publish_draft_to_version(template_id, version_no)
    except FileNotFoundError:
        _fail('模板草稿源文件丢失，请重新上传后再发布')


@transaction.atomic
def publish_version(user, template):
    """发布：校验 → 复制版本文件 → 快照落库（版本不可变，只增不改）。"""
    locked = get_excel_template(template.pk, user, for_update=True)
    if locked is None:
        _fail('Excel台账模板不存在')
    if not locked.is_active:
        _fail('模板已删除（停用），不能发布新版本')
    if not locked.draft_layout or not locked.draft_source_hash:
        _fail('当前没有可发布的草稿，请先上传 .xlsx 源文件')
    bindings = json.loads(locked.draft_bindings) if locked.draft_bindings else []
    if not bindings:
        _fail('请先绑定至少一个可填写字段再发布')
    draft_path = excel_template_storage.draft_path(locked.pk)
    if not os.path.isfile(draft_path):
        _fail('模板草稿源文件丢失，请重新上传后再发布')
    with open(draft_path, 'rb') as f:
        draft_hash = hashlib.sha256(f.read()).hexdigest()
    if draft_hash != locked.draft_source_hash:
        _fail('草稿源文件与登记哈希不一致，请重新上传后再发布')
    latest_no = locked.versions.aggregate(max_no=Max('version_no'))['max_no'] or 0
    version_no = latest_no + 1
    _ensure_version_file(locked.pk, version_no, draft_hash)
    version = OperationLedgerExcelTemplateVersion.objects.create(
        tenant_id=user.tenant_id,
        template=locked,
        version_no=version_no,
        template_name_snapshot=locked.name,
        source_filename=locked.draft_source_filename,
        source_hash=draft_hash,
        layout=locked.draft_layout,
        bindings=_canonical(bindings),
        field_count=len(bindings),
        published_by=user,
    )
    locked.updated_at = timezone.now()
    locked.updated_by = user
    locked.save(update_fields=['updated_at', 'updated_by'])
    return version


def deactivate_template(user, template):
    """停用模板（逻辑停用）：is_active=False，不删任何记录与物理文件。

    - 停用后：可用模板接口不再返回、新台账拒绝使用、草稿重传/绑定/
      发布入口被拦截；版本快照、版本源文件、字段绑定与历史台账全部
      保留（历史台账继续按创建时版本查看与导出）；
    - 幂等：已停用再次调用直接返回，不重复变更；
    - 返回 (template, deactivated_now)，deactivated_now 标记本次是否实际
      发生变更（View 层据此决定是否记录审计事件）。
    """
    if not template.is_active:
        return template, False
    template.is_active = False
    template.updated_at = timezone.now()
    template.updated_by = user
    template.save(update_fields=['is_active', 'updated_at', 'updated_by'])
    return template, True


def activate_template(user, template):
    """重新启用模板（停用的逆操作）：is_active=True，幂等。

    - 启用后恢复可用模板接口返回与本期应填台账自动生成参与资格，
      可用于新台账；停用期间版本、草稿与历史台账原样保留，启用不做
      任何数据变更；
    - 幂等：已启用再次调用直接返回，不重复变更；
    - 返回 (template, activated_now)，activated_now 标记本次是否实际
      发生变更（View 层据此决定是否记录审计事件）。
    """
    if template.is_active:
        return template, False
    template.is_active = True
    template.updated_at = timezone.now()
    template.updated_by = user
    template.save(update_fields=['is_active', 'updated_at', 'updated_by'])
    return template, True


def template_ledger_reference_count(template):
    """统计引用模板任意版本的台账数（含已作废——作废台账仍需查看/导出，
    其版本快照不可消失，因此同样阻止物理删除）。"""
    return template.versions.aggregate(
        total=Count('ledger_records', distinct=True))['total'] or 0


@transaction.atomic
def destroy_template(user, template):
    """物理删除模板（含版本与文件）：删除时重新检查引用关系。

    - 引用检查在行锁内重新执行，不依赖前端隐藏按钮：任一版本仍被台账
      填写记录（OperationLedgerExcelRecord）引用（含已作废台账）时拒绝，
      避免历史台账详情/导出因版本消失而损坏；
    - 未发布模板（无版本）与已发布但无引用的模板可删除；
    - 数据库行删除（版本级联）提交后再删除物理文件（草稿 + 各版本），
      文件删除失败仅遗留磁盘孤儿文件，不产生悬挂数据库引用；
    - 幂等保护：传入已不存在的模板由 View 层"模板不存在"拦截。
    返回 (template, version_count)。
    """
    locked = get_excel_template(template.pk, user, for_update=True)
    if locked is None:
        _fail('Excel台账模板不存在')
    refs = template_ledger_reference_count(locked)
    if refs:
        _fail('模板已被 %s 个台账引用（含已作废），不能删除；如需停止使用请改为停用'
              % refs)
    version_count = locked.versions.count()
    info = {'id': locked.pk, 'name': locked.name, 'versions_count': version_count}
    draft_path = excel_template_storage.draft_path(locked.pk) \
        if locked.draft_source_filename else None
    version_paths = [
        excel_template_storage.version_path(locked.pk, v.version_no)
        for v in locked.versions.all()]
    locked.delete()
    transaction.on_commit(lambda: _remove_template_files(draft_path, version_paths))
    return info


def _remove_template_files(draft_path, version_paths):
    """物理删除模板草稿与版本文件（尽力而为；文件缺失视为已清理）。

    数据库行已提交删除后执行：失败仅遗留磁盘孤儿文件（无引用、无危害），
    不产生"数据库记录指向已删除文件"的悬挂状态。
    """
    for path in ([draft_path] if draft_path else []) + version_paths:
        try:
            if path and os.path.isfile(path):
                os.remove(path)
        except OSError:
            continue


def preview_draft_pdf(template):
    """模板草稿 PDF 预览：未填写字段保持空白的最终版式基准。

    - 只读草稿源文件与草稿布局：不改草稿文件、不写库、不创建版本、
      不改变字段绑定；转换在临时目录进行，结束自动清理；
    - 转换前经布局校验与打印区域净化（与台账导出同一 prepare 路径），
      残留空打印区域不会生成整份空白 PDF；
    - LibreOffice 不可用/转换失败转业务错误，绝不返回伪造 PDF。
    """
    if not template.draft_layout or not template.draft_source_hash:
        _fail('当前没有可预览的草稿，请先上传 .xlsx 源文件')
    draft_path = excel_template_storage.draft_path(template.pk)
    if not os.path.isfile(draft_path):
        _fail('模板草稿源文件丢失，请重新上传后再预览')
    try:
        return preview_blank_pdf(_draft_meta(template), draft_path)
    except ExcelLayoutError as e:
        _fail(str(e))
    except excel_pdf_service.PdfConversionError as e:
        _fail(str(e))


def preview_template_pdf(template, raw_params=None, raw_values=None):
    """模板预览 PDF（可携带未保存参数与临时样例值，全部只作用于本次）。

    - raw_params 为打印设置表单当前值（可含未保存修改）：整体校验后仅
      本次预览生效，不写草稿；未传时使用草稿已保存参数（与既有空白
      预览一致）；
    - raw_values 为临时样例值（键为 field_id）：validate_values 校验
      （未知 field_id 拒绝、按字段类型归一化）后只写入预览副本，不写
      数据库、不改模板源文件、不影响发布与已有台账；空值生成空白版式；
    - 返回 {'content', 'pages', 'paper', 'warnings'}：页数与纸张来自
      真实生成的 PDF（pypdf 读取第 1 页），warnings 复用导出版式预检
      （estimate_pdf_warnings，预览不检查必填），依据实际参数估算，
      不伪造预览结果。
    """
    if not template.draft_layout or not template.draft_source_hash:
        _fail('当前没有可预览的草稿，请先上传 .xlsx 源文件')
    if raw_values is not None and not isinstance(raw_values, dict):
        _fail('预览数据必须是对象')
    draft_path = excel_template_storage.draft_path(template.pk)
    if not os.path.isfile(draft_path):
        _fail('模板草稿源文件丢失，请重新上传后再预览')
    meta = _draft_meta(template)
    meta['field_bindings'] = (
        json.loads(template.draft_bindings) if template.draft_bindings else [])
    try:
        values = validate_values(meta['field_bindings'], raw_values)
        content = preview_pdf(meta, draft_path, values=values,
                              pdf_params=raw_params)
    except ExcelLayoutError as e:
        _fail(str(e))
    except excel_pdf_service.PdfConversionError as e:
        _fail(str(e))
    effective = raw_params if raw_params is not None else meta.get('pdf_params')
    warnings = estimate_pdf_warnings(meta, values, effective, check_required=False)
    info = excel_pdf_service.pdf_page_info(content)
    return {'content': content, 'pages': info['pages'],
            'paper': info['paper'], 'warnings': warnings}


def draft_compatibility(template):
    """草稿兼容性检查结果（模板详情返回；无草稿返回 None）。

    - 文件维度：草稿文件存在性、登记哈希一致性、不支持特性、打印区域
      覆盖（单次解析）；
    - 环境维度：LibreOffice 可用性（缺失仅影响 PDF 预览/导出，属
      warning 不阻断发布）；
    - status: ok | warning | error（error 对齐发布/预览自身会拒绝的
      条件：文件缺失/哈希不一致/含不支持特性，不新增阻断口径）。
    """
    if not template.draft_layout or not template.draft_source_hash:
        return None
    result = _file_compatibility(template)
    if not excel_pdf_service.detect_soffice():
        result['warnings'].append(
            '部署环境未安装 LibreOffice，PDF 预览与导出不可用'
            '（请安装 libreoffice-calc 与中文字体）')
        if result['status'] == 'ok':
            result['status'] = 'warning'
    return result


def _file_compatibility(template):
    """文件维度兼容性检查（读草稿文件一次，异常全部转为结构化结果）。"""
    draft_path = excel_template_storage.draft_path(template.pk)
    if not os.path.isfile(draft_path):
        return {'status': 'error',
                'warnings': ['草稿源文件丢失，请重新上传后再发布或预览'],
                'unsupported': []}
    with open(draft_path, 'rb') as f:
        data = f.read()
    if hashlib.sha256(data).hexdigest() != template.draft_source_hash:
        return {'status': 'error',
                'warnings': ['草稿源文件与登记哈希不一致，请重新上传源文件'],
                'unsupported': []}
    result = assess_compatibility(data)
    if result['unsupported']:
        result['warnings'].append(
            '包含平台暂不支持的特性：%s（发布与 PDF 转换不可用，请处理后重新上传）'
            % '、'.join(result['unsupported']))
    return result


def _version_meta(version):
    """由版本快照组装导出用 meta（布局 + 绑定 + PDF 参数 + 文件定位）。

    布局经读取端列宽修正：导出本身以源文件为事实不受影响，导出预检
    （estimate_pdf_warnings）按修正后列宽估算内容宽度。
    """
    part = version.get_layout()
    return {
        'source_filename': version.source_filename,
        'source_file_hash': version.source_hash,
        'sheet_name': part.get('sheet_name'),
        'layout': _corrected_version_layout(version),
        'field_bindings': version.get_bindings(),
        'sample_values': {},
        'pdf_params': part.get('pdf_params') or {},
        'protocol_version': part.get('protocol_version', PROTOCOL_VERSION),
    }


def version_source_path(version):
    path = excel_template_storage.version_path(version.template_id, version.version_no)
    if not os.path.isfile(path):
        _fail('模板版本源文件缺失，请联系管理员')
    return path


def _corrected_version_layout(version):
    """版本布局快照的读取端列宽修正（快照不可变，仅修读取视图）。

    历史快照由旧解析逻辑生成：<col min="1" max="3"> 范围只落在起始列，
    其余列被误记为 openpyxl 缺省宽度 13、隐藏范围漏报，网页按快照渲染
    会把范围列画窄。以版本源文件为准重新推导 column_widths/
    hidden_columns；源文件缺失等异常原样返回快照，不影响详情与导出
    （导出另有源文件校验）。详见 excel_template_services.refresh_column_layout。
    """
    layout = version.get_layout().get('layout') or {}
    try:
        path = version_source_path(version)
    except ExcelTemplateError:
        return layout
    return refresh_column_layout(layout, path)


def version_content_view(version):
    """版本详情视图（含布局与绑定快照；布局经读取端列宽修正）。

    台账详情与版本详情接口共用，历史台账据此以正确列宽回放版式。
    """
    view = version.to_view(with_content=True)
    view['layout'] = _corrected_version_layout(version)
    return view


def draft_meta_view(template):
    """草稿布局+绑定视图（前端绑定工作区数据源）；无草稿返回 None。

    布局经读取端列宽修正（历史草稿 <col min max> 范围只记起始列），
    工作区按正确列宽渲染；草稿文件缺失/解析失败时原样返回快照。
    """
    if not template.draft_layout:
        return None
    meta = _draft_meta(template)
    return {
        'sheet_name': meta['sheet_name'],
        'layout': refresh_column_layout(
            meta['layout'], excel_template_storage.draft_path(template.pk)),
        'field_bindings': json.loads(template.draft_bindings) if template.draft_bindings else [],
        'pdf_params': meta.get('pdf_params') or {},
        'source_filename': template.draft_source_filename,
        'source_hash': template.draft_source_hash,
        'draft_updated_at': template.draft_updated_at,
        'draft_updated_by': template.draft_updated_by.nickname
        if template.draft_updated_by else '',
    }


def _template_summary(template, latest_version_no=None, versions_count=None,
                      ledgers_count=None):
    return template.to_view(
        latest_version_no=latest_version_no, versions_count=versions_count,
        ledgers_count=ledgers_count)


def list_templates(user):
    query = apply_tenant_filter(OperationLedgerExcelTemplate.objects.all(), user)
    query = query.annotate(
        latest_version_no=Max('versions__version_no'),
        versions_count=Count('versions', distinct=True),
        ledgers_count=Count('versions__ledger_records', distinct=True))
    return [_template_summary(t, t.latest_version_no or 0, t.versions_count or 0,
                              t.ledgers_count or 0)
            for t in query]


def available_templates(user, ledger_type=None):
    """台账创建用：启用且有已发布版本的模板（可按类型过滤）。

    versions 只含当前在用版本（模板内最大 version_no）：新增台账固定
    使用当前版本，旧版本仅供历史追溯，不进入创建入口；发布新版本后
    本接口自动切换到新版本。历史台账仍绑定创建时的版本快照，不受影响。
    """
    query = apply_tenant_filter(
        OperationLedgerExcelTemplate.objects.filter(is_active=True), user)
    if ledger_type:
        query = query.filter(ledger_type=ledger_type)
    query = query.annotate(versions_count=Count('versions')).filter(versions_count__gt=0)
    items = []
    for template in query:
        current = template.versions.first()
        items.append({
            'id': template.id,
            'name': template.name,
            'ledger_type': template.ledger_type,
            'description': template.description,
            'versions': [current.to_view()] if current else [],
        })
    return items


def generation_config_options(user):
    """生成周期配置选项：本租户系统清单（模板配置弹窗数据源，专用接口
    避免依赖 system.view 权限）。"""
    from apps.equipment_lifecycle.models import LifecycleSystem
    systems = apply_tenant_filter(LifecycleSystem.objects.all(), user).order_by(
        '-is_active', 'system_code', 'id')
    return {
        'systems': [
            {'id': s.id, 'system_code': s.system_code, 'name': s.name,
             'is_active': s.is_active}
            for s in systems
        ],
        'periods': {
            'week_month': [
                {'value': TEMPLATE_PERIOD_WEEKLY, 'label': TEMPLATE_PERIOD_TEXT[TEMPLATE_PERIOD_WEEKLY]},
                {'value': TEMPLATE_PERIOD_MONTHLY, 'label': TEMPLATE_PERIOD_TEXT[TEMPLATE_PERIOD_MONTHLY]},
            ],
            'seasonal': [
                {'value': TEMPLATE_PERIOD_SEASONAL, 'label': TEMPLATE_PERIOD_TEXT[TEMPLATE_PERIOD_SEASONAL]},
            ],
        },
    }


def save_generation_config(user, template, body):
    """保存模板生成配置（适用系统 + 生成周期，整体校验后落库）。

    - 一模板只对应一个系统；生成周期按台账类型收敛（周月维护=每周/每月，
      季维护=每航季）；空值显式清空回"待配置"（不猜测历史模板配置）；
    - 配置只影响自动生成，不影响手工创建；已生成台账不回溯。
    """
    if not template.is_active:
        _fail('模板已删除（停用），不能修改生成配置')
    system_id = body.get('system')
    generation_period = str(body.get('generation_period') or '').strip()
    system = None
    if system_id not in (None, '', 0, '0'):
        from apps.equipment_lifecycle.models import LifecycleSystem
        if not str(system_id).isdigit():
            _fail('适用系统参数不合法')
        system = apply_tenant_filter(LifecycleSystem.objects.all(), user).filter(
            pk=int(system_id)).first()
        if system is None:
            _fail('适用系统不存在或无权限访问')
    if generation_period:
        allowed = TEMPLATE_PERIOD_BY_LEDGER_TYPE.get(template.ledger_type) or []
        if generation_period not in allowed:
            _fail('该台账类型的生成周期应为：%s'
                  % '、'.join(TEMPLATE_PERIOD_TEXT.get(v, v) for v in allowed))
    with transaction.atomic():
        template.system = system
        template.generation_period = generation_period
        template.updated_at = timezone.now()
        template.updated_by = user
        template.save(update_fields=[
            'system', 'generation_period', 'updated_at', 'updated_by'])
    return template


def template_detail(template):
    latest_no = template.versions.aggregate(max_no=Max('version_no'))['max_no'] or 0
    total = template.versions.count()
    ledgers = template.versions.aggregate(
        total=Count('ledger_records', distinct=True))['total'] or 0
    view = _template_summary(template, latest_no, total, ledgers)
    view['draft'] = draft_meta_view(template)
    view['compatibility'] = draft_compatibility(template)
    return view


def default_prefill(bindings):
    """台账创建时的默认值骨架（历史版本兼容）。

    default_value 属性已退役，新版本绑定不再携带；历史发布的版本快照
    中若仍存在默认值，创建台账时继续按类型校验预填（校验失败静默跳过）。
    """
    defaults = {b['field_id']: b['default_value'] for b in bindings
                if b.get('default_value')}
    if not defaults:
        return {}
    try:
        return validate_values(bindings, defaults)
    except ExcelLayoutError:
        return {}
