"""upgrade 模块 CRUD 审计测试脚本"""
import os, sys, traceback, inspect, re
from datetime import datetime, timedelta
from django.db import connection
from django.utils import timezone

_results = []

def _record(name, passed, detail=''):
    _results.append({'name': name, 'passed': passed, 'detail': detail})
    symbol = '✓' if passed else '✗'
    print(f'  {symbol} {name}: {"PASS" if passed else "FAIL"} {detail}')

def _cleanup(model, **filters):
    try: model.objects.filter(**filters).delete()
    except: pass

def _make_user():
    from apps.account.models import User
    return User.objects.filter(username='admin').first() or User.objects.first()

def _clean_all(prefix):
    from apps.upgrade.models import UpgradeRecord, UpgradeRecordStep
    from apps.upgrade.models_template import UpgradeTemplate, UpgradePlanStep
    from apps.upgrade.models_status_log import UpgradeStatusLog
    rids = list(UpgradeRecord.objects.filter(title__startswith=prefix).values_list('id', flat=True))
    if rids:
        _cleanup(UpgradeStatusLog, upgrade_id__in=rids)
        _cleanup(UpgradeRecordStep, upgrade_id__in=rids)
    _cleanup(UpgradeRecord, title__startswith=prefix)
    tids = list(UpgradeTemplate.objects.filter(name__startswith=prefix).values_list('id', flat=True))
    if tids:
        _cleanup(UpgradePlanStep, template_id__in=tids)
    _cleanup(UpgradeTemplate, name__startswith=prefix)

# R01: upload.py _get_record 不过滤 is_deleted
def test_r01():
    from apps.upgrade.models import UpgradeRecord
    from apps.upgrade.views.upload import _get_record
    user = _make_user()
    r = UpgradeRecord.objects.create(
        tenant_id=getattr(user,'tenant_id','admin'), title='AUD_R01_TEST',
        system='测试', upgrade_type='常规', upgrade_time=timezone.now(),
        status='处理中', owner='测试', created_by=user)
    try:
        r.is_deleted=True; r.deleted_at=timezone.now(); r.save(update_fields=['is_deleted','deleted_at'])
        result=_get_record(r.id, user)
        _record('R01_upload_no_is_deleted_filter', result is not None,
            f'_get_record 返回了软删除记录(id={r.id})' if result else '正确过滤了')
    finally: _cleanup(UpgradeRecord, pk=r.id)

# R02: exporters.py 不过滤 is_deleted
def test_r02():
    from apps.upgrade.models import UpgradeRecord
    from libs.tenant_utils import apply_tenant_filter
    user=_make_user()
    p='AUD_R02_TEST'
    _clean_all(p)
    UpgradeRecord.objects.create(
        tenant_id=getattr(user,'tenant_id','admin'), title=f'{p}_正常',
        system='测试', upgrade_type='常规', upgrade_time=timezone.now(),
        status='处理中', owner='测试', created_by=user)
    UpgradeRecord.objects.create(
        tenant_id=getattr(user,'tenant_id','admin'), title=f'{p}_已删',
        system='测试', upgrade_type='常规', upgrade_time=timezone.now(),
        status='处理中', owner='测试', created_by=user,
        is_deleted=True, deleted_at=timezone.now())
    try:
        qs=apply_tenant_filter(UpgradeRecord.objects.all(), user)
        titles=list(qs.values_list('title',flat=True))
        bug = f'{p}_已删' in titles
        _record('R02_export_no_is_deleted_filter', bug,
            f'导出包含软删除记录' if bug else '正确过滤了')
    finally: _clean_all(p)

