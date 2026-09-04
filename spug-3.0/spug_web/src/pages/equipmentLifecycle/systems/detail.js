/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Descriptions, Table, Tag, Modal, message, Button, Select } from 'antd';
import { AuthDiv, AuthButton, Breadcrumb } from 'components';
import { history } from 'libs';
import SystemForm from './SystemForm';
import RelationForm from './RelationForm';
import { systemStore, relationStore, RELATION_STATUS_OPTIONS } from './store';

/**
 * 系统基本信息子组件：置于 system.view 权限的 AuthDiv 内，仅授权后触发详情请求
 */
@observer
class SystemInfo extends React.Component {
  componentDidMount() {
    systemStore.fetchRecord(this.props.id)
      .then(res => {
        systemStore.current = res;
      })
      .catch(() => {});
  }

  componentWillUnmount() {
    systemStore.current = null;
  }

  render() {
    const system = systemStore.current || {};
    return (
      <div style={{marginBottom: 16}}>
        <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
          <Descriptions title={system.name || '系统详情'} bordered size="small" column={2}
                        style={{flex: 1, marginRight: 16}}>
            <Descriptions.Item label="系统编码">{system.code || '-'}</Descriptions.Item>
            <Descriptions.Item label="在役设备数">{system.active_device_count ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="系统描述" span={2}>{system.description || '-'}</Descriptions.Item>
            <Descriptions.Item label="创建时间">{system.created_at || '-'}</Descriptions.Item>
            <Descriptions.Item label="最后更新时间">{system.updated_at || '-'}</Descriptions.Item>
          </Descriptions>
          <div>
            <AuthButton auth="equipment_lifecycle.system.manage" type="primary"
                        onClick={() => systemStore.showForm(system)}>编辑系统</AuthButton>
            <Button style={{marginLeft: 8}}
                    onClick={() => history.push('/equipment-lifecycle/systems')}>返回列表</Button>
          </div>
        </div>
      </div>
    );
  }
}

/**
 * 关系维护子组件：置于 relation.view 权限的 AuthDiv 内，仅授权后触发关系请求
 */
@observer
class RelationSection extends React.Component {
  componentDidMount() {
    relationStore.setSystem(this.props.id);
    relationStore.fetchRecords();
  }

  componentWillUnmount() {
    relationStore.systemId = null;
    relationStore.records = [];
  }

  handleExit = (record) => {
    Modal.confirm({
      title: '确认退出关系',
      content: `退出后该记录将封存为历史（不会被删除），重新加入需建立新的时间段。确定让设备「${record.device_name}」退出该系统吗？`,
      okText: '确定退出',
      cancelText: '取消',
      onOk: () => relationStore.handleExit(record.id).then(() => message.success('已退出')),
    });
  };

  render() {
    const columns = [
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
                        onClick={() => relationStore.showForm(record)}>编辑</AuthButton>
            <AuthButton auth="equipment_lifecycle.relation.manage" type="link" danger
                        onClick={() => this.handleExit(record)}>退出</AuthButton>
          </React.Fragment>
        ) : <span style={{color: '#999'}}>历史记录</span>
      }
    ];

    return (
      <div>
        <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12}}>
          <span style={{fontWeight: 500, fontSize: 16}}>设备关系维护</span>
          <div>
            <Select
              allowClear
              placeholder="全部状态"
              style={{width: 130, marginRight: 8}}
              value={relationStore.f_status}
              options={RELATION_STATUS_OPTIONS}
              onChange={(value) => {
                relationStore.statusFilter = value || null;
                relationStore.page = 1;
                relationStore.fetchRecords();
              }}
            />
            <AuthButton auth="equipment_lifecycle.relation.manage" type="primary"
                        onClick={() => relationStore.showForm({})}>新增关系</AuthButton>
          </div>
        </div>
        <Table
          loading={relationStore.isFetching}
          dataSource={relationStore.records}
          rowKey="id"
          columns={columns}
          pagination={{
            current: relationStore.page,
            pageSize: relationStore.pageSize,
            total: relationStore.total,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 条`,
            onChange: (page, pageSize) => {
              relationStore.page = page;
              relationStore.pageSize = pageSize;
              relationStore.fetchRecords();
            }
          }}
          scroll={{ x: 1000 }}
        />
      </div>
    );
  }
}

/**
 * 系统详情 + 关系维护页（路由页，不经菜单进入）
 * 权限：system.view 或 relation.view 可进入；各区段数据请求由对应权限的内层组件触发
 */
@observer
class SystemDetail extends React.Component {
  render() {
    const id = this.props.match && this.props.match.params && this.props.match.params.id;
    return (
      <AuthDiv auth="equipment_lifecycle.system.view|equipment_lifecycle.relation.view">
        <Breadcrumb>
          <Breadcrumb.Item>首页</Breadcrumb.Item>
          <Breadcrumb.Item>设备生命周期</Breadcrumb.Item>
          <Breadcrumb.Item>系统档案</Breadcrumb.Item>
          <Breadcrumb.Item>系统详情</Breadcrumb.Item>
        </Breadcrumb>
        <AuthDiv auth="equipment_lifecycle.system.view">
          <SystemInfo id={id}/>
        </AuthDiv>
        <AuthDiv auth="equipment_lifecycle.relation.view">
          <RelationSection id={id}/>
        </AuthDiv>
        {systemStore.formVisible && <SystemForm/>}
        {relationStore.formVisible && <RelationForm systemId={relationStore.systemId}/>}
      </AuthDiv>
    );
  }
}

export default SystemDetail
