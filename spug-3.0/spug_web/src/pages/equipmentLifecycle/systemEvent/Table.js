/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——统一系统履历列表表格（步骤 3.4，只读，单系统简化）。
 * 来源列仅渲染跳转链接；点击后由来源页面独立重新校验权限与租户。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Tag, Empty } from 'antd';
import { AuthDiv } from 'components';
import { history } from 'libs';
import store from './store';
import {
  PERM, EVENT_TYPE_TEXT, EVENT_TYPE_COLOR, SOURCE_TYPE_TEXT, buildSourceHref,
} from './constants';

@observer
class ComTable extends React.Component {
  componentDidMount() {
    store.fetchRecords();
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
    width: 150,
  }, {
    title: '系统',
    key: 'system',
    width: 200,
    render: (text, record) => (
      <span>
        <span style={{marginRight: 6}}>{record.system_code}</span>
        <span style={{color: '#999'}}>{record.system_name}</span>
      </span>
    ),
  }, {
    title: '事件类型',
    dataIndex: 'event_type',
    width: 100,
    render: (text) => <Tag color={EVENT_TYPE_COLOR[text]}>{EVENT_TYPE_TEXT[text] || text}</Tag>,
  }, {
    title: '来源',
    key: 'source',
    width: 180,
    render: (text, record) => this.renderSource(record),
  }, {
    title: '事件摘要',
    dataIndex: 'title',
    ellipsis: true,
  }, {
    title: '记录人',
    dataIndex: 'created_by_name',
    width: 100,
    render: (text) => text || '-',
  }];

  render() {
    return (
      <AuthDiv auth={PERM.EVENT_VIEW}>
        <Table
          rowKey="id"
          size="small"
          loading={store.isFetching}
          pagination={{
            pageSize: store.pageSize,
            current: store.page,
            total: store.total,
            showTotal: total => `共 ${total} 条`,
            onChange: (page) => {
              store.page = page;
              store.fetchRecords();
            },
          }}
          dataSource={store.records}
          columns={this.columns}
          locale={{emptyText: <Empty description="暂无系统履历" image={Empty.PRESENTED_IMAGE_SIMPLE}/>}}
        />
      </AuthDiv>
    );
  }
}

export default ComTable;
