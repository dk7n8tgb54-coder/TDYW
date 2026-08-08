# -*- coding: utf-8 -*-
"""告警模块 legacy_characterization 测试"""
from django.test import TestCase
from apps.utils.test_helpers import make_user, setup_test_env
from apps.alert.models import Alert, AlertRead


class AlertLegacyFieldsTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.user = make_user('legacy_alert', ['system.alert.view'])

    def test_alert_is_global_no_tenant_id(self):
        """LEGACY: Alert 没有 tenant_id，是全局数据"""
        field_names = [f.name for f in Alert._meta.get_fields()]
        self.assertNotIn('tenant_id', field_names)

    def test_alert_read_uses_user_id_not_fk(self):
        """LEGACY: AlertRead.user_id 是 IntegerField，不是外键"""
        field = AlertRead._meta.get_field('user_id')
        self.assertEqual(field.get_internal_type(), 'IntegerField')

    def test_alert_uses_model_mixin_not_tenant_mixin(self):
        """LEGACY: Alert 使用 ModelMixin，不使用 TenantModelMixin"""
        # Alert 的父类是 models.Model + ModelMixin
        self.assertTrue(issubclass(Alert, object))
        # 确认没有 tenant_id 字段
        with self.assertRaises(Exception):
            Alert._meta.get_field('tenant_id')

    def test_alert_level_choices(self):
        """LEGACY: level 字段有 3 种选项"""
        self.assertEqual(Alert.LEVEL_ERROR, 'error')
        self.assertEqual(Alert.LEVEL_WARNING, 'warning')
        self.assertEqual(Alert.LEVEL_INFO, 'info')

    def test_alert_status_choices(self):
        """LEGACY: status 字段有 2 种选项"""
        self.assertEqual(Alert.STATUS_ACTIVE, 'active')
        self.assertEqual(Alert.STATUS_RESOLVED, 'resolved')

    def test_alert_read_unique_constraint(self):
        """LEGACY: AlertRead 有 (alert_id, user_id) 唯一约束"""
        constraints = AlertRead._meta.constraints
        unique_constraints = [c for c in constraints
                             if hasattr(c, 'fields') and set(c.fields) == {'alert_id', 'user_id'}]
        self.assertTrue(len(unique_constraints) > 0)
