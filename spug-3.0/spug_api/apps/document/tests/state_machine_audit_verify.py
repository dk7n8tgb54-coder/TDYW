#!/usr/bin/env python3
"""状态机全链路审计风险点修复验证脚本
验证 9 个风险点是否已修复

运行方式（Windows 本地直接运行）：
  python spug_api/apps/document/tests/state_machine_audit_verify.py
"""
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent
WEB = BASE.parent.parent.parent.parent / 'spug_web' / 'src' / 'pages' / 'document' / 'stores'
API = BASE.parent  # .../apps/document

def rf(p):
    with open(p, encoding='utf-8') as f: return f.read()

results = []

def check(rid, sev, title, verdict, evidence):
    results.append((rid, sev, title, verdict, evidence))


# ── P0-1: cancelled 非可靠终态 ──
def v_p0_cancelled():
    usm = rf(WEB/'upload'/'core'/'UploadStateMachine.js')
    cancel_py = rf(API/'views'/'transfer'/'cancel.py')
    merge_py = rf(API/'tasks'/'merge.py')

    fe_allows = False
    merging_start = usm.find('merging:')
    if merging_start >= 0:
        window = usm[merging_start:merging_start+400]
        fe_allows = bool(re.search(r"CANCEL.*?target:\s*['\"]cancelled['\"]", window, re.DOTALL))
    has_revoke = bool(re.search(r'revoke|terminate_task|abort_task', cancel_py, re.I))
    has_guard = bool(re.search(r"CANCELED.*?return\s+False|old_status.*?CANCELED", merge_py, re.DOTALL))
    ev = [
        f"前端 merging->cancelled: {fe_allows}",
        f"cancel.py revoke Celery: {has_revoke}",
        f"merge.py CANCELED守卫: {has_guard}",
    ]
    # 修复条件: cancel.py 有 revoke + merge.py 有守卫
    fixed = has_revoke and has_guard
    v = "FIXED" if fixed else ("PARTIAL" if has_guard else "NOT_FIXED")
    ev.append("修复状态: " + ("cancel已revoke+worker有守卫" if fixed else ("仅worker有守卫(未revoke)" if has_guard else "未修复")))
    check("P0-1","P0","cancelled不是可靠终态",v,ev)


# ── P0-2: 批量取消排除 merging ──
def v_p0_batch():
    smm = rf(WEB/'upload'/'core'/'StateMachineManager.js')
    m = re.search(r"NON_CANCELLABLE_STATES\s*=\s*\[([^\]]*)\]", smm)
    excludes = m and 'merging' in m.group(1)
    ev = [f"批量取消NON_CANCELLABLE_STATES含merging: {excludes}",
          f"实际值: {m.group(1).strip() if m else '未找到'}"]
    # 修复条件: merging 不在排除列表中
    v = "FIXED" if not excludes else "NOT_FIXED"
    check("P0-2","P0","批量取消排除merging不一致",v,ev)


# ── P1-1: RETRY_MERGE 链路不可用 ──
def v_p1_retry():
    ioc = rf(WEB/'upload'/'core'/'controls'/'ItemOperationController.js')
    chunk = rf(WEB/'upload'/'core'/'chunkUpload.js')

    saves_task = bool(re.search(r"item\.taskId\s*=", ioc))
    saves_celery = bool(re.search(r"item\.celeryTaskId\s*=", ioc))
    sig = re.search(r"async\s+pollMergeStatus\s*\(([^)]*)\)", chunk)
    sig_str = sig.group(1) if sig else ''
    # 找 RETRY_MERGE 附近的 pollMergeStatus 调用
    retry_section = ioc[ioc.find('retryMerge'):] if 'retryMerge' in ioc else ioc
    call = re.search(r"pollMergeStatus\s*\(([^)]*)\)", retry_section)
    call_arg = call.group(1).strip() if call else ''
    arg_mismatch = call_arg == 'item'
    # 检查是否传了4个参数
    has_4_args = call_arg.count(',') >= 3 if call_arg else False

    ev = [
        f"保存item.taskId: {saves_task}",
        f"保存item.celeryTaskId: {saves_celery}",
        f"pollMergeStatus调用参数: ({call_arg})",
        f"参数不匹配(传item): {arg_mismatch}",
        f"传4个参数: {has_4_args}",
    ]
    issues = sum([saves_task, arg_mismatch, not has_4_args])
    v = "FIXED" if issues == 0 else ("PARTIAL" if issues == 1 else "NOT_FIXED")
    ev.append(f"剩余问题数: {issues}")
    check("P1-1","P1","RETRY_MERGE链路不可用",v,ev)


# ── P1-2: 状态同步失败被永久去重 ──
def v_p1_sync():
    sync = rf(WEB/'upload'/'core'/'sync'/'StatusSynchronizer.js')
    # 找实际的 this.markSynced( 调用（非注释）
    mp = sync.find('this.markSynced(')
    up = sync.find('updateTransferStatus')
    before = mp >= 0 and up >= 0 and mp < up
    after = mp >= 0 and up >= 0 and mp > up
    ev = [f"this.markSynced(位置: {mp}", f"updateTransferStatus位置: {up}",
          f"markSynced在请求前(旧): {before}",
          f"markSynced在请求后(新): {after}"]
    v = "FIXED" if after else "NOT_FIXED"
    check("P1-2","P1","状态同步失败被永久去重",v,ev)


