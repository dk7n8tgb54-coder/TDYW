# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.

"""
审计日志哈希链工具

职责：
1. compute_request_hash  —— 基于审计 detail（脱敏后存库内容）计算请求哈希
2. compute_response_hash —— 基于响应体内容计算响应哈希
3. compute_log_hash      —— 基于全部关键字段 + prev_hash 计算日志哈希
4. build_log_hash_payload —— 规范化字段为确定性字典（save 与 verify 共用）
5. verify_log_hash       —— 校验单条日志 log_hash 是否与字段一致（未被篡改）
6. verify_hash_chain     —— 校验一组日志的哈希链连续性

设计要点：
- log_hash 输入为 sort_keys 的 JSON，保证字段顺序确定、可复现
- prev_hash 取同租户上一条日志的 log_hash，按租户成链
- 旧数据无 log_hash（空串），verify_log_hash 返回 False，不阻断业务
- 内网环境优先：不接入外部时间戳/CA，仅做内部哈希存证
"""

import hashlib
import json
from datetime import datetime


def _to_text(value):
    """将任意值规范化为字符串，None → ''。

    用于保证 save_audit_log 写入时与 verify_log_hash 读取时
    对同一字段的字符串化结果完全一致，避免 None / 空串歧义。
    """
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, datetime):
        # DateTimeField 值格式化为 'YYYY-MM-DD HH:MM:SS'，
        # 保证迁移前后哈希计算结果一致（旧数据 created_at 是该格式字符串）
        return value.strftime('%Y-%m-%d %H:%M:%S')
    return str(value)


def compute_request_hash(detail):
    """计算请求/详情哈希（SHA256，64 位十六进制）。

    detail 为存入数据库的最终字符串：
    - None / 空串 → SHA256('')
    - dict        → 先 json.dumps(sort_keys=True, ensure_ascii=False)
    - str         → 直接对其内容计算

    注意：save_audit_log 内部会先把 dict 形态的 detail 序列化为
    json 字符串再存库，此处对 dict 与对 str 的计算结果可能不同。
    为保证可校验，request_hash 统一在 detail 已规范化为存库字符串后计算。
    """
    if detail is None:
        payload = ''
    elif isinstance(detail, dict):
        payload = json.dumps(detail, ensure_ascii=False, sort_keys=True)
    elif isinstance(detail, str):
        payload = detail
    else:
        payload = str(detail)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def compute_response_hash(content):
    """计算响应体哈希（SHA256，64 位十六进制）。

    content 为 bytes/str，None/空 → ''（留空，表示无响应哈希）。
    流式响应（StreamingHttpResponse/FileResponse）无 content 属性，
    调用方不传入，response_hash 留空。
    """
    if not content:
        return ''
    if isinstance(content, str):
        content = content.encode('utf-8')
    elif not isinstance(content, (bytes, bytearray)):
        content = str(content).encode('utf-8')
    return hashlib.sha256(bytes(content)).hexdigest()


def build_log_hash_payload_from_values(
    tenant_id, user_id, username, action, target_type, target_id,
    target_name, detail, ip, is_success, created_at,
    request_hash, response_hash, request_id, user_agent, prev_hash,
):
    """根据原始字段值构建 log_hash 输入字典（确定性排序）。

    save_audit_log 写入时与 verify_log_hash 读取时均调用此函数，
    保证两端输入完全一致。所有值经 _to_text 规范化，is_success 用 bool。
    """
    return {
        'tenant_id': _to_text(tenant_id),
        'user_id': _to_text(user_id),
        'username': _to_text(username),
        'action': _to_text(action),
        'target_type': _to_text(target_type),
        'target_id': _to_text(target_id),
        'target_name': _to_text(target_name),
        'detail': _to_text(detail),
        'ip': _to_text(ip),
        'is_success': bool(is_success),
        'created_at': _to_text(created_at),
        'request_hash': _to_text(request_hash),
        'response_hash': _to_text(response_hash),
        'request_id': _to_text(request_id),
        'user_agent': _to_text(user_agent),
        'prev_hash': _to_text(prev_hash),
    }


