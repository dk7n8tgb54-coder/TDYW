/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——系统履历分组表格（按系统分组，事项聚合展示）。
 * 系统行展开显示该系统的业务事项（随分组接口返回，无需二次请求）；
 * 当前健康状态展示在分组头，"状态变化"入口打开健康状态历史抽屉。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Tag, Empty } from 'antd';
import { AuthDiv } from 'components';
import store from './groupStore';
import ItemTable from './ItemTable';
import { PERM, HEALTH_COLOR, formatDateTime } from './constants';

@observer
class GroupTable extends React.Component {
  componentDidMount() {
    store.fetchGroups();
  }

  columns = [{
    title: '系统',
    key: 'system',
    width: 260,
    render: (text, group) => group.system.name,
  }, {
    title: '当前健康状态',
    key: 'health',
    width: 170,
    render: (text, group) => (
      <span>
        <Tag color={HEALTH_COLOR[group.system.health_status] || 'default'}>
          {group.system.health_status_text || '未知'}
        </Tag>
        <a onClick={() => store.openHealthDrawer(group)}>状态变化</a>
      </span>
    ),
  }, {
    title: '履历事项',
    dataIndex: 'item_count',
    width: 100,
    render: (text) => `${text} 项`,
  }, {
    title: '未关闭故障',
    dataIndex: 'open_fault_count',
    width: 110,
    render: (text) => text > 0 ? <Tag color="red">{text}</Tag> : <Tag>0</Tag>,
  }, {
    title: '最近履历时间',
    dataIndex: 'last_event_at',
    width: 160,
    render: (text) => formatDateTime(text),
  }];

  render() {
    return (
      <AuthDiv auth={PERM.EVENT_VIEW}>
        <Table
          rowKey={record => record.system.id}
          size="small"
          loading={store.isFetching}
          pagination={{
            pageSize: store.pageSize,
            current: store.page,
            total: store.total,
            showTotal: total => `共 ${total} 个系统`,
            onChange: store.changePage,
          }}
          dataSource={store.groups}
          columns={this.columns}
          expandable={{
            expandedRowRender: record => <ItemTable group={record}/>,
          }}
          locale={{emptyText: (
            <Empty
              description={store.fetchFailed ? '履历加载失败，请重试' : '暂无系统履历'}
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            />
          )}}
        />
      </AuthDiv>
    );
  }
}

export default GroupTable;
