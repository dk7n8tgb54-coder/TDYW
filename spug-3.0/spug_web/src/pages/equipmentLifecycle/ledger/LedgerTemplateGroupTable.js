/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运维台账"按模板查看"分组表格（2026-10-11）：
 * 一行 = 一个模板身份分组（Excel 模板组按模板主键，或"无模板/临时补录"组），
 * 列 = 模板名称（停用标注）/台账总数/各状态数量/最近执行日期。
 *
 * - 数据来自 /ledgers/template-groups/（后端按组聚合统计，仅含有历史台账的
 *   组；统计不受分页影响，分页由后端切片、本组件只渲染当前页）；
 * - 组内页码等状态保存在 LedgerStore（activeGroup/templateGroupsPage），
 *   从组内返回、详情返回后均保留；
 * - 无模板/临时补录组（source_type=manual）名称与停用标注由后端下发。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Table} from 'antd';

const GROUP_COLUMNS = (onOpen) => [
  {
    title: '模板名称', dataIndex: 'template_name', width: 240, ellipsis: true,
    render: (v, record) => (
      <a onClick={() => onOpen(record)}>
        {v}{record.source_type === 'excel' && record.is_active === false ? ' [已停用]' : ''}
      </a>
    ),
  },
  {title: '台账总数', dataIndex: 'total', width: 100, align: 'center'},
  {title: '草稿', dataIndex: 'draft', width: 80, align: 'center', render: v => v || 0},
  {title: '已提交', dataIndex: 'submitted', width: 80, align: 'center', render: v => v || 0},
  {title: '已退回', dataIndex: 'returned', width: 80, align: 'center', render: v => v || 0},
  {title: '已复核', dataIndex: 'reviewed', width: 80, align: 'center', render: v => v || 0},
  {title: '已作废', dataIndex: 'void', width: 80, align: 'center', render: v => v || 0},
  {title: '最近执行日期', dataIndex: 'last_executed_date', width: 130,
    render: v => v || '—'},
  {
    title: '操作', width: 100, align: 'center',
    render: (text, record) => <a onClick={() => onOpen(record)}>查看台账</a>,
  },
];

function LedgerTemplateGroupTable({store}) {
  const columns = GROUP_COLUMNS(group => store.openTemplateGroup(group));
  return (
    <Table
      rowKey="group_key"
      loading={store.isTemplateGroupsFetching}
      dataSource={store.templateGroups}
      columns={columns}
      pagination={{
        total: store.templateGroupsTotal,
        current: store.templateGroupsPage,
        pageSize: store.templateGroupsPageSize,
        showSizeChanger: false,
        showTotal: t => `共 ${t} 个分组`,
        onChange: page => {
          store.templateGroupsPage = page;
          store.fetchTemplateGroups();
        },
      }}
    />
  );
}

export default observer(LedgerTemplateGroupTable);
