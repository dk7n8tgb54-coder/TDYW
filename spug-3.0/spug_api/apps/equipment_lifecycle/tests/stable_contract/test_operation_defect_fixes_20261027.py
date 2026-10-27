# -*- coding: utf-8 -*-
"""运行处置记录 2026-10-27 只读审计四缺陷的回归契约测试。

缺陷复现（修复前红、修复后绿，断言不弱化），全部走真实
HTTP → View → JsonParser → Model 链路（Docker + 隔离测试库）：

- D1 确认恢复并结案：前端恒显式提交 reason_analysis（留空=空串），
  后端 Argument(default=None, help=...) 对显式空串抛 ParseError(help)，
  "最终原因分析留空"被拒且错误文案即参数说明——结案被阻塞。
  契约：显式空串=清空为空、缺键=保留原值、原因未明仍必须填说明；
- D2 编辑记录：异常类别清除后前端丢键、后端按"未提交保留原值"静默失效，
  显式空串同样撞 ParseError(help)。契约：显式空串=清空为未选择、
  缺键=保留原值、值变更照常生效；
- D3 台账异常转故障未持编号锁（generate_record_no 约定"须在编号锁内
  调用"，手工创建入口有锁而本入口没有）：另一连接持有
  el_operation_record_no 锁时本入口必须等待/拒绝而非旁路成功，
  且编号生成确实发生在编号锁内（真实双连接 GET_LOCK 竞争 + 锁探针）；
- D4 待办列表 to_view 访问 created_by.username 无 select_related：
  查询数随行数线性增长（N+1）。契约：行数增长查询数恒定，
  且行数据仍真实携带 created_by_name。
"""
import json
import threading
from contextlib import contextmanager
from unittest import mock

from django.db import connection, connections
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext

from apps.equipment_lifecycle import operation_services
from apps.equipment_lifecycle.models import OperationLedger
from apps.equipment_lifecycle.operation_models import SystemOperationRecord
from apps.equipment_lifecycle.tests.base import (
    ALL_OPERATION_PERMS, RECORDS_URL, make_client, make_record, make_system,
    make_user,
)
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    ALL_LEDGER_PERMS, LEDGER_URL, make_full_ledger,
)

CONVERT_URL = '/equipment-lifecycle/ledgers/%d/items/%d/convert-to-fault/'
LEDGER_HANDLE_PERM = 'equipment_lifecycle.ledger.handle_exception'
TODO_URL = RECORDS_URL + '/todo/'


class RecoverFinalReasonEmptyStringTests(TestCase):
    """D1 回归：结案"最终原因分析"显式空串=清空、缺键=保留原值。"""

    def setUp(self):
        self.user = make_user('recover_empty_reason_user', perms=ALL_OPERATION_PERMS)
        self.client = make_client(self.user)
        self.system = make_system(self.user)
        self.fault = make_record(
            self.user, self.system, record_type='fault',
            reason_analysis='初步原因分析X')

    def _recover(self, payload):
        return self.client.post(
            RECORDS_URL + '/%d/recover/' % self.fault.id,
            json.dumps(payload), content_type='application/json')

    def test_recover_with_explicit_empty_final_reason_succeeds(self):
        """前端留空（显式空串）必须能结案，最终原因为空而非报错。"""
        res = self._recover({
            'recovered_at': '2026-10-11 12:00',
            'recovered_by_name': '赵六',
            'recovery_close_note': '更换电源模块，观察30分钟无异常',
            'reason_analysis': '',
        })
        data = res.json()
        self.assertFalse(data.get('error'), data)
        self.fault.refresh_from_db()
        self.assertEqual(self.fault.status, 'closed')
        self.assertEqual(self.fault.reason_analysis, '')

    def test_recover_without_reason_key_preserves_original(self):
        """缺键（未提交）保留处置中的原因分析——修复不得破坏该语义。"""
        res = self._recover({
            'recovered_at': '2026-10-11 12:00',
            'recovered_by_name': '赵六',
            'recovery_close_note': '更换电源模块，观察30分钟无异常',
        })
        data = res.json()
        self.assertFalse(data.get('error'), data)
        self.fault.refresh_from_db()
        self.assertEqual(self.fault.status, 'closed')
        self.assertEqual(self.fault.reason_analysis, '初步原因分析X')

    def test_recover_unknown_reason_still_requires_note(self):
        """原因未明 + 空串仍被业务校验拒绝（非解析器误伤）。"""
        res = self._recover({
            'recovered_at': '2026-10-11 12:00',
            'recovered_by_name': '赵六',
            'recovery_close_note': '更换电源模块，观察30分钟无异常',
            'reason_analysis': '',
            'reason_unknown': True,
        })
        data = res.json()
        self.assertTrue(data.get('error'), data)
        self.assertIn('原因未明', data['error'])
        self.fault.refresh_from_db()
        self.assertEqual(self.fault.status, 'handling')


