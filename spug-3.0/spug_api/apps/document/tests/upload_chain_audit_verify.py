#!/usr/bin/env python3
"""上传链路审计风险点验证脚本
验证上传链路代码中的潜在风险点是否真实存在。

运行方式：
  python spug_api/apps/document/tests/upload_chain_audit_verify.py
"""
import re
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent  # spug_api/apps/document/tests
API = BASE.parent  # spug_api/apps/document
PROJECT_ROOT = API.parent.parent.parent  # spug-3.0
WEB = PROJECT_ROOT / 'spug_web' / 'src' / 'pages' / 'document' / 'stores'

def rf(p):
    with open(p, encoding='utf-8') as f:
        return f.read()

results = []

def check(rid, sev, title, verdict, evidence):
    results.append((rid, sev, title, verdict, evidence))


# ============================================================
# P0-1: ALLOWED_STATUS_TRANSITIONS 缺失 UPLOADING→COMPLETED
# ============================================================
def v_p0_uploading_completed():
    consts = rf(API / 'constants.py')
    m = re.search(r'TransferStatus\.UPLOADING\s*:\s*\[([^\]]*)\]', consts)
    if not m:
        check("P0-1", "P0", "ALLOWED_STATUS_TRANSITIONS 缺失 UPLOADING→COMPLETED",
              "NOT_FIXED", ["未找到 UPLOADING 转换规则"])
        return

    allowed = m.group(1)
    has_completed = 'COMPLETED' in allowed

    status_py = rf(API / 'views' / 'transfer' / 'status.py')
    uses_validation = 'is_valid_status_transition' in status_py and 'TransferCompleteView' in status_py
    fe_file_upload = rf(WEB / 'upload' / 'core' / 'fileUpload.js')
    calls_complete = 'completeTransfer' in fe_file_upload
    has_ensure_call = 'ensureTransferUploading' in fe_file_upload
    silent_swallow = 'console.warn' in fe_file_upload and 'completeTransfer' in fe_file_upload

    ev = [
        f"UPLOADING 允许转换列表: [{allowed.strip()}]",
        f"包含 COMPLETED: {has_completed}",
        f"TransferCompleteView 使用 is_valid_status_transition: {uses_validation}",
        f"前端 fileUpload.js 调用 completeTransfer: {calls_complete}",
        f"前端调用 ensureTransferUploading: {has_ensure_call}",
        f"前端静默吞错误: {silent_swallow}",
    ]

    if uses_validation and calls_complete and not has_completed:
        check("P0-1", "P0", "ALLOWED_STATUS_TRANSITIONS 缺失 UPLOADING→COMPLETED",
              "RISK_CONFIRMED", ev)
    elif has_completed:
        check("P0-1", "P0", "ALLOWED_STATUS_TRANSITIONS 缺失 UPLOADING→COMPLETED",
              "FIXED", ev + ["UPLOADING→COMPLETED 已存在"])
    else:
        check("P0-1", "P0", "ALLOWED_STATUS_TRANSITIONS 缺失 UPLOADING→COMPLETED",
              "NOT_RISK", ev + ["但前端/后端流程不触发此路径"])


# ============================================================
# P0-1b: DirectMergeView COMPLETED 分支缺少文件记录验证
# ============================================================
def v_p0_direct_merge_completed():
    """
    验证 DirectMergeView 中 COMPLETED 分支是否检查文件记录真实存在。

    2026-08-05 发现：DirectMergeView 返回 {'status': 'completed'} 时，
    未验证文件记录在数据库中是否存在，导致状态 COMPLETED 但文件未创建。
    """
    dm = rf(API / 'views' / 'upload' / 'direct_merge.py')

    # 查找 COMPLETED 分支
    completed_check = re.search(
        r"if transfer\.status == TransferStatus\.COMPLETED\.value:",
        dm
    )

    # 检查是否有文件记录验证
    has_file_record_check = 'FileModel.objects.filter' in dm and 'file_record_exists' in dm

    # 检查是否有重置逻辑
    has_reset_logic = 'transfer.status = TransferStatus.UPLOADING.value' in dm

    ev = [
        f"COMPLETED 分支存在: {completed_check is not None}",
        f"有文件记录验证: {has_file_record_check}",
        f"有状态重置逻辑: {has_reset_logic}",
    ]

    if has_file_record_check and has_reset_logic:
        check("P0-1b", "P0", "DirectMergeView COMPLETED 分支缺少文件记录验证",
              "FIXED", ev + ["已添加文件记录验证和状态重置逻辑"])
    elif has_file_record_check:
        check("P0-1b", "P0", "DirectMergeView COMPLETED 分支缺少文件记录验证",
              "PARTIALLY_FIXED", ev + ["有文件记录验证但无状态重置逻辑"])
    else:
        check("P0-1b", "P0", "DirectMergeView COMPLETED 分支缺少文件记录验证",
              "RISK_CONFIRMED", ev + ["未修复：COMPLETED 分支直接返回成功，不验证文件记录"])


