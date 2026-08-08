#!/usr/bin/env python
"""租户隔离专项测试 - 独立运行脚本
在 Docker 内: python manage.py shell < tests/tenant_isolation/run_tests.py
"""
import json, uuid, traceback, time
from datetime import date
from django.test import Client

# Monkey-patch Client to always set REMOTE_ADDR
_orig_request = Client.request
def _patched_request(self, **request):
    request['HTTP_X_REAL_IP'] = '127.0.0.1'
    return _orig_request(self, **request)
Client.request = _patched_request

RESULTS = []
def rec(module, test, passed, detail='', sev='info'):
    RESULTS.append({'module':module,'test':test,'passed':passed,'detail':detail,'severity':sev})
    print(f"  [{'PASS' if passed else 'FAIL'}] {test}: {detail}")

def _uid(): return uuid.uuid4().hex[:12]

def setup_data():
    from apps.account.models import User, Role, Tenant
    from apps.reminder.models import Reminder
    from apps.runlog.models import RunLog
    from apps.fault.models import FaultRecord
    from apps.regulation.models import Regulation, RegulationCategory
    # 获取一个现有用户作为 created_by（Tenant/Role 的 FK）
    bootstrap_user = User.objects.first()
    d = {}
    d['tid_a'] = f'ti_a_{_uid()}'
    d['tid_b'] = f'ti_b_{_uid()}'
    d['tenant_a'] = Tenant.objects.create(id=d['tid_a'], name='测试A', created_by=bootstrap_user)
    d['tenant_b'] = Tenant.objects.create(id=d['tid_b'], name='测试B', created_by=bootstrap_user)
    perms = json.dumps({"home":{"reminder":["view","add","edit","delete"]},"runlog":{"runlog":["view","add","edit","del","update_view","update_add","update_edit","update_del"]},"fault":{"faultrecord":["view","add","edit","del"]},"regulation":{"regulation":["view","add","edit","del"]},"dashboard":{"dashboard":["view"]},"system":{"account":["view","add","edit","del"],"role":["view","add","edit","del"]},"logs":{"audit":["view"]}})
    for lbl, tid, uname in [('ua',d['tid_a'],f'ti_a_{_uid()}'),('ub',d['tid_b'],f'ti_b_{_uid()}')]:
        r = Role.objects.create(name=f'r{uname}',tenant_id=tid,page_perms=perms,created_by=bootstrap_user)
        u = User(username=uname,nickname=uname,password_hash=User.make_password('t'),tenant_id=tid,is_supper=False,is_active=True,access_token=uuid.uuid4().hex,last_ip='127.0.0.1',token_expired=time.time()+86400)
        u.save(); u.roles.add(r)
        d[lbl]=u; d[f'tk_{lbl}']=u.access_token
    d['rem_a']=Reminder.objects.create(name=f'RA_{_uid()}',target_date=date.today(),repeat_type='none',content='c',enabled=True,recipient_users='[]',tenant_id=d['tid_a'],created_by_id=d['ua'].id,created_by_name=d['ua'].nickname)
    d['rem_b']=Reminder.objects.create(name=f'RB_{_uid()}',target_date=date.today(),repeat_type='none',content='c',enabled=True,recipient_users='[]',tenant_id=d['tid_b'],created_by_id=d['ub'].id,created_by_name=d['ub'].nickname)
    d['rl_a']=RunLog.objects.create(event_title=f'LA_{_uid()}',event_type='运行异常',system_name='SA',severity='P2',status='in_progress',created_by=d['ua'],tenant_id=d['tid_a'])
    d['rl_b']=RunLog.objects.create(event_title=f'LB_{_uid()}',event_type='运行异常',system_name='SB',severity='P2',status='in_progress',created_by=d['ub'],tenant_id=d['tid_b'])
    d['ft_a']=FaultRecord.objects.create(system_name=f'FA_{_uid()}',device_code='DA',handler='h',recorder='r',fault_level='一般',fault_phenomenon='p',handling_process='pr',created_by=d['ua'],tenant_id=d['tid_a'])
    d['ft_b']=FaultRecord.objects.create(system_name=f'FB_{_uid()}',device_code='DB',handler='h',recorder='r',fault_level='一般',fault_phenomenon='p',handling_process='pr',created_by=d['ub'],tenant_id=d['tid_b'])
    d['reg_cat']=RegulationCategory.objects.create(name=f'RC_{_uid()}', created_by=bootstrap_user)
    d['reg']=Regulation.objects.create(title=f'RG_{_uid()}',rule_no=f'NO_{_uid()}',category=d['reg_cat'])
    return d

