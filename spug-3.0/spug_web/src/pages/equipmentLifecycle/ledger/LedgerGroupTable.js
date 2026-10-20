/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运维台账周期分组表格（2026-10-11，2026-10-14 增强，2026-10-20 单表头改版）：
 * 一张表承载全部内容——表头即台账记录列（模板名称/系统/期次/状态/台账编号/
 * 操作），周期作为分组行以首列 colSpan 贯通整行（本期徽标 + 完整期次标签 +
 * 台账数/草稿/已完成/已作废统计），展开后直接显示该周期的台账记录行。
 *
 * - 旧版为"外层分组表 + expandedRowRender 内嵌台账表"，每个展开周期都渲染
 *   一套子表表头，多周期同时展开时表头与记录交替出现；单表头改版后整表
 *   只有一套列标题（antd 合并单元格模式：首列 colSpan=列数，其余列
 *   colSpan=0）；
 * - 数据来自 /ledgers/period-groups/（后端分组+分页，组内统计与可见行一致）；
 * - 展开受控：默认只展开本期（is_current，后端按生成规则判定），历史期次
 *   折叠；展开状态存 LedgerStore 并持久化，刷新/翻页/返回详情后保留；
 *   分组行点击或行首展开按钮均可切换，各周期相互独立；
 * - 数字 scroll.x + 显式 tableLayout fixed 使表格宽度锁定容器（min-width
 *   100%），窄屏横向滚动时 fixed right 操作列保持可见；
 * - 分页按期次组切片，历史数据量大时不再无限制全部展开。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Pagination, Table, Tag} from 'antd';
import {CaretDownOutlined, CaretRightOutlined} from '@ant-design/icons';
import {LEDGER_TABLE_SCROLL_X} from './LedgerColumns';

// 周期行统计项（2026-10-20 自旧分组表头迁入行内）：与组内可见行同口径的
// 后端统计；数值在前、灰字名称在后，零值淡化但保留（作废数不隐藏）
const GROUP_COUNTS = [
  ['total', '台账数'],
  ['draft', '草稿'],
  ['completed', '已完成'],
  ['void', '已作废'],
];

function GroupCount({label, value}) {
  const count = value || 0;
  return (
    <span style={{whiteSpace: 'nowrap', color: count ? '#333' : '#bfbfbf'}}>
      <span style={{fontWeight: 600}}>{count}</span>
      <span style={{marginLeft: 4, fontSize: 12, color: '#8c8c8c'}}>{label}</span>
    </span>
  );
}

const CARET_BUTTON_STYLE = {
  border: 'none', padding: '0 4px', background: 'transparent',
  cursor: 'pointer', color: '#8c8c8c', fontSize: 12, lineHeight: 1,
  display: 'inline-flex', alignItems: 'center',
};

function PeriodGroupCell({group, expanded, onToggle}) {
  return (
    <div style={{display: 'flex', alignItems: 'center', minHeight: 22}}>
      <button
        type="button"
        data-testid="period-group-caret"
        aria-expanded={expanded}
        aria-label={expanded ? `收起${group.period_text}` : `展开${group.period_text}`}
        style={CARET_BUTTON_STYLE}
        onClick={e => {
          e.stopPropagation();
          onToggle();
        }}>
        {expanded ? <CaretDownOutlined/> : <CaretRightOutlined/>}
      </button>
      {group.is_current && (
        <Tag color="processing" style={{marginRight: 6}}>本期</Tag>
      )}
      <span style={{fontWeight: 600}}>{group.period_text}</span>
      <span
        data-testid="period-group-counts"
        style={{marginLeft: 'auto', display: 'inline-flex', gap: 16, alignItems: 'baseline'}}>
        {GROUP_COUNTS.map(([key, label]) => (
          <GroupCount key={key} label={label} value={group[key]}/>
        ))}
      </span>
    </div>
  );
}

function LedgerGroupTable({store, columns}) {
  const expandedKeys = store.expandedPeriodKeys;
  const togglePeriod = key => {
    store.togglePeriodExpanded(
      expandedKeys.includes(key)
        ? expandedKeys.filter(k => k !== key)
        : [...expandedKeys, key]);
  };
  // 平铺行序列：分组行 + 其展开后的台账记录行（收起的周期只保留分组行）
  const rows = [];
  store.groups.forEach(group => {
    rows.push({__group: group});
    if (expandedKeys.includes(group.maintenance_period)) {
      (group.ledgers || []).forEach(ledger => rows.push(ledger));
    }
  });
  // 单表头合并：分组行由首列单元格贯通整行（colSpan=列数），其余列不渲染；
  // 台账记录行走原列渲染（fixed right 操作列、ellipsis 均保持既有配置）
  const mergedColumns = columns.map((column, index) => ({
    ...column,
    onCell: record => (record.__group
      ? {
          colSpan: index === 0 ? columns.length : 0,
          ...(index === 0 ? {style: {background: '#fafafa'}} : {}),
        }
      : {}),
    ...(index === 0
      ? {
          render: (value, record) => (record.__group ? (
            <PeriodGroupCell
              group={record.__group}
              expanded={expandedKeys.includes(record.__group.maintenance_period)}
              onToggle={() => togglePeriod(record.__group.maintenance_period)}/>
          ) : (
            column.render ? column.render(value, record) : value
          )),
        }
      : {}),
  }));

  return (
    <div>
      <Table
        rowKey={record => (record.__group
          ? `group:${record.__group.maintenance_period}` : record.id)}
        loading={store.isGroupsFetching}
        dataSource={rows}
        columns={mergedColumns}
        tableLayout="fixed"
        scroll={{x: LEDGER_TABLE_SCROLL_X}}
        onRow={record => (record.__group
          ? {
              onClick: () => togglePeriod(record.__group.maintenance_period),
              style: {cursor: 'pointer'},
              'data-testid': 'period-group-row',
            }
          : {})}
        pagination={false}
      />
      {/* 分页为服务端周期组切片（store.setGroupsPage 重新请求），必须独立于
          Table 渲染：内置分页会按 pageSize 对平铺 dataSource 本地切片，
          展开的台账记录行超过 6 条时会被截断（实机 2026-10-20 发现） */}
      <div style={{overflow: 'hidden'}}>
        <Pagination
          style={{float: 'right', margin: '16px 0'}}
          total={store.groupsTotal}
          current={store.groupsPage}
          pageSize={store.groupsPageSize}
          showSizeChanger={false}
          showTotal={t => `共 ${t} 个周期分组`}
          onChange={page => store.setGroupsPage(page)}
        />
      </div>
    </div>
  );
}

export default observer(LedgerGroupTable);
