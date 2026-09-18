/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运维台账模板管理页（步骤 3.2）：列表 + 新增/编辑（含项目配置）。
 * 模板按台账类型分别维护；停用模板不能用于新台账。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Input, Select, Button, Tag, Popconfirm, Table, message} from 'antd';
import {PlusOutlined} from '@ant-design/icons';
import {SearchForm, AuthDiv, Breadcrumb, AuthButton} from 'components';
import TemplateForm from './TemplateForm';
import {templateStore as store} from './store';
import {
  API_PREFIX_L, CREATED_FROM_TEXT, CYCLE_TEXT, EXEC_SCOPE_TEXT,
  INPUT_TYPE_TEXT, LEDGER_TYPE_TEXT, PERM_L,
} from './constants';

const STATUS_ACTIVE = {color: 'green'};

@observer
class TemplateIndex extends React.Component {
  componentDidMount() {
    store.fetchRecords();
  }

  columns = [
    {title: '模板编号', dataIndex: 'template_code', width: 140},
    {title: '模板名称', dataIndex: 'name', width: 180},
    {
      title: '台账类型', dataIndex: 'ledger_type', width: 110,
      render: (v, r) => `${LEDGER_TYPE_TEXT[v] || v}${r.maintenance_cycle ? `（${CYCLE_TEXT[r.maintenance_cycle]}）` : ''}`,
    },
    {title: '适用系统类型', dataIndex: 'applicable_system_type_name', width: 130, render: v => v || '-'},
    {
      title: '适用系统', dataIndex: 'applicable_systems', ellipsis: true,
      render: list => (list || []).length ? list.map(s => s.name).join('、') : '-',
    },
    {title: '项目数', dataIndex: 'items_count', width: 70, align: 'center'},
    {
      title: '状态', dataIndex: 'is_active', width: 80, align: 'center',
      render: v => <Tag {...(v ? STATUS_ACTIVE : {})}>{v ? '启用' : '停用'}</Tag>,
    },
    {
      title: '操作', width: 160, align: 'center',
      render: (t, record) => (
        <span>
          <AuthButton auth={PERM_L.TPL_EDIT}>
            <a onClick={() => store.showForm(record)}>编辑</a>
          </AuthButton>
          <AuthButton auth={PERM_L.TPL_DEL}>
            <Popconfirm
              title={record.is_active ? '停用后模板不能用于新台账，历史台账不受影响。确定停用？' : '确定启用该模板？'}
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
      <AuthDiv auth={PERM_L.TPL_VIEW}>
        <Breadcrumb>
          <Breadcrumb.Item>首页</Breadcrumb.Item>
          <Breadcrumb.Item>设备全生命周期</Breadcrumb.Item>
          <Breadcrumb.Item>运行维护</Breadcrumb.Item>
          <Breadcrumb.Item>台账模板</Breadcrumb.Item>
        </Breadcrumb>
        <SearchForm>
          <SearchForm.Item span={6} title="模板编号/名称">
            <Input
              allowClear value={store.f_keyword}
              onChange={e => store.setFilter('f_keyword', e.target.value)}
              placeholder="请输入模板编号或名称"
              onPressEnter={() => store.fetchRecords()}/>
          </SearchForm.Item>
          <SearchForm.Item span={6} title="台账类型">
            <Select
              allowClear style={{width: '100%'}} value={store.f_ledger_type}
              onChange={v => {
                store.setFilter('f_ledger_type', v);
                store.fetchRecords();
              }}
              placeholder="请选择类型">
              {Object.keys(LEDGER_TYPE_TEXT).map(key => (
                <Select.Option value={key} key={key}>{LEDGER_TYPE_TEXT[key]}</Select.Option>
              ))}
            </Select>
          </SearchForm.Item>
        </SearchForm>
        <div style={{marginBottom: 12}}>
          <AuthButton
            auth={PERM_L.TPL_ADD} type="primary" icon={<PlusOutlined/>}
            onClick={() => store.showForm()}>
            新增模板
          </AuthButton>
        </div>
        <TableRender store={store} columns={this.columns}/>
        {store.formVisible && <TemplateForm store={store}/>}
      </AuthDiv>
    );
  }
}

@observer
class TableRender extends React.Component {
  render() {
    const {store, columns} = this.props;
    return (
      <Table
        rowKey="id"
        loading={store.isFetching}
        dataSource={store.records}
        columns={columns}
        pagination={{showSizeChanger: false, showTotal: t => `共 ${t} 条`}}
      />
    );
  }
}

export default TemplateIndex;
