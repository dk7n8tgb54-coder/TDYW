# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——原生维护台账模板模型（Univer 在线编辑路线，2026-10-18 接入）。

与 Excel 上传版模板（excel_models.py）长期并行，共用正式维护台账的
编号、权限、租户、状态与审计规则；模型结构对齐 Excel 三件套：

- OperationLedgerNativeTemplate       模板 = 草稿容器（Univer 快照 + 绑定 + 纸张）
- OperationLedgerNativeTemplateVersion 发布 = 草稿快照为不可变版本（只增不改不删，
  不存在修改/删除版本的服务函数与视图方法）
- OperationLedgerNativeRecord         台账填写记录，与正式台账 OperationLedger
  一对一，创建即固定引用某已发布版本（PROTECT），历史台账详情/打印/导出
  全部读取该版本快照，不读当前草稿。

与 Excel 路线的差异：原生模板没有物理源文件（版式即 Univer 快照 JSON，
直接落库，无文件存储与哈希比对）；台账行复用 OperationLedger，
created_from='native_template'（models.py 来源枚举，迁移同步放宽 CHECK）。
models.py 在文件底部导入本模块完成模型注册（本文件不反向 import models，
ledger_type CHECK 用字面枚举，一致性由契约测试守护）。
"""
import json

from django.db import models

from apps.account.models import User
from apps.equipment_lifecycle.excel_field_types import LongTextField
from libs.tenant_base_model import TenantModelManager, TenantModelMixin, make_tenant_id

# 原生绑定字段类型（前端编辑器绑定面板枚举；status=正常/不正常二选一）
NATIVE_BINDING_TYPE_TEXT = 'text'
NATIVE_BINDING_TYPE_NUMBER = 'number'
NATIVE_BINDING_TYPE_DATE = 'date'
NATIVE_BINDING_TYPE_STATUS = 'status'
NATIVE_BINDING_TYPE_TEXTAREA = 'textarea'
NATIVE_BINDING_TYPE_VALUES = [
    NATIVE_BINDING_TYPE_TEXT, NATIVE_BINDING_TYPE_NUMBER, NATIVE_BINDING_TYPE_DATE,
    NATIVE_BINDING_TYPE_STATUS, NATIVE_BINDING_TYPE_TEXTAREA,
]

# status 类型绑定候选值（与前端 FieldOverlay 下拉一致）
NATIVE_STATUS_NORMAL = '正常'
NATIVE_STATUS_ABNORMAL = '不正常'
NATIVE_STATUS_VALUES = [NATIVE_STATUS_NORMAL, NATIVE_STATUS_ABNORMAL]

# 纸张设置协议（打印/PDF 读取该设置分页）
NATIVE_PAPER_SIZES = {'A4': (210, 297), 'A3': (297, 420)}
NATIVE_PAPER_ORIENTATIONS = ['portrait', 'landscape']


class OperationLedgerNativeTemplate(TenantModelMixin, models.Model):
    """原生维护台账模板：草稿容器 + 不可变发布版本（结构对齐 Excel 模板）。

    - ledger_type 复用台账类型枚举（周月维护/季维护），创建后不可修改；
    - 草稿 = 当前 Univer 快照（版式与静态内容）+ 字段绑定 + 纸张设置，
      整体 JSON 落库（无物理文件）；保存为整体替换；
    - 发布版本见 OperationLedgerNativeTemplateVersion，本表不冗余版本内容；
    - 不参与本期应填台账自动生成（生成配置/适用系统字段不建，周期批量
      生成仍只面向 Excel 模板）。
    """

    name = models.CharField(max_length=100, help_text='模板名称')
    ledger_type = models.CharField(max_length=20, help_text='台账类型（创建后不可修改）')
    description = models.CharField(max_length=500, default='', blank=True, help_text='说明')
    draft_snapshot = LongTextField(
        default='', blank=True, help_text='当前草稿 Univer 工作簿快照 JSON（空为无草稿）')
    draft_bindings = LongTextField(
        default='', blank=True, help_text='当前草稿字段绑定 JSON 数组（空为未绑定）')
    draft_paper = LongTextField(
        default='', blank=True, help_text='当前草稿纸张/打印设置 JSON（空用内置缺省）')
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
        db_table = 'tdyw_el_ledger_native_template'
        verbose_name = '原生台账模板'
        verbose_name_plural = '原生台账模板'
        ordering = ('-created_at', '-id')
        constraints = [
            models.CheckConstraint(
                check=models.Q(ledger_type__in=['week_month', 'seasonal']),
                name='el_ledger_native_template_type_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'ledger_type']),
        ]

    def __repr__(self):
        return '<OperationLedgerNativeTemplate %r>' % self.name

    def to_view(self, latest_version_no=None, versions_count=None, ledgers_count=None):
        return {
            'id': self.id,
            'name': self.name,
            'ledger_type': self.ledger_type,
            'description': self.description,
            'is_active': self.is_active,
            'has_draft': bool(self.draft_snapshot),
            'has_draft_bindings': bool(self.draft_bindings),
            'draft_updated_at': self.draft_updated_at,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'latest_version_no': latest_version_no,
            'versions_count': versions_count,
            'ledgers_count': ledgers_count,
            'status': self.display_status(latest_version_no, ledgers_count),
        }

    def display_status(self, latest_version_no=None, ledgers_count=None):
        """模板四态：deleted | used | published | draft（与 Excel 模板口径一致）。"""
        if not self.is_active:
            return 'deleted'
        if ledgers_count:
            return 'used'
        return 'published' if latest_version_no else 'draft'


class OperationLedgerNativeTemplateVersion(TenantModelMixin, models.Model):
    """原生模板发布版本：发布即快照，快照/绑定/纸张不可变（只增不改不删）。

    - version_no 模板内从 1 递增，(template, version_no) 唯一；
    - snapshot/bindings/paper 为发布时通过发布级校验的快照，读取端原样
      返回；template_name_snapshot 固定发布时的模板名称（改名不回溯）；
    - 台账创建即固定引用某版本（OperationLedgerNativeRecord.version，
      PROTECT：被引用后版本不可删），历史台账详情与 PDF 全部读该快照；
    - 不存在修改/删除版本的服务函数与视图方法（写方法缺失即 405）。
    """

    template = models.ForeignKey(
        OperationLedgerNativeTemplate, models.CASCADE, related_name='versions',
        help_text='所属模板')
    version_no = models.IntegerField(help_text='模板内递增版本号，从 1 开始')
    template_name_snapshot = models.CharField(max_length=100, help_text='模板名称快照（发布时）')
    snapshot = LongTextField(help_text='Univer 工作簿快照 JSON（发布后不可变）')
    bindings = LongTextField(help_text='字段绑定快照 JSON 数组（发布后不可变）')
    paper = LongTextField(default='', blank=True, help_text='纸张/打印设置快照 JSON')
    field_count = models.IntegerField(default=0, help_text='填写字段数量（发布时校验产出）')
    published_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    published_at = models.DateTimeField(auto_now_add=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_ledger_native_version'
        verbose_name = '原生台账模板版本'
        verbose_name_plural = '原生台账模板版本'
        ordering = ('-version_no',)
        constraints = [
            models.UniqueConstraint(
                fields=['template', 'version_no'], name='el_ledger_native_version_no_unique'),
            models.CheckConstraint(
                check=models.Q(version_no__gte=1), name='el_ledger_native_version_no_valid'),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'template']),
        ]

    def __repr__(self):
        return '<OperationLedgerNativeTemplateVersion %r v%s>' % (
            self.template_name_snapshot, self.version_no)

    def get_bindings(self):
        """绑定快照列表（内容损坏返回空列表，防御性分支）。"""
        return _loads_list(self.bindings)

    def get_snapshot(self):
        """工作簿快照 dict（内容损坏返回空 dict，防御性分支）。"""
        return _loads_dict(self.snapshot)

    def get_paper(self):
        """纸张设置 dict（空/损坏返回空 dict，打印端用内置缺省兜底）。"""
        return _loads_dict(self.paper)

    def to_view(self, with_content=False):
        data = {
            'id': self.id,
            'template': self.template_id,
            'version_no': self.version_no,
            'template_name': self.template_name_snapshot,
            'ledger_type': self.template.ledger_type if self.template else '',
            'field_count': self.field_count,
            'published_at': self.published_at,
        }
        if with_content:
            data['snapshot'] = self.get_snapshot()
            data['bindings'] = self.get_bindings()
            data['paper'] = self.get_paper()
        return data


class OperationLedgerNativeRecord(TenantModelMixin, models.Model):
    """原生台账填写记录：与正式台账 OperationLedger 一对一（对齐 Excel 记录）。

    - version 固定台账创建时引用的模板版本（PROTECT），版本不可变保证
      填写值语义与版式永不漂移；
    - values 为填写值 JSON（绑定 key -> 值），草稿与完成后同列保存，
      完成后修改走更正接口并留痕。
    """

    ledger = models.OneToOneField(
        'OperationLedger', models.CASCADE, related_name='native_record',
        help_text='所属正式台账')
    version = models.ForeignKey(
        OperationLedgerNativeTemplateVersion, models.PROTECT, related_name='ledger_records',
        help_text='创建时引用的模板版本（不可变）')
    values = LongTextField(default='', blank=True, help_text='填写值 JSON（绑定 key -> 值）')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_ledger_native_record'
        verbose_name = '原生台账填写记录'
        verbose_name_plural = '原生台账填写记录'
        ordering = ('-id',)
        indexes = [
            models.Index(fields=['tenant_id', 'version']),
        ]

    def __repr__(self):
        return '<OperationLedgerNativeRecord ledger=%s v%s>' % (
            self.ledger_id, self.version_id)

    def get_values(self):
        """填写值 dict（空或内容损坏返回空 dict，防御性分支）。"""
        return _loads_dict(self.values)


def _loads_list(raw):
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (ValueError, TypeError):
        return []


def _loads_dict(raw):
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}
