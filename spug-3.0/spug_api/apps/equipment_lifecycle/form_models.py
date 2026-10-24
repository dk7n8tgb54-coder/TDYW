# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——数字表单台账模板模型（结构化表单路线，2026-10-21）。

与 Excel 路线（excel_models.py）平行的独立路线：模板 = 结构化表单草稿
（分组/字段/明细组/矩阵的 JSON 定义），发布 = 草稿快照为不可变版本，
台账填写结果以稳定 field_id 为键存 JSON（不落文件系统，全部入库）。

- 模板/版本/填写记录三表与 Excel 专属模型完全隔离，不共用草稿与版本
  存储；台账表头复用正式 OperationLedger（created_from=form_template，
  source_form_template 外键指回本模板），周期生成/状态机/编号/审计/
  附件等公共能力由既有模块承载；
- 发布后版本不可原地修改（不存在修改/删除版本的服务函数与视图方法），
  修改模板应重新编辑草稿并发布新版本；历史台账经 OperationLedgerFormRecord
  继续引用创建时版本，模板修改不改变历史记录的字段含义；
- models.py 在文件底部导入本模块完成模型注册（本文件不反向 import models，
  ledger_type CHECK 用字面枚举，一致性由契约测试守护）；
- 生成周期复用 excel_models 的 TEMPLATE_PERIOD_* 枚举（一模板一系统、
  weekly/monthly/seasonal 语义与 Excel 路线完全一致，见该模块注释）。
