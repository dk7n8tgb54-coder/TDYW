# CRUD 可靠性审查测试：部门值班日志
# 运行：docker restart tdyw-test && docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test \
#       python manage.py test apps.department_duty_log.crud_audit_tests --noinput
import io, json, os, shutil, tempfile, time, uuid
from datetime import date, timedelta
from django.test import TestCase, override_settings
from django.conf import settings
from apps.account.models import User, Role
from apps.setting.utils import AppSetting
from apps.signature import services as sig_services
from apps.signature.models import SignatureUsage
from .models import DepartmentDutyLog, STATUS_DRAFT, STATUS_SIGNED
from . import services

def _make_user(username, **kw):
    defaults = {'username': username, 'nickname': username, 'password_hash': 'x',
                'is_active': True, 'is_supper': False,
                'access_token': (username*10)[:32], 'token_expired': int(time.time())+3600,
                'last_login': '2026-01-01', 'last_ip': '127.0.0.1',
                'type': 'default', 'tenant_id': 'default'}
    defaults.update(kw)
    return User.objects.create(**defaults)

def _make_client(user):
    from django.test import Client
    c = Client()
    c.defaults['HTTP_X_TOKEN'] = user.access_token
    c.defaults['HTTP_X_FORWARDED_FOR'] = '10.0.0.1'
    return c

def _grant_perms(user, perms):
    pd = {}
    for m, p, ks in perms:
        pd.setdefault(m, {}).setdefault(p, []).extend(ks)
    rn = f'crud_role_{user.username}'
    r = Role.objects.filter(name=rn).first()
    if r:
        ex = json.loads(r.page_perms) if r.page_perms else {}
        for m, ps in pd.items():
            if m not in ex: ex[m] = {}
            for p, ks in ps.items():
                if p not in ex[m]: ex[m][p] = []
                ex[m][p].extend(ks)
        r.page_perms = json.dumps(ex); r.save()
    else:
        r = Role.objects.create(name=rn, page_perms=json.dumps(pd), created_by=user)
        user.roles.add(r)
    user.set_perms_cache()

def _make_record(user, **kw):
    defaults = {'duty_date': date.today(), 'duty_person': user,
                'duty_person_name': user.nickname, 'weather': '晴',
                'duty_record': '值班正常', 'remark': '', 'status': STATUS_DRAFT,
                'version': 1, 'created_by': user}
    defaults.update(kw)
    if defaults['status'] == STATUS_SIGNED:
        for f, v in {'signature_usage_id': uuid.uuid4().int & ((1<<63)-1),
                      'signed_by': user, 'signed_by_name': user.nickname,
                      'signed_at': '2026-01-01 00:00:00', 'signature_version': 1,
                      'signature_sha256': 'a'*64, 'business_snapshot_hash': 'b'*64}.items():
            defaults.setdefault(f, v)
    return DepartmentDutyLog.objects.create(**defaults)

def _make_png_file(w=200, h=100):
    from PIL import Image
    from django.core.files.uploadedfile import SimpleUploadedFile
    img = Image.new('RGBA', (w, h), (255, 0, 0, 128))
    buf = io.BytesIO(); img.save(buf, format='PNG')
    return SimpleUploadedFile('sig.png', buf.getvalue(), content_type='image/png')


# 风险点 1：同一用户同一日期可创建多条记录（无唯一约束）
class CRUDRisk1_NoUniqueOnDatePersonTests(TestCase):
    """验证：同一用户同一天可创建多条记录，无唯一约束阻止重复登记。"""
    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('crud_u1', tenant_id='ta')
        _grant_perms(self.user, [('department_duty_log', 'department_duty_log', ['view', 'add'])])
        self.c = _make_client(self.user)
    def test_same_user_same_date_multiple_records(self):
        payload = {'duty_date': str(date.today()), 'weather': '晴', 'duty_record': '第一条', 'remark': ''}
        r1 = self.c.post('/department-duty-log/records/', data=json.dumps(payload), content_type='application/json')
        self.assertFalse(json.loads(r1.content).get('error'))
        payload['duty_record'] = '第二条'
        r2 = self.c.post('/department-duty-log/records/', data=json.dumps(payload), content_type='application/json')
        self.assertFalse(json.loads(r2.content).get('error'))
        count = DepartmentDutyLog.objects.filter(duty_person=self.user, duty_date=date.today(), deleted_at__isnull=True).count()
        self.assertEqual(count, 2, '同一天创建了 2 条记录，无唯一约束')


