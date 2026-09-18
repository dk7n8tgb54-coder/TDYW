/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——系统列表表格。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Modal, Tag, Button } from 'antd';
import { AuthButton, Action } from 'components';
import store from './store';
import { HEALTH_STATUS_TEXT, PERM } from './constants';

const HEALTH_TAG_COLOR = {
  normal: 'green',
  degraded: 'orange',
  fault: 'red',
  repairing: 'geekblue',
  interrupted: 'red',
  unknown: 'default',
};

function confirmDelete(record) {
  Modal.confirm({
    title: '删除确认',
    content: `确定删除系统「${record.name}」吗？其配置字段值、组成项、变更历史与快照将一并删除，且不可恢复。`,
    onOk: () => store.deleteRecord(record),
  });
}

class SystemTable extends React.Component {
  componentDidMount() {
    store.fetchTypes();
    store.fetchRecords();
  }

  columns = [{
    title: '系统编号',
    dataIndex: 'system_code',
    width: 130,
  }, {
    title: '系统名称',
    dataIndex: 'name',
    width: 200,
  }, {
    title: '系统类型',
    dataIndex: 'system_type_name',
    width: 110,
  }, {
    title: '系统型号',
    dataIndex: 'system_model',
    width: 110,
  }, {
    title: '安装地点',
    dataIndex: 'install_location',
    width: 160,
    ellipsis: true,
  }, {
    title: '使用单位',
    dataIndex: 'use_unit',
    width: 110,
  }, {
    title: '系统负责人',
    dataIndex: 'responsible_user_name',
    width: 100,
  }, {
    title: '运行健康状态',
    dataIndex: 'health_status',
    width: 110,
    render: (value, record) => (
      <Tag color={HEALTH_TAG_COLOR[value] || 'default'}>
        {record.health_status_text || HEALTH_STATUS_TEXT[value] || value}
      </Tag>
    ),
  }, {
    title: '是否可用',
    dataIndex: 'is_active',
    width: 90,
    render: value => value
      ? <Tag color="green">可用</Tag>
      : <Tag color="default">已停用</Tag>,
  }, {
    title: '操作',
    width: 230,
    render: (text, record) => (
      <Action>
        <Action.Button
          auth={PERM.SYS_VIEW}
          onClick={() => store.showDetail(record)}
        >
          详情
        </Action.Button>
        <Action.Button
          auth={PERM.SYS_EDIT}
          onClick={() => store.showForm(record)}
        >
          编辑
        </Action.Button>
        <Action.Button
          auth={PERM.SYS_DEACTIVATE}
          onClick={() => store.toggleActive(record, !record.is_active)}
        >
          {record.is_active ? '停用' : '启用'}
        </Action.Button>
        <Action.Button auth={PERM.SYS_DEL} onClick={() => confirmDelete(record)}>
          删除
        </Action.Button>
      </Action>
    ),
  }];

  render() {
    return (
      <div>
        <Table
          loading={store.isFetching}
          rowKey="id"
          columns={this.columns}
          dataSource={store.records}
          pagination={{
            current: store.page,
            pageSize: store.pageSize,
            total: store.total,
            showTotal: t => `共 ${t} 条`,
            onChange: (page, pageSize) => {
              store.page = page;
              store.pageSize = pageSize;
              store.fetchRecords();
            },
          }}
        />
      </div>
    );
  }
}

export default observer(SystemTable);
