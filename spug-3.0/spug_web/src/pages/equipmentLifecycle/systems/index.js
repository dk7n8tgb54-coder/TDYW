/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Modal, message } from 'antd';
import { FilterBar, AuthDiv, Breadcrumb, AuthButton } from 'components';
import { history } from 'libs';
import SystemForm from './SystemForm';
import { systemStore as store } from './store';

/**
 * 系统列表子组件：置于 AuthDiv 内，仅授权用户可见并触发数据请求
 */
@observer
class SystemTable extends React.Component {
  componentDidMount() {
    store.fetchRecords();
  }

  handleDelete = (record) => {
    Modal.confirm({
      title: '确认删除',
      content: `确定要删除系统「${record.name}」吗？存在设备关系记录（含历史）的系统无法删除。`,
      okText: '确定',
      cancelText: '取消',
      onOk: () => store.handleDelete(record.id).then(() => message.success('删除成功')),
    });
  };

  render() {
    const columns = [
      { title: '系统编码', dataIndex: 'code', width: 140, render: (v) => v || '-' },
      { title: '系统名称', dataIndex: 'name', width: 220 },
      { title: '系统描述', dataIndex: 'description', ellipsis: true, render: (v) => v || '-' },
      { title: '在役设备数', dataIndex: 'active_device_count', width: 110, align: 'center' },
      { title: '创建时间', dataIndex: 'created_at', width: 170 },
      {
        title: '操作',
        width: 200,
        fixed: 'right',
        render: (text, record) => (
          <React.Fragment>
            <AuthButton auth="equipment_lifecycle.system.view" type="link"
                        onClick={() => history.push(`/equipment-lifecycle/systems/detail/${record.id}`)}>详情</AuthButton>
            <AuthButton auth="equipment_lifecycle.system.manage" type="link"
                        onClick={() => store.showForm(record)}>编辑</AuthButton>
            <AuthButton auth="equipment_lifecycle.system.manage" type="link" danger
                        onClick={() => this.handleDelete(record)}>删除</AuthButton>
          </React.Fragment>
        )
      }
    ];

    return (
      <React.Fragment>
        <FilterBar
          store={store}
          fields={[
            { key: 'f_keyword', label: '系统名称/编码', type: 'input', placeholder: '请输入' },
          ]}
          onSearch={store.fetchRecords}
          onReset={store.resetFilter}
        />
        <div style={{marginBottom: 16}}>
          <AuthButton auth="equipment_lifecycle.system.manage" type="primary"
                      onClick={() => store.showForm({})}>新增系统</AuthButton>
        </div>
        <Table
          loading={store.isFetching}
          dataSource={store.records}
          rowKey="id"
          columns={columns}
          pagination={{
            current: store.page,
            pageSize: store.pageSize,
            total: store.total,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (total) => `共 ${total} 条`,
            onChange: (page, pageSize) => {
              store.page = page;
              store.pageSize = pageSize;
              store.fetchRecords();
            }
          }}
          scroll={{ x: 1000 }}
        />
      </React.Fragment>
    );
  }
}

/**
 * 系统档案列表页（系统主数据维护）
 * 权限：equipment_lifecycle.system.view 查看 / equipment_lifecycle.system.manage 维护
 */
@observer
class SystemIndex extends React.Component {
  render() {
    return (
      <AuthDiv auth="equipment_lifecycle.system.view">
        <Breadcrumb>
          <Breadcrumb.Item>首页</Breadcrumb.Item>
          <Breadcrumb.Item>设备生命周期</Breadcrumb.Item>
          <Breadcrumb.Item>系统档案</Breadcrumb.Item>
        </Breadcrumb>
        <SystemTable/>
        {store.formVisible && <SystemForm/>}
      </AuthDiv>
    );
  }
}

export default SystemIndex
