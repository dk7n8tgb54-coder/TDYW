# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——Excel 上传版维护台账模板模型（固定版式，2026-09-28 试点）。

- 模板 = 草稿容器（源文件哈希 + 布局 meta + 字段绑定），发布 = 草稿快照为
  不可变版本，版本原始 .xlsx 文件独立保存（文件存储见 excel_template_storage）；
- 发布后版本与文件不可原地修改（不存在修改/删除版本的服务函数与视图方法），
  修改模板应重新编辑草稿并发布新版本，历史台账继续引用创建时的版本；
- 台账接入：OperationLedgerExcelRecord 与正式台账 OperationLedger 一对一，
  保存所用版本与填写值；台账行本身复用既有状态机与 ledger_no；
- models.py 在文件底部导入本模块完成模型注册（本文件不反向 import models，
  ledger_type CHECK 用字面枚举，一致性由契约测试守护）。
"""
import json

from django.db import models

from apps.account.models import User
from apps.equipment_lifecycle.excel_field_types import LongTextField
from libs.tenant_base_model import TenantModelManager, TenantModelMixin, make_tenant_id


class OperationLedgerExcelTemplate(TenantModelMixin, models.Model):
    """Excel 上传版维护台账模板：草稿容器 + 不可变发布版本。

    - ledger_type 复用台账类型枚举（周月维护/季维护），创建后不可修改；
    - 草稿 = 当前上传的源文件（存储按模板 id 定位）+ 布局 meta + 字段绑定；
      重新上传源文件后布局重建、原绑定清空（坐标可能已失效）；
    - 发布版本见 OperationLedgerExcelTemplateVersion，本表不冗余版本内容。
    """

    name = models.CharField(max_length=100, help_text='模板名称')
    ledger_type = models.CharField(max_length=20, help_text='台账类型（创建后不可修改）')
    description = models.CharField(max_length=500, default='', blank=True, help_text='说明')
    draft_source_filename = models.CharField(
        max_length=200, default='', blank=True, help_text='当前草稿源文件名（空为无草稿）')
    draft_source_hash = models.CharField(
        max_length=64, default='', blank=True, help_text='当前草稿源文件 SHA-256')
    draft_layout = LongTextField(
        default='', blank=True, help_text='当前草稿布局 meta JSON（工作表/合并/样式/打印设置）')
    draft_bindings = LongTextField(
        default='', blank=True, help_text='当前草稿字段绑定 JSON 数组（空为未绑定）')
    draft_updated_at = models.DateTimeField(null=True, blank=True, help_text='草稿最后更新时间')
    draft_updated_by = models.ForeignKey(
        User, models.PROTECT, related_name='+', null=True, help_text='草稿最后更新人')
    is_active = models.BooleanField(default=True, help_text='是否启用（停用后不能用于新台账）')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_ledger_excel_template'
        verbose_name = 'Excel台账模板'
        verbose_name_plural = 'Excel台账模板'
        ordering = ('-created_at', '-id')
        constraints = [
            models.CheckConstraint(
                check=models.Q(ledger_type__in=['week_month', 'seasonal']),
                name='el_ledger_excel_template_type_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'ledger_type']),
        ]

    def __repr__(self):
        return '<OperationLedgerExcelTemplate %r>' % self.name

    def to_view(self, latest_version_no=None, versions_count=None,
                ledgers_count=None):
        view = {
            'id': self.id,
            'name': self.name,
            'ledger_type': self.ledger_type,
            'description': self.description,
            'is_active': self.is_active,
            'draft_source_filename': self.draft_source_filename,
            'draft_source_hash': self.draft_source_hash,
            'has_draft_bindings': bool(self.draft_bindings),
            'draft_updated_at': self.draft_updated_at,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'latest_version_no': latest_version_no,
            'versions_count': versions_count,
            'ledgers_count': ledgers_count,
            'status': self.display_status(latest_version_no, ledgers_count),
        }
        return view

    def display_status(self, latest_version_no=None, ledgers_count=None):
        """模板四态：deleted | used | published | draft（前端文案映射）。"""
        if not self.is_active:
            return 'deleted'
        if ledgers_count:
            return 'used'
        return 'published' if latest_version_no else 'draft'


class OperationLedgerExcelTemplateVersion(TenantModelMixin, models.Model):
    """Excel 模板发布版本：发布即快照，文件与绑定不可变（只增不改不删）。

    - version_no 模板内从 1 递增，(template, version_no) 唯一；
    - 原始 .xlsx 文件按 (template_id, version_no) 定位独立保存，SHA-256
      落库（source_hash），发布时与草稿哈希比对确保字节一致；
    - layout/bindings 为发布时通过发布级校验的快照，读取端原样返回；
    - template_name_snapshot 固定发布时的模板名称（模板改名不回溯版本）；
    - 不存在修改/删除版本的服务函数与视图方法（写方法缺失即 405）。
    """

    template = models.ForeignKey(
        OperationLedgerExcelTemplate, models.CASCADE, related_name='versions',
        help_text='所属模板')
    version_no = models.IntegerField(help_text='模板内递增版本号，从 1 开始')
    template_name_snapshot = models.CharField(max_length=100, help_text='模板名称快照（发布时）')
    source_filename = models.CharField(max_length=200, help_text='原始 .xlsx 文件名')
    source_hash = models.CharField(max_length=64, help_text='原始 .xlsx SHA-256')
    layout = LongTextField(help_text='工作表布局快照 JSON（发布后不可变）')
    bindings = LongTextField(help_text='字段绑定快照 JSON 数组（发布后不可变）')
    field_count = models.IntegerField(default=0, help_text='填写字段数量（发布时校验产出）')
    published_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    published_at = models.DateTimeField(auto_now_add=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_ledger_excel_version'
        verbose_name = 'Excel台账模板版本'
        verbose_name_plural = 'Excel台账模板版本'
        ordering = ('-version_no',)
        constraints = [
            models.UniqueConstraint(
                fields=['template', 'version_no'], name='el_ledger_excel_version_no_unique'),
            models.CheckConstraint(
                check=models.Q(version_no__gte=1), name='el_ledger_excel_version_no_valid'),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'template']),
        ]

    def __repr__(self):
        return '<OperationLedgerExcelTemplateVersion %r v%s>' % (
            self.template_name_snapshot, self.version_no)

    def get_bindings(self):
        """绑定快照列表（内容损坏返回空列表，防御性分支）。"""
        if not self.bindings:
            return []
        try:
            data = json.loads(self.bindings)
            return data if isinstance(data, list) else []
        except (ValueError, TypeError):
            return []

    def get_layout(self):
        """布局快照 dict（内容损坏返回空 dict，防御性分支）。"""
        if not self.layout:
            return {}
        try:
            data = json.loads(self.layout)
            return data if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            return {}

    def to_view(self, with_content=False):
        data = {
            'id': self.id,
            'template': self.template_id,
            'version_no': self.version_no,
            'template_name': self.template_name_snapshot,
            'ledger_type': self.template.ledger_type if self.template else '',
            'source_filename': self.source_filename,
            'source_hash': self.source_hash,
            'field_count': self.field_count,
            'published_at': self.published_at,
        }
        if with_content:
            # 布局快照拍平：layout 与原型解析 meta 的 layout 部分同构
            # （{active_sheet, sheets}），sheet_name 单列，避免嵌套取值；
            # pdf_params 为模板级 PDF 打印参数（旧版本快照缺省为空 dict）
            part = self.get_layout()
            data['layout'] = part.get('layout') or {}
            data['sheet_name'] = part.get('sheet_name')
            data['pdf_params'] = part.get('pdf_params') or {}
            data['bindings'] = self.get_bindings()
        return data


class OperationLedgerExcelRecord(TenantModelMixin, models.Model):
    """Excel 台账填写记录：与正式台账 OperationLedger 一对一。

    - version 固定台账创建时引用的模板版本（PROTECT：版本被台账引用后
      不可删除），历史台账详情据此回放当时的字段、绑定与版式；
    - values 为填写值 JSON（field_id -> 值），草稿与提交后同列保存；
      版本不可变保证填写值语义永不漂移。
    """

    ledger = models.OneToOneField(
        'OperationLedger', models.CASCADE, related_name='excel_record',
        help_text='所属正式台账')
    version = models.ForeignKey(
        OperationLedgerExcelTemplateVersion, models.PROTECT, related_name='ledger_records',
        help_text='创建时引用的模板版本（不可变）')
    values = LongTextField(default='', blank=True, help_text='填写值 JSON（field_id -> 值）')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_ledger_excel_record'
        verbose_name = 'Excel台账填写记录'
        verbose_name_plural = 'Excel台账填写记录'
        ordering = ('-id',)
        indexes = [
            models.Index(fields=['tenant_id', 'version']),
        ]

    def __repr__(self):
        return '<OperationLedgerExcelRecord ledger=%s v%s>' % (
            self.ledger_id, self.version_id)

    def get_values(self):
        """填写值 dict（空或内容损坏返回空 dict，防御性分支）。"""
        if not self.values:
            return {}
        try:
            data = json.loads(self.values)
            return data if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            return {}