# 风险点 2：创建幂等性检查（修复后双击提交被拦截）
class CRUDRisk2_CreateIdempotencyTests(TestCase):
    """验证修复：创建操作现在有幂等性检查，双击提交被拦截。"""
    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('crud_u2', tenant_id='ta')
        _grant_perms(self.user, [('department_duty_log', 'department_duty_log', ['view', 'add'])])
        self.c = _make_client(self.user)
    def test_double_submit_blocked(self):
        """修复后：相同 payload 30 秒内第二次提交被拒绝"""
        payload = {'duty_date': str(date.today()), 'weather': '晴', 'duty_record': '双击测试', 'remark': ''}
        r1 = self.c.post('/department-duty-log/records/', data=json.dumps(payload), content_type='application/json')
        self.assertFalse(json.loads(r1.content).get('error'))
        r2 = self.c.post('/department-duty-log/records/', data=json.dumps(payload), content_type='application/json')
        body2 = json.loads(r2.content)
        self.assertTrue(body2.get('error'), '修复后双击提交应被拒绝')
        self.assertIn('频繁', body2['error'])
        count = DepartmentDutyLog.objects.filter(duty_record='双击测试', deleted_at__isnull=True).count()
        self.assertEqual(count, 1, '只创建了 1 条记录')
    def test_different_content_not_blocked(self):
        """不同内容的提交不被拦截"""
        p1 = {'duty_date': str(date.today()), 'weather': '晴', 'duty_record': '内容A', 'remark': ''}
        p2 = {'duty_date': str(date.today()), 'weather': '晴', 'duty_record': '内容B', 'remark': ''}
        r1 = self.c.post('/department-duty-log/records/', data=json.dumps(p1), content_type='application/json')
        self.assertFalse(json.loads(r1.content).get('error'))
        r2 = self.c.post('/department-duty-log/records/', data=json.dumps(p2), content_type='application/json')
        self.assertFalse(json.loads(r2.content).get('error'), '不同内容不应被拦截')


# 风险点 3：导出无行数上限
class CRUDRisk3_ExportNoLimitTests(TestCase):
    """验证：导出 queryset 没有行数上限。"""
    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('crud_u3', tenant_id='ta')
    def test_export_no_row_limit(self):
        for i in range(50):
            _make_record(self.user, duty_date=date.today()-timedelta(days=i),
                         duty_record=f'导出{i}', status=STATUS_SIGNED)
        filters, _ = services._parse_export_filters({})
        qs = services._get_export_queryset(self.user, filters)
        self.assertEqual(qs.count(), 50, '导出返回全部 50 条，无行数上限')
    def test_export_no_date_includes_very_old(self):
        _make_record(self.user, duty_date=date.today()-timedelta(days=700),
                     duty_record='700天前', status=STATUS_SIGNED)
        filters, _ = services._parse_export_filters({})
        qs = services._get_export_queryset(self.user, filters)
        self.assertTrue(qs.filter(duty_record='700天前').exists(), '导出无日期时包含 700 天前记录')


# 风险点 4：受保护字段注入防护
class CRUDRisk4_ProtectedFieldsTests(TestCase):
    """验证：客户端不能注入 status/signature/duty_person 等受保护字段。"""
    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('crud_u4', tenant_id='ta')
        _grant_perms(self.user, [('department_duty_log', 'department_duty_log', ['view', 'add', 'edit'])])
        self.c = _make_client(self.user)
    def test_inject_status_rejected(self):
        p = {'duty_date': str(date.today()), 'weather': '晴', 'duty_record': 'x', 'status': 'signed'}
        r = self.c.post('/department-duty-log/records/', data=json.dumps(p), content_type='application/json')
        self.assertTrue(json.loads(r.content).get('error'), '注入 status 应被拒绝')
    def test_inject_signature_fields_rejected(self):
        p = {'duty_date': str(date.today()), 'weather': '晴', 'duty_record': 'x',
             'signature_usage_id': 99999, 'signed_by_name': '张三', 'signature_sha256': 'a'*64}
        r = self.c.post('/department-duty-log/records/', data=json.dumps(p), content_type='application/json')
        self.assertTrue(json.loads(r.content).get('error'), '注入签署字段应被拒绝')
    def test_inject_duty_person_id_rejected(self):
        other = _make_user('crud_other4', tenant_id='ta')
        p = {'duty_date': str(date.today()), 'weather': '晴', 'duty_record': 'x', 'duty_person_id': other.id}
        r = self.c.post('/department-duty-log/records/', data=json.dumps(p), content_type='application/json')
        self.assertTrue(json.loads(r.content).get('error'), '注入 duty_person_id 应被拒绝')


