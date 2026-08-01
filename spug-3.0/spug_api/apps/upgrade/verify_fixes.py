"""upgrade 模块修复验证测试脚本

验证所有 19 项风险点的修复是否生效。
测试逻辑：每项测试确认"修复后的正确行为"，PASS = 修复生效。
"""
import os, sys, inspect, re, traceback
from datetime import datetime, timedelta
from django.db import connection
from django.utils import timezone

_results = []

def _record(name, passed, detail=''):
    _results.append({'name': name, 'passed': passed, 'detail': detail})
    symbol = '✓' if passed else '✗'
    print(f'  {symbol} {name}: {"FIXED" if passed else "STILL BROKEN"} | {detail}')

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
        # 使用 all_with_deleted 确保物理清理
        UpgradeRecordStep.objects.all_with_deleted().filter(upgrade_id__in=rids).delete()
    _cleanup(UpgradeRecord, title__startswith=prefix)
    tids = list(UpgradeTemplate.objects.filter(name__startswith=prefix).values_list('id', flat=True))
    if tids:
        _cleanup(UpgradePlanStep, template_id__in=tids)
    _cleanup(UpgradeTemplate, name__startswith=prefix)


# R01: upload._get_record 过滤了 is_deleted
def verify_r01():
    from apps.upgrade.models import UpgradeRecord
    from apps.upgrade.views.upload import _get_record
    user = _make_user()
    r = UpgradeRecord.objects.create(
        tenant_id=getattr(user,'tenant_id','admin'), title='VR01_TEST',
        system='测试', upgrade_type='常规', upgrade_time=timezone.now(),
        status='处理中', owner='测试', created_by=user)
    try:
        r.is_deleted=True; r.deleted_at=timezone.now(); r.save(update_fields=['is_deleted','deleted_at'])
        result = _get_record(r.id, user)
        _record('R01_upload_filters_is_deleted', result is None,
            '软删除记录被正确过滤' if result is None else '软删除记录仍可访问')
    finally: _cleanup(UpgradeRecord, pk=r.id)

# R02: exporters 过滤了 is_deleted
def verify_r02():
    from apps.upgrade.models import UpgradeRecord
    from libs.tenant_utils import apply_tenant_filter
    user=_make_user(); p='VR02_TEST'
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
        ok = f'{p}_已删' not in titles
        _record('R02_export_filters_is_deleted', ok,
            '软删除记录被排除' if ok else '软删除记录仍包含在导出中')
    finally: _clean_all(p)

# R03: statistics 过滤了 is_deleted
def verify_r03():
    from apps.upgrade.models import UpgradeRecord
    from apps.upgrade.services.statistics_service import StatisticsService
    user=_make_user(); p='VR03_TEST'
    _clean_all(p)
    for i in range(2):
        UpgradeRecord.objects.create(
            tenant_id=getattr(user,'tenant_id','admin'), title=f'{p}_{i}',
            system='VR03_SYS', upgrade_type='常规', upgrade_time=timezone.now(),
            status='处理中', owner='测试', created_by=user)
    UpgradeRecord.objects.create(
        tenant_id=getattr(user,'tenant_id','admin'), title=f'{p}_del',
        system='VR03_SYS', upgrade_type='常规', upgrade_time=timezone.now(),
        status='处理中', owner='测试', created_by=user,
        is_deleted=True, deleted_at=timezone.now())
    try:
        stats=StatisticsService.get_statistics(user, filters={'system':'VR03_SYS'})
        total=stats['total_count']
        _record('R03_stats_filters_is_deleted', total==2,
            f'total={total}（期望2，正确排除软删除）' if total==2 else f'total={total}（仍包含软删除）')
    finally: _clean_all(p)