"""
import json

from django.db import models

from apps.account.models import User
from apps.equipment_lifecycle.excel_field_types import LongTextField
from libs.tenant_base_model import TenantModelManager, TenantModelMixin, make_tenant_id


class OperationLedgerFormTemplate(TenantModelMixin, models.Model):
    """数字表单台账模板：草稿容器 + 不可变发布版本。

    - ledger_type 复用台账类型枚举（周月维护/季维护），创建后不可修改；
    - 草稿 = 结构化表单定义 JSON（draft_form），发布时整体校验并快照；
    - system/generation_period 语义与 Excel 模板一致：一模板一系统，
      生成周期显式声明（周月维护=weekly/monthly，季维护=seasonal），
      空=待配置，不参与自动生成、不影响手工创建；
    - 发布版本见 OperationLedgerFormTemplateVersion，本表不冗余版本内容。
    """

    name = models.CharField(max_length=100, help_text='模板名称')
    ledger_type = models.CharField(max_length=20, help_text='台账类型（创建后不可修改）')
    description = models.CharField(max_length=500, default='', blank=True, help_text='说明')
    system = models.ForeignKey(
        'LifecycleSystem', models.PROTECT, related_name='form_ledger_templates',
        null=True, blank=True,
        help_text='唯一适用系统（空=待配置；一模板只对应一个系统，同系统可多模板）')
    generation_period = models.CharField(
        max_length=10, default='', blank=True,
        help_text='生成周期（week_month: weekly 每周 / monthly 每月；seasonal: seasonal 每航季；'
                  '空=待配置，仅用于本期应填台账自动生成，不影响手工创建')
    draft_form = LongTextField(
        default='', blank=True, help_text='当前草稿表单定义 JSON（分组/字段/明细组/矩阵）')
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
        db_table = 'tdyw_el_ledger_form_template'
        verbose_name = '数字表单台账模板'
        verbose_name_plural = '数字表单台账模板'
        ordering = ('-created_at', '-id')
        constraints = [
            models.CheckConstraint(
                check=models.Q(ledger_type__in=['week_month', 'seasonal']),
                name='el_ledger_form_template_type_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'ledger_type']),
        ]

    def __repr__(self):
        return '<OperationLedgerFormTemplate %r>' % self.name

    def to_view(self, latest_version_no=None, versions_count=None, ledgers_count=None):
        return {
            'id': self.id,
            'name': self.name,
            'ledger_type': self.ledger_type,
            'description': self.description,
            'system': self.system_id,
            'system_name': self.system.name if self.system_id else '',
            'system_code': self.system.system_code if self.system_id else '',
            'generation_period': self.generation_period,
            'is_active': self.is_active,
            'has_draft': bool(self.draft_form),
            'draft_updated_at': self.draft_updated_at,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'latest_version_no': latest_version_no,
            'versions_count': versions_count,
            'ledgers_count': ledgers_count,
            'status': self.display_status(latest_version_no, ledgers_count),
        }

    def display_status(self, latest_version_no=None, ledgers_count=None):
        """模板四态：deleted | used | published | draft（与 Excel 模板同口径）。"""
        if not self.is_active:
            return 'deleted'
        if ledgers_count:
            return 'used'
        return 'published' if latest_version_no else 'draft'


class OperationLedgerFormTemplateVersion(TenantModelMixin, models.Model):
    """数字表单模板发布版本：发布即快照，表单定义不可变（只增不改不删）。

    - version_no 模板内从 1 递增，(template, version_no) 唯一；
    - form 为发布时通过发布级校验的表单定义快照，读取端原样返回；
    - field_count = 可填写字段总数（普通字段 + 明细组字段 + 矩阵行）；
    - template_name_snapshot 固定发布时的模板名称（模板改名不回溯版本）；
    - 不存在修改/删除版本的服务函数与视图方法（写方法缺失即 405）。
    """

    template = models.ForeignKey(
        OperationLedgerFormTemplate, models.CASCADE, related_name='versions',
        help_text='所属模板')
    version_no = models.IntegerField(help_text='模板内递增版本号，从 1 开始')
    template_name_snapshot = models.CharField(max_length=100, help_text='模板名称快照（发布时）')
    form = LongTextField(help_text='表单定义快照 JSON（发布后不可变）')
    field_count = models.IntegerField(default=0, help_text='可填写字段总数（发布时校验产出）')
    published_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    published_at = models.DateTimeField(auto_now_add=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_ledger_form_version'
        verbose_name = '数字表单台账模板版本'
        verbose_name_plural = '数字表单台账模板版本'
        ordering = ('-version_no',)
        constraints = [
            models.UniqueConstraint(
                fields=['template', 'version_no'], name='el_ledger_form_version_no_unique'),
            models.CheckConstraint(
                check=models.Q(version_no__gte=1), name='el_ledger_form_version_no_valid'),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'template']),
        ]

    def __repr__(self):
        return '<OperationLedgerFormTemplateVersion %r v%s>' % (
            self.template_name_snapshot, self.version_no)

    def get_form(self):
        """表单定义快照 dict（内容损坏返回空 dict，防御性分支）。"""
        if not self.form:
            return {}
        try:
            data = json.loads(self.form)
        except (ValueError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

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
            data['form'] = self.get_form()
        return data


class OperationLedgerFormRecord(TenantModelMixin, models.Model):
    """数字表单台账填写记录：与正式台账 OperationLedger 一对一。

    - version 固定台账创建时引用的模板版本（PROTECT：版本被台账引用后
      不可删除），历史台账详情据此回放当时的表单结构；
    - values 为填写值 JSON，键为稳定 field_id / 组 id（明细组值为行数组、
      矩阵组值为 行id→列id→值 嵌套 dict），normal_abnormal 字段的异常说明
      以 `<field_id>__desc` 键存放；版本不可变保证填写值语义永不漂移。
    """

    ledger = models.OneToOneField(
        'OperationLedger', models.CASCADE, related_name='form_record',
        help_text='所属正式台账')
    version = models.ForeignKey(
        OperationLedgerFormTemplateVersion, models.PROTECT, related_name='form_ledger_records',
        help_text='创建时引用的模板版本（不可变）')
    values = LongTextField(default='', blank=True, help_text='填写值 JSON（field_id -> 值）')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_ledger_form_record'
        verbose_name = '数字表单台账填写记录'
        verbose_name_plural = '数字表单台账填写记录'
        ordering = ('-id',)
        indexes = [
            models.Index(fields=['tenant_id', 'version']),
        ]

    def __repr__(self):
        return '<OperationLedgerFormRecord ledger=%s v%s>' % (
            self.ledger_id, self.version_id)

    def get_values(self):
        """填写值 dict（空或内容损坏返回空 dict，防御性分支）。"""
        if not self.values:
            return {}
        try:
            data = json.loads(self.values)
        except (ValueError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}
