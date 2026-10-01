# -*- coding: utf-8 -*-
"""值班巡检单稳定契约（今日巡检改造）。

覆盖行为契约：
- 四个固定轮次（r1 11:00-11:20 / r2 16:00-16:20 / r3 22:00-22:20 / r4 次日 6:30-6:50），
  第四轮虽发生在下一自然日仍归属前一值班日的巡检单；
- 不记录实际填写时间作为巡检业务字段（无 executed_at/迟填标记）；
- 巡检单唯一范围 = 值班日 + 巡检模板（多人登记在单上，姓名快照）；
- 模板结构 = 模板 → 设备名称 → 检查内容（设备名称不关联系统，
  一个设备可配多个检查内容），模板修改不影响历史快照；
- 记录/提交分离、client_token 幂等、version 乐观锁、提交后不可改、
  受控作废释放唯一占用、跨租户隔离、全程不查不选系统。

全部通过真实 HTTP 路径 + 隔离测试数据库执行，验证数据库状态与真实副作用。
"""
from datetime import datetime, timedelta

from django.test import TestCase

from apps.account.models import User
from apps.equipment_lifecycle.models import (
    InspectionDutyPerson,
    InspectionDutySheet,
    InspectionRecord,
    InspectionTemplateItem,
    INSPECTION_ROUND_TEXT_MAP,
)
from apps.equipment_lifecycle.tests.base import make_client, make_system, make_user
from apps.equipment_lifecycle.tests.stable_contract.inspection_base import (
    ALL_INSPECTION_PERMS,
    INS_URL,
    ITPL_URL,
    P_INS_VIEW,
    create_sheet_ok,
    get_sheet_detail,
    get_template_items,
    make_inspection_template,
    make_inspection_user,
    put_records_ok,
    sheet_payload,
    submit_sheet_ok,
    template_payload,
)


class InspectionSheetTestBase(TestCase):
    """公共夹具：双租户 + 巡检模板（设备A 两项 + 设备B 一项）。"""

    def setUp(self):
        self.admin = make_inspection_user('ins_admin', tenant_id='tenant_a')
        self.other_admin = make_inspection_user('ins_admin_b', tenant_id='tenant_b')
        self.client = make_client(self.admin)
        self.template = make_inspection_template(
            tenant_id='tenant_a', created_by=self.admin)
        self.items = get_template_items(self.template)
        self.duty_date = '2026-09-23'

    def create_sheet(self, payload=None, user=None, expect_error=None):
        target = make_client(user) if user else self.client
        resp = target.post(f'{INS_URL}/', payload or sheet_payload(
            self.template.id, duty_date=self.duty_date),
            content_type='application/json')
        body = resp.json()
        if expect_error is not None:
            self.assertIn(expect_error, body.get('error', ''), body)
            return body
        self.assertFalse(body.get('error'), body)
        return body['data']