# R04: status_log.add_log 拒绝软删除记录
def verify_r04():
    from apps.upgrade.models import UpgradeRecord
    from apps.upgrade.services.status_log_service import StatusLogService
    user=_make_user()
    r=UpgradeRecord.objects.create(
        tenant_id=getattr(user,'tenant_id','admin'), title='VR04_TEST',
        system='测试', upgrade_type='常规', upgrade_time=timezone.now(),
        status='处理中', owner='测试', created_by=user)
    log_id=None
    try:
        r.is_deleted=True; r.deleted_at=timezone.now(); r.save(update_fields=['is_deleted','deleted_at'])
        log,err=StatusLogService.add_log(upgrade_id=r.id, user=user, action='pause', remark='VR04')
        if log: log_id=log.id
        _record('R04_status_log_rejects_deleted', log is None,
            f'正确拒绝了软删除记录（err={err}）' if log is None else '仍可对软删除记录添加日志')
    finally:
        from apps.upgrade.models_status_log import UpgradeStatusLog
        if log_id: _cleanup(UpgradeStatusLog, pk=log_id)
        _cleanup(UpgradeRecord, pk=r.id)

# R05: apply_to_record replace 使用软删除
def verify_r05():
    from apps.upgrade.models import UpgradeRecord, UpgradeRecordStep
    from apps.upgrade.models_template import UpgradeTemplate, UpgradePlanStep
    from apps.upgrade.services.plan_service import PlanService
    user=_make_user(); p='VR05_TEST'
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
                description='', sequence=i+1, is_required=True, status='pending')
        PlanService.apply_to_record(plan_id=t.id, upgrade_id=r.id, user=user, replace=True)
        # 旧步骤应该被软删除（is_deleted=True），而不是物理删除
        all_steps = UpgradeRecordStep.objects.all_with_deleted().filter(upgrade_id=r.id)
        old_steps = all_steps.filter(title__startswith='旧步骤')
        soft_deleted_old = old_steps.filter(is_deleted=True).count()
        # 检查步骤仍然存在（物理记录保留）
        still_exists = old_steps.count()
        ok = still_exists == 3 and soft_deleted_old == 3
        _record('R05_replace_uses_soft_delete', ok,
            f'旧步骤保留{still_exists}条(期望3)，其中软删除{soft_deleted_old}条' if ok
            else f'旧步骤残留{still_exists}条，软删除{soft_deleted_old}条')
    finally: _clean_all(p)

# R06: apply_to_record append start_seq 正确
def verify_r06():
    from apps.upgrade.models import UpgradeRecord, UpgradeRecordStep
    from apps.upgrade.models_template import UpgradeTemplate, UpgradePlanStep
    from apps.upgrade.services.plan_service import PlanService
    user=_make_user(); p='VR06_TEST'
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
        # 3 活跃 + 2 软删除
        for i in range(5):
            UpgradeRecordStep.objects.create(
                tenant_id=getattr(user,'tenant_id','admin'), upgrade_id=r.id,
                checklist_id=0, phase='旧阶段', title=f'旧步骤{i+1}',
                description='', sequence=i+1, is_required=True, status='pending',
                is_deleted=(i>=3))
        PlanService.apply_to_record(plan_id=t.id, upgrade_id=r.id, user=user, replace=False)
        new_step = UpgradeRecordStep.objects.filter(upgrade_id=r.id, title='新追加步骤').first()
        if new_step:
            seq = new_step.sequence
            # 活跃步骤 3 条，正确 start_seq 应为 4
            ok = seq == 4
            _record('R06_append_seq_correct', ok,
                f'新步骤 seq={seq}（正确为4）' if ok else f'新步骤 seq={seq}（期望4）')
        else:
            _record('R06_append_seq_correct', False, '新步骤未创建')
    finally: _clean_all(p)

