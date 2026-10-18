/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运维台账周期分组表格（2026-10-11，2026-10-14 增强）：
 * 外层一行 = 一个"维护类型＋周期"分组（完整期次标签 + 本期徽标 + 五状态
 * 统计），展开行 = 该期次下各系统台账（复用列表既有列与操作）。
 *
 * - 数据来自 /ledgers/period-groups/（后端分组+分页，组内统计与可见行一致）；
 * - 展开受控：默认只展开本期（is_current，后端按生成规则判定），历史期次
 *   折叠；展开状态存 LedgerStore 并持久化，刷新/翻页/返回详情后保留；
 * - 分页按期次组切片，历史数据量大时不再无限制全部展开。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Table, Tag} from 'antd';
import {LEDGER_TABLE_SCROLL_X} from './LedgerColumns';

const GROUP_COLUMNS = [
  {
    title: '维护周期', dataIndex: 'period_text', width: 240,
    render: (v, group) => (
      <span>
        {group.is_current && (
          <Tag color="processing" style={{marginRight: 6}}>本期</Tag>
        )}
        {v}
      </span>
    ),
  },
  {title: '台账数', dataIndex: 'total', width: 80, align: 'center'},
  {
    title: '草稿（待填写）', dataIndex: 'draft', width: 120, align: 'center',
    render: v => v || 0,
  },
  {
    title: '已完成', dataIndex: 'completed', width: 80, align: 'center',
    render: v => v || 0,
  },
  {
    title: '已作废', dataIndex: 'void', width: 80, align: 'center',
    render: v => v || 0,
  },
];

const GROUP_COLUMNS_TOTAL = 648; // 展开列 48 + 五列宽合计 600

function LedgerGroupTable({store, columns}) {
  return (
    <Table
      rowKey="maintenance_period"
      loading={store.isGroupsFetching}
      dataSource={store.groups}
      columns={GROUP_COLUMNS}
      // 数字 scroll.x + 显式 tableLayout fixed 使外层分组表宽度锁定容器
      // （min-width 100%），不被展开内容撑宽——展开的内嵌台账表
      // （scroll.x 1270）因而在自身容器内横向滚动，fixed right 操作列
      // 保持可见；无显式 tableLayout 时 rc-table 对本表推导 auto，
      // 展开内容仍会把 auto 布局的表格撑宽（2026-10-18）
      tableLayout="fixed"
      scroll={{x: GROUP_COLUMNS_TOTAL}}
      pagination={{
        total: store.groupsTotal,
        current: store.groupsPage,
        pageSize: store.groupsPageSize,
        showSizeChanger: false,
        showTotal: t => `共 ${t} 个周期分组`,
        onChange: page => store.setGroupsPage(page),
      }}
      expandedRowKeys={store.expandedPeriodKeys.slice()}
      onExpandedRowsChange={keys => store.togglePeriodExpanded(keys)}
      expandedRowRender={group => (
        <Table
          rowKey="id"
          size="small"
          dataSource={group.ledgers}
          columns={columns}
          pagination={false}
          scroll={{x: LEDGER_TABLE_SCROLL_X}}
        />
      )}
    />
  );
}

export default observer(LedgerGroupTable);
