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
 * - 无模板/临时补录组（source_type=manual）名称与停用标注由后端下发；
 * - Excel 模板组行内提供"翻阅台账"（2026-10-18）：进入翻阅视图连续查看
 *   该模板历次台账（manual 组无模板版式，不提供）。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Table} from 'antd';

const GROUP_COLUMNS = (onOpen, onBrowse) => [
  {
    title: '模板名称', dataIndex: 'template_name', width: 240, ellipsis: true,
    render: (v, record) => (
      <a onClick={() => onOpen(record)}>
        {v}{(record.source_type === 'excel' || record.source_type === 'form')
          && record.is_active === false ? ' [已停用]' : ''}
        {record.source_type === 'form' ? (
          <span style={{color: '#722ed1', marginLeft: 6, fontSize: 12}}>[数字表单]</span>
        ) : null}
      </a>
    ),
  },
  {title: '台账总数', dataIndex: 'total', width: 100, align: 'center'},
  {title: '草稿', dataIndex: 'draft', width: 80, align: 'center', render: v => v || 0},
  {title: '已完成', dataIndex: 'completed', width: 80, align: 'center', render: v => v || 0},
  {title: '已作废', dataIndex: 'void', width: 80, align: 'center', render: v => v || 0},
  {title: '最近录入时间', dataIndex: 'last_created_at', width: 150,
    render: v => v ? String(v).slice(0, 19).replace('T', ' ') : '—'},
  {
    title: '操作', width: 150, align: 'center',
    render: (text, record) => (
      <span>
        {record.source_type === 'excel' && (
          <a data-testid="group-browse" onClick={() => onBrowse(record)}>翻阅台账</a>
        )}
        <a
          style={record.source_type === 'excel' ? {marginLeft: 8} : undefined}
          onClick={() => onOpen(record)}>
          查看台账
        </a>
      </span>
    ),
  },
];

function LedgerTemplateGroupTable({store}) {
  const columns = GROUP_COLUMNS(
    group => store.openTemplateGroup(group),
    group => store.openBrowse(group).catch(() => {}));
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