# R07: 日期范围通过 _apply_filters 正确过滤
def verify_r07():
    from apps.upgrade.models import UpgradeRecord
    from apps.upgrade.services.record_service import RecordService
    from libs.tenant_utils import apply_tenant_filter
    user=_make_user(); p='VR07_TEST'
    _clean_all(p)
    UpgradeRecord.objects.create(
        tenant_id=getattr(user,'tenant_id','admin'), title=f'{p}_中午',
        system='测试', upgrade_type='常规',
        upgrade_time=datetime(2026,8,1,12,0,0),
        status='处理中', owner='测试', created_by=user)
    try:
        qs = apply_tenant_filter(UpgradeRecord.objects.all(), user)
        # 通过 _apply_filters 过滤（修复后的路径）
        qs_filtered = RecordService._apply_filters(qs, {
            'start_date': '2026-08-01',
            'end_date': '2026-08-01',
        })
        count = qs_filtered.count()
        # 正确行为：单日范围应匹配到当天所有时间的记录
        ok = count == 1
        _record('R07_date_range_correct', ok,
            f'_apply_filters 单日范围 count={count}（期望1，正确匹配全天）' if ok
            else f'_apply_filters 单日范围 count={count}（期望1，仍有边界问题）')
    finally: _clean_all(p)

# R08: StatusLogService 调用在 atomic 块内
def verify_r08():
    from apps.upgrade.services.step_service import RecordStepService
    source = inspect.getsource(RecordStepService.batch_update_status)
    lines = source.split('\n')
    atomic_indent = None
    status_log_outside = []
    check_record_outside = []
    for line in lines:
        stripped = line.lstrip()
        if 'with transaction.atomic()' in stripped:
            atomic_indent = len(line) - len(line.lstrip())
        elif atomic_indent is not None:
            ci = len(line) - len(line.lstrip())
            if 'StatusLogService.' in stripped and ci <= atomic_indent:
                status_log_outside.append(stripped)
            if '_check_and_update_record_status' in stripped and ci <= atomic_indent:
                check_record_outside.append(stripped)
    # 修复标准：StatusLogService 在 atomic 内，_check_and_update_record_status 在 atomic 外（仅成功后执行）
    ok = len(status_log_outside) == 0
    _record('R08_status_log_in_atomic', ok,
        f'StatusLogService 调用全在 atomic 内' if ok
        else f'{len(status_log_outside)}处 StatusLogService 在 atomic 外: {status_log_outside[:2]}')

# R09: batch_update_status 不更新软删除步骤
def verify_r09():
    from apps.upgrade.models import UpgradeRecord, UpgradeRecordStep
    from apps.upgrade.services.step_service import RecordStepService
    user=_make_user(); p='VR09_TEST'
    _clean_all(p)
    r=UpgradeRecord.objects.create(
        tenant_id=getattr(user,'tenant_id','admin'), title=f'{p}_记录',
        system='测试', upgrade_type='常规', upgrade_time=timezone.now(),
        status='处理中', owner='测试', created_by=user)
    s1=UpgradeRecordStep.objects.create(
        tenant_id=getattr(user,'tenant_id','admin'), upgrade_id=r.id, checklist_id=0,
        phase='阶段A', title='活跃', description='', sequence=1, is_required=True, status='pending')
    s2=UpgradeRecordStep.objects.create(
        tenant_id=getattr(user,'tenant_id','admin'), upgrade_id=r.id, checklist_id=0,
        phase='阶段A', title='已删除', description='', sequence=2, is_required=True, status='pending',
        is_deleted=True, deleted_at=timezone.now())
    try:
        RecordStepService.batch_update_status(
            upgrade_id=r.id,
            steps_data=[
                {'step_id': s1.id, 'action': 'complete', 'remark': ''},
                {'step_id': s2.id, 'action': 'complete', 'remark': ''},
            ],
            user=user)
        s2_raw = UpgradeRecordStep.objects.all_with_deleted().get(pk=s2.id)
        ok = s2_raw.status == 'pending'  # 软删除步骤未被更新
        _record('R09_batch_update_skips_deleted', ok,
            f'软删除步骤 status={s2_raw.status}（正确保持 pending）' if ok
            else f'软删除步骤 status={s2_raw.status}（被错误更新）')
    finally: _clean_all(p)