# 风险点 5：已签记录不可编辑/删除
class CRUDRisk5_SignedImmutableTests(TestCase):
    """验证：已签记录不能被编辑或删除。"""
    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('crud_u5', tenant_id='ta')
        _grant_perms(self.user, [('department_duty_log', 'department_duty_log', ['view', 'add', 'edit', 'del'])])
        self.c = _make_client(self.user)
        self.rec = _make_record(self.user, duty_record='已签', status=STATUS_SIGNED, version=2)
    def test_cannot_edit_signed(self):
        r = self.c.put(f'/department-duty-log/records/{self.rec.id}/',
                       data=json.dumps({'duty_date': str(date.today()), 'weather': '雨',
                                        'duty_record': '篡改', 'remark': '', 'version': 2}),
                       content_type='application/json')
        b = json.loads(r.content)
        self.assertTrue(b.get('error'))
        self.assertIn('已签署', b['error'])
    def test_cannot_delete_signed(self):
        r = self.c.delete(f'/department-duty-log/records/{self.rec.id}/')
        b = json.loads(r.content)
        self.assertTrue(b.get('error'))
        self.assertTrue(DepartmentDutyLog.objects.filter(pk=self.rec.id).exists())


# 风险点 6：跨用户操作防护
class CRUDRisk6_CrossUserTests(TestCase):
    """验证：用户不能编辑/删除/查看他人草稿。"""
    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.owner = _make_user('crud_owner6', tenant_id='ta')
        _grant_perms(self.owner, [('department_duty_log', 'department_duty_log', ['view', 'add', 'edit', 'del', 'sign'])])
        self.attacker = _make_user('crud_atk6', tenant_id='ta')
        _grant_perms(self.attacker, [('department_duty_log', 'department_duty_log', ['view', 'add', 'edit', 'del', 'sign'])])
        self.oc = _make_client(self.owner)
        self.ac = _make_client(self.attacker)
        r = self.oc.post('/department-duty-log/records/',
                        data=json.dumps({'duty_date': str(date.today()), 'weather': '晴',
                                         'duty_record': 'owner草稿', 'remark': ''}),
                        content_type='application/json')
        self.did = json.loads(r.content)['data']['id']
    def test_cannot_edit_other_draft(self):
        r = self.ac.put(f'/department-duty-log/records/{self.did}/',
                       data=json.dumps({'duty_date': str(date.today()), 'weather': '雨',
                                        'duty_record': '篡改', 'remark': '', 'version': 1}),
                       content_type='application/json')
        self.assertTrue(json.loads(r.content).get('error'))
    def test_cannot_delete_other_draft(self):
        r = self.ac.delete(f'/department-duty-log/records/{self.did}/')
        self.assertTrue(json.loads(r.content).get('error'))
    def test_cannot_view_other_draft_detail(self):
        r = self.ac.get(f'/department-duty-log/records/{self.did}/')
        self.assertTrue(json.loads(r.content).get('error'))
    def test_other_draft_not_in_list(self):
        r = self.ac.get('/department-duty-log/records/')
        items = json.loads(r.content)['data']['records']
        self.assertFalse(any(i['id'] == self.did for i in items))


# 风险点 7：乐观锁并发更新防护
class CRUDRisk7_OptimisticLockTests(TestCase):
    """验证：乐观锁防止并发覆盖。"""
    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('crud_u7', tenant_id='ta')
        _grant_perms(self.user, [('department_duty_log', 'department_duty_log', ['view', 'add', 'edit'])])
        self.c = _make_client(self.user)
        r = self.c.post('/department-duty-log/records/',
                       data=json.dumps({'duty_date': str(date.today()), 'weather': '晴',
                                        'duty_record': '并发', 'remark': ''}),
                       content_type='application/json')
        self.rid = json.loads(r.content)['data']['id']
    def test_old_version_rejected(self):
        self.c.put(f'/department-duty-log/records/{self.rid}/',
                   data=json.dumps({'duty_date': str(date.today()), 'weather': '阴',
                                    'duty_record': '第一次', 'remark': '', 'version': 1}),
                   content_type='application/json')
        r = self.c.put(f'/department-duty-log/records/{self.rid}/',
                      data=json.dumps({'duty_date': str(date.today()), 'weather': '雨',
                                       'duty_record': '旧版本', 'remark': '', 'version': 1}),
                      content_type='application/json')
        b = json.loads(r.content)
        self.assertTrue(b.get('error'))
        self.assertIn('版本', b['error'])
    def test_correct_version_succeeds(self):
        r = self.c.put(f'/department-duty-log/records/{self.rid}/',
                      data=json.dumps({'duty_date': str(date.today()), 'weather': '多云',
                                       'duty_record': '正确', 'remark': '', 'version': 1}),
                      content_type='application/json')
        b = json.loads(r.content)
        self.assertFalse(b.get('error'))
        self.assertEqual(b['data']['version'], 2)


