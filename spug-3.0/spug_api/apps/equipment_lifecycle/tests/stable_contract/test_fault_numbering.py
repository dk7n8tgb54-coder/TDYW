# -*- coding: utf-8 -*-
"""故障编号生成规则（2026-09 起当日序号全租户共享）稳定契约测试。

覆盖行为契约：
- 编号日期取系统创建故障的当天，与用户填写的故障发生时间无关；
- 当日序号全租户共享：跨租户、跨创建入口（手工新增 / 台账异常转故障）连续编号；
- 序号按当日所有租户已保存编号的有效四位数字后缀最大值加一（不按记录数加一，
  缺口不回填，五位/非数字等非法后缀不参与最大值计算）；
- 次日序号重新从 0001 开始；
- 当日序号用尽（9999 已占用）明确返回业务错误，不产生五位序号或重复编号，
  两个正式创建入口（FaultView / LedgerItemConvertToFaultView）均不落库；
- 不同数据库连接并发创建在 health_recalc_lock 全局锁（锁内事务提交后释放）
  串行下编号不重复。

历史数据只保证租户内唯一（uniq_el_fault_tenant_no）；本套契约只约束
正式创建路径今后生成的编号全局唯一。
全部通过真实创建路径（HTTP 视图 / 正式创建服务）+ 隔离测试数据库执行。
"""
import threading
from datetime import datetime, timedelta
from unittest import mock

from django.db import connections, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.equipment_lifecycle import fault_services
from apps.equipment_lifecycle.models import SystemFault

from apps.equipment_lifecycle.tests.base import (
    ALL_SYSTEM_PERMS, make_client, make_system, make_user,
)
from apps.equipment_lifecycle.tests.stable_contract.test_exception_conversion import (
    ALL_HANDLE_PERMS, ConversionTestBase,
)
from apps.equipment_lifecycle.tests.stable_contract.test_fault_management import (
    ALL_FAULT_PERMS, fault_payload,
)

FAULT_URL = '/equipment-lifecycle/faults/'


def today_prefix():
    return 'GZ' + timezone.now().date().strftime('%Y%m%d') + '-'


def seq_of(fault_no):
    """取编号后缀整数（调用方保证为有效四位数字后缀）。"""
    return int(fault_no.split('-')[1])


def seed_fault(system, created_by, fault_no):
    """直接落库一条存量故障行（模拟历史数据，不经过编号生成）。"""
    return SystemFault.objects.create(
        tenant_id=system.tenant_id, fault_no=fault_no, system=system,
        impact_status='', affects_system_operation=False,
        system_code=system.system_code, system_name=system.name,
        system_location=system.install_location,
        occurred_at=timezone.now(),
        phenomenon='存量编号占位',
        created_by=created_by,
    )