class SheetRoundsContractTest(InspectionSheetTestBase):
    """四个固定轮次与"第四轮（6:30-6:50）归属前一值班日"。"""

    def _fill_all_rounds(self, sheet_id, version=1):
        items = self.items
        # 单轮提交契约：一次 PUT 只允许提交一个轮次（记录本轮）
        rounds = ['r1', 'r2', 'r3', 'r4']
        detail = None
        for idx, round_no in enumerate(rounds):
            detail = put_records_ok(self.client, sheet_id, version + idx, records=[
                {'template_item_id': items['面板指示灯'].id, 'round_no': round_no,
                 'value_text': '正常'},
            ])
        # 第四轮：6:30-6:50（次日早晨）填写，仍归属 duty_date 的巡检单
        return detail

    def test_four_fixed_rounds_r4_belongs_to_duty_date_sheet(self):
        """四轮记录进入同一张单，r4 文案为"6:30-6:50"且单仍归属前一值班日。"""
        body = self.create_sheet()
        detail = self._fill_all_rounds(body['id'])
        by_round = {r['round_no']: r for r in detail['records']}
        self.assertEqual(set(by_round), {'r1', 'r2', 'r3', 'r4'})
        self.assertEqual(by_round['r4']['round_text'],
                         INSPECTION_ROUND_TEXT_MAP['r4'])
        self.assertIn('6:30', by_round['r4']['round_text'])
        sheet = InspectionDutySheet.objects.get(pk=body['id'])
        self.assertEqual(str(sheet.duty_date), self.duty_date)
        self.assertEqual(sheet.records.filter(round_no='r4').count(), 1)

    def test_same_round_same_item_upserts_not_duplicates(self):
        """同一载荷内同轮次同检查内容重复上送只更新一行（upsert 语义，
        记录成功后该轮次即记入 recorded_rounds，不可再次提交）。"""
        body = self.create_sheet()
        item = self.items['面板指示灯']
        detail = put_records_ok(self.client, body['id'], 1, records=[
            {'template_item_id': item.id, 'round_no': 'r1', 'value_text': '正常'},
            {'template_item_id': item.id, 'round_no': 'r1', 'value_text': '正常'},
        ])
        rows = [r for r in detail['records'] if r['round_no'] == 'r1']
        self.assertEqual(len(rows), 1)
        self.assertEqual(InspectionRecord.objects.filter(
            sheet_id=body['id'], round_no='r1').count(), 1)

    def test_no_fill_time_as_business_field(self):
        """不记录实际填写时间：明细载荷无 executed_at/迟填字段，
        created_at 仅为系统审计字段。"""
        body = self.create_sheet()
        put_records_ok(self.client, body['id'], 1, records=[
            {'template_item_id': self.items['面板指示灯'].id,
             'round_no': 'r2', 'value_text': '正常'}])
        detail = get_sheet_detail(self.client, body['id'])
        record = detail['records'][0]
        self.assertNotIn('executed_at', record)
        self.assertNotIn('is_late', record)
        self.assertNotIn('late', record)
        sheet = InspectionDutySheet.objects.get(pk=body['id'])
        # 巡检单本身也没有"实际执行时间"业务字段
        self.assertNotIn('executed_at', detail)
        self.assertTrue(sheet.created_at is not None)  # 仅系统审计

    def test_result_derived_from_choice_value(self):
        """结果由后端派生：choice 填"不正常"→ abnormal，"正常"→ normal。"""
        body = self.create_sheet()
        item = self.items['面板指示灯']
        put_records_ok(self.client, body['id'], 1, records=[
            {'template_item_id': item.id, 'round_no': 'r1', 'value_text': '不正常'},
        ])
        detail = put_records_ok(self.client, body['id'], 2, records=[
            {'template_item_id': item.id, 'round_no': 'r2', 'value_text': '正常'},
        ])
        rows = {r['round_no']: r for r in detail['records']}
        self.assertEqual(rows['r1']['result'], 'abnormal')
        self.assertEqual(rows['r2']['result'], 'normal')

    def test_text_numeric_value_lands_value_number(self):
        """text 类型纯数字填写同时落 value_number（供后续统计/拦截）。"""
        body = self.create_sheet()
        item = self.items['输出功率读数']
        detail = put_records_ok(self.client, body['id'], 1, records=[
            {'template_item_id': item.id, 'round_no': 'r1', 'value_text': '512'}])
        row = detail['records'][0]
        self.assertEqual(row['value_text'], '512')
        self.assertEqual(row['value_number'], 512)

    def test_manual_temporary_item_keeps_snapshot(self):
        """手工临时加项不依赖模板，同样保存快照并可参与派生结果。"""
        body = self.create_sheet()
        detail = put_records_ok(self.client, body['id'], 1, records=[
            {'client_key': 'tmp-1', 'round_no': 'r1', 'device_name': '空调机组',
             'item_name': '机房温度', 'input_type': 'text', 'value_text': '26.5'}])
        row = detail['records'][0]
        self.assertTrue(row['is_temporary'])
        self.assertEqual(row['device_name'], '空调机组')
        self.assertEqual(row['item_name'], '机房温度')
        self.assertEqual(row['value_number'], 26.5)


