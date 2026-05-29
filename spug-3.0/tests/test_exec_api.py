# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
from django.test import TestCase, Client
from apps.account.models import User
from apps.exec.models import RunLog, FaultRecord, UpgradeRecord
from apps.setting.utils import AppSetting
import json
import time


class ExecAPITest(TestCase):
    """执行运维模块API测试"""

    def setUp(self):
        """测试前准备"""
        token = 'a' * 32

        self.user = User.objects.create(
            username='testuser',
            nickname='测试用户',
            password_hash=User.make_password('password123'),
            tenant_id='test_tenant',
            is_supper=True,
            is_active=True,
            access_token=token,
            token_expired=int(time.time()) + 3600,
            last_ip='127.0.0.1',
            last_login='2026-01-01',
            type='default'
        )
        self.client = Client()
        self.client.defaults['HTTP_X_TOKEN'] = token
        self.client.defaults['HTTP_X_FORWARDED_FOR'] = '127.0.0.1'
        AppSetting.set('bind_ip', False)

    def test_get_run_logs(self):
        """测试获取运行日志列表"""
        RunLog.objects.create(
            user_id=self.user.id,
            tenant_id=self.user.tenant_id,
            run_date='2026-01-01',
            run_time='12:00:00',
            content='运行正常'
        )

        response = self.client.get('/exec/runlog/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('data', data)

    def test_update_run_log(self):
        """测试更新运行日志"""
        log = RunLog.objects.create(
            user_id=self.user.id,
            tenant_id=self.user.tenant_id,
            run_date='2026-01-01',
            run_time='12:00:00',
            content='运行正常'
        )

        response = self.client.post(
            '/exec/runlog/',
            data=json.dumps({
                'id': log.id,
                'content': '更新后的内容'
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)

        log.refresh_from_db()
        self.assertEqual(log.content, '更新后的内容')

    def test_delete_run_log(self):
        """测试删除运行日志"""
        log = RunLog.objects.create(
            user_id=self.user.id,
            tenant_id=self.user.tenant_id,
            run_date='2026-01-01',
            run_time='12:00:00',
            content='运行正常'
        )

        response = self.client.delete(f'/exec/runlog/{log.id}/')
        self.assertEqual(response.status_code, 200)

        # 验证已删除
        self.assertFalse(RunLog.objects.filter(id=log.id).exists())

    def test_create_fault_record(self):
        """测试创建故障记录"""
        response = self.client.post(
            '/exec/fault/',
            data=json.dumps({
                'device_name': '设备A',
                'fault_type': '硬件故障',
                'description': '故障描述'
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)

        # 验证故障记录已创建
        fault = FaultRecord.objects.filter(user_id=self.user.id).first()
        self.assertIsNotNone(fault)
        self.assertEqual(fault.device_name, '设备A')

    def test_get_fault_records(self):
        """测试获取故障记录列表"""
        FaultRecord.objects.create(
            user_id=self.user.id,
            tenant_id=self.user.tenant_id,
            device_name='设备A',
            fault_type='硬件故障'
        )

        response = self.client.get('/exec/fault/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('data', data)

    def test_create_upgrade_record(self):
        """测试创建升级记录"""
        response = self.client.post(
            '/exec/upgrade/',
            data=json.dumps({
                'version': 'v2.0.0',
                'upgrade_type': '系统升级',
                'description': '升级内容描述'
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)

        # 验证升级记录已创建
        upgrade = UpgradeRecord.objects.filter(user_id=self.user.id).first()
        self.assertIsNotNone(upgrade)
        self.assertEqual(upgrade.version, 'v2.0.0')

    def test_get_upgrade_records(self):
        """测试获取升级记录列表"""
        UpgradeRecord.objects.create(
            user_id=self.user.id,
            tenant_id=self.user.tenant_id,
            version='v2.0.0',
            upgrade_type='系统升级'
        )

        response = self.client.get('/exec/upgrade/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('data', data)

    def test_tenant_isolation(self):
        """测试租户隔离"""
        # 创建用户2
        user2 = User.objects.create(
            username='testuser2',
            nickname='测试用户2',
            password_hash=User.make_password('password123'),
            tenant_id='tenant2',
            is_supper=False,
            is_active=True,
            access_token='b' * 32,
            token_expired=int(time.time()) + 3600,
            last_ip='127.0.0.1',
            last_login='2026-01-01',
            type='default'
        )

        # 用户1创建运行日志
        RunLog.objects.create(
            user_id=self.user.id,
            tenant_id=self.user.tenant_id,
            run_date='2026-01-01',
            run_time='12:00:00',
            content='用户1的日志'
        )

        # 用户1获取日志，应该能获取到
        response = self.client.get('/exec/runlog/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['data']), 1)

        # 用户2获取日志，应该获取不到（租户隔离）
        client2 = Client()
        client2.defaults['HTTP_X_TOKEN'] = user2.access_token
        client2.defaults['HTTP_X_FORWARDED_FOR'] = '127.0.0.1'
        response2 = client2.get('/exec/runlog/')
        self.assertEqual(response2.status_code, 200)
        data2 = response2.json()
        self.assertEqual(len(data2['data']), 0)
