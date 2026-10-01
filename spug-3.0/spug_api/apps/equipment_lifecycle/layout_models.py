# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——设计器维护台账模板模型（已下线，休眠保留，2026-09-29）。

在线设计器路线（/el/ledger-designer + layout-templates API + layout_services）
已于 2026-09-29 整体下线：视图、服务、路由与前端页面均已删除，业务代码
不存在任何访问本模块模型的路径。两个模型类仍保持注册（models.py 底部
导入）并保留 0039 迁移对应的历史表与数据，原因：

- migrations/0039_ledger_layout_templates.py 序列化引用
  ``apps.equipment_lifecycle.layout_models.LongTextField``（历史迁移不改写，
  测试库/全新环境重放迁移必须可解析），本模块的 LongTextField 定义因此
  不可迁移或删除（Excel 路线改用 excel_field_types.LongTextField）；
- 若注销模型，makemigrations 将生成 DeleteModel 并在下次 migrate 时删除
  历史表与数据，违背「保留历史表和历史数据」的保守处理原则；保持注册
  可使模型状态与迁移状态一致（makemigrations 无变更）。

Excel 模板（excel_models，2026-09-28 试点）与设计器模板互不转换、互不引用；
本模块不反向导入 models.py（models.py 底部导入本模块，避免循环）。
"""
import json

from django.db import models

from apps.account.models import User
from libs.tenant_base_model import TenantModelManager, TenantModelMixin, make_tenant_id


class LongTextField(models.TextField):
    """LONGTEXT 文本域：仅服务本模块休眠模型与 0039 序列化引用（Excel 用 excel_field_types.LongTextField）。"""

    def db_type(self, connection):
        if connection.vendor == 'mysql':
            return 'longtext'
        return super().db_type(connection)


class OperationLedgerLayoutTemplate(TenantModelMixin, models.Model):
    """设计器维护台账模板：表格布局草稿 + 不可变发布版本的容器。

    - ledger_type 复用台账类型枚举（周月维护/季维护），创建后不可修改；
      本文件不反向导入 models.py（models.py 底部导入本模块，避免循环），
      CHECK 约束的字面枚举由契约测试保证与 models.LEDGER_TYPE_VALUES 一致；
    - draft_content 为当前草稿（协议 JSON 串），空串表示尚无草稿；
    - 发布版本见 OperationLedgerLayoutVersion，本表不冗余版本内容。
    """

    name = models.CharField(max_length=100, help_text='模板名称')
    ledger_type = models.CharField(max_length=20, help_text='台账类型（创建后不可修改）')
    description = models.CharField(max_length=500, default='', blank=True, help_text='说明')
    draft_content = LongTextField(
        default='', blank=True, help_text='当前草稿（ledger_layout 协议 JSON 串，空为无草稿）')
    draft_updated_at = models.DateTimeField(null=True, blank=True, help_text='草稿最后保存时间')
    draft_updated_by = models.ForeignKey(
        User, models.PROTECT, related_name='+', null=True, help_text='草稿最后保存人')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_ledger_layout_template'
        verbose_name = '设计器台账模板'
        verbose_name_plural = '设计器台账模板'
        ordering = ('-created_at', '-id')
        constraints = [
            models.CheckConstraint(
                check=models.Q(ledger_type__in=['week_month', 'seasonal']),
                name='el_ledger_layout_template_type_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'ledger_type']),
        ]

    def __repr__(self):
        return '<OperationLedgerLayoutTemplate %r>' % self.name

    def to_view(self, latest_version_no=None, versions_count=None):
        return {
            'id': self.id,
            'name': self.name,
            'ledger_type': self.ledger_type,
            'description': self.description,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'draft_updated_at': self.draft_updated_at,
            'has_draft': bool(self.draft_content),
            'latest_version_no': latest_version_no,
            'versions_count': versions_count,
        }


class OperationLedgerLayoutVersion(TenantModelMixin, models.Model):
    """设计器台账模板发布版本：发布即快照，内容不可变（只增不改不删）。

    - version_no 模板内从 1 递增，(template, version_no) 唯一；
    - content 为发布时通过发布级校验的协议 JSON 规范化快照，读取端
      原样返回，不做任何二次转换；
    - 不存在修改/删除版本的服务函数与视图方法（写方法缺失即 405）。
    """

    template = models.ForeignKey(
        OperationLedgerLayoutTemplate, models.CASCADE, related_name='versions',
        help_text='所属模板')
    version_no = models.IntegerField(help_text='模板内递增版本号，从 1 开始')
    content = LongTextField(help_text='ledger_layout 协议 JSON 快照，发布后不可变')
    protocol_version = models.IntegerField(default=1, help_text='协议版本号')
    field_count = models.IntegerField(default=0, help_text='填写字段数量（发布时校验产出）')
    published_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    published_at = models.DateTimeField(auto_now_add=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_ledger_layout_version'
        verbose_name = '设计器台账模板版本'
        verbose_name_plural = '设计器台账模板版本'
        ordering = ('-version_no',)
        constraints = [
            models.UniqueConstraint(
                fields=['template', 'version_no'], name='el_ledger_layout_version_no_unique'),
            models.CheckConstraint(
                check=models.Q(version_no__gte=1), name='el_ledger_layout_version_no_valid'),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'template']),
        ]

    def __repr__(self):
        return '<OperationLedgerLayoutVersion %r v%s>' % (self.template_id, self.version_no)

    def to_view(self, with_content=False):
        data = {
            'id': self.id,
            'version_no': self.version_no,
            'protocol_version': self.protocol_version,
            'field_count': self.field_count,
            'published_at': self.published_at,
        }
        if with_content:
            data['content'] = json.loads(self.content)
        return data
