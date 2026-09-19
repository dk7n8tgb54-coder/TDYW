/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 系统详情——系统履历页签（步骤 3.4）。
 * 展示当前系统的履历事件并区分角色：主体（primary）/受影响（affected）/
 * 关联（related，如工单受影响登记，不参与健康状态计算）；
 * 履历只读，来源详情跳转由来源页面重新校验权限。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Tag, Radio, Empty } from 'antd';
import { AuthDiv } from 'components';
import { history } from 'libs';
import { EventStore } from './store';
import {
  PERM, EVENT_TYPE_TEXT, EVENT_TYPE_COLOR,
  EVENT_ROLE_TEXT, EVENT_ROLE_COLOR, SOURCE_TYPE_TEXT, buildSourceHref,
} from './constants';

const ROLE_OPTIONS = [
  {value: '', label: '全部'},
  {value: 'primary', label: '主体'},
  {value: 'affected', label: '受影响'},
  {value: 'related', label: '关联'},
];

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

  handleRoleChange = (e) => {
    tabStore.page = 1;
    tabStore.fetchSystemEvents(this.props.systemId, e.target.value || undefined);
  };

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
    title: '角色',
    dataIndex: 'role',
    width: 80,
    render: (text) => <Tag color={EVENT_ROLE_COLOR[text]}>{EVENT_ROLE_TEXT[text] || text}</Tag>,
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
        <div style={{marginBottom: 12}}>
          <Radio.Group
            value={tabStore.f_role || ''}
            onChange={this.handleRoleChange}
            optionType="button"
            options={ROLE_OPTIONS}
          />
        </div>
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
              tabStore.fetchSystemEvents(this.props.systemId, tabStore.f_role || undefined);
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