# 风险点 8：软删除隔离
class CRUDRisk8_SoftDeleteTests(TestCase):
    """验证：软删除后记录从列表/详情消失，不可再操作。"""
    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('crud_u8', tenant_id='ta')
        _grant_perms(self.user, [('department_duty_log', 'department_duty_log', ['view', 'add', 'edit', 'del'])])
        self.c = _make_client(self.user)
        r = self.c.post('/department-duty-log/records/',
                       data=json.dumps({'duty_date': str(date.today()), 'weather': '晴',
                                        'duty_record': '删除测试', 'remark': ''}),
                       content_type='application/json')
        self.rid = json.loads(r.content)['data']['id']
    def test_deleted_not_in_list(self):
        self.c.delete(f'/department-duty-log/records/{self.rid}/')
        r = self.c.get('/department-duty-log/records/')
        items = json.loads(r.content)['data']['records']
        self.assertFalse(any(i['id'] == self.rid for i in items))
    def test_deleted_not_in_detail(self):
        self.c.delete(f'/department-duty-log/records/{self.rid}/')
        r = self.c.get(f'/department-duty-log/records/{self.rid}/')
        self.assertTrue(json.loads(r.content).get('error'))
    def test_deleted_cannot_edit(self):
        self.c.delete(f'/department-duty-log/records/{self.rid}/')
        r = self.c.put(f'/department-duty-log/records/{self.rid}/',
                      data=json.dumps({'duty_date': str(date.today()), 'weather': '雨',
                                       'duty_record': 'x', 'remark': '', 'version': 1}),
                      content_type='application/json')
        self.assertTrue(json.loads(r.content).get('error'))
    def test_soft_delete_preserves_data(self):
        self.c.delete(f'/department-duty-log/records/{self.rid}/')
        rec = DepartmentDutyLog.objects.get(pk=self.rid)
        self.assertIsNotNone(rec.deleted_at)
        self.assertEqual(rec.duty_record, '删除测试')


# 风险点 9：退回操作彻底清除签署字段
@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class CRUDRisk9_ReturnClearsSignatureTests(TestCase):
    """验证：退回操作清除全部签署字段并递增版本号。"""
    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.supper = _make_user('crud_sp9', is_supper=True, tenant_id='default')
        self.sc = _make_client(self.supper)
        self.signer = _make_user('crud_sg9', tenant_id='ta')
        _grant_perms(self.signer, [('department_duty_log', 'department_duty_log', ['view', 'add', 'sign', 'return'])])
        self.sgc = _make_client(self.signer)
        self.sc.post(f'/account/user/{self.signer.id}/signature/',
                     {'file': _make_png_file(), 'remark': 'crud sig'})
        r = self.sgc.post('/department-duty-log/records/',
                         data=json.dumps({'duty_date': str(date.today()), 'weather': '晴',
                                          'duty_record': '退回测试', 'remark': ''}),
                         content_type='application/json')
        rid = json.loads(r.content)['data']['id']
        self.sgc.post(f'/department-duty-log/records/{rid}/sign/',
                      data=json.dumps({'version': 1, 'confirm': True,
                                       'request_id': f'crud-ret-{uuid.uuid4().hex[:8]}'}),
                      content_type='application/json')
        self.rec = DepartmentDutyLog.objects.get(pk=rid)
        self.signed_ver = self.rec.version
    def tearDown(self):
        sb = os.path.join(settings.MEDIA_ROOT, sig_services.SIGNATURE_MODULE)
        if os.path.exists(sb): shutil.rmtree(sb, ignore_errors=True)
    def test_return_clears_all_fields(self):
        self.sgc.post(f'/department-duty-log/records/{self.rec.id}/return/')
        self.rec.refresh_from_db()
        self.assertEqual(self.rec.status, STATUS_DRAFT)
        self.assertIsNone(self.rec.signature_usage_id)
        self.assertIsNone(self.rec.signed_by_id)
        self.assertIsNone(self.rec.signed_at)
        self.assertIsNone(self.rec.signature_version)
        self.assertEqual(self.rec.signed_by_name, '')
        self.assertEqual(self.rec.signature_sha256, '')
        self.assertEqual(self.rec.business_snapshot_hash, '')
    def test_return_increments_version(self):
        self.sgc.post(f'/department-duty-log/records/{self.rec.id}/return/')
        self.rec.refresh_from_db()
        self.assertEqual(self.rec.version, self.signed_ver + 1)
    def test_returned_draft_editable(self):
        self.sgc.post(f'/department-duty-log/records/{self.rec.id}/return/')
        self.rec.refresh_from_db()
        self.rec.duty_record = '退回后修改'
        self.rec.save()
        self.rec.refresh_from_db()
        self.assertEqual(self.rec.duty_record, '退回后修改')
