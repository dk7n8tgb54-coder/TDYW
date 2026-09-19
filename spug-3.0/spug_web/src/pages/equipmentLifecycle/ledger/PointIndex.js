/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 巡检点管理页（步骤 3.2）：巡检点属于具体系统，用于组织检查位置/功能点。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Input, InputNumber, Select, Button, Tag, Modal, Form, Popconfirm, Table, message} from 'antd';
import {PlusOutlined} from '@ant-design/icons';
import {AuthDiv, Breadcrumb, AuthButton} from 'components';
import {http} from 'libs';
import {pointStore as store} from './store';
import {API_PREFIX_L, PERM_L} from './constants';

@observer
class PointIndex extends React.Component {
  componentDidMount() {
    store.fetchRecords();
    store.fetchSystems();
  }

  columns = [
    {title: '巡检点编码', dataIndex: 'point_code', width: 130},
    {title: '巡检点名称', dataIndex: 'name', width: 160},
    {
      title: '所属系统', key: 'system', width: 240,
      render: (t, r) => `${r.system_name}（${r.system_code}）`,
    },
    {title: '位置说明', dataIndex: 'location_desc', ellipsis: true, render: v => v || '-'},
    {title: '显示顺序', dataIndex: 'display_order', width: 90, align: 'center'},
    {
      title: '状态', dataIndex: 'is_active', width: 80, align: 'center',
      render: v => <Tag color={v ? 'green' : 'default'}>{v ? '启用' : '停用'}</Tag>,
    },
    {title: '备注', dataIndex: 'remark', ellipsis: true, render: v => v || '-'},
    {
      title: '操作', width: 130, align: 'center',
      render: (t, record) => (
        <span>
          <AuthButton auth={PERM_L.POINT_MANAGE}>
            <a onClick={() => store.showForm(record)}>编辑</a>
          </AuthButton>
          <AuthButton auth={PERM_L.POINT_MANAGE}>
            <Popconfirm
              title={record.is_active ? '停用后巡检点不能用于新台账，历史台账快照继续显示。确定停用？' : '确定启用该巡检点？'}
              onConfirm={() => store.toggleActive(record, !record.is_active)}>
              <a style={{marginLeft: 8}}>{record.is_active ? '停用' : '启用'}</a>
            </Popconfirm>
          </AuthButton>
        </span>
      ),
    },
  ];

  render() {
    return (
      <AuthDiv auth={PERM_L.POINT_VIEW}>
        <Breadcrumb>
          <Breadcrumb.Item>首页</Breadcrumb.Item>
          <Breadcrumb.Item>设备全生命周期管理</Breadcrumb.Item>
          <Breadcrumb.Item>运行维护</Breadcrumb.Item>
          <Breadcrumb.Item>巡检点管理</Breadcrumb.Item>
        </Breadcrumb>
        <div style={{marginBottom: 12}}>
          <AuthButton
            auth={PERM_L.POINT_MANAGE} type="primary" icon={<PlusOutlined/>}
            onClick={() => store.showForm()}>
            新增巡检点
          </AuthButton>
        </div>
        <PointTable store={store}/>
        {store.formVisible && <PointForm store={store}/>}
      </AuthDiv>
    );
  }
}

@observer
class PointTable extends React.Component {
  render() {
    const {store} = this.props;
    return (
      <Table
        rowKey="id"
        loading={store.isFetching}
        dataSource={store.records}
        columns={this.columns}
        pagination={{showSizeChanger: false, showTotal: t => `共 ${t} 条`}}
      />
    );
  }
}

@observer
class PointForm extends React.Component {
  state = {loading: false, name: '', point_code: '', system: undefined, location_desc: '', display_order: 0, remark: ''};

  componentDidMount() {
    const record = this.props.store.record || {};
    this.setState({
      name: record.name || '',
      point_code: record.point_code || '',
      system: record.system || undefined,
      location_desc: record.location_desc || '',
      display_order: record.display_order || 0,
      remark: record.remark || '',
    });
  }

  submit = () => {
    const {name, point_code, system, location_desc, display_order, remark} = this.state;
    const record = this.props.store.record || {};
    if (!name || !point_code) {
      message.error('巡检点编码和名称不能为空');
      return;
    }
    if (!system) {
      message.error('请选择所属系统');
      return;
    }
    this.setState({loading: true});
    const request = record.id
      ? http.put(`${API_PREFIX_L}/inspection-points/${record.id}/`, {name, location_desc, display_order, remark})
      : http.post(`${API_PREFIX_L}/inspection-points/`, {system, point_code, name, location_desc, display_order, remark});
    request.then(() => {
      store.formVisible = false;
      store.fetchRecords();
      message.success('保存成功');
    }).finally(() => this.setState({loading: false}));
  };

  render() {
    const record = this.props.store.record || {};
    const isEdit = !!record.id;
    const {store} = this.props;
    return (
      <Modal
        title={`${isEdit ? '编辑' : '新增'}巡检点`}
        visible={store.formVisible}
        confirmLoading={this.state.loading}
        onCancel={() => {
          store.formVisible = false;
        }}
        onOk={this.submit}
        destroyOnClose
        okText="保存">
        <Form labelCol={{span: 6}} wrapperCol={{span: 16}}>
          {!isEdit && (
            <Form.Item required label="所属系统">
              <Select
                showSearch optionFilterProp="children"
                value={this.state.system}
                onChange={v => this.setState({system: v})}
                placeholder="请选择系统">
                {store.systems.map(s => (
                  <Select.Option value={s.id} key={s.id}>
                    {s.system_code}｜{s.name}
                  </Select.Option>
                ))}
              </Select>
            </Form.Item>
          )}
          <Form.Item required label="巡检点编码">
            <Input
              disabled={isEdit} value={this.state.point_code}
              onChange={e => this.setState({point_code: e.target.value})}
              placeholder="同一系统内唯一"/>
          </Form.Item>
          <Form.Item required label="巡检点名称">
            <Input value={this.state.name} onChange={e => this.setState({name: e.target.value})}/>
          </Form.Item>
          <Form.Item label="位置说明">
            <Input value={this.state.location_desc} onChange={e => this.setState({location_desc: e.target.value})}/>
          </Form.Item>
          <Form.Item label="显示顺序">
            <InputNumber
              min={0} value={this.state.display_order}
              onChange={v => this.setState({display_order: v || 0})}/>
          </Form.Item>
          <Form.Item label="备注">
            <Input.TextArea rows={2} value={this.state.remark} onChange={e => this.setState({remark: e.target.value})}/>
          </Form.Item>
        </Form>
      </Modal>
    );
  }
}

export default PointIndex;
