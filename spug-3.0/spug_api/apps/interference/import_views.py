# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Copyright (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""干扰管理双业务类型 Excel 导入视图：模板下载 / 预校验 / 确认导入 / 错误报告。

与 business_views.py 的职责边界：
- 本文件只提供两类业务记录的 Excel 导入增量接口，不涉及 CRUD；
- 业务类型由 URL 入口（地面/空中页面各自接口）决定，不从文件内容猜测；
- 上传文件若包含另一业务类型的专用表头将被拒绝（见 import_service）。

安全与事务约定：
- 模板下载使用 interference.interference.view；预校验与确认导入均要求
  interference.interference.add（与手工新增一致），不扩展权限体系；
- 预校验不写业务记录，仅下发一次性预校验凭证（Redis 缓存，绑定
  用户/业务/文件 SHA-256，带过期时间）；
- 确认导入在一个数据库事务中执行：先整文件重新校验 + 数据库重复复查，
  任一行失败整体回滚，不允许部分导入；写入采用内层 savepoint，
  将数据库异常转换为业务错误（HTTP 200 + {"error": ...}）；
- 幂等保护：同一预校验凭证只允许成功提交一次（cache.add 一次性锁），
  防止双击或网络重试创建重复数据；重复数据本身也会被重复检测拒绝；
- 审计：每次确认导入（无论成功失败）写入一条 import 审计，包含导入人、
  记录类型、源文件名、文件 SHA-256、总行数、成功数、失败数、创建记录 ID，
  不写入 Excel 单元格内容；
