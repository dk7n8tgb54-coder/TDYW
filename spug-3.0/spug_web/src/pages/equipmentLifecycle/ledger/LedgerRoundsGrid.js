/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 已记录轮次只读网格（"一日一账"的已记录检查回显）：
 * - 行 = 检查项目（系统分组），列 = 已记录的检查轮次（列头 = 检查时刻），
 *   对齐纸质台账"一页见全天"的形态；
 * - 数据来自当日草稿台账明细（以服务器为准），工作台内只读展示，
 *   编辑走台账列表的编辑入口；某轮未覆盖的项目显示 "—"；
 * - 异常行红色高亮（口径与填写区一致）。
 */
import React from 'react';
import {Collapse, Table} from 'antd';
import {rowLooksAbnormal, rowValueText} from './ledgerCommon';

const {Panel} = Collapse;

export default function LedgerRoundsGrid({rounds, systems}) {
  if (!rounds || !rounds.length) return null;
  // 系统按首次出现顺序聚合；行 = 项目（模板项 id 或临时项名称）在各轮次的取值
  const groups = [];
  const groupMap = {};
  rounds.forEach(round => {
    (round.rows || []).forEach(r => {
      const sKey = String(r.system_id);
      if (!groupMap[sKey]) {
        const system = (systems || []).find(s => s.id === r.system_id);
        groupMap[sKey] = {
          system_id: r.system_id,
          label: system ? `${system.name}（${system.install_location}）` : `系统 #${r.system_id}`,
          itemMap: {},
          rows: [],
        };
        groups.push(groupMap[sKey]);
      }
      const group = groupMap[sKey];
      const key = r.template_item_id ? `ti_${r.template_item_id}` : `tmp_${r.item_name}`;
      if (!group.itemMap[key]) {
        group.itemMap[key] = {key, item_name: r.item_name, unit: r.unit, values: {}};
        group.rows.push(group.itemMap[key]);
      }
      group.itemMap[key].values[round.time] = r;
    });
  });
  const roundColumns = rounds.map(round => ({
    title: round.time, key: `round_${round.time}`, width: 110, align: 'center',
    render: (t, item) => {
      const row = item.values[round.time];
      if (!row) return <span style={{color: '#bbb'}}>—</span>;
      const text = rowValueText(row);
      return <span style={rowLooksAbnormal(row) ? {color: '#f5222d'} : null}>{text || '—'}</span>;
    },
  }));
  return (
    <Collapse defaultActiveKey={groups.map(g => String(g.system_id))}>
      {groups.map(g => {
        const hasAbnormal = g.rows.some(item => Object.values(item.values).some(rowLooksAbnormal));
        return (
          <Panel
            header={g.label} key={String(g.system_id)}
            extra={
              <span>
                {g.rows.length} 项
                {hasAbnormal && <span style={{color: '#f5222d', marginLeft: 8}}>含异常</span>}
              </span>
            }>
            <Table
              rowKey="key" size="small" pagination={false}
              dataSource={g.rows}
              rowClassName={item => Object.values(item.values).some(rowLooksAbnormal) ? 'el-ledger-abnormal-row' : ''}
              columns={[
                {title: '检查项目', dataIndex: 'item_name', width: 180},
                ...(g.rows.some(item => item.unit) ? [{title: '单位', dataIndex: 'unit', width: 60, render: v => v || '-'}] : []),
                ...roundColumns,
              ]}
            />
          </Panel>
        );
      })}
    </Collapse>
  );
}