class FaultNumberingEntryPointsTest(ConversionTestBase):
    """跨租户、跨创建入口共享当日序号（真实 HTTP 创建路径）。"""

    def setUp(self):
        super().setUp()
        # 台账异常转故障要求"处置权限 + fault.add"双权限：给租户B台账用户补齐故障权限
        self.other_ledger_user.set_perms_cache(
            set(ALL_HANDLE_PERMS + ALL_SYSTEM_PERMS + ALL_FAULT_PERMS),
            version=0)

    def _create_manual_fault(self, system, user):
        """手工新增故障（真实 HTTP 路径），返回详情 dict。"""
        resp = make_client(user).post(
            FAULT_URL, fault_payload(system, occurred_at='2026-01-01 08:30'),
            content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        return body['data']

    def test_cross_tenant_sequence_shared_by_manual_and_ledger_convert(self):
        """手工新增（租户A）与台账异常转故障（租户B）当日序号跨租户连续，
        且编号日期取创建当天（故障发生时间为历史日期不影响编号）。"""
        first = self._create_manual_fault(self.system_a, self.admin)
        self.assertEqual(first['fault_no'], today_prefix() + '0001')

        ledger_id, item_ids = self.make_submitted_ledger(
            system=self.system_b, user=self.other_ledger_user)
        converted = self.convert_to_fault(
            ledger_id, item_ids[0], user=self.other_ledger_user)
        self.assertFalse(converted.get('error'), converted)
        self.assertEqual(converted['data']['fault_no'], today_prefix() + '0002')

        # 再一张手工新增：序号继续接续（不同发生时间避开创建幂等窗口）
        third_payload = fault_payload(
            self.system_a2, occurred_at='2026-01-02 08:30', phenomenon='备用链路中断')
        resp = make_client(self.admin).post(
            FAULT_URL, third_payload, content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        self.assertEqual(body['data']['fault_no'], today_prefix() + '0003')

        # DB 终态：当日编号恰好三条且后缀 0001-0003，租户不同但序号共享
        numbers = list(SystemFault.objects.filter(
            fault_no__startswith=today_prefix()).values_list('fault_no', flat=True))
        self.assertEqual(sorted(seq_of(n) for n in numbers), [1, 2, 3], numbers)

    def test_9999_exhausted_rejects_manual_creation(self):
        """当日 9999 已被任一租户占用：手工新增明确返回业务错误且不落库。"""
        seed_fault(self.system_b, self.other_ledger_user, today_prefix() + '9999')
        before = SystemFault.objects.count()
        resp = make_client(self.admin).post(
            FAULT_URL, fault_payload(self.system_a, occurred_at='2026-01-01 08:30'),
            content_type='application/json')
        body = resp.json()
        self.assertIn('上限', body.get('error', ''), body)
        self.assertEqual(SystemFault.objects.count(), before)

    def test_9999_exhausted_rejects_ledger_convert(self):
        """当日 9999 已被占用：台账异常转故障明确返回业务错误且不落库。"""
        seed_fault(self.system_a, self.admin, today_prefix() + '9999')
        ledger_id, item_ids = self.make_submitted_ledger(
            system=self.system_b, user=self.other_ledger_user)
        before = SystemFault.objects.count()
        body = self.convert_to_fault(
            ledger_id, item_ids[0], user=self.other_ledger_user)
        self.assertIn('上限', body.get('error', ''), body)
        self.assertEqual(SystemFault.objects.count(), before)


class FaultNumberingServiceTest(TestCase):
    """服务层编号规则（正式创建服务，与视图同锁同事务的真实创建路径）。"""

    def setUp(self):
        self.admin = make_user('num_svc_admin', ALL_SYSTEM_PERMS + ALL_FAULT_PERMS,
                               tenant_id='tenant_a')
        self.other_admin = make_user('num_svc_admin_b', ALL_SYSTEM_PERMS + ALL_FAULT_PERMS,
                                     tenant_id='tenant_b')
        self.system_a = make_system(self.admin, tenant_id='tenant_a',
                                    system_code='SYS-A1', name='编号测试系统A')
        self.system_b = make_system(self.other_admin, tenant_id='tenant_b',
                                    system_code='SYS-B1', name='编号测试系统B')

    def _create_via_service(self, system, user):
        """真实创建路径：health_recalc_lock + 事务内调用正式创建服务（与视图层一致）。"""
        with fault_services.health_recalc_lock():
            with transaction.atomic():
                return fault_services.create_fault_record(
                    tenant_id=system.tenant_id, created_by=user, system=system,
                    impact_status='', affects_system_operation=False,
                    occurred_at=timezone.now() - timedelta(hours=1),
                    phenomenon='编号服务路径测试',
                )

    def test_gap_takes_max_valid_suffix_plus_one_across_tenants(self):
        """已有缺口取有效四位后缀最大值加一：不按记录数加一、不回填缺口，
        五位/非数字等非法后缀不参与最大值计算。"""
        seed_fault(self.system_a, self.admin, today_prefix() + '0001')
        seed_fault(self.system_b, self.other_admin, today_prefix() + '0005')
        # 非法后缀（五位数字 / 非数字）：跨租户存量，也不得被当作序号参与计算
        seed_fault(self.system_a, self.admin, today_prefix() + '00012')
        seed_fault(self.system_b, self.other_admin, today_prefix() + '00XY')

        first = self._create_via_service(self.system_a, self.admin)
        self.assertEqual(first.fault_no, today_prefix() + '0006')
        # 记录数为 4：若按记录数加一会回填缺口 0002；按最大值加一应为 0007
        second = self._create_via_service(self.system_b, self.other_admin)
        self.assertEqual(second.fault_no, today_prefix() + '0007')

    def test_next_day_sequence_resets(self):
        """次日序号重新从 0001 开始（时钟推进一天后编号日期随之变化）。"""
        first = self._create_via_service(self.system_a, self.admin)
        self.assertEqual(first.fault_no, today_prefix() + '0001')

        tomorrow = (timezone.now() + timedelta(days=1)).replace(
            hour=8, minute=0, second=0, microsecond=0)
        tomorrow_prefix = 'GZ' + tomorrow.date().strftime('%Y%m%d') + '-'
        with mock.patch.object(fault_services.timezone, 'now', return_value=tomorrow):
            second = self._create_via_service(self.system_b, self.other_admin)
        self.assertEqual(second.fault_no, tomorrow_prefix + '0001')
        self.assertNotEqual(first.fault_no[:11], second.fault_no[:11])


class FaultNumberingConcurrencyTest(TransactionTestCase):
    """不同数据库连接并发创建：全局锁（锁内事务提交后释放）串行分配，编号不重复。"""

    def setUp(self):
        self.workers = []
        for i in range(4):
            user = make_user(f'num_cc_{i}', ALL_SYSTEM_PERMS + ALL_FAULT_PERMS,
                             tenant_id=f'cc_tenant_{i}')
            system = make_system(user, tenant_id=f'cc_tenant_{i}',
                                 system_code=f'CC-SYS-{i}', name=f'并发编号系统{i}')
            self.workers.append((user, system))

    def test_concurrent_creation_allocates_unique_numbers(self):
        """四租户四线程并发创建：编号唯一且当日序号恰为 0001-0004。"""
        barrier = threading.Barrier(len(self.workers))
        results = {}
        errors = {}

        def _runner(key, user, system):
            def run():
                try:
                    try:
                        barrier.wait(timeout=15)
                    except Exception:
                        pass
                    try:
                        with fault_services.health_recalc_lock():
                            with transaction.atomic():
                                fault = fault_services.create_fault_record(
                                    tenant_id=system.tenant_id, created_by=user,
                                    system=system,
                                    impact_status='', affects_system_operation=False,
                                    occurred_at=timezone.now(),
                                    phenomenon=f'并发编号测试-{key}',
                                )
                        results[key] = fault.fault_no
                    except Exception as exc:
                        errors[key] = exc
                finally:
                    connections.close_all()
            return run

        threads = [threading.Thread(target=_runner(i, user, system))
                   for i, (user, system) in enumerate(self.workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        self.assertEqual(errors, {}, errors)
        self.assertEqual(len(results), len(self.workers), results)
        numbers = list(results.values())
        self.assertEqual(len(set(numbers)), len(numbers), numbers)
        for number in numbers:
            self.assertTrue(number.startswith(today_prefix()), number)
        self.assertEqual(sorted(seq_of(n) for n in numbers),
                         list(range(1, len(numbers) + 1)), numbers)
