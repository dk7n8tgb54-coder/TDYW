# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.db import models
from libs import human_datetime
from libs.tenant_base_model import TenantModelMixin, TenantModelManager, make_tenant_id
from apps.account.models import User
import logging

logger = logging.getLogger(__name__)


class Interference(models.Model, TenantModelMixin):
    """干扰记录表"""
    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    serial_number = models.IntegerField(default=0)
    frequency = models.CharField(max_length=100)
    report_dept = models.CharField(max_length=100)
    datetime = models.CharField(max_length=20)
    coordinates = models.CharField(max_length=200)
    interference_type = models.CharField(max_length=100)
    phenomenon = models.TextField()
    flight_number = models.CharField(max_length=100, null=True, blank=True)
    aircraft_type = models.CharField(max_length=100, null=True, blank=True)
    is_reported = models.CharField(max_length=10, default='否')
    created_at = models.CharField(max_length=20, default=human_datetime)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.CharField(max_length=20, null=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    def __repr__(self):
        return '<Interference %r>' % self.frequency

    def to_view(self):
        return self.to_dict()

    class Meta:
        db_table = 'tdyw_interferences'
        verbose_name = '干扰记录'
        verbose_name_plural = '干扰记录'
        ordering = ('serial_number', '-datetime', '-id',)
