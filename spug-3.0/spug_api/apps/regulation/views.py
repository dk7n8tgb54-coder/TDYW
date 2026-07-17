# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""规章管理业务接口

接口清单：
  GET    /api/regulation/categories/tree/                 分类树（全量，递归）
  GET    /api/regulation/categories/                      分类列表（扁平）
  POST   /api/regulation/categories/                      新建分类
  PUT    /api/regulation/categories/<id>/                 编辑分类
  DELETE /api/regulation/categories/<id>/                 删除分类（无子节点无规章才允许）
  GET    /api/regulation/                                 规章列表
  POST   /api/regulation/create/                          新建规章
  GET    /api/regulation/<id>/                            规章详情（含附件）
  PUT    /api/regulation/<id>/                            编辑规章
  DELETE /api/regulation/<id>/                            删除规章
  POST   /api/regulation/<id>/retire/                     废止规章
  GET    /api/regulation/<id>/attachments/                附件列表
  POST   /api/regulation/<id>/attachments/upload/         上传附件（multipart/form-data）
  GET    /api/regulation/<id>/attachments/<att_id>/download/   下载附件
  GET    /api/regulation/<id>/attachments/<att_id>/preview-url/    获取kkFileView预览地址
  GET    /api/regulation/<id>/attachments/<att_id>/preview-file/   kkFileView回调读取文件流
  DELETE /api/regulation/<id>/attachments/<att_id>/       删除附件（软删除）