# R03: statistics_service 不过滤 is_deleted
def test_r03():
    from apps.upgrade.models import UpgradeRecord
    from apps.upgrade.services.statistics_service import StatisticsService
    user=_make_user(); p='AUD_R03_TEST'
    _clean_all(p)
    for i in range(2):
        UpgradeRecord.objects.create(
            tenant_id=getattr(user,'tenant_id','admin'), title=f'{p}_{i}',
            system='AUD_R03_SYS', upgrade_type='常规', upgrade_time=timezone.now(),
            status='处理中', owner='测试', created_by=user)
    UpgradeRecord.objects.create(
        tenant_id=getattr(user,'tenant_id','admin'), title=f'{p}_del',
        system='AUD_R03_SYS', upgrade_type='常规', upgrade_time=timezone.now(),
        status='处理中', owner='测试', created_by=user,
        is_deleted=True, deleted_at=timezone.now())
    try:
        stats=StatisticsService.get_statistics(user, filters={'system':'AUD_R03_SYS'})
        total=stats['total_count']
        _record('R03_stats_no_is_deleted_filter', total==3,
            f'total={total}（期望2，包含软删除记录）' if total==3 else f'total={total}，正确')
    finally: _clean_all(p)

# R04: status_log_service.add_log 不过滤 is_deleted
def test_r04():
    from apps.upgrade.models import UpgradeRecord
    from apps.upgrade.models_status_log import UpgradeStatusLog
    from apps.upgrade.services.status_log_service import StatusLogService
    user=_make_user()
    r=UpgradeRecord.objects.create(
        tenant_id=getattr(user,'tenant_id','admin'), title='AUD_R04_TEST',
        system='测试', upgrade_type='常规', upgrade_time=timezone.now(),
        status='处理中', owner='测试', created_by=user)
    log_id=None
    try:
        r.is_deleted=True; r.deleted_at=timezone.now(); r.save(update_fields=['is_deleted','deleted_at'])
        log,err=StatusLogService.add_log(upgrade_id=r.id, user=user, action='pause', remark='R04审计')
        if log: log_id=log.id
        _record('R04_status_log_no_is_deleted_filter', log is not None,
            f'成功对软删除记录添加了状态日志(log_id={log_id})' if log else f'正确拒绝了(err={err})')
    finally:
        if log_id: _cleanup(UpgradeStatusLog, pk=log_id)
        _cleanup(UpgradeRecord, pk=r.id)

# R05: apply_to_record replace 模式物理删除 + 不过滤 is_deleted
def test_r05():
    from apps.upgrade.models import UpgradeRecord, UpgradeRecordStep
    from apps.upgrade.models_template import UpgradeTemplate, UpgradePlanStep
    from apps.upgrade.services.plan_service import PlanService
    user=_make_user(); p='AUD_R05_TEST'
    _clean_all(p)
    r=UpgradeRecord.objects.create(
        tenant_id=getattr(user,'tenant_id','admin'), title=f'{p}_记录',
        system='测试', upgrade_type='常规', upgrade_time=timezone.now(),
        status='处理中', owner='测试', created_by=user)
    t=UpgradeTemplate.objects.create(
        tenant_id=getattr(user,'tenant_id','admin'), name=f'{p}_模板',
        system='测试', upgrade_type='常规', created_by=user)
    UpgradePlanStep.objects.create(
        tenant_id=getattr(user,'tenant_id','admin'), template_id=t.id,
        phase='新阶段', title='新步骤', description='', sequence=1, is_required=True)
    try:
        for i in range(3):
            UpgradeRecordStep.objects.create(
                tenant_id=getattr(user,'tenant_id','admin'), upgrade_id=r.id,
                checklist_id=0, phase='旧阶段', title=f'旧步骤{i+1}',
                description='', sequence=i+1, is_required=True, status='pending',
                is_deleted=(i==2))
        msg, applied = PlanService.apply_to_record(plan_id=t.id, upgrade_id=r.id, user=user, replace=True)
        old_remaining=UpgradeRecordStep.objects.filter(upgrade_id=r.id, title__startswith='旧步骤').count()
        _record('R05_apply_replace_physical_delete', old_remaining==0,
            f'旧步骤残留={old_remaining}（物理删除了含已软删除的所有旧步骤）' if old_remaining==0 else f'旧步骤残留={old_remaining}')
    finally: _clean_all(p)

