/**
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 系统详情——升级记录页签（升级管理挂接系统档案）。
 * 展示升级系统为当前系统的升级记录；数据来自 upgrade app 的
 * GET /api/equipment-lifecycle/systems/<id>/upgrade-records/（权限 upgrade.upgrade.view）。
 */
import React from 'react';
import { Table, Tag, Empty } from 'antd';
import { AuthDiv } from 'components';
import { http } from 'libs';

const UPGRADE_STATUS_COLOR = {
  '处理中': 'processing',
  '已完成': 'success',
  '已回退': 'error',
};

class UpgradeRecordsTab extends React.Component {
  // 服务端分页：后端 paginate() 默认 page_size=20，客户端分页会静默截断
  state = {records: [], total: 0, page: 1, pageSize: 10, loading: false};

  componentDidMount() {
    this.fetchRecords();
  }

  fetchRecords = (page = this.state.page) => {
    this.setState({loading: true});
    http.get(`/api/equipment-lifecycle/systems/${this.props.systemId}/upgrade-records/`,
      {params: {page, page_size: this.state.pageSize}})
      .then(res => {
        const data = (res && res.data) || [];
        this.setState({
          records: data,
          total: (res && res.total) || data.length,
          page,
        });
      })
      .catch(() => {})
      .finally(() => this.setState({loading: false}));
  };

  handlePageChange = (page) => {
    this.fetchRecords(page);
  };

  columns = [{
    title: '编号',
    dataIndex: 'upgrade_no',
    width: 140,
  }, {
    title: '标题',
    dataIndex: 'title',
    width: 220,
    ellipsis: true,
  }, {
    title: '升级类型',
    dataIndex: 'upgrade_type',
    width: 100,
  }, {
    title: '升级时间',
    dataIndex: 'upgrade_time',
    width: 150,
  }, {
    title: '状态',
    dataIndex: 'status',
    width: 90,
    render: (text) => <Tag color={UPGRADE_STATUS_COLOR[text] || 'default'}>{text}</Tag>,
  }, {
    title: '负责人',
    dataIndex: 'owner',
    width: 100,
  }];

  render() {
    return (
      <AuthDiv auth="upgrade.upgrade.view">
        <Table
          rowKey="id"
          size="small"
          loading={this.state.loading}
          pagination={{
            current: this.state.page,
            pageSize: this.state.pageSize,
            total: this.state.total,
            showTotal: total => `共 ${total} 条`,
            onChange: this.handlePageChange,
          }}
          dataSource={this.state.records}
          columns={this.columns}
          locale={{emptyText: <Empty description="当前系统暂无升级记录" image={Empty.PRESENTED_IMAGE_SIMPLE}/>}}
        />
      </AuthDiv>
    );
  }
}

export default UpgradeRecordsTab;