class EditCategoryClearContractTests(TestCase):
    """D2 回归：编辑时异常类别显式空串=清空为未选择、缺键=保留原值。"""

    def setUp(self):
        self.user = make_user('edit_category_user', perms=ALL_OPERATION_PERMS)
        self.client = make_client(self.user)
        self.system = make_system(self.user)
        self.record = make_record(
            self.user, self.system, record_type='abnormal', category='device')

    def _edit(self, payload):
        base = {
            'system': self.system.id,
            'occurred_at': '2026-10-11 08:00',
            'title': '测试记录-改',
            'description': '测试情况描述-改',
        }
        base.update(payload)
        return self.client.put(
            RECORDS_URL + '/%d/' % self.record.id,
            json.dumps(base), content_type='application/json')

    def test_edit_with_explicit_empty_category_clears(self):
        res = self._edit({'category': ''})
        data = res.json()
        self.assertFalse(data.get('error'), data)
        self.record.refresh_from_db()
        self.assertEqual(self.record.category, '')

    def test_edit_without_category_key_preserves(self):
        res = self._edit({})
        data = res.json()
        self.assertFalse(data.get('error'), data)
        self.record.refresh_from_db()
        self.assertEqual(self.record.category, 'device')

    def test_edit_category_value_change_works(self):
        res = self._edit({'category': 'signal'})
        data = res.json()
        self.assertFalse(data.get('error'), data)
        self.record.refresh_from_db()
        self.assertEqual(self.record.category, 'signal')