def cleanup(d):
    from apps.account.models import User,Role,Tenant
    from apps.reminder.models import Reminder
    from apps.runlog.models import RunLog
    from apps.fault.models import FaultRecord
    from apps.regulation.models import Regulation,RegulationCategory
    for m in [Reminder,RunLog,FaultRecord]:
        m.objects.filter(tenant_id__in=[d['tid_a'],d['tid_b']]).delete()
    Regulation.objects.filter(pk=d['reg'].pk).delete()
    RegulationCategory.objects.filter(pk=d['reg_cat'].pk).delete()
    for k in ['ua','ub']:
        u=d[k]; u.roles.clear(); u.delete()
    Role.objects.filter(tenant_id__in=[d['tid_a'],d['tid_b']]).delete()
    Tenant.objects.filter(id__in=[d['tid_a'],d['tid_b']]).delete()

def _body(resp):
    try: return resp.json()
    except: return {'raw': resp.content[:200].decode('utf-8','ignore')}

def _items(body):
    if isinstance(body,list): return body
    if isinstance(body,dict):
        if body.get('error'): return []
        return body.get('data',body.get('items',[]))
    return []

# === 测试 ===
def test_nav_removed(d):
    c=Client(); r=c.get('/home/navigation/',**{'HTTP_X_TOKEN':d['tk_ua']})
    rec('home/navigation','Nav接口已删除',r.status_code==404,f'status={r.status_code}(应404)',sev='critical' if r.status_code!=404 else 'info')

def test_rem_list(d):
    c=Client(); r=c.get('/reminder/',**{'HTTP_X_TOKEN':d['tk_ua']})
    b=_body(r); items=_items(b)
    names=[str(i.get('name','')) for i in items]
    has_b=any('RB_' in n for n in names)
    rec('reminder','Reminder列表跨租户',not has_b,f'看到B:{has_b},共{len(items)}条',sev='high' if has_b else 'info')

def test_rem_users(d):
    c=Client(); r=c.get('/reminder/users/',**{'HTTP_X_TOKEN':d['tk_ua']})
    b=_body(r); users=_items(b)
    found_b=any(u.get('id')==d['ub'].id for u in users)
    rec('reminder','ReminderUsers跨租户泄露',not found_b,f'看到B用户:{found_b},共{len(users)}用户',sev='high' if found_b else 'info')

def test_rem_edit(d):
    c=Client(); bid=d['rem_b'].id
    r=c.put('/reminder/',data=json.dumps({'id':bid,'name':'HACKED'}),content_type='application/json',**{'HTTP_X_TOKEN':d['tk_ua']})
    from apps.reminder.models import Reminder
    n=Reminder.objects.get(pk=bid)
    rec('reminder','Reminder修改跨租户',n.name!='HACKED',f'name={n.name},resp={_body(r)}',sev='high' if n.name=='HACKED' else 'info')

def test_rem_del(d):
    c=Client(); bid=d['rem_b'].id
    r=c.delete(f'/reminder/?id={bid}',**{'HTTP_X_TOKEN':d['tk_ua']})
    from apps.reminder.models import Reminder
    n=Reminder.objects.filter(pk=bid,is_deleted=False).first()
    rec('reminder','Reminder删除跨租户',n is not None,f'已删={n is None},resp={_body(r)}',sev='high' if n is None else 'info')

def test_rem_tenant_forgery(d):
    c=Client()
    r=c.post('/reminder/',data=json.dumps({'name':'FORGE','target_date':str(date.today()),'repeat_type':'none','content':'c','tenant_id':d['tid_b']}),content_type='application/json',**{'HTTP_X_TOKEN':d['tk_ua']})
    b=_body(r)
    from apps.reminder.models import Reminder
    if b and not b.get('error') and b.get('id'):
        obj=Reminder.objects.get(pk=b['id'])
        forged=obj.tenant_id==d['tid_b']
        rec('reminder','Reminder租户伪造',not forged,f'伪造tid_b,实际={obj.tenant_id}',sev='critical' if forged else 'info')
        obj.delete()
    else:
        rec('reminder','Reminder租户伪造',True,f'创建失败:{b}')

def test_rl_list(d):
    c=Client(); r=c.get('/runlog/',**{'HTTP_X_TOKEN':d['tk_ua']})
    b=_body(r); items=_items(b)
    titles=[str(i.get('event_title','')) for i in items]
    has_b=any('LB_' in t for t in titles)
    rec('runlog','RunLog列表跨租户',not has_b,f'看到B:{has_b},共{len(items)}条',sev='high' if has_b else 'info')

def test_rl_detail(d):
    c=Client(); bid=d['rl_b'].id
    r=c.get(f'/runlog/{bid}/',**{'HTTP_X_TOKEN':d['tk_ua']})
    b=_body(r)
    leaked=not b.get('error') and b.get('id')==bid
    rec('runlog','RunLog详情跨租户',not leaked,f'resp={b}',sev='high' if leaked else 'info')

