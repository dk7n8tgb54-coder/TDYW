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


class FaultRecord(models.Model, ModelMixin):
    TENANT_TYPE = TENANT_TYPE_PRIVATE
    tenant_id = models.CharField(max_length=50, default='', help_text='租户标识')
    system_name = models.CharField(max_length=100)
    device_code = models.CharField(max_length=100)
    fault_date = models.CharField(max_length=20)
    handler = models.CharField(max_length=100)
    recorder = models.CharField(max_length=100)
    fault_level = models.CharField(max_length=50)
    fault_phenomenon = models.TextField()
    handling_process = models.TextField()
    created_at = models.CharField(max_length=20, default=human_datetime)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.CharField(max_length=20, null=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    def __repr__(self):
        return '<FaultRecord %r>' % self.system_name

    def to_view(self):
        return self.to_dict()

    class Meta:
        db_table = 'exec_fault_records'
        ordering = ('-fault_date', '-id',)


class FaultPart(models.Model, ModelMixin):
    TENANT_TYPE = TENANT_TYPE_PRIVATE
    tenant_id = models.CharField(max_length=50, default='', help_text='租户标识')
    name = models.CharField(max_length=100)
    system_name = models.CharField(max_length=100)
    date = models.CharField(max_length=20)
    fault_date = models.CharField(max_length=20)
    status = models.CharField(max_length=50)
    fault_sent_date = models.CharField(max_length=20, null=True, blank=True)
    test_return_date = models.CharField(max_length=20, null=True, blank=True)
    archive_date = models.CharField(max_length=20, null=True, blank=True)
    created_at = models.CharField(max_length=20, default=human_datetime)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.CharField(max_length=20, null=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    def __repr__(self):
        return '<FaultPart %r>' % self.name

    def to_view(self):
        return self.to_dict()

    class Meta:
        db_table = 'exec_fault_parts'
        ordering = ('-date', '-id',)
