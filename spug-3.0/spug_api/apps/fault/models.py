# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.db import models
from libs.tenant_base_model import TenantModelMixin, TenantModelManager, make_tenant_id
from apps.account.models import User
import logging

logger = logging.getLogger(__name__)


class FaultRecord(models.Model, TenantModelMixin):
    """故障处置记录"""
    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    system_name = models.CharField(max_length=100)
    device_code = models.CharField(max_length=100)
    fault_date = models.DateTimeField(null=True, blank=True)
    handler = models.CharField(max_length=100)
    recorder = models.CharField(max_length=100)
    fault_level = models.CharField(max_length=50)
    fault_phenomenon = models.TextField()
    handling_process = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    def __repr__(self):
        return '<FaultRecord %r>' % self.system_name

    def to_view(self):
        return self.to_dict()

    class Meta:
        db_table = 'tdyw_fault_records'
        verbose_name = '故障处置记录'
        verbose_name_plural = '故障处置记录'
        ordering = ('-fault_date', '-id',)
        indexes = [
            models.Index(fields=['tenant_id', '-fault_date', '-id'], name='fault_rec_t_date_idx'),
        ]


class FaultPart(models.Model, TenantModelMixin):
    """故障件"""
    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    name = models.CharField(max_length=100)
    system_name = models.CharField(max_length=100)
    date = models.DateTimeField(null=True, blank=True)
    fault_date = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=50)
    fault_sent_date = models.DateTimeField(null=True, blank=True)
    test_return_date = models.DateTimeField(null=True, blank=True)
    archive_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    def __repr__(self):
        return '<FaultPart %r>' % self.name

    def to_view(self):
        return self.to_dict()

    class Meta:
        db_table = 'tdyw_fault_parts'
        verbose_name = '故障件'
        verbose_name_plural = '故障件'
        ordering = ('-date', '-id',)
        indexes = [
            models.Index(fields=['tenant_id', '-date', '-id'], name='fault_part_t_date_idx'),
        ]