# ============================================================
# P0-1c: merge.py _build_result_from_transfer 缺少文件记录验证
# ============================================================
def v_p0_merge_build_result():
    mp = rf(API / 'views' / 'upload' / 'merge.py')

    # 检查 _build_result_from_transfer 函数是否有文件记录验证
    has_file_check = 'file_exists' in mp and 'get_file_model' in mp

    ev = [
        f"有文件记录验证: {has_file_check}",
    ]

    if has_file_check:
        check("P0-1c", "P0", "merge.py _build_result_from_transfer 缺少文件记录验证",
              "FIXED", ev + ["已添加文件记录验证"])
    else:
        check("P0-1c", "P0", "merge.py _build_result_from_transfer 缺少文件记录验证",
              "RISK_CONFIRMED", ev + ["未修复"])


# ============================================================
# P1-1: 分片完整性检查逻辑重复（direct_merge.py vs merge.py）
# ============================================================
def v_p1_duplicate_chunk_check():
    dm = rf(API / 'views' / 'upload' / 'direct_merge.py')
    mp = rf(API / 'views' / 'upload' / 'merge.py')

    dm_m = re.search(r'for i in range\(total_chunks\):\s*\n\s+chunk_path\s*=\s*os\.path\.join\(chunk_dir,\s*[\'"]\{\}\.part[\'"]\)',
                     dm, re.DOTALL)
    mp_m = re.search(r'for i in range\(total_chunks\):\s*\n\s+chunk_path\s*=\s*os\.path\.join\(chunk_dir,\s*[\'"]\{\}\.part[\'"]\)',
                     mp, re.DOTALL)
    dm_has_ref = bool(re.search(r'check_all_chunks_present|validate_chunk_directory', dm))
    mp_has_ref = bool(re.search(r'check_all_chunks_present|validate_chunk_directory', mp))

    ev = [
        f"direct_merge.py 有遍历分片逻辑: {dm_m is not None}",
        f"merge.py 有遍历分片逻辑: {mp_m is not None}",
        f"direct_merge.py 引用公共函数: {dm_has_ref}",
        f"merge.py 引用公共函数: {mp_has_ref}",
    ]

    if dm_m and mp_m and not dm_has_ref and not mp_has_ref:
        check("P1-1", "P1", "分片完整性检查逻辑重复", "RISK_CONFIRMED", ev)
    elif dm_m and mp_m:
        check("P1-1", "P1", "分片完整性检查逻辑重复", "FIXED", ev + ["已提取公共函数"])
    else:
        check("P1-1", "P1", "分片完整性检查逻辑重复", "NOT_RISK", ev)


# ============================================================
# P2-1: error_code_mapper 关键词模糊匹配可能误判
# ============================================================
def v_p2_error_code_mapper():
    ecm = rf(API / 'views' / 'upload' / 'error_code_mapper.py')

    keyword_matches = re.findall(r"['\"]([^'\"]+?)['\"].*?\b(in|contains)\b.*?\b(message|error|msg)\b", ecm)
    dict_matches = re.findall(r"['\"]([^'\"]+?)['\"]\s*:\s*['\"][^'\"]*['\"]", ecm)
    has_exact_first = bool(re.search(r'exact|code.*==|error_code.*==|STATUS_CODE|CODE_MAP', ecm))
    has_merge_kw = bool(re.search(r"['\"]合并['\"]", ecm))

    normal_status_words = ['合并中', '上传中', '计算中', '等待中', '暂停中', '完成']
    false_positive_risks = []
    for word in normal_status_words:
        for kw_match in keyword_matches:
            if kw_match[0] in word:
                false_positive_risks.append(f"'{kw_match[0]}' 可能匹配 '{word}'")

    ev = [
        f"关键词匹配规则数: {len(keyword_matches)}",
        f"字典映射规则数: {len(dict_matches)}",
        f"有精确匹配优先: {has_exact_first}",
        f"包含'合并'关键词: {has_merge_kw}",
        f"误判风险数: {len(false_positive_risks)}",
    ]
    for risk in false_positive_risks[:5]:
        ev.append(f"  - {risk}")

    if false_positive_risks:
        check("P2-1", "P2", "error_code_mapper 关键词模糊匹配可能误判", "RISK_CONFIRMED", ev)
    else:
        check("P2-1", "P2", "error_code_mapper 关键词模糊匹配可能误判", "NOT_RISK", ev + ["未发现明显的误判风险"])


# ============================================================
# 主函数
# ============================================================
def main():
    v_p0_uploading_completed()
    v_p0_direct_merge_completed()
    v_p0_merge_build_result()
    v_p1_duplicate_chunk_check()
    v_p2_error_code_mapper()

    print("=" * 80)
    print("上传链路审计风险点验证报告（后端）")
    print("=" * 80)
    confirmed = fixed = not_risk = partially = 0
    for rid, sev, title, verdict, ev in results:
        print(f"\n[{rid}] [{sev}] {title}")
        print(f"  结论: {verdict}")
        for e in ev:
            print(f"  - {e}")
        if verdict == "RISK_CONFIRMED":
            confirmed += 1
        elif verdict == "FIXED":
            fixed += 1
        elif verdict == "PARTIALLY_FIXED":
            partially += 1
        else:
            not_risk += 1

    print("\n" + "=" * 80)
    print(f"汇总: RISK_CONFIRMED={confirmed}  FIXED={fixed}  PARTIALLY_FIXED={partially}  NOT_RISK={not_risk}  总计={len(results)}")
    print("=" * 80)


if __name__ == '__main__':
    main()