def test_rl_edit(d):
    c=Client(); bid=d['rl_b'].id
    r=c.put(f'/runlog/{bid}/',data=json.dumps({'event_title':'HACKED'}),content_type='application/json',**{'HTTP_X_TOKEN':d['tk_ua']})
    from apps.runlog.models import RunLog
    n=RunLog.objects.get(pk=bid)
    rec('runlog','RunLog修改跨租户',n.event_title!='HACKED',f'title={n.event_title},resp={_body(r)}',sev='high' if n.event_title=='HACKED' else 'info')

def test_rl_del(d):
    c=Client(); bid=d['rl_b'].id
    r=c.delete(f'/runlog/{bid}/',**{'HTTP_X_TOKEN':d['tk_ua']})
    from apps.runlog.models import RunLog
    n=RunLog.objects.filter(pk=bid,is_deleted=False).first()
    rec('runlog','RunLog删除跨租户',n is not None,f'已删={n is None},resp={_body(r)}',sev='high' if n is None else 'info')

def test_ft_list(d):
    c=Client(); r=c.get('/fault/',**{'HTTP_X_TOKEN':d['tk_ua']})
    b=_body(r); items=_items(b)
    systems=[str(i.get('system_name','')) for i in items]
    has_b=any('FB_' in s for s in systems)
    rec('fault','Fault列表跨租户',not has_b,f'看到B:{has_b},共{len(items)}条',sev='high' if has_b else 'info')

def test_ft_edit(d):
    c=Client(); bid=d['ft_b'].id
    r=c.put(f'/fault/{bid}/',data=json.dumps({'system_name':'HACKED'}),content_type='application/json',**{'HTTP_X_TOKEN':d['tk_ua']})
    from apps.fault.models import FaultRecord
    n=FaultRecord.objects.get(pk=bid)
    rec('fault','Fault修改跨租户',n.system_name!='HACKED',f'system={n.system_name},resp={_body(r)}',sev='high' if n.system_name=='HACKED' else 'info')

def test_ft_del(d):
    c=Client(); bid=d['ft_b'].id
    r=c.delete(f'/fault/{bid}/',**{'HTTP_X_TOKEN':d['tk_ua']})
    from apps.fault.models import FaultRecord
    n=FaultRecord.objects.filter(pk=bid,is_deleted=False).first()
    rec('fault','Fault删除跨租户',n is not None,f'已删={n is None},resp={_body(r)}',sev='high' if n is None else 'info')

def test_dashboard(d):
    c=Client(); r=c.get('/home/statistic/',**{'HTTP_X_TOKEN':d['tk_ua']})
    b=_body(r)
    if b.get('error'):
        rec('dashboard','Dashboard统计隔离',True,f'错误:{b}')
        return
    # 检查 fault 统计是否包含 B 的数据
    fault_info=b.get('fault',{})
    recent=fault_info.get('recent',[])
    has_b=any('FB_' in str(r.get('system_name','')) for r in recent)
    rec('dashboard','Dashboard统计跨租户',not has_b,f'统计中含B数据:{has_b},fault_total={fault_info.get("total_all","?")}',sev='medium' if has_b else 'info')

def test_regulation_global(d):
    """Regulation 无 tenant_id - 记录为全局数据"""
    from apps.regulation.models import Regulation
    has_tenant = hasattr(Regulation, 'tenant_id')
    rec('regulation','Regulation无tenant_id(全局)',not has_tenant,
        f'Regulation有tenant_id字段:{has_tenant},无租户隔离',sev='info')

ALL_TESTS = [
    test_nav_removed,
    test_rem_list, test_rem_users, test_rem_edit, test_rem_del, test_rem_tenant_forgery,
    test_rl_list, test_rl_detail, test_rl_edit, test_rl_del,
    test_ft_list, test_ft_edit, test_ft_del,
    test_dashboard,
    test_regulation_global,
]

def main():
    print('='*60)
    print('  租户隔离与跨租户越权专项测试')
    print('='*60)
    d = setup_data()
    try:
        for t in ALL_TESTS:
            try:
                t(d)
            except Exception as e:
                rec(t.__name__, t.__name__, False, f'异常: {e}', 'error')
                traceback.print_exc()
    finally:
        cleanup(d)
    # 汇总
    print('\n' + '='*60)
    print('  测试汇总')
    print('='*60)
    passed = sum(1 for r in RESULTS if r['passed'])
    failed = sum(1 for r in RESULTS if not r['passed'])
    print(f'  总计: {len(RESULTS)} | 通过: {passed} | 失败: {failed}')
    if failed:
        print('\n  失败项:')
        for r in RESULTS:
            if not r['passed']:
                print(f"    [{r['severity'].upper()}] {r['module']}/{r['test']}: {r['detail']}")
    # 输出 JSON 供报告生成
    print('\n__RESULTS_JSON__')
    print(json.dumps(RESULTS, ensure_ascii=False))

if __name__ == '__main__':
    main()
