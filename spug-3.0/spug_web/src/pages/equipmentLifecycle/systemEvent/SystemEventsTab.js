/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 系统详情——系统履历页签（步骤 3.4，单系统简化）。
 * 只展示当前系统自己的履历事件（不再区分主体/受影响/关联角色）；
 * 履历只读，来源详情跳转由来源页面重新校验权限。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Tag, Empty } from 'antd';
import { AuthDiv } from 'components';
import { history } from 'libs';
import { EventStore } from './store';
import {
  PERM, EVENT_TYPE_TEXT, EVENT_TYPE_COLOR, SOURCE_TYPE_TEXT, buildSourceHref,
} from './constants';

const tabStore = new EventStore();

@observer
class SystemEventsTab extends React.Component {
  componentDidMount() {
    tabStore.page = 1;
    tabStore.fetchSystemEvents(this.props.systemId);
  }

  componentWillUnmount() {
    tabStore.resetFilter();
    tabStore.records = [];
    tabStore.total = 0;
  }

  renderSource(record) {
    const text = SOURCE_TYPE_TEXT[record.source_type] || record.source_type;
    const label = record.source_no ? `${text} ${record.source_no}` : text;
    const href = buildSourceHref(record);
    if (!href) return label || '-';
    return <a onClick={() => history.push(href)}>{label}</a>;
  }

  columns = [{
    title: '发生时间',
    dataIndex: 'occurred_at',
    width: 140,
  }, {
    title: '事件类型',
    dataIndex: 'event_type',
    width: 95,
    render: (text) => <Tag color={EVENT_TYPE_COLOR[text]}>{EVENT_TYPE_TEXT[text] || text}</Tag>,
  }, {
    title: '来源',
    key: 'source',
    width: 170,
    render: (text, record) => this.renderSource(record),
  }, {
    title: '事件摘要',
    dataIndex: 'title',
    ellipsis: true,
  }];

  render() {
    return (
      <AuthDiv auth={PERM.EVENT_VIEW}>
        <Table
          rowKey="id"
          size="small"
          loading={tabStore.isFetching}
          pagination={{
            pageSize: tabStore.pageSize,
            current: tabStore.page,
            total: tabStore.total,
            showTotal: total => `共 ${total} 条`,
            onChange: (page) => {
              tabStore.page = page;
              tabStore.fetchSystemEvents(this.props.systemId);
            },
          }}
          dataSource={tabStore.records}
          columns={this.columns}
          locale={{emptyText: <Empty description="当前系统暂无履历事件" image={Empty.PRESENTED_IMAGE_SIMPLE}/>}}
        />
      </AuthDiv>
    );
  }
}

export default SystemEventsTab;
