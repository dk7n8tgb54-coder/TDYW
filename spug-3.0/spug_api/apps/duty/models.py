# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.db import models
from libs import ModelMixin, human_datetime
from apps.account.models import User
import logging

logger = logging.getLogger(__name__)

# 租户类型常量
TENANT_TYPE_PRIVATE = 'PRIVATE'


class DutyRecord(models.Model, ModelMixin):
    """值班日志"""
    TENANT_TYPE = TENANT_TYPE_PRIVATE
    tenant_id = models.CharField(max_length=50, default='', help_text='租户标识')

    duty_person = models.CharField(max_length=100, help_text='值班人员')
    reporter = models.CharField(max_length=100, help_text='填报人')
    department = models.CharField(max_length=100, help_text='所属科室')
    duty_date = models.CharField(max_length=20, help_text='值班日期')
    duty_situation = models.TextField(null=True, blank=True, help_text='值班情况')
    created_at = models.CharField(max_length=20, default=human_datetime)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.CharField(max_length=20, null=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    def __repr__(self):
        return '<DutyRecord %r>' % self.duty_person

    def to_view(self):
        return self.to_dict()

    class Meta:
        db_table = 'exec_duty_records'
        ordering = ('-duty_date', '-id',)
