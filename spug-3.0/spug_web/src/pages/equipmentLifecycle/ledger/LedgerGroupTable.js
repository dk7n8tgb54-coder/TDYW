/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运维台账周期分组表格（2026-10-11）：
 * 外层一行 = 一个"维护类型＋周期"分组（台账数/待填写/已提交复核），
 * 展开行 = 该周期下各系统台账（复用列表既有列与操作）。
 *
 * - 数据来自 /ledgers/period-groups/（后端分组，组内已排序）；
 * - groupsVersion 作 remount key：新数据到达后默认全部展开
 *   （antd4 非受控 defaultExpandAllRows 只在挂载时生效）；
 * - 无分页：周期分组视图面向小体量周期数据（每系统每周期一张）。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Table} from 'antd';

const GROUP_COLUMNS = [
  {title: '维护周期', dataIndex: 'period_text', width: 180},
  {title: '台账数', dataIndex: 'total', width: 100, align: 'center'},
  {
    title: '待填写（草稿）', dataIndex: 'pending', width: 140, align: 'center',
    render: v => v || 0,
  },
  {
    title: '已提交/已复核', dataIndex: 'filled', width: 140, align: 'center',
    render: v => v || 0,
  },
];

function LedgerGroupTable({store, columns}) {
  return (
    <Table
      key={store.groupsVersion}
      rowKey="maintenance_period"
      loading={store.isGroupsFetching}
      dataSource={store.groups}
      columns={GROUP_COLUMNS}
      pagination={false}
      defaultExpandAllRows
      expandedRowRender={group => (
        <Table
          rowKey="id"
          size="small"
          dataSource={group.ledgers}
          columns={columns}
          pagination={false}
        />
      )}
    />
  );
}

export default observer(LedgerGroupTable);
