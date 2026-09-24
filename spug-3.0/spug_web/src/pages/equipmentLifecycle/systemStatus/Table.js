/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 当前运行状态——系统状态列表（只读，复用 /systems/ 查询接口）。
 * 行内"详情"跳转系统列表页 ?detail= 直达详情抽屉，由该页重新加载数据。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Tag, Input, Button, Empty } from 'antd';
import { AuthDiv } from 'components';
import { history } from 'libs';
import { listStore as store } from './store';
import { PERM, HEALTH_STATUS_OPTIONS, HEALTH_STATUS_TEXT, HEALTH_STATUS_COLOR } from '../constants';

@observer
class ComTable extends React.Component {
  columns = [{
    title: '系统名称',
    dataIndex: 'name',
    width: 200,
  }, {
    title: '安装地点',
    dataIndex: 'install_location',
    ellipsis: true,
  }, {
    title: '运行健康状态',
    dataIndex: 'health_status',
    width: 130,
    render: (text) => (
      <Tag color={HEALTH_STATUS_COLOR[text]}>{HEALTH_STATUS_TEXT[text] || text}</Tag>
    ),
  }, {
    title: '是否可用',
    dataIndex: 'is_active',
    width: 90,
    render: (text) => (text ? <Tag color="green">可用</Tag> : <Tag color="default">已停用</Tag>),
  }, {
    title: '操作',
    key: 'action',
    width: 90,
    render: (text, record) => (
      <a onClick={() => history.push(`/el/systems?detail=${record.id}`)}>详情</a>
    ),
  }];

  render() {
    return (
      <AuthDiv auth={PERM.SYS_VIEW}>
        <div style={{marginBottom: 12}}>
          <Input
            allowClear
            style={{width: 240}}
            value={store.f_keyword}
            onChange={e => store.f_keyword = e.target.value}
            placeholder="系统名称"
            onPressEnter={() => {store.page = 1; store.fetchRecords();}}
          />
          <Button type="primary" style={{marginLeft: 8}}
                  onClick={() => {store.page = 1; store.fetchRecords();}}>查询</Button>
        </div>
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
          locale={{emptyText: <Empty description="暂无系统" image={Empty.PRESENTED_IMAGE_SIMPLE}/>}}
        />
      </AuthDiv>
    );
  }
}

export default ComTable;
