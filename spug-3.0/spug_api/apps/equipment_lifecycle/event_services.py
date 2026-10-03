# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""统一系统履历服务（步骤 3.4，单系统简化）。

职责：
- record_system_event：履历事件写入唯一入口，故障、台账异常、健康状态、
  升级与值班巡检共用同一事件模型（SystemEvent）；config_snapshot 类型仅
  存量兼容展示（配置快照功能已下线，不再新增写入）；工单事件类型已随
  "故障维修工单"功能整体删除（2026-09-30），存量工单事件由迁移 0043 清理；
- 按业务对象提供写入辅助：每条事件只关联业务对象所属的那一个系统，
  不再向其他系统（受影响/关联）分布写入事件。

约定：
- 须在业务保存的同一数据库事务内调用（业务回滚则履历一并回滚）；
- 事件只追加、不改写：更正与受控撤销（故障作废）以追加新事件表达；
- 重复业务请求由业务层状态机与幂等键（client_token、处置状态防重）拦截，
  业务对象不重复则事件不重复；
- 事件为纯插入，不递归触发健康状态重算；
- 事件保存来源编号与系统快照，不保存自由文本冒充来源关系（来源以
  source_type + source_id 表达，详情跳转由来源页面重新校验权限）。
"""
import json

from django.utils import timezone

from apps.equipment_lifecycle.models import (
    LifecycleSystem,
    SystemEvent,
    SystemFault,
)


def record_system_event(*, tenant_id, system, event_type, action, source_type,
                        title, source_id='', source_no='', detail=None,
                        occurred_at=None, created_by=None):
    """写入一条系统履历事件，返回 SystemEvent。

    - system 为 LifecycleSystem 实例（正式系统 ID 关联 + 编号/名称快照）；
    - occurred_at 缺省取当前时间（业务事实时间由调用方传入更佳）；
    - detail 为 dict，序列化为 JSON 存储（受控结构，不塞大文本）。
    """
    return SystemEvent.objects.create(
        tenant_id=tenant_id,
        system=system,
        event_type=event_type,
        action=action,
        source_type=source_type,
        source_id=str(source_id or ''),
        source_no=(source_no or '')[:50],
        title=(title or '')[:200],
        detail=json.dumps(detail or {}, ensure_ascii=False),
        system_code=system.system_code,
        system_name=system.name,
        occurred_at=occurred_at or timezone.now(),
        created_by=created_by,
    )


def record_fault_lifecycle_events(fault, action, detail=None, occurred_at=None, created_by=None):
    """故障生命周期事件：只落故障所属系统的履历（单系统简化）。

    - create/recover/close/cancel 共用本写入；
    - occurred_at：create 用故障发生时间，recover 用恢复时间，其余取当前时间。
    """
    # 故障级别字段已删除（2026-09）：履历标题与 detail 不再携带 level
    base_detail = {
        'fault_no': fault.fault_no,
        'status': fault.status,
        'impact_status': fault.impact_status,
        'source_type': fault.source_type,
    }
    base_detail.update(detail or {})
    if action == 'create':
        title = '发生故障'
    else:
        title = {
            'recover': '故障恢复确认',
            'close': '故障关闭',
            'cancel': '故障撤销登记',
        }[action]
    record_system_event(
        tenant_id=fault.tenant_id,
        system=fault.system,
        event_type=SystemEvent.EVENT_FAULT,
        action=action,
        source_type='fault',
        source_id=fault.id,
        source_no=fault.fault_no,
        title=title,
        detail=base_detail,
        occurred_at=occurred_at,
        created_by=created_by,
    )


def record_ledger_convert_event(item, ledger, action, target_no='', detail=None,
                                created_by=None):
    """台账异常明细转故障事件（落到明细所属系统的履历）。

    - action = convert_to_fault（转工单动作已随工单功能删除，2026-09-30）；
    - target_no 为生成的故障号（来源关系双向可追溯）。
    """
    return record_system_event(
        tenant_id=item.tenant_id,
        system=item.system,
        event_type=SystemEvent.EVENT_LEDGER,
        action=action,
        source_type='ledger_item',
        source_id=item.id,
        source_no=ledger.ledger_no,
        title='台账异常转故障',
        detail={
            'ledger_id': ledger.id,
            'ledger_no': ledger.ledger_no,
            'ledger_type': ledger.ledger_type,
            'ledger_item_id': item.id,
            'item_name': item.item_name_snapshot,
            'target_no': target_no,
            **(detail or {}),
        },
        created_by=created_by,
    )


def record_upgrade_lifecycle_events(record, action, detail=None, created_by=None):
    """升级记录生命周期事件：只落升级记录所属系统的履历（升级管理挂接系统档案）。

    - create/complete/rollback 共用本写入；登记、完成、回退为里程碑动作，
      过程性状态记录在升级状态时间线（UpgradeStatusLog），不生成履历事件；
    - record 为 apps.upgrade.models.UpgradeRecord 实例（鸭子类型，不引入反向依赖）；
    - 历史未匹配系统档案的记录（system 为空）不写履历。
    """
    if getattr(record, 'system_id', None) is None:
        return None
    base_detail = {
        'upgrade_title': record.title,
        'upgrade_type': record.upgrade_type,
        'status': record.status,
        'owner': record.owner,
    }
    base_detail.update(detail or {})
    title = {
        'create': '系统升级登记',
        'complete': '系统升级完成',
        'rollback': '系统升级回退',
    }[action]
    return record_system_event(
        tenant_id=record.tenant_id,
        system=record.system,
        event_type=SystemEvent.EVENT_UPGRADE,
        action=action,
        source_type='upgrade',
        source_id=record.id,
        title=title,
        detail=base_detail,
        created_by=created_by,
    )


def record_runtime_record_event(record, action, title, detail=None,
                                occurred_at=None, created_by=None):
    """运行记录履历事件（2026-10 运行记录第一版）。

    只在满足履历条件时由服务层调用（影响系统运行 / 标记重要 / 转为故障），
    普通小问题不写履历；无手工创建履历接口。
    - action：create（影响系统运行的记录创建时）/ mark_important（标记重要，
      只在普通→重要升级时生成一次，不伪造历史事件）/ convert_to_fault；
    - 事件保留运行记录编号（source_no）与来源链接（source_type+source_id）。
    """
    return record_system_event(
        tenant_id=record.tenant_id,
        system=record.system,
        event_type=SystemEvent.EVENT_RUNTIME,
        action=action,
        source_type='runtime_record',
        source_id=record.id,
        source_no=record.record_no,
        title=title,
        detail=detail,
        occurred_at=occurred_at,
        created_by=created_by,
    )


def record_health_change_event(system, old_status, new_status, reason='', created_by=None):
    """健康状态变化事件（仅状态实际变化时由重算服务调用，纯追加）。"""
    return record_system_event(
        tenant_id=system.tenant_id,
        system=system,
        event_type=SystemEvent.EVENT_HEALTH,
        action='status_change',
        source_type='health',
        title=f'运行健康状态由「{LifecycleSystem.HEALTH_STATUS_TEXT_MAP.get(old_status, old_status)}」'
              f'变为「{LifecycleSystem.HEALTH_STATUS_TEXT_MAP.get(new_status, new_status)}」',
        detail={'before': old_status, 'after': new_status, 'reason': (reason or '')[:200]},
        created_by=created_by,
    )