# R06: apply_to_record append 模式 start_seq 被夸大
def test_r06():
    from apps.upgrade.models import UpgradeRecord, UpgradeRecordStep
    from apps.upgrade.models_template import UpgradeTemplate, UpgradePlanStep
    from apps.upgrade.services.plan_service import PlanService
    user=_make_user(); p='AUD_R06_TEST'
    _clean_all(p)
    r=UpgradeRecord.objects.create(
        tenant_id=getattr(user,'tenant_id','admin'), title=f'{p}_记录',
        system='测试', upgrade_type='常规', upgrade_time=timezone.now(),
        status='处理中', owner='测试', created_by=user)
    t=UpgradeTemplate.objects.create(
        tenant_id=getattr(user,'tenant_id','admin'), name=f'{p}_模板',
        system='测试', upgrade_type='常规', created_by=user)
    UpgradePlanStep.objects.create(
        tenant_id=getattr(user,'tenant_id','admin'), template_id=t.id,
        phase='新阶段', title='新追加步骤', description='', sequence=1, is_required=True)
    try:
        for i in range(5):
            UpgradeRecordStep.objects.create(
                tenant_id=getattr(user,'tenant_id','admin'), upgrade_id=r.id,
                checklist_id=0, phase='旧阶段', title=f'旧步骤{i+1}',
                description='', sequence=i+1, is_required=True, status='pending',
                is_deleted=(i>=3))
        msg, applied = PlanService.apply_to_record(plan_id=t.id, upgrade_id=r.id, user=user, replace=False)
        new_step=UpgradeRecordStep.objects.filter(upgrade_id=r.id, title='新追加步骤').first()
        if new_step:
            seq=new_step.sequence
            _record('R06_apply_append_inflated_seq', seq==6,
                f'新步骤 seq={seq}（正确应为4，被夸大到{seq}）' if seq==6 else f'新步骤 seq={seq}，正确')
        else:
            _record('R06_apply_append_inflated_seq', False, '新步骤未创建')
    finally: _clean_all(p)

# R07: 日期范围过滤 __lte 边界问题
def test_r07():
    from apps.upgrade.models import UpgradeRecord
    user=_make_user(); p='AUD_R07_TEST'
    _clean_all(p)
    UpgradeRecord.objects.create(
        tenant_id=getattr(user,'tenant_id','admin'), title=f'{p}_中午',
        system='测试', upgrade_type='常规',
        upgrade_time=datetime(2026,8,1,12,0,0),
        status='处理中', owner='测试', created_by=user)
    try:
        from libs.tenant_utils import apply_tenant_filter
        qs=apply_tenant_filter(UpgradeRecord.objects.all(), user)
        count=qs.filter(upgrade_time__gte='2026-08-01', upgrade_time__lte='2026-08-01').count()
        _record('R07_date_range_boundary', count==0,
            f'单日范围 count={count}（期望1，__lte只匹配午夜）' if count==0 else f'单日范围 count={count}，正确')
    finally: _clean_all(p)

# R08: batch_update_status 事务边界（代码审查型）
def test_r08():
    from apps.upgrade.services.step_service import RecordStepService
    source=inspect.getsource(RecordStepService.batch_update_status)
    lines=source.split('\n')
    atomic_indent=None
    log_outside=[]
    for line in lines:
        if 'with transaction.atomic()' in line:
            atomic_indent=len(line)-len(line.lstrip())
        elif ('StatusLogService.' in line or '_check_and_update_record_status' in line) and atomic_indent is not None:
            ci=len(line)-len(line.lstrip())
            if ci<=atomic_indent:
                log_outside.append(line.strip())
    _record('R08_batch_update_txn_boundary', len(log_outside)>0,
        f'发现{len(log_outside)}处在atomic块外的调用' if log_outside else '所有调用在atomic块内')