- 附件边界：Excel 导入不处理附件，导入成功后由用户在记录详情页单独上传。
"""
import hashlib
import logging
from uuid import uuid4
from urllib.parse import quote

from django.core.cache import cache
from django.db import transaction
from django.http import HttpResponse
from django.views.generic import View

from libs import auth, json_response
from libs.export_utils import build_export_error_response
from apps.logs.audit import record_audit_event

from apps.interference.import_service import (
    BUSINESS_CONFIG,
    ImportParseError,
    apply_db_duplicate_errors,
    build_error_report_workbook,
    build_template_workbook,
    build_stats,
    import_max_file_mb,
    parse_workbook,
)

logger = logging.getLogger(__name__)

EXCEL_CONTENT_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
VALIDATE_TOKEN_CACHE_PREFIX = 'interference:import:token:'
VALIDATE_TOKEN_TTL_SECONDS = 1800


def _check_upload_file(request):
    """上传文件基础校验：存在性 / .xlsx 格式 / 大小上限。返回 (file, error)。"""
    file = request.FILES.get('file')
    if not file:
        return None, '请选择要导入的 Excel 文件'
    name = (file.name or '').lower()
    if name.endswith('.xls') and not name.endswith('.xlsx'):
        return None, '不支持 .xls 格式，请用 Excel 将文件另存为 .xlsx 后再导入'
    if not name.endswith('.xlsx'):
        return None, '仅支持 .xlsx 格式的 Excel 文件，请将文件另存为 .xlsx 后再导入'
    max_mb = import_max_file_mb()
    if file.size > max_mb * 1024 * 1024:
        return None, f'文件大小超过上限（最大 {max_mb}MB），请拆分后分批导入'
    return file, None


class _ImportTemplateView(View):
    """下载导入模板（.xlsx，含标题/说明/文本格式表头）。"""

    business = None

    @auth('interference.interference.view')
    def get(self, request):
        config = BUSINESS_CONFIG[self.business]
        workbook = build_template_workbook(self.business)
        filename = f'{config["template_filename"]}.xlsx'
        record_audit_event(
            request, 'export', 'interference',
            target_name=filename,
            detail={'record_type': config['object_type'], 'kind': 'import_template'},
        )
        response = HttpResponse(workbook.getvalue(), content_type=EXCEL_CONTENT_TYPE)
        response['Content-Disposition'] = "attachment; filename*=UTF-8''%s" % quote(filename)
        return response


class _ImportValidateView(View):
    """上传 Excel 预校验：只解析与校验，不写业务记录。"""

    business = None

    @auth('interference.interference.add')
    def post(self, request):
        file, error = _check_upload_file(request)
        if error:
            return json_response(error=error)
        data = file.read()
        try:
            result = parse_workbook(self.business, data)
        except ImportParseError as e:
            return json_response(error=str(e))

        apply_db_duplicate_errors(self.business, request.user, result)

        token = uuid4().hex
        cache.set(VALIDATE_TOKEN_CACHE_PREFIX + token, {
            'user_id': request.user.id,
            'business': self.business,
            'sha256': hashlib.sha256(data).hexdigest(),
        }, VALIDATE_TOKEN_TTL_SECONDS)

        stats = build_stats(result)
        errors = [e for row in result['rows'] for e in row['errors']]
        warnings = [w for row in result['rows'] for w in row['warnings']] + result['warnings']
        return json_response({
            **stats,
            'errors': errors,
            'warnings': warnings,
            'validate_token': token,
        })


class _ImportCommitView(View):
    """确认导入：整文件重新校验 + 数据库重复复查 + 单事务整体写入。"""

    business = None

    @auth('interference.interference.add')
    def post(self, request):
        file, error = _check_upload_file(request)
        if error:
            return json_response(error=error)
        data = file.read()
        sha256 = hashlib.sha256(data).hexdigest()

        # 幂等保护：预校验凭证一次性使用（绑定用户/业务/文件内容）
        token = (request.POST.get('validate_token') or '').strip()
        token_key = VALIDATE_TOKEN_CACHE_PREFIX + token
        lock_key = token_key + ':lock'
        token_info = cache.get(token_key) if token else None
        if not token_info:
            return json_response(error='预校验凭证无效或已过期，请重新预校验后再导入')
        if (token_info.get('user_id') != request.user.id
                or token_info.get('business') != self.business
                or token_info.get('sha256') != sha256):
            return json_response(error='导入文件与预校验文件不一致，请重新预校验后再导入')
        if not cache.add(lock_key, 1, VALIDATE_TOKEN_TTL_SECONDS):
            return json_response(error='导入请求正在处理或已提交，请勿重复操作')

        config = BUSINESS_CONFIG[self.business]
        try:
            result = parse_workbook(self.business, data)
        except ImportParseError as e:
            cache.delete(lock_key)
            return json_response(error=f'导入失败：{e}')

        row_errors = [e for row in result['rows'] for e in row['errors']]
        if row_errors:
            self._audit_failed(request, config, file, sha256, result,
                               f'文件校验未通过（{len(row_errors)} 个错误）')
            cache.delete(lock_key)
            return json_response(
                error=f'导入失败：文件校验未通过（{len(row_errors)} 个错误），'
                      '请根据预校验结果修正后重新导入')

        created_ids = []
        with transaction.atomic():
            # 数据库重复复查（租户隔离）在事务内执行，任一重复即整体拒绝
            apply_db_duplicate_errors(self.business, request.user, result)
            dup_errors = [e for row in result['rows'] for e in row['errors']]
            if dup_errors:
                self._audit_failed(request, config, file, sha256, result,
                                   f'存在{len(dup_errors)}条与已有记录重复的数据')
                cache.delete(lock_key)
                return json_response(
                    error=f'导入失败：存在与已有记录重复的数据'
                          f'（判断依据：{config["duplicate_label"]}），默认拒绝重复导入')

            try:
                with transaction.atomic():
                    for row in result['rows']:
                        values = dict(row['cleaned'])
                        values['created_by'] = request.user
                        # fail-closed：显式按当前登录用户租户写入，信号自动设置兜底
                        values['tenant_id'] = getattr(request.user, 'tenant_id', '') or ''
                        record = config['model'].objects.create(**values)
                        created_ids.append(record.id)
            except Exception:
                logger.exception('[InterferenceImport] 写入失败整体回滚 business=%s', self.business)
                self._audit_failed(request, config, file, sha256, result,
                                   '写入数据库时发生异常，已整体回滚')
                cache.delete(lock_key)
                return json_response(
                    error='导入失败：写入数据库时发生异常，本次导入已整体回滚，请检查数据后重试')

            record_audit_event(
                request, 'import', 'interference',
                target_id=str(created_ids[0]) if created_ids else '',
                target_name=file.name,
                detail={
                    'record_type': config['object_type'],
                    'file_name': file.name,
                    'file_sha256': sha256,
                    'total_rows': result['total_rows'],
                    'success_count': len(created_ids),
                    'fail_count': 0,
                    'created_ids': created_ids,
                },
            )

        cache.delete(token_key)
        cache.delete(lock_key)
        return json_response({'imported_count': len(created_ids)})

    def _audit_failed(self, request, config, file, sha256, result, reason):
        """导入失败也记录审计（成功数0/失败数为错误行数），不写入单元格内容。"""
        try:
            row_errors = [e for row in result['rows'] for e in row['errors']]
            record_audit_event(
                request, 'import', 'interference',
                target_name=file.name,
                detail={
                    'record_type': config['object_type'],
                    'file_name': file.name,
                    'file_sha256': sha256,
                    'total_rows': result['total_rows'],
                    'success_count': 0,
                    'fail_count': len(row_errors),
                    'created_ids': [],
                    'fail_reason': reason,
                },
                error=reason,
            )
        except Exception:
            logger.exception('[InterferenceImport] 失败审计写入异常 business=%s', self.business)


class _ImportErrorReportView(View):
    """下载错误报告：与原文件列一致，追加「Excel行号」「错误原因」两列。"""

    business = None

    @auth('interference.interference.add')
    def post(self, request):
        file, error = _check_upload_file(request)
        if error:
            return build_export_error_response(error)
        data = file.read()
        try:
            result = parse_workbook(self.business, data)
        except ImportParseError as e:
            return build_export_error_response(str(e))

        if not any(row['errors'] for row in result['rows']):
            return build_export_error_response('当前文件没有错误行，无需下载错误报告')

        config = BUSINESS_CONFIG[self.business]
        workbook = build_error_report_workbook(self.business, result)
        error_rows = sum(1 for row in result['rows'] if row['errors'])
        filename = f'{config["template_filename"]}_错误报告.xlsx'
        record_audit_event(
            request, 'export', 'interference',
            target_name=filename,
            detail={'record_type': config['object_type'], 'kind': 'import_error_report',
                    'error_rows': error_rows},
        )
        response = HttpResponse(workbook.getvalue(), content_type=EXCEL_CONTENT_TYPE)
        response['Content-Disposition'] = "attachment; filename*=UTF-8''%s" % quote(filename)
        return response


class BridgeImportTemplateView(_ImportTemplateView):
    business = 'bridge'


class BridgeImportValidateView(_ImportValidateView):
    business = 'bridge'


class BridgeImportCommitView(_ImportCommitView):
    business = 'bridge'


class BridgeImportErrorReportView(_ImportErrorReportView):
    business = 'bridge'


class AirImportTemplateView(_ImportTemplateView):
    business = 'air'


class AirImportValidateView(_ImportValidateView):
    business = 'air'


class AirImportCommitView(_ImportCommitView):
    business = 'air'


class AirImportErrorReportView(_ImportErrorReportView):
    business = 'air'