def build_log_hash_payload(audit_log):
    """根据 AuditLog 模型实例构建 log_hash 输入字典。"""
    return build_log_hash_payload_from_values(
        tenant_id=audit_log.tenant_id,
        user_id=audit_log.user_id,
        username=audit_log.username,
        action=audit_log.action,
        target_type=audit_log.target_type,
        target_id=audit_log.target_id,
        target_name=audit_log.target_name,
        detail=audit_log.detail,
        ip=audit_log.ip,
        is_success=audit_log.is_success,
        created_at=audit_log.created_at,
        request_hash=audit_log.request_hash,
        response_hash=audit_log.response_hash,
        request_id=audit_log.request_id,
        user_agent=audit_log.user_agent,
        prev_hash=audit_log.prev_hash,
    )


def compute_log_hash(fields_dict):
    """计算日志哈希（SHA256，64 位十六进制）。

    fields_dict 为 build_log_hash_payload* 返回的规范化字典。
    sort_keys=True 保证字段顺序确定。
    """
    payload = json.dumps(fields_dict, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def compute_log_hash_from_values(
    tenant_id, user_id, username, action, target_type, target_id,
    target_name, detail, ip, is_success, created_at,
    request_hash, response_hash, request_id, user_agent, prev_hash,
):
    """一站式：根据原始字段值直接计算 log_hash。"""
    payload = build_log_hash_payload_from_values(
        tenant_id, user_id, username, action, target_type, target_id,
        target_name, detail, ip, is_success, created_at,
        request_hash, response_hash, request_id, user_agent, prev_hash,
    )
    return compute_log_hash(payload)


def verify_log_hash(audit_log):
    """校验单条日志的 log_hash 是否与当前字段一致（未被篡改）。

    返回 True 表示 log_hash 与按当前字段重算结果一致。
    旧数据无 log_hash（空串）返回 False，表示不可校验，不阻断业务。
    """
    if not audit_log.log_hash:
        return False
    expected = compute_log_hash(build_log_hash_payload(audit_log))
    return audit_log.log_hash == expected


def verify_hash_chain(audit_logs):
    """校验一组审计日志的哈希链连续性。

    Args:
        audit_logs: 同一租户、按 id 升序排列的 AuditLog 可迭代对象

    Returns:
        dict: {
            'valid': bool,            # 整条链是否连续且无篡改
            'checked': int,           # 校验的记录数
            'broken_at': int or None, # 首个断链记录 id，None 表示无断链
            'errors': [str],          # 断链原因列表
        }

    校验规则：
    - 首条 prev_hash 应为 ''（链首）或与自身字段一致（接入已有链）
    - 每条 log_hash 应等于按其字段重算的结果（防篡改）
    - 每条 prev_hash 应等于上一条的 log_hash（链连续）
    - 旧数据无 log_hash 的记录跳过链连续性校验，但计入 checked
    """
    errors = []
    broken_at = None
    checked = 0
    prev_log_hash = ''
    has_prev = False

    for log in audit_logs:
        checked += 1
        # 1. 单条防篡改校验
        if log.log_hash:
            if not verify_log_hash(log):
                if broken_at is None:
                    broken_at = log.id
                errors.append(
                    f'记录 id={log.id} 的 log_hash 与字段不一致，疑似被篡改'
                )
        # 2. 链连续性校验
        if has_prev and log.log_hash:
            if log.prev_hash != prev_log_hash:
                if broken_at is None:
                    broken_at = log.id
                errors.append(
                    f'记录 id={log.id} 的 prev_hash 与上一条 log_hash 不匹配，'
                    f'链断裂（期望 {prev_log_hash[:12]}...，实际 {log.prev_hash[:12]}...）'
                )
        prev_log_hash = log.log_hash or ''
        has_prev = True

    return {
        'valid': len(errors) == 0,
        'checked': checked,
        'broken_at': broken_at,
        'errors': errors,
    }