# R09: batch_update_status 步骤过滤不过滤 is_deleted
def test_r09():
    from apps.upgrade.models import UpgradeRecord, UpgradeRecordStep
    from apps.upgrade.models_status_log import UpgradeStatusLog
    from apps.upgrade.services.step_service import RecordStepService
    user=_make_user(); p='AUD_R09_TEST'
    _clean_all(p)
    r=UpgradeRecord.objects.create(
        tenant_id=getattr(user,'tenant_id','admin'), title=f'{p}_记录',
        system='测试', upgrade_type='常规', upgrade_time=timezone.now(),
        status='处理中', owner='测试', created_by=user)
    s1=UpgradeRecordStep.objects.create(
        tenant_id=getattr(user,'tenant_id','admin'), upgrade_id=r.id, checklist_id=0,
        phase='阶段A', title='活跃1', description='', sequence=1, is_required=True, status='pending')
    s2=UpgradeRecordStep.objects.create(
        tenant_id=getattr(user,'tenant_id','admin'), upgrade_id=r.id, checklist_id=0,
        phase='阶段A', title='活跃2', description='', sequence=2, is_required=True, status='pending')
    s3=UpgradeRecordStep.objects.create(
        tenant_id=getattr(user,'tenant_id','admin'), upgrade_id=r.id, checklist_id=0,
        phase='阶段A', title='已删除', description='', sequence=3, is_required=True, status='pending',
        is_deleted=True, deleted_at=timezone.now())
    try:
        RecordStepService.batch_update_status(
            upgrade_id=r.id,
            steps_data=[
                {'step_id': s1.id, 'action': 'complete', 'remark': ''},
                {'step_id': s2.id, 'action': 'complete', 'remark': ''},
                {'step_id': s3.id, 'action': 'complete', 'remark': ''},
            ],
            user=user)
        s3.refresh_from_db()
        _record('R09_batch_update_deleted_step', s3.status=='completed',
            f'软删除步骤 status 被更新为 {s3.status}' if s3.status=='completed' else f'软删除步骤未被更新 status={s3.status}')
    finally: _clean_all(p)

# R10: save() 无 update_fields（代码审查型）
def test_r10():
    from apps.upgrade.services.record_service import RecordService
    from apps.upgrade.services.step_service import RecordStepService
    from apps.upgrade.services.plan_service import PlanService
    for name, method in [
        ('R10a_update_record', RecordService.update_record),
        ('R10b_delete_record', RecordService.delete_record),
        ('R10c_delete_step', RecordStepService.delete_step),
        ('R10d_update_plan', PlanService.update_plan),
    ]:
        try:
            src=inspect.getsource(method)
            saves=re.findall(r'\.save\(([^)]*)\)', src)
            bug = any('update_fields' not in s for s in saves) and len(saves)>0
            _record(name, bug,
                f'{len(saves)}处save()无update_fields' if bug else 'save()有update_fields或无save调用')
        except Exception as e:
            _record(name, False, f'检查失败: {e}')

# R11: _apply_filters 使用 icontains
def test_r11():
    from apps.upgrade.services.record_service import RecordService
    src=inspect.getsource(RecordService._apply_filters)
    _record('R11a_system_icontains', 'system__icontains' in src,
        'system__icontains生成LIKE %xxx%' if 'system__icontains' in src else 'system精确匹配')
    _record('R11b_owner_icontains', 'owner__icontains' in src,
        'owner__icontains生成LIKE %xxx%' if 'owner__icontains' in src else 'owner精确匹配')

