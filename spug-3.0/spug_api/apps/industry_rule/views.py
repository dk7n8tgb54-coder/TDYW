# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
行业规章业务接口

接口清单：
  GET    /api/industry-rule/                 列表（支持关键词/类别/状态/发布单位/生效日期范围筛选）
  POST   /api/industry-rule/                 新增
  GET    /api/industry-rule/<id>/            详情
  PUT    /api/industry-rule/<id>/            编辑
  DELETE /api/industry-rule/<id>/            删除
  POST   /api/industry-rule/<id>/retire/     废止
  GET    /api/industry-rule/<id>/attachments/  附件列表
  POST   /api/industry-rule/<id>/attach/     关联附件（file_id 必须在行业规章范围内）
  DELETE /api/industry-rule/<id>/attach/<att_id>/  取消关联附件

权限：
  document.industry_rule.view / add / edit / delete / upload / download / retire

附件文件仍存储在资料库（DocumentFilePublic），通过 system_folder=industry_rules 范围保护，
本模块不复制上传/下载/预览逻辑，只维护规章台账与文件关联。
"""
import logging
from django.views.generic import View
from django.db import transaction

from libs import json_response, JsonParser, Argument, auth
from apps.logs.audit import record_audit_event

from .models import IndustryRule, IndustryRuleAttachment

logger = logging.getLogger(__name__)

# 审计目标类型
AUDIT_TARGET_TYPE = 'industry_rule'
AUDIT_TARGET_NAME = '行业规章'


def _fmt_date(value):
    """安全格式化日期（兼容 str / date / datetime / None）"""
    if not value:
        return None
    if hasattr(value, 'strftime'):
        return value.strftime('%Y-%m-%d')
    # 字符串或其它类型原样返回（前端兼容）
    return str(value)


def _fmt_dt(value):
    """安全格式化日期时间"""
    if not value:
        return None
    if hasattr(value, 'strftime'):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    return str(value)


def _serialize_rule(rule, include_attachments=False):
    """序列化规章记录"""
    data = {
        'id': rule.id,
        'title': rule.title,
        'rule_no': rule.rule_no,
        'category': rule.category,
        'issuing_authority': rule.issuing_authority,
        'applicable_scope': rule.applicable_scope,
        'publish_date': _fmt_date(rule.publish_date),
        'effective_date': _fmt_date(rule.effective_date),
        'repeal_date': _fmt_date(rule.repeal_date),
        'status': rule.status,
        'version': rule.version,
        'summary': rule.summary,
        'created_by': rule.created_by.nickname if rule.created_by else None,
        'created_at': _fmt_dt(rule.created_at),
        'updated_at': _fmt_dt(rule.updated_at),
    }
    if include_attachments:
        data['attachments'] = [
            {
                'id': att.id,
                'file_id': att.document_file_id,
                'file_name': att.document_file.display_name or att.document_file.name,
                'file_size': att.document_file.file_size,
                'file_type': att.document_file.file_type,
                'is_primary': att.is_primary,
                'created_at': _fmt_dt(att.created_at),
            }
            for att in rule.attachments.select_related('document_file').order_by('-is_primary', '-created_at')
        ]
    return data


def _verify_file_in_industry_scope(file_id):
    """校验 file_id 对应的 DocumentFilePublic 属于行业规章根目录范围

    Returns: (file_obj, error_msg)
    """
    from apps.document.models import DocumentFilePublic
    from apps.document.services.system_folder_service import (
        INDUSTRY_RULES_CODE, ensure_file_in_scope_or_error,
    )
    if not file_id:
        return None, '缺少文件ID'
    try:
        file_obj = DocumentFilePublic.objects.get(pk=file_id)
    except DocumentFilePublic.DoesNotExist:
        return None, '文件不存在'
    ok, err = ensure_file_in_scope_or_error(file_obj, INDUSTRY_RULES_CODE)
    if not ok:
        return None, err
    return file_obj, None


class IndustryRuleListView(View):
    """行业规章列表（支持筛选 + 分页）"""

    @auth('document.industry_rule.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('keyword', type=str, required=False, default=''),
            Argument('category', type=str, required=False, default=''),
            Argument('status', type=str, required=False, default=''),
            Argument('issuing_authority', type=str, required=False, default=''),
            Argument('effective_start', type=str, required=False, default=''),
            Argument('effective_end', type=str, required=False, default=''),
            Argument('page', type=int, required=False, default=1),
            Argument('page_size', type=int, required=False, default=20),
        ).parse(request.GET)

        if error:
            return json_response(error=error)

        qs = IndustryRule.objects.all().order_by()

        if form.keyword:
            qs = qs.filter(title__icontains=form.keyword) | qs.filter(rule_no__icontains=form.keyword)
        if form.category:
            qs = qs.filter(category=form.category)
        if form.status:
            qs = qs.filter(status=form.status)
        if form.issuing_authority:
            qs = qs.filter(issuing_authority__icontains=form.issuing_authority)
        if form.effective_start:
            qs = qs.filter(effective_date__gte=form.effective_start)
        if form.effective_end:
            qs = qs.filter(effective_date__lte=form.effective_end)

        qs = qs.order_by('-effective_date', '-created_at')
        total = qs.count()
        page = max(1, form.page)
        page_size = min(max(1, form.page_size), 100)
        items = qs[(page - 1) * page_size: page * page_size]

        return json_response(data={
            'total': total,
            'page': page,
            'page_size': page_size,
            'items': [_serialize_rule(r, include_attachments=True) for r in items],
        })


class IndustryRuleCreateView(View):
    """新增行业规章"""

    @auth('document.industry_rule.add')
    @transaction.atomic
    def post(self, request):
        form, error = JsonParser(
            Argument('title', type=str, required=True, help='规章名称不能为空'),
            Argument('rule_no', type=str, required=False, default=''),
            Argument('category', type=str, required=False, default=''),
            Argument('issuing_authority', type=str, required=False, default=''),
            Argument('applicable_scope', type=str, required=False, default=''),
            Argument('publish_date', type=str, required=False, default=''),
            Argument('effective_date', type=str, required=False, default=''),
            Argument('repeal_date', type=str, required=False, default=''),
            Argument('status', type=str, required=False, default=IndustryRule.STATUS_DRAFT),
            Argument('version', type=str, required=False, default=''),
            Argument('summary', type=str, required=False, default=''),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        if form.status not in dict(IndustryRule.STATUS_CHOICES):
            return json_response(error='未知的规章状态')

        rule = IndustryRule.objects.create(
            title=form.title,
            rule_no=form.rule_no,
            category=form.category,
            issuing_authority=form.issuing_authority,
            applicable_scope=form.applicable_scope,
            publish_date=form.publish_date or None,
            effective_date=form.effective_date or None,
            repeal_date=form.repeal_date or None,
            status=form.status,
            version=form.version,
            summary=form.summary,
            created_by=request.user,
            updated_by=request.user,
        )

        record_audit_event(
            request, 'create', AUDIT_TARGET_TYPE,
            target_id=rule.id, target_name=rule.title,
            detail={'rule_no': rule.rule_no, 'category': rule.category, 'status': rule.status},
        )
        return json_response(data=_serialize_rule(rule))


class IndustryRuleDetailView(View):
    """行业规章详情（含附件）"""

    @auth('document.industry_rule.view')
    def get(self, request, r_id):
        rule = self._get_rule(r_id)
        if rule is None:
            return json_response(error='规章不存在')
        return json_response(data=_serialize_rule(rule, include_attachments=True))

    @auth('document.industry_rule.edit')
    @transaction.atomic
    def put(self, request, r_id):
        rule = self._get_rule(r_id)
        if rule is None:
            return json_response(error='规章不存在')

        form, error = JsonParser(
            Argument('title', type=str, required=False),
            Argument('rule_no', type=str, required=False),
            Argument('category', type=str, required=False),
            Argument('issuing_authority', type=str, required=False),
            Argument('applicable_scope', type=str, required=False),
            Argument('publish_date', type=str, required=False),
            Argument('effective_date', type=str, required=False),
            Argument('repeal_date', type=str, required=False),
            Argument('status', type=str, required=False),
            Argument('version', type=str, required=False),
            Argument('summary', type=str, required=False),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        changed = {}
        field_map = {
            'title': 'title', 'rule_no': 'rule_no', 'category': 'category',
            'issuing_authority': 'issuing_authority', 'applicable_scope': 'applicable_scope',
            'version': 'version', 'summary': 'summary',
        }
        for arg_name, field_name in field_map.items():
            val = getattr(form, arg_name, None)
            if val is not None and getattr(rule, field_name) != val:
                setattr(rule, field_name, val)
                changed[field_name] = val
        for date_field in ('publish_date', 'effective_date', 'repeal_date'):
            val = getattr(form, date_field, None)
            if val is not None:
                new_val = val or None
                if getattr(rule, date_field) != new_val:
                    setattr(rule, date_field, new_val)
                    changed[date_field] = val
        if form.status is not None:
            if form.status not in dict(IndustryRule.STATUS_CHOICES):
                return json_response(error='未知的规章状态')
            if rule.status != form.status:
                rule.status = form.status
                changed['status'] = form.status

        rule.updated_by = request.user
        rule.save()

        record_audit_event(
            request, 'update', AUDIT_TARGET_TYPE,
            target_id=rule.id, target_name=rule.title,
            detail=changed or {'summary': '无变更'},
        )
        return json_response(data=_serialize_rule(rule, include_attachments=True))

    @auth('document.industry_rule.delete')
    @transaction.atomic
    def delete(self, request, r_id):
        rule = self._get_rule(r_id)
        if rule is None:
            return json_response(error='规章不存在')
        title = rule.title
        rid = rule.id
        # 附件关联记录一并删除（文件本身不删，仍归资料库管理）
        rule.delete()
        record_audit_event(
            request, 'delete', AUDIT_TARGET_TYPE,
            target_id=rid, target_name=title,
            detail={'summary': '删除规章及附件关联'},
        )
        return json_response(data={'status': 'deleted'})

    @staticmethod
    def _get_rule(r_id):
        try:
            return IndustryRule.objects.get(pk=r_id)
        except (IndustryRule.DoesNotExist, ValueError, TypeError):
            return None


class IndustryRuleRetireView(View):
    """废止行业规章

    将状态置为 retired 并记录废止日期。
    """

    @auth('document.industry_rule.retire')
    @transaction.atomic
    def post(self, request, r_id):
        rule = IndustryRuleDetailView._get_rule(r_id)
        if rule is None:
            return json_response(error='规章不存在')

        form, error = JsonParser(
            Argument('repeal_date', type=str, required=False, default=''),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        if rule.status == IndustryRule.STATUS_RETIRED:
            return json_response(data={'status': 'retired', 'message': '规章已废止'})

        import datetime
        rule.status = IndustryRule.STATUS_RETIRED
        rule.repeal_date = form.repeal_date or datetime.date.today().strftime('%Y-%m-%d')
        rule.updated_by = request.user
        rule.save()

        record_audit_event(
            request, 'retire', AUDIT_TARGET_TYPE,
            target_id=rule.id, target_name=rule.title,
            detail={'repeal_date': rule.repeal_date},
        )
        return json_response(data=_serialize_rule(rule))


class IndustryRuleAttachView(View):
    """行业规章附件管理

    GET    附件列表
    POST   关联附件（file_id 必须在行业规章范围内）
    DELETE 取消关联（att_id）
    """

    @auth('document.industry_rule.view')
    def get(self, request, r_id):
        rule = IndustryRuleDetailView._get_rule(r_id)
        if rule is None:
            return json_response(error='规章不存在')
        return json_response(data=_serialize_rule(rule, include_attachments=True).get('attachments', []))

    @auth('document.industry_rule.upload')
    @transaction.atomic
    def post(self, request, r_id):
        rule = IndustryRuleDetailView._get_rule(r_id)
        if rule is None:
            return json_response(error='规章不存在')

        form, error = JsonParser(
            Argument('file_id', type=int, required=True, help='缺少文件ID'),
            Argument('is_primary', type=bool, required=False, default=False),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        file_obj, err = _verify_file_in_industry_scope(form.file_id)
        if err:
            return json_response(error=err)

        att, created = IndustryRuleAttachment.objects.get_or_create(
            rule=rule, document_file=file_obj,
            defaults={'is_primary': form.is_primary, 'created_by': request.user},
        )
        if not created:
            return json_response(error='该文件已关联此规章')

        # 主附件唯一性：设为主附件时取消其他主附件
        if form.is_primary:
            rule.attachments.exclude(id=att.id).update(is_primary=False)

        record_audit_event(
            request, 'attach_file', AUDIT_TARGET_TYPE,
            target_id=rule.id, target_name=rule.title,
            detail={'file_id': file_obj.id, 'file_name': file_obj.display_name or file_obj.name, 'is_primary': form.is_primary},
        )
        return json_response(data={
            'id': att.id, 'file_id': file_obj.id,
            'file_name': file_obj.display_name or file_obj.name,
            'is_primary': att.is_primary,
        })

    @auth('document.industry_rule.upload')
    @transaction.atomic
    def delete(self, request, r_id, att_id):
        rule = IndustryRuleDetailView._get_rule(r_id)
        if rule is None:
            return json_response(error='规章不存在')
        try:
            att = rule.attachments.get(pk=att_id)
        except IndustryRuleAttachment.DoesNotExist:
            return json_response(error='附件关联不存在')
        file_name = att.document_file.display_name or att.document_file.name
        att.delete()
        record_audit_event(
            request, 'detach_file', AUDIT_TARGET_TYPE,
            target_id=rule.id, target_name=rule.title,
            detail={'file_id': att.document_file_id, 'file_name': file_name},
        )
        return json_response(data={'status': 'detached'})


class IndustryRuleCategoriesView(View):
    """规章类别去重列表（供筛选下拉）"""

    @auth('document.industry_rule.view')
    def get(self, request):
        cats = (
            IndustryRule.objects.exclude(category='')
            .values_list('category', flat=True)
            .distinct()
            .order_by('category')
        )
        return json_response(data=list(cats))
