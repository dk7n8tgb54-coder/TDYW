/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 本期工作概览卡（2026-10-14）：填写列表默认关注点。
 *
 * - 周月维护展示 本周 + 本月 两块，季维护展示本航季一块；
 * - 数量全部来自后端 /ledgers/period-overview/ 真实统计：应填/待生成依据
 *   模板生成规则计算（待生成≠前端估算），待填写/已完成为本期已有台账的
 *   真实状态数量；前端不伪造任何数字；
 * - "需处理"为缺少版本/系统停用/作废或历史草稿占用的槽位数，提示去处理；
 * - 未配置适用系统/生成周期的模板单列提示（不参与本期应填统计）。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Spin, Tag, Tooltip} from 'antd';

const COUNT_ITEMS = [
  ['expected', '应填', '本期按模板配置应填写的台账数（可生成 + 已存在）'],
  ['to_generate', '待生成', '尚未生成、可一键生成的数量（依据模板生成规则计算）'],
  ['drafting', '待填写', '本期已有台账中处于草稿的数量'],
  ['completed', '已完成', '本期已完成填写的数量'],
  ['voided', '已作废', '本期已作废的数量（不自动重建，需人工处理或补建）'],
  ['attention', '需处理', '缺少版本/系统停用/作废或历史草稿占用，需人工处理的槽位'],
];

function countColor(key, value) {
  if (!value) return '#999';
  if (key === 'to_generate') return '#1890ff';
  if (key === 'attention') return '#fa8c16';
  return '#333';
}

function BlockCard({block}) {
  return (
    <div
      data-testid={`overview-block-${block.key}`}
      style={{
        border: '1px solid #e8e8e8', borderRadius: 4, padding: '8px 12px',
        marginBottom: 8, background: '#fafafa',
      }}>
      <div style={{marginBottom: 4}}>
        <Tag color="processing" style={{marginRight: 8}}>{block.title}</Tag>
        <span style={{fontWeight: 600}}>{block.period_label}</span>
        <span style={{color: '#999', marginLeft: 8, fontSize: 12}}>
          {block.period_start} ~ {block.period_end}
        </span>
      </div>
      <div style={{display: 'flex', gap: 20, flexWrap: 'wrap'}}>
        {COUNT_ITEMS.map(([key, label, tip]) => (
          <Tooltip key={key} title={tip}>
            <span style={{cursor: 'help'}}>
              <span style={{fontSize: 18, fontWeight: 600, color: countColor(key, block[key])}}>
                {block[key] || 0}
              </span>
              <span style={{marginLeft: 4, color: '#666'}}>{label}</span>
            </span>
          </Tooltip>
        ))}
      </div>
    </div>
  );
}

function LedgerPeriodOverviewCard({store}) {
  const overview = store.overview;
  if (!overview || !Array.isArray(overview.blocks)) return null;
  return (
    <div data-testid="period-overview" style={{marginBottom: 12}}>
      {store.isOverviewFetching && (
        <div style={{marginBottom: 4}}><Spin size="small"/></div>
      )}
      {overview.blocks.map(block => <BlockCard key={block.key} block={block}/>)}
      {overview.unconfigured_templates > 0 && (
        <div style={{color: '#999', fontSize: 12}}>
          另有 {overview.unconfigured_templates} 个模板待配置适用系统/生成周期（在模板管理中配置），不参与本期应填统计
        </div>
      )}
    </div>
  );
}

export default observer(LedgerPeriodOverviewCard);