# R12: created_at=now_str 传给 auto_now_add 字段
def test_r12():
    from apps.upgrade.services.record_service import RecordService
    from apps.upgrade.services.step_service import RecordStepService
    src1=inspect.getsource(RecordService.create_record)
    _record('R12a_create_record_created_at_str', 'created_at=' in src1,
        '传递created_at给auto_now_add字段（死代码）' if 'created_at=' in src1 else '未传')
    try:
        src2=inspect.getsource(RecordStepService.add_manual_step)
        _record('R12b_add_step_created_at_str', 'created_at=' in src2,
            '传递created_at给auto_now_add字段（死代码）' if 'created_at=' in src2 else '未传')
    except: _record('R12b_add_step_created_at_str', False, '方法不存在')

# R13: status_log_service.check_phase_completion 不过滤 is_deleted 步骤
def test_r13():
    from apps.upgrade.services.status_log_service import StatusLogService
    src=inspect.getsource(StatusLogService.check_phase_completion)
    # 检查步骤查询是否过滤 is_deleted=False
    has_is_deleted_filter = 'is_deleted=False' in src or 'is_deleted__exact=False' in src
    _record('R13_check_phase_no_is_deleted', not has_is_deleted_filter,
        'check_phase_completion 查询步骤未过滤 is_deleted=False' if not has_is_deleted_filter else '已过滤')

# R14: plan_service.apply_to_record 不过滤 is_deleted 记录
def test_r14():
    from apps.upgrade.services.plan_service import PlanService
    src=inspect.getsource(PlanService.apply_to_record)
    # 检查记录查询是否过滤 is_deleted=False
    has_is_deleted = 'is_deleted=False' in src
    _record('R14_apply_to_record_no_is_deleted', not has_is_deleted,
        'apply_to_record 查询记录未过滤 is_deleted=False' if not has_is_deleted else '已过滤')


# ====== 主函数 ======
def main():
    print('='*70)
    print('  Upgrade 模块 CRUD 审计测试')
    print('  基于 CRUD系统可靠性指南.md + 前10模块审计经验')
    print('='*70)
    tests = [
        ('R01 upload._get_record 不过滤 is_deleted (P0)', test_r01),
        ('R02 exporters 不过滤 is_deleted (P0)', test_r02),
        ('R03 statistics 不过滤 is_deleted (P0)', test_r03),
        ('R04 status_log.add_log 不过滤 is_deleted (P0)', test_r04),
        ('R05 apply_to_record replace 物理删除+不过滤 (P1)', test_r05),
        ('R06 apply_to_record append start_seq 夸大 (P1)', test_r06),
        ('R07 日期范围 __lte 边界问题 (P1)', test_r07),
        ('R08 batch_update 事务边界 (P1)', test_r08),
        ('R09 batch_update 步骤过滤不过滤 is_deleted (P2)', test_r09),
        ('R10 save() 无 update_fields (P1)', test_r10),
        ('R11 _apply_filters icontains 性能 (P2)', test_r11),
        ('R12 created_at=now_str 死代码 (P2)', test_r12),
        ('R13 check_phase_completion 不过滤 is_deleted (P1)', test_r13),
        ('R14 apply_to_record 不过滤记录 is_deleted (P1)', test_r14),
    ]
    for label, fn in tests:
        print(f'\n--- {label} ---')
        try:
            fn()
        except Exception as e:
            _record(label.split(' ')[0], False, f'EXCEPTION: {e}')
            traceback.print_exc()

    # 汇总
    print('\n' + '='*70)
    total = len(_results)
    passed = sum(1 for r in _results if r['passed'])
    failed = sum(1 for r in _results if not r['passed'])
    print(f'  总计: {total} 项 | 通过(BUG确认): {passed} | 未确认: {failed}')
    print('='*70)
    for r in _results:
        symbol = '✓' if r['passed'] else '✗'
        print(f'  {symbol} {r["name"]}: {r["detail"]}')
    print('='*70)
    return _results

if __name__ == '__main__' or 'DJANGO_SETTINGS_MODULE' in os.environ:
    main()
