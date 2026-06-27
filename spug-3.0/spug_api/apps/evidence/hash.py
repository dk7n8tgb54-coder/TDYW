# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.

"""
证据事件哈希链工具

职责：
1. build_event_hash_payload_from_values —— 规范化字段为确定性字典（save 与 verify 共用）
2. compute_event_hash                  —— 基于 + prev_hash 计算 SHA256
3. verify_event_hash                   —— 校验单条事件 event_hash 是否与字段一致
4. verify_event_chain                  —— 校验同一业务对象证据链连续性

哈希链策略（方案 3.2.1 第一期）：
- 按"业务对象"(tenant_id + module + object_type + object_id) 形成链
- prev_hash = 同一业务对象链上一条的 event_hash
- 便于单条业务记录导出完整证据包
"""
import hashlib
import json


def _to_text(value):
    """将任意值规范化为字符串，None → ''。"""
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


def build_event_hash_payload_from_values(
    tenant_id, module, object_type, object_id, event_type,
    actor_user_id, actor_username, actor_name,
    object_snapshot, attachment_hashes, prev_hash, created_at,
):
    """根据原始字段值构建 event_hash 输入字典（确定性排序）。

    与方案 3.2.1 的 event_hash 定义保持一致：
        event_hash = SHA256(
          tenant_id + module + object_type + object_id + event_type
          + actor_user_id + object_snapshot + attachment_hashes
          + prev_hash + created_at
        )
    所有值经 _to_text 规范化，保证 save 与 verify 口径一致。
    """
    return {
        'tenant_id': _to_text(tenant_id),
        'module': _to_text(module),
        'object_type': _to_text(object_type),
        'object_id': _to_text(object_id),
        'event_type': _to_text(event_type),
        'actor_user_id': _to_text(actor_user_id),
        'actor_username': _to_text(actor_username),
        'actor_name': _to_text(actor_name),
        'object_snapshot': _to_text(object_snapshot),
        'attachment_hashes': _to_text(attachment_hashes),
        'prev_hash': _to_text(prev_hash),
        'created_at': _to_text(created_at),
    }


def build_event_hash_payload(event):
    """根据 EvidenceEvent 模型实例构建 event_hash 输入字典。"""
    return build_event_hash_payload_from_values(
        tenant_id=event.tenant_id,
        module=event.module,
        object_type=event.object_type,
        object_id=event.object_id,
        event_type=event.event_type,
        actor_user_id=event.actor_user_id,
        actor_username=event.actor_username,
        actor_name=event.actor_name,
        object_snapshot=event.object_snapshot,
        attachment_hashes=event.attachment_hashes,
        prev_hash=event.prev_hash,
        created_at=event.created_at,
    )


def compute_event_hash(fields_dict):
    """计算证据事件哈希（SHA256，64 位十六进制）。sort_keys=True 保证字段顺序确定。"""
    payload = json.dumps(fields_dict, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def compute_event_hash_from_values(
    tenant_id, module, object_type, object_id, event_type,
    actor_user_id, actor_username, actor_name,
    object_snapshot, attachment_hashes, prev_hash, created_at,
):
    """一站式：根据原始字段值直接计算 event_hash。"""
    payload = build_event_hash_payload_from_values(
        tenant_id, module, object_type, object_id, event_type,
        actor_user_id, actor_username, actor_name,
        object_snapshot, attachment_hashes, prev_hash, created_at,
    )
    return compute_event_hash(payload)


def verify_event_hash(event):
    """校验单条证据事件的 event_hash 是否与当前字段一致（未被篡改）。

    返回 True 表示 event_hash 与按当前字段重算结果一致。
    旧数据无 event_hash（空串）返回 False，表示不可校验，不阻断业务。
    """
    if not event.event_hash:
        return False
    expected = compute_event_hash(build_event_hash_payload(event))
    return event.event_hash == expected


def verify_event_chain(events):
    """校验同一业务对象证据链连续性。

    Args:
        events: 同一 (tenant_id, module, object_type, object_id)、按 id 升序的 EvidenceEvent

    Returns:
        dict: {
            'valid': bool,
            'checked': int,
            'broken_at': int or None,
            'errors': [str],
        }

    校验规则：
    - 每条 event_hash 应等于按其字段重算的结果（防篡改）
    - 每条 prev_hash 应等于上一条的 event_hash（链连续）
    - 旧数据无 event_hash 的记录跳过链连续性校验，但计入 checked
    """
    errors = []
    broken_at = None
    checked = 0
    prev_event_hash = ''
    has_prev = False

    for ev in events:
        checked += 1
        # 1. 单条防篡改校验
        if ev.event_hash:
            if not verify_event_hash(ev):
                if broken_at is None:
                    broken_at = ev.id
                errors.append(
                    f'证据事件 id={ev.id} 的 event_hash 与字段不一致，疑似被篡改'
                )
        # 2. 链连续性校验
        if has_prev and ev.event_hash:
            if ev.prev_hash != prev_event_hash:
                if broken_at is None:
                    broken_at = ev.id
                errors.append(
                    f'证据事件 id={ev.id} 的 prev_hash 与上一条 event_hash 不匹配，'
                    f'链断裂'
                )
        prev_event_hash = ev.event_hash or ''
        has_prev = True

    return {
        'valid': len(errors) == 0,
        'checked': checked,
        'broken_at': broken_at,
        'errors': errors,
    }
