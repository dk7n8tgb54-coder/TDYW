# -*- coding: utf-8 -*-
"""Celery 任务测试 - 阶段 5 补充

直接调用 task 函数（不通过 Celery worker），验证执行结果。
如实报告，不绕过 bug。
"""
import os
import sys
import json
import time
from datetime import date, timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django
django.setup()

from django.test.utils import setup_test_environment, teardown_test_environment
from django.test.runner import DiscoverRunner

runner = DiscoverRunner(verbosity=0)
setup_test_environment()
old_config = runner.setup_databases()

results = []

def log(name, passed, detail=''):
    status = 'PASS' if passed else 'FAIL'
    results.append((name, passed, detail))
    print(f'  [{status}] {name}: {detail}')

try:
    from django.core.cache import cache
    from apps.account.models import User, Role
    from apps.setting.utils import AppSetting

    cache.clear()
    AppSetting.set('bind_ip', False)
    AppSetting.get.cache_clear()

    today = date.today()
    supper = User.objects.create(
        username='supper', nickname='supper', password_hash='x',
        is_active=True, is_supper=True,
        access_token=('supper' * 10)[:32],
        token_expired=int(time.time()) + 3600,
        last_login='2026-01-01', last_ip='127.0.0.1', type='default',
        tenant_id='admin',
    )

    # ================================================================
    # 场景 1：执照到期扫描
    # ================================================================
    print('\n===== 场景 1：执照到期扫描 =====')
    try:
        from apps.radio_license.models import RadioLicense
        from apps.radio_license.tasks import scan_radio_license_expiration

        # 创建 3 张执照：normal / expiring / expired
        lic_normal = RadioLicense.objects.create(
            tenant_id='admin', station_name='正常执照', purpose='测试',
            valid_from=today - timedelta(days=365),
            valid_to=today + timedelta(days=365),
            responsible_user_id=supper.id, responsible_user_name='supper',
            status='normal', created_by=supper,
        )
        lic_expiring = RadioLicense.objects.create(
            tenant_id='admin', station_name='即将到期', purpose='测试',
            valid_from=today - timedelta(days=300),
            valid_to=today + timedelta(days=30),
            responsible_user_id=supper.id, responsible_user_name='supper',
            status='normal', created_by=supper,
        )
        lic_expired = RadioLicense.objects.create(
            tenant_id='admin', station_name='已过期', purpose='测试',
            valid_from=today - timedelta(days=400),
            valid_to=today - timedelta(days=10),
            responsible_user_id=supper.id, responsible_user_name='supper',
            status='normal', created_by=supper,
        )
        log('创建3张执照', RadioLicense.objects.count() == 3, f'count={RadioLicense.objects.count()}')

        # 调用 task（直接调用函数，不通过 Celery worker）
        result = scan_radio_license_expiration.apply()
        log('task执行无异常', result.failed() is False, str(result.result) if result.failed() else '成功')

        # 验证状态更新
        lic_normal.refresh_from_db()
        lic_expiring.refresh_from_db()
        lic_expired.refresh_from_db()

        log('正常执照status=normal', lic_normal.status == 'normal', f'status={lic_normal.status}')
        log('即将到期status=expiring', lic_expiring.status == 'expiring', f'status={lic_expiring.status}')
        log('已过期status=expired', lic_expired.status == 'expired', f'status={lic_expired.status}')

    except Exception as e:
        import traceback
        traceback.print_exc()
        log('执照到期扫描', False, f'异常: {e}')

    # ================================================================
    # 场景 2：批复到期扫描
    # ================================================================
    print('\n===== 场景 2：批复到期扫描 =====')
    try:
        from apps.radio_license.models import StationFrequencyApproval
        from apps.radio_license.tasks import scan_approval_expiration

        appr_normal = StationFrequencyApproval.objects.create(
            tenant_id='admin', name='正常批复', doc_no='AP-001',
            frequency_text='100MHz',
            valid_from=today - timedelta(days=365),
            valid_to=today + timedelta(days=365),
            responsible_user_id=supper.id, responsible_user_name='supper',
            status='normal', created_by=supper,
        )
        appr_expiring = StationFrequencyApproval.objects.create(
            tenant_id='admin', name='即将到期批复', doc_no='AP-002',
            frequency_text='200MHz',
            valid_from=today - timedelta(days=300),
            valid_to=today + timedelta(days=30),
            responsible_user_id=supper.id, responsible_user_name='supper',
            status='normal', created_by=supper,
        )
        appr_expired = StationFrequencyApproval.objects.create(
            tenant_id='admin', name='已过期批复', doc_no='AP-003',
            frequency_text='300MHz',
            valid_from=today - timedelta(days=400),
            valid_to=today - timedelta(days=10),
            responsible_user_id=supper.id, responsible_user_name='supper',
            status='normal', created_by=supper,
        )
        log('创建3条批复', StationFrequencyApproval.objects.count() == 3, '')

        result = scan_approval_expiration.apply()
        log('task执行无异常', result.failed() is False, str(result.result) if result.failed() else '成功')

        appr_normal.refresh_from_db()
        appr_expiring.refresh_from_db()
        appr_expired.refresh_from_db()

        log('正常批复status=normal', appr_normal.status == 'normal', f'status={appr_normal.status}')
        log('即将到期status=expiring', appr_expiring.status == 'expiring', f'status={appr_expiring.status}')
        log('已过期status=expired', appr_expired.status == 'expired', f'status={appr_expired.status}')

    except Exception as e:
        import traceback
        traceback.print_exc()
        log('批复到期扫描', False, f'异常: {e}')

    # ================================================================
    # 场景 3：合同到期扫描
    # ================================================================
    print('\n===== 场景 3：合同到期扫描 =====')
    try:
        from apps.contract_agreement.models import ContractAgreement
        from apps.contract_agreement.tasks import scan_contract_agreement_expiration

        # 合同用 valid_start_date / valid_end_date（DateField）
        contract_normal = ContractAgreement.objects.create(
            tenant_id='admin', contract_name='正常合同', contract_type='normal',
            valid_start_date=today - timedelta(days=365),
            valid_end_date=today + timedelta(days=365),
            signing_party='甲方', responsible_user_id=supper.id,
            responsible_user_name='supper', status='normal', created_by=supper,
        )
        contract_expiring = ContractAgreement.objects.create(
            tenant_id='admin', contract_name='即将到期合同', contract_type='normal',
            valid_start_date=today - timedelta(days=300),
            valid_end_date=today + timedelta(days=30),
            signing_party='甲方', responsible_user_id=supper.id,
            responsible_user_name='supper', status='normal', created_by=supper,
        )
        contract_expired = ContractAgreement.objects.create(
            tenant_id='admin', contract_name='已过期合同', contract_type='normal',
            valid_start_date=today - timedelta(days=400),
            valid_end_date=today - timedelta(days=10),
            signing_party='甲方', responsible_user_id=supper.id,
            responsible_user_name='supper', status='normal', created_by=supper,
        )
        log('创建3条合同', ContractAgreement.objects.count() == 3, '')

        result = scan_contract_agreement_expiration.apply()
        log('task执行无异常', result.failed() is False, str(result.result) if result.failed() else '成功')

        contract_normal.refresh_from_db()
        contract_expiring.refresh_from_db()
        contract_expired.refresh_from_db()

        log('正常合同status=normal', contract_normal.status == 'normal', f'status={contract_normal.status}')
        log('即将到期status=expiring', contract_expiring.status == 'expiring', f'status={contract_expiring.status}')
        log('已过期status=expired', contract_expired.status == 'expired', f'status={contract_expired.status}')

    except Exception as e:
        import traceback
        traceback.print_exc()
        log('合同到期扫描', False, f'异常: {e}')

    # ================================================================
    # 场景 4：文档清理（待清理文件重试删除）
    # ================================================================
    print('\n===== 场景 4：文档清理 =====')
    try:
        from apps.document.models import DocumentFilePrivate, DocumentFolderPrivate
        from apps.document.tasks.cleanup.pending_files import retry_clean_pending_files

        # 先创建文件夹（folder_id 是外键，不能用 0）
        folder = DocumentFolderPrivate.objects.create(
            tenant_id='admin', name='清理测试文件夹',
            created_by=supper,
        )
        # 创建一个待清理文件记录（is_pending_clean=True）
        # 文件路径不存在，safe_delete_document_file 应返回成功（文件不存在视为已删除）
        pending_file = DocumentFilePrivate.objects.create(
            tenant_id='admin', folder_id=folder.id, name='待清理测试文件.txt',
            file_path='/tmp/nonexistent_test_file.txt',
            file_size=100, file_type='txt',
            is_pending_clean=True, clean_retry_count=0,
            created_by=supper,
        )
        log('创建待清理文件记录', DocumentFilePrivate.objects.filter(is_pending_clean=True).count() == 1, '')

        # 直接调用函数（不用 .apply()）：
        # retry_clean_pending_files 声明了 bind=True 但函数没有 self 参数，
        # .apply() 会传 self 导致 TypeError。
        # 这是生产代码的 bug（bind=True + 无 self），Celery worker 调度时也会报错。
        # 先直接调用验证函数逻辑是否正确。
        result = retry_clean_pending_files()
        log('task函数逻辑执行无异常', result is not None, f'result={result}')

        # 验证记录被删除
        still_exists = DocumentFilePrivate.objects.filter(id=pending_file.id).exists()
        log('待清理文件已删除', not still_exists, f'still_exists={still_exists}')

        # 验证 bind=True + 无 self 参数的 bug
        # 这个 bug 会导致 Celery worker 调度时 TypeError
        import inspect
        sig = inspect.signature(retry_clean_pending_files)
        params = list(sig.parameters.keys())
        has_self = params[0] == 'self' if params else False
        log('bind=True需要self参数', has_self,
            f'bind=True但参数列表={params}（生产bug：Celery worker调度会TypeError）' if not has_self else '正确')

    except Exception as e:
        import traceback
        traceback.print_exc()
        log('文档清理', False, f'异常: {e}')

    # ================================================================
    # 汇总
    # ================================================================
    print('\n===== 汇总 =====')
    passed = sum(1 for _, p, _ in results if p)
    failed = sum(1 for _, p, _ in results if not p)
    total = len(results)
    print(f'  PASS: {passed}/{total}, FAIL: {failed}/{total}')

    if failed > 0:
        print('\n  失败项:')
        for name, p, detail in results:
            if not p:
                print(f'    X {name}: {detail}')
    else:
        print('\n  全部通过')

    sys.exit(1 if failed > 0 else 0)

except Exception as e:
    import traceback
    traceback.print_exc()
    sys.exit(2)
finally:
    runner.teardown_databases(old_config)
    teardown_test_environment()