权限：document.regulation.view / add / edit / delete / upload / download / category_manage
"""
import os
import base64
import datetime
import logging
import mimetypes

from django.db import transaction
from django.db.models import Q
from django.http import FileResponse
from django.views.generic import View
from django.conf import settings
from urllib.parse import quote

from libs import json_response, JsonParser, Argument, auth, human_datetime
from apps.logs.audit import record_audit_event
from apps.evidence.attachment_preview_token import (
    generate_attachment_preview_token,
    validate_attachment_preview_token,
)

from .models import Regulation, RegulationCategory, RegulationAttachment
from . import storage

logger = logging.getLogger(__name__)

# 审计目标类型
AUDIT_TARGET_TYPE = 'regulation'
AUDIT_TARGET_NAME = '规章管理'


# ==================== 辅助函数 ====================

def _fmt_date(value):
    """安全格式化日期（兼容 str / date / datetime / None）"""
    if not value:
        return None
    if hasattr(value, 'strftime'):
        return value.strftime('%Y-%m-%d')
    return str(value)


def _parse_date(value, field_label):
    """解析日期字符串，返回 (date_or_None, error_or_None)

    允许空字符串/None 转 None；非法格式返回明确错误。
    """
    if not value:
        return None, None
    try:
        return datetime.datetime.strptime(value, '%Y-%m-%d').date(), None
    except (ValueError, TypeError):
        return None, f'{field_label}格式必须为 YYYY-MM-DD'


def _validate_category(category_id, require_leaf=True):
    """校验分类存在性，返回 (category_or_None, error_or_None)"""
    if not category_id:
        return None, None
    try:
        cat = RegulationCategory.objects.get(pk=category_id)
    except (RegulationCategory.DoesNotExist, ValueError, TypeError):
        return None, '所选分类不存在'
    if require_leaf and not cat.is_leaf:
        return None, '请选择叶子分类'
    return cat, None


def _get_regulation(pk):
    """获取规章对象，不存在返回 None"""
    try:
        return Regulation.objects.get(pk=pk)
    except (Regulation.DoesNotExist, ValueError, TypeError):
        return None


def _get_attachment(regulation, att_id):
    """获取规章下属未删除的附件对象，不存在返回 None"""
    try:
        return regulation.attachments.get(pk=att_id, is_deleted=False)
    except (RegulationAttachment.DoesNotExist, ValueError, TypeError):
        return None


def _serialize_attachment(att):
    """序列化附件记录"""
    ext = storage.extract_extension(att.original_name)
    return {
        'id': att.id,
        'file_name': att.original_name,
        'previewable': ext in storage.PREVIEWABLE_EXTENSIONS,
    }


def _serialize_regulation(regulation, include_attachments=False):
    """序列化规章记录"""
    data = {
        'id': regulation.id,
        'title': regulation.title,
        'rule_no': regulation.rule_no,
        'category_id': regulation.category_id,
        'category_name': regulation.category.name if regulation.category else None,
        'issuing_authority': regulation.issuing_authority,
        'biz_type': regulation.biz_type,
        'publish_date': _fmt_date(regulation.publish_date),
        'effective_date': _fmt_date(regulation.effective_date),
        'status': regulation.status,
    }
    if include_attachments:
        data['attachments'] = [
            _serialize_attachment(att)
            for att in regulation.attachments.filter(
                is_deleted=False
            ).order_by('sort_order', '-id')
        ]
    return data


def _serialize_category_tree():
    """序列化分类树（全量，内存递归构建，避免 N+1 查询）"""
    all_categories = list(
        RegulationCategory.objects.order_by('sort_order', 'id').values(
            'id', 'name', 'parent_id', 'sort_order', 'code', 'is_leaf'
        )
    )
    children_map = {}
    for cat in all_categories:
        pid = cat['parent_id']
        if pid not in children_map:
            children_map[pid] = []
        children_map[pid].append(cat)

    def build_tree(parent_id):
        nodes = children_map.get(parent_id, [])
        result = []
        for node in nodes:
            node['children'] = build_tree(node['id'])
            result.append(node)
        return result

    return build_tree(None)


# ==================== 分类树 View ====================

class CategoryTreeView(View):
    """分类树全量查询（左侧树）"""

    @auth('document.regulation.view')
    def get(self, request):
        tree = _serialize_category_tree()
        return json_response(data=tree)


class CategoryListCreateView(View):
    """分类节点列表/新建"""

    @auth('document.regulation.view')
    def get(self, request):
        cats = list(
            RegulationCategory.objects.order_by('sort_order', 'id').values(
                'id', 'name', 'parent_id', 'sort_order', 'code', 'is_leaf'
            )
        )
        return json_response(data=cats)

    @auth('document.regulation.category_manage')
    @transaction.atomic
    def post(self, request):
        form, error = JsonParser(
            Argument('name', type=str, required=True, help='分类名称不能为空'),
            Argument('parent_id', type=int, required=False, default=None),
            Argument('sort_order', type=int, required=False, default=0),
            Argument('code', type=str, required=False, default=''),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        # 如果有父分类，父分类的 is_leaf 设为 False（它现在是中间节点）
        if form.parent_id:
            try:
                parent = RegulationCategory.objects.get(pk=form.parent_id)
            except RegulationCategory.DoesNotExist:
                return json_response(error='父分类不存在')
            if parent.is_leaf:
                parent.is_leaf = False
                parent.save(update_fields=['is_leaf'])

        cat = RegulationCategory.objects.create(
            name=form.name,
            parent_id=form.parent_id,
            sort_order=form.sort_order,
            code=form.code,
            is_leaf=True,  # 新建节点默认是叶子
            created_by=request.user,
        )

        record_audit_event(
            request, 'create', AUDIT_TARGET_TYPE,
            target_id=cat.id, target_name=cat.name,
            detail={'type': 'category', 'parent_id': form.parent_id},
        )
        return json_response(data={
            'id': cat.id, 'name': cat.name,
            'parent_id': cat.parent_id, 'sort_order': cat.sort_order,
            'code': cat.code, 'is_leaf': cat.is_leaf,
        })


class CategoryDetailView(View):
    """分类节点编辑/删除"""

    @auth('document.regulation.category_manage')
    @transaction.atomic
    def put(self, request, pk):
        try:
            cat = RegulationCategory.objects.get(pk=pk)
        except RegulationCategory.DoesNotExist:
            return json_response(error='分类不存在')

        form, error = JsonParser(
            Argument('name', type=str, required=False),
            Argument('sort_order', type=int, required=False),
            Argument('code', type=str, required=False),
            # is_leaf 不再允许手动修改，由后端根据子节点存在性自动维护
        ).parse(request.body)

        if error:
            return json_response(error=error)

        changed = {}
        for field in ('name', 'sort_order', 'code'):
            val = getattr(form, field, None)
            if val is not None and getattr(cat, field) != val:
                setattr(cat, field, val)
                changed[field] = val

        cat.save()
        record_audit_event(
            request, 'update', AUDIT_TARGET_TYPE,
            target_id=cat.id, target_name=cat.name,
            detail={'type': 'category', **changed} if changed else {'type': 'category', 'summary': '无变更'},
        )
        return json_response(data={
            'id': cat.id, 'name': cat.name,
            'parent_id': cat.parent_id, 'sort_order': cat.sort_order,
            'code': cat.code, 'is_leaf': cat.is_leaf,
        })

    @auth('document.regulation.category_manage')
    @transaction.atomic
    def delete(self, request, pk):
        try:
            cat = RegulationCategory.objects.get(pk=pk)
        except RegulationCategory.DoesNotExist:
            return json_response(error='分类不存在')

        # 检查是否有子分类
        if RegulationCategory.objects.filter(parent=cat).exists():
            return json_response(error='该分类下有子分类，不能删除')

        # 检查是否有关联规章
        if Regulation.objects.filter(category=cat).exists():
            return json_response(error='该分类下有规章，不能删除')

        parent = cat.parent
        name = cat.name
        cid = cat.id
        cat.delete()

        # 维护 is_leaf：删除最后一个子分类后恢复父节点为叶子
        if parent:
            if not RegulationCategory.objects.filter(parent=parent).exists():
                parent.is_leaf = True
                parent.save(update_fields=['is_leaf'])

        record_audit_event(
            request, 'delete', AUDIT_TARGET_TYPE,
            target_id=cid, target_name=name,
            detail={'type': 'category'},
        )
        return json_response(data={'status': 'deleted'})


# ==================== 规章 View ====================

class RegulationListView(View):
    """规章列表（支持筛选 + 分页）"""

    @auth('document.regulation.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('keyword', type=str, required=False, default=''),
            Argument('category_id', type=int, required=False, default=None),
            Argument('biz_type', type=str, required=False, default=''),
            Argument('status', type=str, required=False, default=''),
            Argument('issuing_authority', type=str, required=False, default=''),
            Argument('effective_start', type=str, required=False, default=''),
            Argument('effective_end', type=str, required=False, default=''),
            Argument('page', type=int, required=False, default=1),
            Argument('page_size', type=int, required=False, default=20),
        ).parse(request.GET)

        if error:
            return json_response(error=error)

        qs = Regulation.objects.all()

        if form.keyword:
            qs = qs.filter(
                Q(title__icontains=form.keyword) | Q(rule_no__icontains=form.keyword)
            )
        if form.category_id:
            qs = qs.filter(category_id=form.category_id)
        if form.biz_type:
            qs = qs.filter(biz_type__icontains=form.biz_type)
        if form.status:
            qs = qs.filter(status=form.status)
        if form.issuing_authority:
            qs = qs.filter(issuing_authority__icontains=form.issuing_authority)
        if form.effective_start:
            qs = qs.filter(effective_date__gte=form.effective_start)
        if form.effective_end:
            qs = qs.filter(effective_date__lte=form.effective_end)

        qs = qs.order_by('-effective_date', '-id')
        total = qs.count()
        page = max(1, form.page)
        page_size = min(max(1, form.page_size), 100)
        items = qs.select_related('category').prefetch_related(
            'attachments'
        )[(page - 1) * page_size: page * page_size]

        return json_response(data={
            'total': total,
            'page': page,
            'page_size': page_size,
            'items': [_serialize_regulation(r, include_attachments=True) for r in items],
        })


class RegulationCreateView(View):
    """新增规章"""

    @auth('document.regulation.add')
    @transaction.atomic
    def post(self, request):
        form, error = JsonParser(
            Argument('title', type=str, required=True, help='规章名称不能为空'),
            Argument('rule_no', type=str, required=True, help='规章编号不能为空'),
            Argument('category_id', type=int, required=False, default=None),
            Argument('issuing_authority', type=str, required=False, default=''),
            Argument('biz_type', type=str, required=False, default=''),
            Argument('publish_date', type=str, required=False, default=''),
            Argument('effective_date', type=str, required=False, default=''),
            Argument('status', type=str, required=False, default=Regulation.STATUS_ACTIVE),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        form.rule_no = form.rule_no.strip()
        if not form.rule_no:
            return json_response(error='规章编号不能为空')

        if form.status not in dict(Regulation.STATUS_CHOICES):
            return json_response(error='未知的规章状态')

        # 校验分类存在且为叶子
        _, cat_err = _validate_category(form.category_id, require_leaf=True)
        if cat_err:
            return json_response(error=cat_err)

        # 校验日期格式
        date_fields = {
            'publish_date': '发布日期',
            'effective_date': '生效日期',
        }
        parsed_dates = {}
        for field, label in date_fields.items():
            val = getattr(form, field, '')
            parsed, date_err = _parse_date(val, label)
            if date_err:
                return json_response(error=date_err)
            parsed_dates[field] = parsed

        regulation = Regulation.objects.create(
            title=form.title,
            rule_no=form.rule_no,
            category_id=form.category_id,
            issuing_authority=form.issuing_authority,
            biz_type=form.biz_type,
            publish_date=parsed_dates['publish_date'],
            effective_date=parsed_dates['effective_date'],
            status=form.status,
            updated_by=request.user,
        )

        record_audit_event(
            request, 'create', AUDIT_TARGET_TYPE,
            target_id=regulation.id, target_name=regulation.title,
            detail={'rule_no': regulation.rule_no, 'biz_type': regulation.biz_type, 'status': regulation.status},
        )
        return json_response(data=_serialize_regulation(regulation))


class RegulationDetailView(View):
    """规章详情/编辑/删除（含附件）"""

    @auth('document.regulation.view')
    def get(self, request, pk):
        regulation = _get_regulation(pk)
        if regulation is None:
            return json_response(error='规章不存在')
        return json_response(data=_serialize_regulation(regulation, include_attachments=True))

    # 普通字段名映射：val is not None 时更新（允许传空字符串清空）
    _PLAIN_FIELD_MAP = {
        'title': 'title', 'rule_no': 'rule_no',
        'issuing_authority': 'issuing_authority', 'biz_type': 'biz_type',
    }

    # 日期字段名 → 中文标签
    _DATE_FIELD_MAP = {
        'publish_date': '发布日期',
        'effective_date': '生效日期',
    }

    def _apply_plain_fields(self, regulation, form):
        """普通字段：val is not None 时更新；rule_no 需 strip 且非空"""
        changed = {}
        for arg_name, field_name in self._PLAIN_FIELD_MAP.items():
            val = getattr(form, arg_name, None)
            if field_name == 'rule_no' and val is not None:
                val = val.strip()
                if not val:
                    return '规章编号不能为空', None
            if val is not None and getattr(regulation, field_name) != val:
                setattr(regulation, field_name, val)
                changed[field_name] = val
        return None, changed

    def _apply_category(self, regulation, form):
        """分类字段：校验存在且为叶子"""
        if form.category_id is None:
            return None, {}
        _, cat_err = _validate_category(form.category_id, require_leaf=True)
        if cat_err:
            return cat_err, None
        if regulation.category_id != form.category_id:
            regulation.category_id = form.category_id
            return None, {'category_id': form.category_id}
        return None, {}

    def _apply_date_fields(self, regulation, form):
        """日期字段：校验格式，空字符串 → None（清空）"""
        changed = {}
        for date_field, label in self._DATE_FIELD_MAP.items():
            val = getattr(form, date_field, None)
            if val is None:
                continue
            parsed, date_err = _parse_date(val, label)
            if date_err:
                return date_err, None
            if getattr(regulation, date_field) != parsed:
                setattr(regulation, date_field, parsed)
                changed[date_field] = val
        return None, changed

    def _apply_status(self, regulation, form):
        """状态字段：校验枚举值"""
        if form.status is None:
            return None, {}
        if form.status not in dict(Regulation.STATUS_CHOICES):
            return '未知的规章状态', None
        if regulation.status != form.status:
            regulation.status = form.status
            return None, {'status': form.status}
        return None, {}

    @auth('document.regulation.edit')
    @transaction.atomic
    def put(self, request, pk):
        regulation = _get_regulation(pk)
        if regulation is None:
            return json_response(error='规章不存在')

        form, error = JsonParser(
            Argument('title', type=str, required=False),
            Argument('rule_no', type=str, required=False),
            Argument('category_id', type=int, required=False),
            Argument('issuing_authority', type=str, required=False),
            Argument('biz_type', type=str, required=False),
            Argument('publish_date', type=str, required=False),
            Argument('effective_date', type=str, required=False),
            Argument('status', type=str, required=False),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        # 按固定顺序应用各字段子处理器：任一返回 error 立即中止
        changed = {}
        for applier in (self._apply_plain_fields, self._apply_category,
                        self._apply_date_fields, self._apply_status):
            err, partial = applier(regulation, form)
            if err:
                return json_response(error=err)
            if partial:
                changed.update(partial)

        regulation.updated_by = request.user
        regulation.updated_at = human_datetime()
        regulation.save()

        record_audit_event(
            request, 'update', AUDIT_TARGET_TYPE,
            target_id=regulation.id, target_name=regulation.title,
            detail=changed or {'summary': '无变更'},
        )
        return json_response(data=_serialize_regulation(regulation, include_attachments=True))

    @auth('document.regulation.delete')
    @transaction.atomic
    def delete(self, request, pk):
        regulation = _get_regulation(pk)
        if regulation is None:
            return json_response(error='规章不存在')
        title = regulation.title
        rid = regulation.id
        # 软删除所有附件记录并尽量清理物理文件
        for att in regulation.attachments.filter(is_deleted=False):
            att.is_deleted = True
            att.deleted_by = request.user
            att.deleted_at = human_datetime()
            att.save(update_fields=['is_deleted', 'deleted_by', 'deleted_at'])
            try:
                abs_path = storage.resolve_absolute_path(att.file_path)
                storage.safe_delete_attachment_file(abs_path)
            except ValueError as e:
                logger.warning(f'[Regulation] 跳过附件物理文件清理: att_id={att.id}, error={e}')
        regulation.delete()
        record_audit_event(
            request, 'delete', AUDIT_TARGET_TYPE,
            target_id=rid, target_name=title,
            detail={'summary': '删除规章及附件'},
        )
        return json_response(data={'status': 'deleted'})


class RegulationRetireView(View):
    """废止规章

    将状态置为 retired。
    """

    @auth('document.regulation.edit')
    @transaction.atomic
    def post(self, request, pk):
        regulation = _get_regulation(pk)
        if regulation is None:
            return json_response(error='规章不存在')

        if regulation.status == Regulation.STATUS_RETIRED:
            return json_response(data={'status': 'retired', 'message': '规章已废止'})

        regulation.status = Regulation.STATUS_RETIRED
        regulation.updated_by = request.user
        regulation.updated_at = human_datetime()
        regulation.save()

        record_audit_event(
            request, 'retire', AUDIT_TARGET_TYPE,
            target_id=regulation.id, target_name=regulation.title,
            detail={'status': regulation.status},
        )
        return json_response(data=_serialize_regulation(regulation))


# ==================== 附件管理 View ====================

class RegulationAttachmentListView(View):
    """规章附件列表

    GET /api/regulation/<id>/attachments/
    权限：document.regulation.view
    """

    @auth('document.regulation.view')
    def get(self, request, pk):
        regulation = _get_regulation(pk)
        if regulation is None:
            return json_response(error='规章不存在')
        attachments = regulation.attachments.filter(
            is_deleted=False
        ).order_by('sort_order', '-id')
        return json_response(data=[_serialize_attachment(att) for att in attachments])


class RegulationAttachmentUploadView(View):
    """上传规章附件

    POST /api/regulation/<id>/attachments/upload/
    Content-Type: multipart/form-data
    权限：document.regulation.upload

    参数：
      file: 文件（必填）
      sort_order: 排序（可选，默认 0）
    """

    @auth('document.regulation.upload')
    @transaction.atomic
    def post(self, request, pk):
        regulation = _get_regulation(pk)
        if regulation is None:
            return json_response(error='规章不存在')

        file = request.FILES.get('file')
        if not file:
            return json_response(error='请选择要上传的文件')

        # 校验文件大小
        if file.size > storage.MAX_FILE_SIZE:
            max_mb = storage.MAX_FILE_SIZE // 1024 // 1024
            return json_response(error=f'文件大小不能超过 {max_mb}MB')

        # 校验文件类型
        ext = storage.extract_extension(file.name)
        if ext not in storage.ALLOWED_EXTENSIONS:
            return json_response(error=f'不支持的文件类型: {ext or "无扩展名"}')

        try:
            sort_order = int(request.POST.get('sort_order', '0') or '0')
        except ValueError:
            sort_order = 0

        # 生成存储路径
        stored_name = storage.build_stored_name(file.name)
        relative_path = storage.build_relative_path(regulation.id, stored_name)
        try:
            abs_path = storage.resolve_absolute_path(relative_path)
        except ValueError as e:
            return json_response(error=str(e))

        # 写入文件并计算 MD5
        file_hash = storage.save_upload_file(file, abs_path)

        # 创建附件记录
        att = RegulationAttachment.objects.create(
            regulation=regulation,
            original_name=file.name,
            stored_name=stored_name,
            file_path=relative_path,
            file_size=file.size,
            file_type=ext.lstrip('.'),
            file_hash=file_hash,
            sort_order=sort_order,
            uploaded_by=request.user,
        )

        record_audit_event(
            request, 'upload_attachment', AUDIT_TARGET_TYPE,
            target_id=regulation.id, target_name=regulation.title,
            detail={'attachment_id': att.id, 'file_name': att.original_name,
                    'file_size': att.file_size},
        )
        return json_response(data=_serialize_attachment(att))


class RegulationAttachmentDownloadView(View):
    """下载规章附件

    GET /api/regulation/<id>/attachments/<att_id>/download/
    权限：document.regulation.download

    支持 ?inline=1 参数，返回 Content-Disposition: inline 用于浏览器原生预览图片/PDF。
    """

    @auth('document.regulation.download')
    def get(self, request, pk, att_id):
        regulation = _get_regulation(pk)
        if regulation is None:
            return json_response(error='规章不存在')
        att = _get_attachment(regulation, att_id)
        if att is None:
            return json_response(error='附件不存在')

        try:
            abs_path = storage.resolve_absolute_path(att.file_path)
        except ValueError:
            return json_response(error='文件不存在')

        if not abs_path or not os.path.exists(abs_path):
            return json_response(error='文件不存在')

        encoded_filename = quote(att.original_name)
        inline = request.GET.get('inline') in ('1', 'true', 'True')

        if inline:
            content_type, _ = mimetypes.guess_type(att.original_name)
            if not content_type:
                content_type = 'application/octet-stream'
            disposition = 'inline'
        else:
            content_type = 'application/octet-stream'
            disposition = 'attachment'

        response = FileResponse(
            open(abs_path, 'rb'),
            content_type=content_type,
        )
        response['Content-Disposition'] = (
            f'{disposition}; filename="{encoded_filename}"; '
            f'filename*=UTF-8\'\'{encoded_filename}'
        )
        response['Content-Length'] = os.path.getsize(abs_path)

        record_audit_event(
            request, 'download_attachment', AUDIT_TARGET_TYPE,
            target_id=regulation.id, target_name=regulation.title,
            detail={'attachment_id': att.id, 'file_name': att.original_name, 'inline': inline},
        )
        return response


class RegulationAttachmentPreviewUrlView(View):
    """获取 kkFileView 在线预览地址

    GET /api/regulation/<id>/attachments/<att_id>/preview-url/
    权限：document.regulation.view（能查看规章即可预览）

    返回短时效 preview_token + kkFileView 预览 URL，避免在 URL 中暴露长期 x-token。
    """

    @auth('document.regulation.view')
    def get(self, request, pk, att_id):
        regulation = _get_regulation(pk)
        if regulation is None:
            return json_response(error='规章不存在')
        att = _get_attachment(regulation, att_id)
        if att is None:
            return json_response(error='附件不存在')

        ext = storage.extract_extension(att.original_name)
        if ext not in storage.PREVIEWABLE_EXTENSIONS:
            return json_response(error='该文件类型不支持在线预览')

        preview_token = generate_attachment_preview_token(
            attachment_id=att.id,
            user_id=request.user.id,
            tenant_id='',
            module=storage.PREVIEW_MODULE,
            object_type=storage.PREVIEW_OBJECT_TYPE,
            object_id=str(regulation.id),
        )

        preview_file_api_path = (
            f'/api/regulation/{regulation.id}/attachments/{att.id}/preview-file/'
        )

        # 图片/PDF 走浏览器原生预览，但仍使用短时效 preview_token 鉴权。
        if ext in storage.IMAGE_EXTENSIONS or ext in storage.PDF_EXTENSIONS:
            inline_url = f'{preview_file_api_path}?preview_token={quote(preview_token)}'
            return json_response(data={
                'preview_url': inline_url,
                'file_name': att.original_name,
                'preview_type': 'native',
            })

        # Office/文本走 kkFileView。
        kkfileview_api_url = getattr(settings, 'KKFILEVIEW_API_URL', '')
        kkfileview_server_url = getattr(settings, 'KKFILEVIEW_SERVER_URL', '')
        if not kkfileview_api_url or not kkfileview_server_url:
            return json_response(error='Office文档预览服务未配置，请联系管理员')

        file_url = (
            f'{kkfileview_server_url}{preview_file_api_path}'
            f'?preview_token={quote(preview_token)}'
            f'&fullfilename={quote(att.original_name)}'
        )
        encoded_url = base64.b64encode(file_url.encode('utf-8')).decode('utf-8')
        preview_url = f'{kkfileview_api_url}/onlinePreview?url={encoded_url}'

        return json_response(data={
            'preview_url': preview_url,
            'file_name': att.original_name,
            'preview_type': 'kkfileview',
        })


class RegulationAttachmentPreviewFileView(View):
    """kkFileView 回调读取文件流

    GET /api/regulation/<id>/attachments/<att_id>/preview-file/
    无 @auth 装饰器，由中间件通过 preview_token 鉴权（ATTACHMENT_PREVIEW_PATTERNS 匹配）。

    校验流程：
    1. 验证 preview_token 签名和时效
    2. 校验 token 中的 attachment_id 与 URL 中的 att_id 一致
    3. 校验附件未删除、属于当前规章
    4. 校验 token 绑定信息（module/object_type/object_id）与附件一致
    5. 返回 FileResponse，Content-Disposition: inline
    """

    def get(self, request, pk, att_id):
        preview_token = request.GET.get('preview_token')
        if not preview_token:
            return json_response(error='缺少 preview_token 参数')

        token_data = validate_attachment_preview_token(preview_token)
        if not token_data:
            return json_response(error='预览令牌无效或已过期')

        # 校验 attachment_id 一致
        if token_data['attachment_id'] != int(att_id):
            logger.warning(
                f'[Regulation] preview_token attachment_id mismatch: '
                f'token={token_data["attachment_id"]}, request={att_id}'
            )
            return json_response(error='预览令牌与请求附件不匹配')

        regulation = _get_regulation(pk)
        if regulation is None:
            return json_response(error='规章不存在')

        try:
            att = regulation.attachments.get(pk=att_id)
        except (RegulationAttachment.DoesNotExist, ValueError, TypeError):
            return json_response(error='附件不存在')

        if att.is_deleted:
            return json_response(error='附件已删除')

        # 校验 token 绑定信息
        if (token_data['module'] != storage.PREVIEW_MODULE
                or token_data['object_type'] != storage.PREVIEW_OBJECT_TYPE
                or str(token_data['object_id']) != str(regulation.id)):
            logger.warning(
                f'[Regulation] preview_token binding mismatch for attachment {att_id}: '
                f'token module={token_data["module"]}/object_type={token_data["object_type"]}/'
                f'object_id={token_data["object_id"]} vs '
                f'expected module={storage.PREVIEW_MODULE}/'
                f'object_type={storage.PREVIEW_OBJECT_TYPE}/'
                f'object_id={regulation.id}'
            )
            return json_response(error='预览令牌无效')

        try:
            abs_path = storage.resolve_absolute_path(att.file_path)
        except ValueError:
            return json_response(error='文件不存在')

        if not abs_path or not os.path.exists(abs_path):
            return json_response(error='文件不存在')

        encoded_filename = quote(att.original_name)
        content_type, _ = mimetypes.guess_type(att.original_name)
        if not content_type:
            content_type = 'application/octet-stream'

        response = FileResponse(
            open(abs_path, 'rb'),
            content_type=content_type,
        )
        response['Content-Disposition'] = (
            f'inline; filename="{encoded_filename}"; '
            f'filename*=UTF-8\'\'{encoded_filename}'
        )
        response['Content-Length'] = os.path.getsize(abs_path)
        return response


class RegulationAttachmentDetailView(View):
    """删除规章附件（软删除）

    DELETE /api/regulation/<id>/attachments/<att_id>/
    权限：document.regulation.upload
    """

    @auth('document.regulation.upload')
    @transaction.atomic
    def delete(self, request, pk, att_id):
        regulation = _get_regulation(pk)
        if regulation is None:
            return json_response(error='规章不存在')
        att = _get_attachment(regulation, att_id)
        if att is None:
            return json_response(error='附件不存在')

        att.is_deleted = True
        att.deleted_by = request.user
        att.deleted_at = human_datetime()
        att.save(update_fields=['is_deleted', 'deleted_by', 'deleted_at'])

        # 尝试清理物理文件，失败不影响数据库状态
        try:
            abs_path = storage.resolve_absolute_path(att.file_path)
            storage.safe_delete_attachment_file(abs_path)
        except ValueError as e:
            logger.warning(f'[Regulation] 跳过附件物理文件清理: att_id={att.id}, error={e}')

        record_audit_event(
            request, 'delete_attachment', AUDIT_TARGET_TYPE,
            target_id=regulation.id, target_name=regulation.title,
            detail={'attachment_id': att.id, 'file_name': att.original_name},
        )
        return json_response(data={'status': 'deleted'})


