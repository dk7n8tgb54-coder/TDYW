/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Tag, Modal, message } from 'antd';
import { FilterBar, AuthDiv, Breadcrumb, AuthButton } from 'components';
import RelationForm from './systems/RelationForm';
import { relationStore as store, RELATION_STATUS_OPTIONS } from './systems/store';

/**
 * 关系列表子组件：置于 AuthDiv 内，仅授权用户可见并触发数据请求。
 * 支持按系统/状态/设备关键字筛选，跨系统查看全部系统—设备关系。
 */
@observer
class RelationTable extends React.Component {
  componentDidMount() {
    store.fetchRecords();
    store.fetchSystemOptions();
  }

  handleExit = (record) => {
    Modal.confirm({
      title: '确认退出关系',
      content: `退出后该记录将封存为历史（不会被删除），重新加入需建立新的时间段。确定让设备「${record.device_name}」退出系统「${record.system_name}」吗？`,
      okText: '确定退出',
      cancelText: '取消',
      onOk: () => store.handleExit(record.id).then(() => message.success('已退出')),
    });
  };

  render() {
    const columns = [
      { title: '所属系统', dataIndex: 'system_name', width: 180 },
      { title: '设备编号', dataIndex: 'device_sn', width: 140 },
      { title: '设备名称', dataIndex: 'device_name', width: 140 },
      { title: '关系角色', dataIndex: 'role_text', width: 100 },
      {
        title: '主要归属', dataIndex: 'is_primary', width: 90, align: 'center',
        render: (v) => v ? <Tag color="blue">是</Tag> : <Tag>否</Tag>,
      },
      { title: '生效日期', dataIndex: 'valid_from', width: 110 },
      { title: '失效日期', dataIndex: 'valid_to', width: 110, render: (v) => v || '长期' },
      {
        title: '状态', dataIndex: 'status_text', width: 90,
        render: (text, record) => (
          <Tag color={record.status === 'active' ? 'green' : 'default'}>{text}</Tag>
        )
      },
      { title: '备注', dataIndex: 'remark', ellipsis: true, render: (v) => v || '-' },
      {
        title: '操作',
        width: 130,
        fixed: 'right',
        render: (text, record) => record.status === 'active' ? (
          <React.Fragment>
            <AuthButton auth="equipment_lifecycle.relation.manage" type="link"
                        onClick={() => store.showForm(record)}>编辑</AuthButton>
            <AuthButton auth="equipment_lifecycle.relation.manage" type="link" danger
                        onClick={() => this.handleExit(record)}>退出</AuthButton>
          </React.Fragment>
        ) : <span style={{color: '#999'}}>历史记录</span>
      }
    ];

    return (
      <React.Fragment>
        <FilterBar
          store={store}
          fields={[
            { key: 'f_keyword', label: '设备编号/名称', type: 'input', placeholder: '请输入' },
            {
              key: 'f_system_id', label: '所属系统', type: 'select',
              options: () => store.systemOptions.map(sys => ({
                value: sys.id,
                label: sys.code ? `${sys.name}（${sys.code}）` : sys.name,
              })),
            },
            { key: 'f_status', label: '状态', type: 'select', options: RELATION_STATUS_OPTIONS },
          ]}
          onSearch={store.fetchRecords}
          onReset={store.resetFilter}
        />
        <div style={{marginBottom: 16}}>
          <AuthButton auth="equipment_lifecycle.relation.manage" type="primary"
                      onClick={() => store.showForm({})}>新增关系</AuthButton>
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
          scroll={{ x: 1200 }}
        />
      </React.Fragment>
    );
  }
}

/**
 * 系统设备关系维护页（独立页面，跨系统视角）
 * 权限：equipment_lifecycle.relation.view 查看 / equipment_lifecycle.relation.manage 维护
 */
@observer
class RelationIndex extends React.Component {
  render() {
    return (
      <AuthDiv auth="equipment_lifecycle.relation.view">
        <Breadcrumb>
          <Breadcrumb.Item>首页</Breadcrumb.Item>
          <Breadcrumb.Item>设备生命周期</Breadcrumb.Item>
          <Breadcrumb.Item>设备关系</Breadcrumb.Item>
        </Breadcrumb>
        <RelationTable/>
        {store.formVisible && <RelationForm systemSelectable/>}
      </AuthDiv>
    );
  }
}

export default RelationIndex