class SheetUniquenessTest(InspectionSheetTestBase):
    """巡检单唯一范围 = 值班日 + 巡检模板。"""

    def test_same_duty_date_and_template_unique(self):
        """同一值班日同一模板不能重复建单（不同 client_token 的两次请求）。"""
        self.create_sheet()
        second = sheet_payload(self.template.id, duty_date=self.duty_date,
                               client_token='tok-second-attempt')
        self.create_sheet(second, expect_error='不能重复建单')
        self.assertEqual(InspectionDutySheet.objects.count(), 1)

    def test_void_releases_uniqueness(self):
        """作废后释放当日唯一占用，可重新建单（旧单留档可查）。"""
        body = self.create_sheet()
        resp = self.client.post(f'{INS_URL}/{body["id"]}/void/',
                                {'void_reason': '选错模板重开'},
                                content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        second = self.create_sheet()
        self.assertEqual(InspectionDutySheet.objects.filter(
            status='void').count(), 1)
        self.assertNotEqual(second['id'], body['id'])

    def test_same_template_different_day_allowed(self):
        """同模板不同值班日各自建单。"""
        self.create_sheet(sheet_payload(self.template.id, duty_date='2026-09-23'))
        self.create_sheet(sheet_payload(self.template.id, duty_date='2026-09-24',
                                        client_token='tok-day2'))
        self.assertEqual(InspectionDutySheet.objects.count(), 2)

    def test_same_day_different_template_allowed(self):
        """同值班日不同模板各自建单。"""
        other_template = make_inspection_template(
            tenant_id='tenant_a', created_by=self.admin, name='周一巡检模板')
        self.create_sheet()
        self.create_sheet(sheet_payload(other_template.id, duty_date=self.duty_date,
                                        client_token='tok-other-tpl'))
        self.assertEqual(InspectionDutySheet.objects.count(), 2)


class SheetPersonsTest(InspectionSheetTestBase):
    """值班人员多人 + 姓名快照。"""

    def test_multiple_persons_with_name_snapshot(self):
        """单上登记多名值班人员：账号（稳定 ID）与手工补录姓名并存。"""
        user_b = make_inspection_user('ins_duty_b', tenant_id='tenant_a')
        payload = sheet_payload(self.template.id, duty_date=self.duty_date,
                                persons=[
                                    {'user': self.admin.id},
                                    {'user': user_b.id, 'person_name': '值班员乙'},
                                    {'person_name': '外聘代班（无账号）'},
                                ])
        body = self.create_sheet(payload)
        persons = body['persons']
        self.assertEqual(len(persons), 3)
        names = {p['person_name'] for p in persons}
        self.assertIn('外聘代班（无账号）', names)
        self.assertEqual(
            InspectionDutyPerson.objects.filter(sheet_id=body['id']).count(), 3)
        # 账号行带稳定 ID，手工行为空
        manual_rows = [p for p in persons if p['person_name'].startswith('外聘')]
        self.assertEqual(manual_rows[0]['user'], None)

    def test_invalid_person_user_rejected(self):
        """值班人员账号必须属于本租户。"""
        payload = sheet_payload(self.template.id, duty_date=self.duty_date,
                                persons=[{'user': self.other_admin.id}])
        self.create_sheet(payload, expect_error='值班人员账号不存在')

    def test_submit_requires_person_and_records(self):
        """提交前必须登记值班人员且有巡检记录。"""
        body = self.create_sheet(sheet_payload(
            self.template.id, duty_date=self.duty_date, persons=[]))
        resp = self.client.post(f'{INS_URL}/{body["id"]}/submit/', {},
                                content_type='application/json')
        self.assertIn('值班人员', resp.json().get('error', ''))
        # 登记人员后仍缺记录
        put_records_ok(self.client, body['id'], 1, records=[],
                       persons=[{'person_name': '值班员甲'}])
        resp = self.client.post(f'{INS_URL}/{body["id"]}/submit/', {},
                                content_type='application/json')
        self.assertIn('巡检记录', resp.json().get('error', ''))


class InspectionTemplateContractTest(InspectionSheetTestBase):
    """模板结构契约：模板 → 设备名称 → 检查内容（不关联系统）。"""

    def test_aggregate_create_one_device_multiple_items(self):
        """一个模板多个设备名称；一个设备名称多个检查内容。"""
        resp = self.client.post(f'{ITPL_URL}/', template_payload(),
                                content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        devices = body['data']['devices']
        self.assertEqual(len(devices), 2)
        self.assertEqual(len(devices[0]['items']), 2)
        self.assertEqual(len(devices[1]['items']), 1)
        # 设备名称不关联系统：载荷与返回中均无 system 字段
        self.assertNotIn('system', devices[0])

    def test_template_change_keeps_history_snapshots(self):
        """模板修改/停用检查内容不影响历史巡检明细快照。"""
        body = self.create_sheet()
        item = self.items['面板指示灯']
        put_records_ok(self.client, body['id'], 1, records=[
            {'template_item_id': item.id, 'round_no': 'r1', 'value_text': '正常'}])
        before = get_sheet_detail(self.client, body['id'])['records'][0]
        # 修改模板：改名 + 改必填规则 + 停用该项
        item.name = '面板指示灯（改）'
        item.is_required = False
        item.is_active = False
        item.save()
        after = get_sheet_detail(self.client, body['id'])['records'][0]
        self.assertEqual(after['item_name'], before['item_name'])
        self.assertEqual(after['is_required'], before['is_required'])
        self.assertEqual(after['item_name'], '面板指示灯')

    def test_inactive_template_cannot_create_sheet(self):
        """停用模板不能新建巡检单（历史单据不受影响）。"""
        self.template.is_active = False
        self.template.save()
        self.create_sheet(expect_error='已停用')

    def test_available_tree_only_active(self):
        """可用模板树只返回启用模板与启用条目（工作台渲染依据）。"""
        InspectionTemplateItem.objects.filter(pk=self.items['输出功率读数'].id).update(
            is_active=False)
        resp = self.client.get(f'{ITPL_URL}/available/')
        body = resp.json()
        # 可用模板树：json_response 载荷在 data 键下
        self.assertEqual(len(body['data']['data']), 1)
        tree = body['data']['data'][0]
        device_names = {d['device_name'] for d in tree['devices']}
        self.assertEqual(device_names, {'1号收发信机', '2号天馈系统'})
        item_names = {d['device_name'] + ':' + i['name']
                      for d in tree['devices'] for i in d['items']}
        self.assertNotIn('1号收发信机:输出功率读数', item_names)
        # 树中没有系统字段：巡检模板与系统档案完全解耦
        self.assertTrue(all('system' not in d for d in tree['devices']))


class SheetRecordedRoundsTest(InspectionSheetTestBase):
    """"记录本轮"轮次保护：单轮提交、已记录轮次只读（后端强制，不信任前端）。"""

    def _record_round(self, sheet_id, round_no, version, value_text='正常'):
        return put_records_ok(self.client, sheet_id, version, records=[
            {'template_item_id': self.items['面板指示灯'].id,
             'round_no': round_no, 'value_text': value_text},
        ])

    def test_round_marked_recorded_after_put(self):
        """记录成功后该轮次写入 recorded_rounds（详情可见，数据库同事务落库）。"""
        body = self.create_sheet()
        detail = self._record_round(body['id'], 'r1', 1)
        self.assertEqual(detail['recorded_rounds'], ['r1'])
        sheet = InspectionDutySheet.objects.get(pk=body['id'])
        self.assertEqual(sheet.get_recorded_rounds(), ['r1'])

    def test_recorded_round_rejects_reput_and_keeps_values(self):
        """已记录轮次再次提交被拒绝，且原记录值与版本号不被破坏。"""
        body = self.create_sheet()
        self._record_round(body['id'], 'r1', 1, value_text='正常')
        item = self.items['面板指示灯']
        resp = self.client.put(f'{INS_URL}/{body["id"]}/',
                               {'version': 2, 'records': [
                                   {'template_item_id': item.id,
                                    'round_no': 'r1', 'value_text': '不正常'}]},
                               content_type='application/json')
        self.assertIn('已记录', resp.json().get('error', ''))
        record = InspectionRecord.objects.get(sheet_id=body['id'], round_no='r1')
        self.assertEqual(record.value_text, '正常')
        self.assertEqual(InspectionDutySheet.objects.get(
            pk=body['id']).version, 2)

    def test_recorded_round_rejects_delete_by_id(self):
        """已记录轮次的明细不能通过 {id, deleted} 载荷删除。"""
        body = self.create_sheet()
        detail = self._record_round(body['id'], 'r1', 1)
        record_id = detail['records'][0]['id']
        resp = self.client.put(f'{INS_URL}/{body["id"]}/',
                               {'version': 2, 'records': [
                                   {'id': record_id, 'deleted': True}]},
                               content_type='application/json')
        self.assertIn('已记录', resp.json().get('error', ''))
        self.assertTrue(InspectionRecord.objects.filter(pk=record_id).exists())

    def test_mixed_rounds_rejected_atomically(self):
        """一次请求混交多轮记录被拒绝，且全部回滚（不落任何明细/轮次状态）。"""
        body = self.create_sheet()
        item = self.items['面板指示灯']
        resp = self.client.put(f'{INS_URL}/{body["id"]}/',
                               {'version': 1, 'records': [
                                   {'template_item_id': item.id,
                                    'round_no': 'r1', 'value_text': '正常'},
                                   {'template_item_id': item.id,
                                    'round_no': 'r2', 'value_text': '正常'}]},
                               content_type='application/json')
        self.assertIn('一次只能记录一个轮次', resp.json().get('error', ''))
        self.assertEqual(InspectionRecord.objects.filter(
            sheet_id=body['id']).count(), 0)
        self.assertEqual(InspectionDutySheet.objects.get(
            pk=body['id']).get_recorded_rounds(), [])

    def test_rounds_recorded_sequentially(self):
        """多轮按顺序逐次记录：recorded_rounds 累积，未记录轮次不受影响。"""
        body = self.create_sheet()
        self._record_round(body['id'], 'r1', 1)
        detail = self._record_round(body['id'], 'r2', 2)
        self.assertEqual(detail['recorded_rounds'], ['r1', 'r2'])

    def test_rounds_recorded_out_of_order(self):
        """四轮可按任意顺序独立记录（不要求先完成前一轮）：先 r3 后 r1。"""
        body = self.create_sheet()
        detail = self._record_round(body['id'], 'r3', 1)
        self.assertEqual(detail['recorded_rounds'], ['r3'])
        detail = self._record_round(body['id'], 'r1', 2)
        self.assertEqual(detail['recorded_rounds'], ['r1', 'r3'])
        detail = self._record_round(body['id'], 'r4', 3)
        self.assertEqual(detail['recorded_rounds'], ['r1', 'r3', 'r4'])
        sheet = InspectionDutySheet.objects.get(pk=body['id'])
        self.assertEqual(sheet.get_recorded_rounds(), ['r1', 'r3', 'r4'])

    def test_recording_one_round_keeps_other_round_values(self):
        """记录某一轮不影响其他轮次：r1 异常+现场处理记录后，记录 r2 时 r1 原样保留。"""
        body = self.create_sheet()
        item = self.items['面板指示灯']
        put_records_ok(self.client, body['id'], 1, records=[
            {'template_item_id': item.id, 'round_no': 'r1',
             'value_text': '不正常', 'onsite_action': '已切换备用'}])
        put_records_ok(self.client, body['id'], 2, records=[
            {'template_item_id': item.id, 'round_no': 'r2',
             'value_text': '正常'}])
        r1 = InspectionRecord.objects.get(sheet_id=body['id'], round_no='r1')
        r2 = InspectionRecord.objects.get(sheet_id=body['id'], round_no='r2')
        self.assertEqual(r1.value_text, '不正常')
        self.assertEqual(r1.onsite_action, '已切换备用')
        self.assertEqual(r1.result, 'abnormal')
        self.assertEqual(r2.value_text, '正常')
        self.assertEqual(r2.result, 'normal')

    def test_failed_save_does_not_lock_round(self):
        """保存失败（载荷校验不通过）时轮次不被错误锁定：事务整体回滚，
        轮次未记入 recorded_rounds、版本号不变，修正后同一轮次可再次记录。"""
        body = self.create_sheet()
        item = self.items['面板指示灯']
        resp = self.client.put(f'{INS_URL}/{body["id"]}/',
                               {'version': 1, 'records': [
                                   {'template_item_id': item.id,
                                    'round_no': 'r2', 'value_text': '非法值'}]},
                               content_type='application/json')
        self.assertIn('不合法', resp.json().get('error', ''))
        sheet = InspectionDutySheet.objects.get(pk=body['id'])
        self.assertEqual(sheet.get_recorded_rounds(), [])
        self.assertEqual(sheet.version, 1)
        self.assertFalse(InspectionRecord.objects.filter(
            sheet_id=body['id'], round_no='r2').exists())
        # 修正载荷后同一轮次可正常记录
        detail = self._record_round(body['id'], 'r2', 1)
        self.assertEqual(detail['recorded_rounds'], ['r2'])

    def test_persons_only_update_allowed_after_recording(self):
        """已记录轮次存在时，人员登记/空记录载荷仍可提交（版本号推进）。"""
        body = self.create_sheet()
        self._record_round(body['id'], 'r1', 1)
        detail = put_records_ok(self.client, body['id'], 2, records=[],
                                persons=[{'person_name': '值班员乙'}])
        self.assertEqual(detail['recorded_rounds'], ['r1'])
        self.assertEqual(InspectionDutySheet.objects.get(pk=body['id']).version, 3)

    def test_existing_sheet_default_no_recorded_rounds(self):
        """新建巡检单默认无已记录轮次（迁移默认值兼容已有巡检单）。"""
        body = self.create_sheet()
        detail = get_sheet_detail(self.client, body['id'])
        self.assertEqual(detail['recorded_rounds'], [])


class SheetWorkflowTest(InspectionSheetTestBase):
    """记录/提交分离、幂等、并发与跨租户。"""

    def test_record_submit_flow_and_submitted_immutable(self):
        """草稿累积四轮记录 → 提交 → 提交后不可再改。"""
        body = self.create_sheet()
        item = self.items['面板指示灯']
        put_records_ok(self.client, body['id'], 1, records=[
            {'template_item_id': item.id, 'round_no': 'r1', 'value_text': '正常'}])
        submit_sheet_ok(self.client, body['id'])
        resp = self.client.put(f'{INS_URL}/{body["id"]}/',
                               {'version': 2, 'records': [
                                   {'template_item_id': item.id,
                                    'round_no': 'r2', 'value_text': '正常'}]},
                               content_type='application/json')
        self.assertIn('不能再修改', resp.json().get('error', ''))
        self.assertEqual(
            InspectionRecord.objects.filter(sheet_id=body['id']).count(), 1)

    def test_version_conflict_rejected(self):
        """并发编辑 version 冲突被拒绝（乐观锁）。"""
        body = self.create_sheet()
        put_records_ok(self.client, body['id'], 1, records=[])
        other_client = make_client(self.admin)
        resp = other_client.put(f'{INS_URL}/{body["id"]}/',
                                {'version': 1, 'records': []},
                                content_type='application/json')
        self.assertIn('已被他人修改', resp.json().get('error', ''))

    def test_version_conflict_leaves_no_partial_save(self):
        """版本冲突时带记录的请求整体失败：不落任何明细、不锁定轮次。"""
        body = self.create_sheet()
        put_records_ok(self.client, body['id'], 1, records=[])
        item = self.items['面板指示灯']
        stale = make_client(self.admin)
        resp = stale.put(f'{INS_URL}/{body["id"]}/',
                         {'version': 1, 'records': [
                             {'template_item_id': item.id,
                              'round_no': 'r2', 'value_text': '正常'}]},
                         content_type='application/json')
        self.assertIn('已被他人修改', resp.json().get('error', ''))
        self.assertEqual(InspectionRecord.objects.filter(
            sheet_id=body['id']).count(), 0)
        self.assertEqual(InspectionDutySheet.objects.get(
            pk=body['id']).get_recorded_rounds(), [])

    def test_record_round_requires_edit_permission(self):
        """无 inspection.edit 权限的用户不能记录轮次（后端独立校验权限）。"""
        body = self.create_sheet()
        viewer = make_user('ins_viewer_only', [P_INS_VIEW], tenant_id='tenant_a')
        resp = make_client(viewer).put(f'{INS_URL}/{body["id"]}/',
                                       {'version': 1, 'records': [
                                           {'template_item_id': self.items['面板指示灯'].id,
                                            'round_no': 'r1', 'value_text': '正常'}]},
                                       content_type='application/json')
        self.assertIn('权限拒绝', resp.json().get('error', ''))
        sheet = InspectionDutySheet.objects.get(pk=body['id'])
        self.assertEqual(sheet.get_recorded_rounds(), [])
        self.assertEqual(sheet.records.count(), 0)

    def test_cross_tenant_cannot_record_round(self):
        """跨租户用户不能对他人巡检单记录轮次（对象级租户隔离）。"""
        body = self.create_sheet()
        foreign = make_client(self.other_admin)
        resp = foreign.put(f'{INS_URL}/{body["id"]}/',
                           {'version': 1, 'records': [
                               {'template_item_id': self.items['面板指示灯'].id,
                                'round_no': 'r1', 'value_text': '正常'}]},
                           content_type='application/json')
        self.assertIn('巡检单不存在', resp.json().get('error', ''))
        sheet = InspectionDutySheet.objects.get(pk=body['id'])
        self.assertEqual(sheet.get_recorded_rounds(), [])
        self.assertEqual(sheet.records.count(), 0)

    def test_client_token_idempotent(self):
        """同 client_token 重复创建返回已有单（不重复建单）。"""
        payload = sheet_payload(self.template.id, duty_date=self.duty_date,
                                client_token='tok-idem-sheet')
        first = self.create_sheet(payload)
        second = self.create_sheet(payload)
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(InspectionDutySheet.objects.count(), 1)

    def test_cross_tenant_isolated(self):
        """跨租户巡检单与模板均不可见、不可用。"""
        body = self.create_sheet()
        foreign = make_client(self.other_admin)
        resp = foreign.get(f'{INS_URL}/{body["id"]}/')
        self.assertTrue(resp.json().get('error'))
        # 其他租户模板不可用于建单
        foreign_payload = sheet_payload(self.template.id, duty_date=self.duty_date)
        resp = foreign.post(f'{INS_URL}/', foreign_payload,
                            content_type='application/json')
        self.assertIn('不存在', resp.json().get('error', ''))
        # 列表互不可见（列表载荷 data.data 嵌套）
        resp = foreign.get(f'{INS_URL}/')
        ids = [row['id'] for row in resp.json()['data']['data']]
        self.assertNotIn(body['id'], ids)

    def test_no_system_dependency_anywhere(self):
        """巡检单全程不查询、不要求选择系统：建单/记录/详情载荷无 system 键。"""
        body = self.create_sheet()
        detail = put_records_ok(self.client, body['id'], 1, records=[
            {'template_item_id': self.items['面板指示灯'].id,
             'round_no': 'r1', 'value_text': '正常'}])
        for key in ('system', 'system_id', 'systems'):
            self.assertNotIn(key, detail)
        for record in detail['records']:
            self.assertNotIn('system', record)
        # 即使恶意传入 system 参数也被忽略（不落库）
        make_system(self.admin, tenant_id='tenant_a',
                    system_code='SYS-INS-1', name='无关系统')
        payload = sheet_payload(self.template.id, duty_date='2026-09-24',
                                client_token='tok-sys-ignored', system=999)
        malicious = self.create_sheet(payload)
        self.assertNotIn('system', malicious)