# R10a-d: save() 使用了 update_fields
def verify_r10():
    from apps.upgrade.services.record_service import RecordService
    from apps.upgrade.services.step_service import RecordStepService
    from apps.upgrade.services.plan_service import PlanService
    checks = [
        ('R10a', RecordService.update_record),
        ('R10b', RecordService.delete_record),
        ('R10c', RecordStepService.delete_step),
        ('R10d', PlanService.update_plan),
    ]
    for name, method in checks:
        try:
            src = inspect.getsource(method)
            saves = re.findall(r'\.save\(([^)]*)\)', src)
            all_have = all('update_fields' in s for s in saves) if saves else True
            _record(f'{name}_save_has_update_fields', all_have,
                f'{len(saves)}处save均有update_fields' if all_have
                else f'{sum(1 for s in saves if "update_fields" not in s)}处save无update_fields')
        except Exception as e:
            _record(f'{name}_save_has_update_fields', False, f'检查失败: {e}')

# R11: _apply_filters 不使用 icontains
def verify_r11():
    from apps.upgrade.services.record_service import RecordService
    src = inspect.getsource(RecordService._apply_filters)
    no_system_icontains = 'system__icontains' not in src
    no_owner_icontains = 'owner__icontains' not in src
    _record('R11a_no_system_icontains', no_system_icontains,
        'system 不再使用 icontains' if no_system_icontains else 'system 仍使用 icontains')
    _record('R11b_no_owner_icontains', no_owner_icontains,
        'owner 不再使用 icontains' if no_owner_icontains else 'owner 仍使用 icontains')

# R12: 不再传 created_at=now_str
def verify_r12():
    from apps.upgrade.services.record_service import RecordService
    from apps.upgrade.services.step_service import RecordStepService
    src1 = inspect.getsource(RecordService.create_record)
    ok1 = 'created_at=now_str' not in src1
    _record('R12a_no_created_at_str', ok1,
        'create_record 不再传 created_at' if ok1 else '仍传 created_at')
    try:
        src2 = inspect.getsource(RecordStepService.add_manual_step)
        ok2 = 'created_at=now_str' not in src2
        _record('R12b_no_created_at_str', ok2,
            'add_manual_step 不再传 created_at' if ok2 else '仍传 created_at')
    except:
        _record('R12b_no_created_at_str', False, '方法不存在')

# R13: check_phase_completion 排除软删除步骤（行为测试）
def verify_r13():
    from apps.upgrade.models import UpgradeRecord, UpgradeRecordStep
    from apps.upgrade.models_status_log import UpgradeStatusLog
    from apps.upgrade.services.status_log_service import StatusLogService
    user=_make_user(); p='VR13_TEST'
    _clean_all(p)
    r=UpgradeRecord.objects.create(
        tenant_id=getattr(user,'tenant_id','admin'), title=f'{p}_记录',
        system='测试', upgrade_type='常规', upgrade_time=timezone.now(),
        status='处理中', owner='测试', created_by=user)
    # 2 活跃步骤 + 1 软删除步骤（都是 pending）
    for i in range(3):
        UpgradeRecordStep.objects.create(
            tenant_id=getattr(user,'tenant_id','admin'), upgrade_id=r.id,
            checklist_id=0, phase='阶段A', title=f'步骤{i+1}',
            description='', sequence=i+1, is_required=True, status='pending',
            is_deleted=(i==2))
    try:
        # 将 2 个活跃步骤标记为完成
        for i in range(2):
            s = UpgradeRecordStep.objects.get(upgrade_id=r.id, title=f'步骤{i+1}')
            s.mark_completed(user, '')
        # 调用 check_phase_completion（返回 None 或 log 对象，不返回元组）
        StatusLogService.check_phase_completion(r.id, user, '阶段A')
        # 检查是否创建了 phase_done 日志
        from apps.upgrade.models_status_log import UpgradeStatusLog
        log = UpgradeStatusLog.objects.filter(
            upgrade_id=r.id, action='phase_done', phase='阶段A'
        ).first()
        # 正确行为：阶段应标记为完成（因为只有 2 个活跃步骤，都已完成）
        # 软删除步骤不应参与判断
        ok = log is not None
        _record('R13_check_phase_excludes_deleted', ok,
            f'阶段完成判断正确排除软删除步骤（log_id={log.id if log else None}）' if ok
            else '阶段完成判断未排除软删除步骤（未创建 phase_done 日志）')
    finally: _clean_all(p)

