/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 本期工作概览卡（2026-10-14，2026-10-20 布局改版，同日二次压缩视觉密度）：
 * 填写列表默认关注点。
 *
 * - 周月维护展示 本周 + 本月 两块，季维护展示本航季一块；宽屏两卡并排
 *   （flex-basis 380px，容器不足两倍宽度时自动上下堆叠），单卡内统计
 *   放不下时自动换行，不截断数字、不出现横向滚动；
 * - 2026-10-20 压缩：卡内边距 4/12/5、统计数字 16px、区块间距 8px，
 *   保留全部统计数字与突出规则，降低卡片视觉重量；
 * - 每卡两行：第一行"周期名称 · 日期"（每周 M.D—M.D，跨年周带年份；
 *   每月 YYYY年M月；季维护沿用后端完整期次标签），第二行固定顺序
 *   应填/待生成/待填写/已完成，已作废/需处理仅非零时追加；
 * - 数量全部来自后端 /ledgers/period-overview/ 真实统计：应填/待生成依据
 *   模板生成规则计算（待生成≠前端估算），待填写/已完成为本期已有台账的
 *   真实状态数量；前端不伪造任何数字；
 * - 待生成/待填写非零时以主题蓝突出，零值淡化；已作废/需处理为零时隐藏，
 *   需处理非零时橙色+警示图标明确提示；
 * - "需处理"为缺少版本/系统停用/作废或历史草稿占用的槽位数，提示去处理；
 * - 未配置适用系统/生成周期的模板单列提示（不参与本期应填统计）。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Spin, Tooltip} from 'antd';
import {WarningOutlined} from '@ant-design/icons';

const COUNT_ITEMS = [
  ['expected', '应填', '本期按模板配置应填写的台账数（可生成 + 已存在）'],
  ['to_generate', '待生成', '尚未生成、可一键生成的数量（依据模板生成规则计算）'],
  ['drafting', '待填写', '本期已有台账中处于草稿的数量'],
  ['completed', '已完成', '本期已完成填写的数量'],
  ['voided', '已作废', '本期已作废的数量（不自动重建，需人工处理或补建）'],
  ['attention', '需处理', '缺少版本/系统停用/作废或历史草稿占用，需人工处理的槽位'],
];

const COLOR_NORMAL = '#333';
const COLOR_DIMMED = '#bfbfbf';
const COLOR_ACTION = '#1890ff';
const COLOR_WARN = '#fa8c16';

function countStyle(key, value) {
  if (key === 'attention' && value) {
    return {num: COLOR_WARN, label: COLOR_WARN, warn: true};
  }
  if (!value) return {num: COLOR_DIMMED, label: COLOR_DIMMED};
  if (key === 'to_generate' || key === 'drafting') {
    return {num: COLOR_ACTION, label: '#666'};
  }
  return {num: COLOR_NORMAL, label: '#666'};
}

// 期次日期短文本：每周 M.D—M.D（跨年周两端都带年份）/ 每月 YYYY年M月；
// 其余（航季或日期字段缺失）回退后端完整期次标签，不猜测、不改写。
function periodRangeText(block) {
  const start = block.period_start || '';
  const end = block.period_end || '';
  const period = block.maintenance_period || '';
  if (/^\d{4}-\d{2}-\d{2}$/.test(period) && start && end) {
    const [startYear, startMonth, startDay] = start.split('-');
    const [endYear, endMonth, endDay] = end.split('-');
    if (startYear !== endYear) {
      return `${startYear}.${startMonth}.${startDay}—${endYear}.${endMonth}.${endDay}`;
    }
    return `${startMonth}.${startDay}—${endMonth}.${endDay}`;
  }
  if (/^\d{4}-\d{2}$/.test(period) && start) {
    const [year, month] = start.split('-');
    return `${year}年${parseInt(month, 10)}月`;
  }
  return block.period_label || '';
}

function CountItem({block, itemKey, label, tip}) {
  const value = block[itemKey] || 0;
  const style = countStyle(itemKey, value);
  return (
    <Tooltip title={tip}>
      <span style={{cursor: 'help', whiteSpace: 'nowrap'}}>
        {style.warn && <WarningOutlined style={{color: COLOR_WARN, marginRight: 2}}/>}
        <span
          data-testid={`overview-count-${block.key}-${itemKey}`}
          style={{fontSize: 16, fontWeight: 600, color: style.num}}>
          {value}
        </span>
        <span style={{marginLeft: 4, fontSize: 12, color: style.label}}>{label}</span>
      </span>
    </Tooltip>
  );
}

function BlockCard({block}) {
  return (
    <div
      data-testid={`overview-block-${block.key}`}
      style={{
        flex: '1 1 380px', minWidth: 0,
        border: '1px solid #e8e8e8', borderRadius: 4, padding: '4px 12px 5px',
        background: '#fafafa',
      }}>
      <div style={{marginBottom: 2}}>
        <span style={{fontWeight: 600}}>{block.title}</span>
        <span style={{color: '#8c8c8c', fontSize: 12}}>{` · ${periodRangeText(block)}`}</span>
      </div>
      <div style={{display: 'flex', flexWrap: 'wrap', columnGap: 16, rowGap: 2, alignItems: 'baseline'}}>
        {COUNT_ITEMS.map(([key, label, tip]) => (
          (key === 'voided' || key === 'attention') && !block[key] ? null : (
            <CountItem key={key} block={block} itemKey={key} label={label} tip={tip}/>
          )
        ))}
      </div>
    </div>
  );
}

function LedgerPeriodOverviewCard({store}) {
  const overview = store.overview;
  if (!overview || !Array.isArray(overview.blocks)) return null;
  return (
    <div data-testid="period-overview" style={{marginBottom: 8}}>
      {store.isOverviewFetching && (
        <div style={{marginBottom: 4}}><Spin size="small"/></div>
      )}
      <div style={{display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'stretch'}}>
        {overview.blocks.map(block => <BlockCard key={block.key} block={block}/>)}
      </div>
      {overview.unconfigured_templates > 0 && (
        <div style={{color: '#999', fontSize: 12, marginTop: 2}}>
          另有 {overview.unconfigured_templates} 个模板待配置适用系统/生成周期（在模板管理中配置），不参与本期应填统计
        </div>
      )}
    </div>
  );
}

export default observer(LedgerPeriodOverviewCard);
