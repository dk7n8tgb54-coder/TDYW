/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 操作记录页签：手册级完整时间线。动作文案与详情解析共享自 oplogShared
 * （FileHistoryModal 按文件过滤弹窗共用同一套），本页签不再自行维护映射。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Tag } from 'antd';
import { formatDateTime } from '../utils';
import { oplogActionLabel, oplogActionHighlight, renderOplogDetail } from './oplogShared';
import store from './store';

@observer
class RecordsTab extends React.Component {
  renderDetail(record) {
    return renderOplogDetail(record);
  }

  render() {
    return (
      <div>
        <Table rowKey="id" size="middle"
          loading={store.isFetchingLogs}
          dataSource={store.logs}
          pagination={{current: store.logsPage, pageSize: 15, total: store.logsTotal,
            onChange: p => store.fetchLogs(store.id, p)}}>
          <Table.Column title="时间" dataIndex="created_at" width={160}
            render={v => formatDateTime(v)}/>
          <Table.Column title="操作账号" dataIndex="user_name" width={140}
            render={v => v || '-'}/>
          <Table.Column title="动作" dataIndex="action" width={130}
            render={v => (
              oplogActionHighlight(v)
                ? <Tag color="orange">{oplogActionLabel(v)}</Tag>
                : <Tag>{oplogActionLabel(v)}</Tag>
            )}/>
          <Table.Column title="详情" render={(_, record) => this.renderDetail(record)}/>
        </Table>
        <div style={{marginTop: 8, color: '#999', fontSize: 12}}>
          操作记录精确到账号；科室共用账号无法区分账号内的实际操作人，请在管理制度中约定。
          按具体文件回看发布参与与操作记录，请使用文件清单行内「文件历史」。
        </div>
      </div>
    );
  }
}

export default RecordsTab;