# R14: apply_to_record 拒绝软删除记录
def verify_r14():
    from apps.upgrade.models import UpgradeRecord
    from apps.upgrade.models_template import UpgradeTemplate, UpgradePlanStep
    from apps.upgrade.services.plan_service import PlanService
    user=_make_user(); p='VR14_TEST'
    _clean_all(p)
    r=UpgradeRecord.objects.create(
        tenant_id=getattr(user,'tenant_id','admin'), title=f'{p}_记录',
        system='测试', upgrade_type='常规', upgrade_time=timezone.now(),
        status='处理中', owner='测试', created_by=user,
        is_deleted=True, deleted_at=timezone.now())
    t=UpgradeTemplate.objects.create(
        tenant_id=getattr(user,'tenant_id','admin'), name=f'{p}_模板',
        system='测试', upgrade_type='常规', created_by=user)
    UpgradePlanStep.objects.create(
        tenant_id=getattr(user,'tenant_id','admin'), template_id=t.id,
        phase='阶段', title='步骤', description='', sequence=1, is_required=True)
    try:
        msg, err = PlanService.apply_to_record(plan_id=t.id, upgrade_id=r.id, user=user, replace=True)
        # 正确行为：应拒绝（返回错误消息）
        ok = err is not None
        _record('R14_apply_rejects_deleted', ok,
            f'正确拒绝了软删除记录（err={err}）' if ok else '仍可对软删除记录应用方案')
    finally: _clean_all(p)


# ====== 主函数 ======
def main():
    print('='*70)
    print('  Upgrade 模块修复验证测试')
    print('  验证 19 项风险点的修复是否生效')
    print('='*70)
    tests = [
        ('R01 upload._get_record 过滤 is_deleted (P0)', verify_r01),
        ('R02 exporters 过滤 is_deleted (P0)', verify_r02),
        ('R03 statistics 过滤 is_deleted (P0)', verify_r03),
        ('R04 status_log.add_log 拒绝软删除 (P0)', verify_r04),
        ('R05 apply_to_record replace 软删除 (P1)', verify_r05),
        ('R06 apply_to_record append seq 正确 (P1)', verify_r06),
        ('R07 日期范围 _apply_filters 正确 (P1)', verify_r07),
        ('R08 StatusLogService 在 atomic 内 (P1)', verify_r08),
        ('R09 batch_update 跳过软删除步骤 (P2)', verify_r09),
        ('R10 save() 有 update_fields (P1)', verify_r10),
        ('R11 不使用 icontains (P2)', verify_r11),
        ('R12 不传 created_at=now_str (P2)', verify_r12),
        ('R13 check_phase 排除软删除步骤 (P1)', verify_r13),
        ('R14 apply_to_record 拒绝软删除记录 (P1)', verify_r14),
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
    fixed = sum(1 for r in _results if r['passed'])
    broken = sum(1 for r in _results if not r['passed'])
    print(f'  总计: {total} 项 | 已修复: {fixed} | 未修复: {broken}')
    print('='*70)
    for r in _results:
        symbol = '✓' if r['passed'] else '✗'
        print(f'  {symbol} {r["name"]}: {r["detail"]}')
    print('='*70)
    return _results

if __name__ == '__main__':
    main()
