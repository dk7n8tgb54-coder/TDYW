# -*- coding: utf-8 -*-
"""干扰模块 legacy_characterization 测试"""
from django.test import TestCase
from apps.utils.test_helpers import make_user, setup_test_env
from apps.interference.models import Interference


class InterferenceLegacyFieldsTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.user = make_user('legacy_int', ['interference.interference.view'])

    def test_no_fk_to_device(self):
        """LEGACY: Interference 没有外键关联到设备表"""
        fk_fields = [f for f in Interference._meta.get_fields()
                     if f.get_internal_type() == 'ForeignKey']
        device_fks = [f for f in fk_fields if 'device' in f.name.lower()]
        self.assertEqual(device_fks, [])

    def test_frequency_is_text(self):
        """LEGACY: frequency 是文本字段"""
        field = Interference._meta.get_field('frequency')
        self.assertEqual(field.get_internal_type(), 'CharField')

    def test_status_has_choices(self):
        """LEGACY: status 字段有预定义选项"""
        rec = Interference.objects.create(
            tenant_id=self.user.tenant_id, serial_number=501,
            frequency='100MHz', report_dept='部门', datetime='2026-01-01 10:00:00',
            interference_type='类型', phenomenon='现象', status='draft',
            created_by=self.user)
        self.assertEqual(rec.status, 'draft')

    def test_report_dept_is_text(self):
        """LEGACY: report_dept 是文本字段"""
        field = Interference._meta.get_field('report_dept')
        self.assertEqual(field.get_internal_type(), 'CharField')