# ── P1-3: ERROR事件丢失错误信息 ──
def v_p1_error_info():
    usm = rf(WEB/'upload'/'core'/'UploadStateMachine.js')
    m = re.search(r"onErrorEntry\s*\(([^)]*)\)\s*\{(.*?)\n\s*\}", usm, re.DOTALL)
    if not m:
        check("P1-3","P1","ERROR事件丢失错误信息","NOT_FIXED",["未找到onErrorEntry"]); return
    params = m.group(1)
    body = m.group(2)
    has_payload = 'payload' in params
    has_err = bool(re.search(r"payload\.error|payload\?\.error", body))
    has_code = bool(re.search(r"errorCode|payload\.code|payload\?\.code", body))
    ev = [f"onErrorEntry接受payload参数: {has_payload}",
          f"写入payload.error: {has_err}",
          f"写入errorCode: {has_code}"]
    v = "FIXED" if has_err or has_code else "NOT_FIXED"
    check("P1-3","P1","ERROR事件丢失错误信息",v,ev)


# ── P1-4: hook异常产生双状态 ──
def v_p1_hook():
    usm = rf(WEB/'upload'/'core'/'UploadStateMachine.js')
    # 用窗口法: 找 catch (error) 后搜索 currentState = 'error'
    catch_pos = usm.find('catch (error)')
    if catch_pos < 0:
        check("P1-4","P1","hook异常双状态","NOT_FIXED",["未找到catch"]); return
    window = usm[catch_pos:catch_pos+500]
    restores = bool(re.search(r"this\.currentState\s*=\s*['\"]error['\"]", window))
    ev = [f"catch位置: {catch_pos}", f"catch恢复currentState='error': {restores}",
          f"窗口内容(前200字符): {window[:200]}"]
    v = "FIXED" if restores else "NOT_FIXED"
    check("P1-4","P1","hook异常产生双状态",v,ev)


# ── P1-5: error同时是终态和可恢复态 ──
def v_p1_error_dual():
    consts = rf(WEB/'upload'/'core'/'upload-core-constants.js')
    sch = rf(WEB/'upload'/'core'/'lifecycle'/'StateChangeHandler.js')
    fm = re.search(r"FINAL_STATES\s*=\s*\[([^\]]*)\]", consts)
    err_final = fm and ("'error'" in fm.group(1) or '"error"' in fm.group(1))
    # 检查 error 状态是否有单独 processPending 调用
    has_error_process = bool(re.search(r"toState\s*===\s*['\"]error['\"].*?processPending", sch, re.DOTALL))
    ev = [f"error在FINAL_STATES: {err_final}",
          f"FINAL_STATES实际值: {fm.group(1).strip() if fm else '未找到'}",
          f"error状态有processPending: {has_error_process}"]
    # 修复条件: error 不在 FINAL_STATES + 有 processPending
    v = "FIXED" if not err_final and has_error_process else "NOT_FIXED"
    check("P1-5","P1","error同时是终态和可恢复态",v,ev)


# ── P2-1: paused->error前后端冲突 ──
def v_p2_paused():
    consts = rf(API/'constants.py')
    bm = re.search(r"PAUSED\s*:\s*\[([^\]]*)\]", consts)
    be = bm and 'FAILED' in bm.group(1)
    ev = [f"后端PAUSED->FAILED允许: {be}",
          f"PAUSED转换列表: {bm.group(0) if bm else '未找到'}"]
    v = "FIXED" if be else "NOT_FIXED"
    check("P2-1","P2","paused->error前后端矩阵冲突",v,ev)


# ── P2-2: 32MB临界值不一致 ──
def v_p2_32mb():
    ul = rf(WEB/'upload'/'core'/'lifecycle'/'UploadLifecycle.js')
    # 检查 MD5 跳出条件: 修复后应使用 <=
    md5_lt = bool(re.search(r"fileSize\s*<\s*\S*MD5|fileSize\s*<\s*\d+\s*\*\s*1024", ul))
    md5_lte = bool(re.search(r"fileSize\s*<=\s*\S*MD5|fileSize\s*<=\s*\d+\s*\*\s*1024", ul))
    ev = [f"MD5跳过使用<(严格小于,旧): {md5_lt}",
          f"MD5跳过使用<=(小于等于,新): {md5_lte}"]
    # 修复条件: 使用 <= 而非 <
    v = "FIXED" if md5_lte and not md5_lt else "NOT_FIXED"
    check("P2-2","P2","32MB临界值规则不一致",v,ev)


# ── 主函数 ──
def main():
    v_p0_cancelled()
    v_p0_batch()
    v_p1_retry()
    v_p1_sync()
    v_p1_error_info()
    v_p1_hook()
    v_p1_error_dual()
    v_p2_paused()
    v_p2_32mb()

    print("=" * 80)
    print("状态机全链路审计风险点修复验证报告")
    print("=" * 80)
    fixed = partial = not_fixed = 0
    for rid, sev, title, verdict, ev in results:
        print(f"\n[{rid}] [{sev}] {title}")
        print(f"  结论: {verdict}")
        for e in ev:
            print(f"  - {e}")
        if verdict == "FIXED": fixed += 1
        elif verdict == "PARTIAL": partial += 1
        else: not_fixed += 1

    print("\n" + "=" * 80)
    print(f"汇总: FIXED={fixed}  PARTIAL={partial}  NOT_FIXED={not_fixed}  总计={len(results)}")
    print("=" * 80)

if __name__ == '__main__':
    main()