class ConvertRecordNoLockTests(TransactionTestCase):
    """D3 回归：台账异常转故障必须在编号锁内生成编号（真实双连接竞争）。"""

    def setUp(self):
        perms = ALL_LEDGER_PERMS + ALL_OPERATION_PERMS + [LEDGER_HANDLE_PERM]
        self.user = make_user('convert_lock_user', perms=perms)
        self.client = make_client(self.user)
        self.system = make_system(self.user)
        detail, _system = make_full_ledger(self.user, system=self.system)
        self.ledger = OperationLedger.objects.get(pk=detail['id'])
        self.abnormal_item = list(self.ledger.items.order_by('id'))[1]
        res = self.client.post(
            LEDGER_URL + '/%d/complete/' % self.ledger.id,
            json.dumps({}), content_type='application/json')
        self.assertFalse(res.json().get('error'), res.json())

    def _convert(self):
        return self.client.post(
            CONVERT_URL % (self.ledger.id, self.abnormal_item.id),
            json.dumps({}), content_type='application/json')

    def test_convert_blocked_while_record_no_lock_held_elsewhere(self):
        """另一连接持有编号锁时，转故障必须等待/拒绝而非旁路创建。"""
        held = threading.Event()
        release = threading.Event()
        holder_errors = []

        def holder():
            try:
                cursor = connection.cursor()
                cursor.execute("SELECT GET_LOCK(%s, 5)",
                               [operation_services.RECORD_NO_LOCK_NAME])
                if cursor.fetchone()[0] != 1:
                    holder_errors.append(AssertionError('夹具线程未取得编号锁'))
                    held.set()
                    return
                held.set()
                if not release.wait(timeout=8):
                    holder_errors.append(AssertionError('主线程未在持锁窗口内放行'))
                cursor.execute("SELECT RELEASE_LOCK(%s)",
                               [operation_services.RECORD_NO_LOCK_NAME])
                cursor.close()
            except Exception as error:  # 线程异常传导到主线程断言
                holder_errors.append(error)
                held.set()
            finally:
                connections.close_all()

        thread = threading.Thread(target=holder)
        thread.start()
        self.assertTrue(held.wait(timeout=5), '夹具线程未取得编号锁')
        try:
            with mock.patch.object(operation_services, 'RECORD_NO_LOCK_TIMEOUT', 1):
                res = self._convert()
            data = res.json()
            self.assertTrue(
                data.get('error'),
                '编号锁被他连接持有时转换不应旁路成功: %r' % data)
            self.assertIn('系统繁忙', data['error'])
        finally:
            release.set()
            thread.join(timeout=8)
        self.assertEqual(holder_errors, [])

        # 锁释放后重试成功：证明上面的拒绝来自锁本身而非权限/夹具问题
        res2 = self._convert()
        data2 = res2.json()
        self.assertFalse(data2.get('error'), data2)
        self.assertTrue(SystemOperationRecord.objects.filter(
            source_type='ledger_item',
            source_ledger_item=self.abnormal_item).exists())

    def test_convert_acquires_record_no_lock_around_creation(self):
        """编号生成必须发生在编号锁内（锁探针：进锁→出锁各一次）。"""
        calls = []
        real_lock = operation_services.record_no_lock

        @contextmanager
        def spy_lock():
            calls.append('enter')
            try:
                with real_lock():
                    yield
            finally:
                calls.append('exit')

        with mock.patch.object(operation_services, 'record_no_lock', spy_lock):
            data = self._convert().json()
        self.assertFalse(data.get('error'), data)
        self.assertEqual(calls, ['enter', 'exit'])


class RecordTodoQueryEfficiencyTests(TestCase):
    """D4 回归：待办列表查询数不随行数增长（created_by 不得 N+1）。"""

    def setUp(self):
        self.user = make_user('todo_perf_user', perms=ALL_OPERATION_PERMS)
        self.client = make_client(self.user)
        self.system = make_system(self.user)
        for seq in range(2):
            make_record(self.user, self.system, record_type='abnormal',
                        status='following_up', title='待办事件-%d' % seq)
        # 预热一次：权限缓存/连接等一次性开销不参与计数
        res = self.client.get(TODO_URL)
        self.assertFalse(res.json().get('error'), res.json())

    def _todo_request(self):
        with CaptureQueriesContext(connection) as context:
            res = self.client.get(TODO_URL)
        payload = res.json()
        self.assertFalse(payload.get('error'), payload)
        # 原始响应双层包装：data.data 行数组 / data.total 总数
        # （前端 http 拦截器剥外层后才有 res.data/res.total）
        return len(context), payload['data']

    def test_todo_query_count_constant_with_row_growth(self):
        count_small, data_small = self._todo_request()
        self.assertEqual(data_small['total'], 2)
        for seq in range(29):
            make_record(self.user, self.system, record_type='abnormal',
                        status='following_up', title='待办事件-增长-%d' % seq)
        count_large, data_large = self._todo_request()
        self.assertEqual(data_large['total'], 31)
        self.assertEqual(
            count_large, count_small,
            '待办查询数随行数增长（created_by N+1）：small=%d large=%d'
            % (count_small, count_large))
        # 行数据仍真实携带登记账号展示名（select_related 生效而非漏序列化）
        row = data_large['data'][0]
        self.assertIn('created_by_name', row)
