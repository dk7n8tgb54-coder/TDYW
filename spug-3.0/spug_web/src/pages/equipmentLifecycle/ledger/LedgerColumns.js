/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运维台账列表列定义（2026-10-14 重排视觉优先级）：
 * - sourceTypeOf：优先取后端 source_type，兼容旧数据仅返回 created_from；
 * - 列顺序以"找台账→辨状态→执行操作"为主链：模板名称/系统/期次/状态/操作
 *   在前，台账编号/实际执行日期/执行人/录入人/录入时间作为次要信息靠后；
 * - 期次列显示完整标签（每周｜周一—周日 / 每月｜YYYY年M月 / 航季含起止
 *   日期），历史台账按执行日期归档时以气泡标注来源（不改写历史记录）；
 * - 操作与真实流程一致：草稿→继续填写（可提交的手工台账另有提交），
 *   已退回→处理退回（详情内查看退回原因并修改重提），已提交/已复核/
 *   已作废→查看；作废为低频危险操作收进"更多"菜单，须填写作废原因；
 *   手工台账可在列表直接提交，Excel 台账在填写详情内提交（后端分开校验）。
 * - inGroup=true 时第一列换为"模板版本"（模板组内组名即模板，不重复列名）。
 */
import React, {useState} from 'react';
import {Dropdown, Input, Menu, Modal, Popconfirm, Tag, Tooltip} from 'antd';
import {EllipsisOutlined} from '@ant-design/icons';
import {AuthButton} from 'components';
import {LEDGER_TYPE_TEXT, PERM_L, STATUS_COLOR, STATUS_TEXT} from './constants';

export function sourceTypeOf(record) {
  if (record.source_type) return record.source_type;
  if (record.created_from === 'excel_template') return 'excel';
  return 'manual';
}

function statusTitle(record) {
  if (record.status === 'returned' && record.return_reason) {
    return `退回原因：${record.return_reason}`;
  }
  if (record.status === 'void' && record.void_reason) {
    return `作废原因：${record.void_reason}`;
  }
  return undefined;
}

function PeriodCell({record}) {
  const label = record.period_label;
  if (!label) return '—';
  if (record.period_is_derived && record.period_source_text) {
    return (
      <Tooltip title={record.period_source_text}>
        <span style={{cursor: 'help'}}>
          {label}
          <span style={{color: '#999', marginLeft: 2}}>*</span>
        </span>
      </Tooltip>
    );
  }
  return <span>{label}</span>;
}

/**
 * 受控作废弹窗：作废必须填写原因（后端校验），不物理删除。
 * 独立组件便于真实渲染测试（填充原因→确认→触发 voidLedger）。
 */
export function LedgerVoidModal({record, onOk, onCancel}) {
  const [reason, setReason] = useState('');
  return (
    <Modal
      title={`作废台账（${record ? record.ledger_no : ''}）`}
      visible={!!record}
      okText="确认作废"
      okButtonProps={{danger: true, disabled: !reason.trim()}}
      cancelText="取消"
      onCancel={onCancel}
      onOk={() => onOk(reason.trim())}
      destroyOnClose>
      <p style={{color: '#666'}}>作废后台账不参与统计，且该期次不会在一键生成中自动重建，请谨慎操作。</p>
      <Input.TextArea
        data-testid="void-reason"
        rows={3}
        maxLength={200}
        value={reason}
        onChange={e => setReason(e.target.value)}
        placeholder="请填写作废原因（必填）"/>
    </Modal>
  );
}

function MoreMenu({record, onVoid}) {
  if (record.status === 'void') return null;
  const menu = (
    <Menu onClick={({key}) => {
      if (key === 'void') onVoid(record);
    }}>
      <Menu.Item key="void">
        <AuthButton auth={PERM_L.LED_DEL} style={{color: '#f5222d'}}>
          作废
        </AuthButton>
      </Menu.Item>
    </Menu>
  );
  return (
    <Dropdown overlay={menu} trigger={['click']}>
      <a style={{marginLeft: 8}} data-testid="row-more" aria-label="更多操作">
        <EllipsisOutlined/>
      </a>
    </Dropdown>
  );
}

function ActionCell({record, ledgerType, store, openDetail}) {
  const [voidRecord, setVoidRecord] = useState(null);
  const isExcel = sourceTypeOf(record) === 'excel';
  const editable = record.status === 'draft' || record.status === 'returned';
  const editLabel = record.status === 'returned' ? '处理退回' : '继续填写';
  const canSubmit = !isExcel && editable; // 手工台账可在列表提交；Excel 台账在填写详情内提交
  return (
    <span>
      <a data-testid="row-primary-action" onClick={() => openDetail(record)}>
        {editable ? editLabel : '查看'}
      </a>
      {canSubmit && (
        <AuthButton auth={PERM_L.LED_SUBMIT}>
          <Popconfirm
            title={`确定提交${LEDGER_TYPE_TEXT[ledgerType]}台账？`}
            onConfirm={() => store.submitLedger(record.id)}>
            <a style={{marginLeft: 8}}>提交</a>
          </Popconfirm>
        </AuthButton>
      )}
      <MoreMenu record={record} onVoid={setVoidRecord}/>
      <LedgerVoidModal
        record={voidRecord}
        onCancel={() => setVoidRecord(null)}
        onOk={reason => {
          Promise.resolve(store.voidLedger(voidRecord.id, reason))
            .catch(() => {})
            .finally(() => setVoidRecord(null));
        }}/>
    </span>
  );
}

export function buildColumns(store, ledgerType, openDetail, inGroup = false) {
  return [
    inGroup ? {
      // 模板组内：列展示创建时引用的版本快照（组名即模板，不重复列模板名）
      title: '模板版本', key: 'source_version', width: 90,
      render: (v, record) => sourceTypeOf(record) === 'excel' && record.source_version_no
        ? `v${record.source_version_no}` : '—',
    } : {
      title: '模板名称', key: 'template_name', width: 160, ellipsis: true,
      render: (v, record) => sourceTypeOf(record) === 'excel'
        ? (record.source_template_name || '—') : '—',
    },
    {
      title: '系统', dataIndex: 'system_name', width: 150, ellipsis: true,
      render: v => v || '—',
    },
    {
      // 期次：每周｜周一—周日 / 每月｜YYYY年M月 / 航季含起止日期；历史台账标注归档来源
      title: '期次', key: 'period', width: 200,
      render: (v, record) => <PeriodCell record={record}/>,
    },
    {
      title: '状态', dataIndex: 'status', width: 90,
      render: (v, record) => {
        const tag = <Tag color={STATUS_COLOR[v]}>{STATUS_TEXT[v] || v}</Tag>;
        const tip = statusTitle(record);
        return tip ? <Tooltip title={tip}>{tag}</Tooltip> : tag;
      },
    },
    {
      title: '操作', key: 'actions', width: 150, align: 'center',
      render: (v, record) => (
        <ActionCell record={record} ledgerType={ledgerType} store={store} openDetail={openDetail}/>
      ),
    },
    // —— 次要信息 ——
    {title: '台账编号', dataIndex: 'ledger_no', width: 180},
    // 周期生成的应填台账执行日期为空（填写人执行后录入），显示 —
    {title: '实际执行日期', dataIndex: 'executed_date', width: 110,
     render: v => v ? String(v).slice(0, 10) : '—'},
    {title: '执行人', dataIndex: 'executor_names', width: 130, ellipsis: true,
     render: v => v || '—'},
    {title: '录入人', dataIndex: 'created_by_name', width: 90,
     render: v => v || '—'},
    {title: '录入时间', dataIndex: 'created_at', width: 160},
  ];
}
