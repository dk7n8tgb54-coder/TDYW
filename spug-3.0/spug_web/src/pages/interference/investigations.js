import React, {useEffect} from 'react';
import {Button, Input, Modal, Select, message} from 'antd';
import {DeleteOutlined, EditOutlined, PlusOutlined, SearchOutlined} from '@ant-design/icons';
import {observer} from 'mobx-react';
import {http} from 'libs';
import {Action, AuthButton, AuthDiv, Breadcrumb, SearchForm, TableCard} from 'components';
import store from './store';
import InvestigationForm from './InvestigationForm';

const STATUS_LABELS = {
  draft: '草稿', observing: '持续观察', measuring: '测量中',
  concluded: '已形成结论', closed: '已结束', cancelled: '已取消',
};

function InvestigationsPage() {
  useEffect(() => { store.page = 1; store.fetchInvestigations(); }, []);

  function remove(record) {
    Modal.confirm({
      title: '删除规律调查',
      content: '调查及其关联信息将被软删除，确定继续吗？',
      onOk: () => http.delete(`/api/interference/investigations/${record.id}/`).then(() => {
        message.success('删除成功');
        return store.fetchInvestigations();
      }).catch(() => {}),
    });
  }

  const columns = [
    {title: '调查名称', dataIndex: 'name', ellipsis: true},
    {title: '调查状态', dataIndex: 'status', width: 110, render: value => STATUS_LABELS[value] || value},
    {title: '关联事件数', dataIndex: 'event_count', width: 100},
    {title: '首次发生时间', dataIndex: 'first_event_datetime', width: 170, render: value => value ? String(value).replace('T', ' ').slice(0, 19) : '-'},
    {title: '最近发生时间', dataIndex: 'last_event_datetime', width: 170, render: value => value ? String(value).replace('T', ' ').slice(0, 19) : '-'},
    {title: '主要地点', dataIndex: 'primary_location', width: 140, ellipsis: true, render: value => value || '-'},
    {title: '主要频率', dataIndex: 'primary_frequency', width: 120, ellipsis: true, render: value => value || '-'},
    {title: '负责人', dataIndex: 'owner', width: 120},
    {title: '操作', width: 160, fixed: 'right', render: record => <Action>
      <Action.Button auth="interference.investigation.view" onClick={() => store.showInvestigation({...record, isViewMode: true})}>查看</Action.Button>
      <Action.Button auth="interference.investigation.edit" icon={<EditOutlined/>} onClick={() => store.showInvestigation(record)}>编辑</Action.Button>
      <Action.Button danger auth="interference.investigation.del" icon={<DeleteOutlined/>} onClick={() => remove(record)}>删除</Action.Button>
    </Action>},
  ];

  return <AuthDiv auth="interference.investigation.view">
    <Breadcrumb><Breadcrumb.Item>首页</Breadcrumb.Item><Breadcrumb.Item>干扰管理</Breadcrumb.Item><Breadcrumb.Item>规律调查</Breadcrumb.Item></Breadcrumb>
    <SearchForm>
      <SearchForm.Item span={7} title="调查名称"><Input allowClear value={store.investigationName} onChange={event => {store.investigationName = event.target.value;}} onPressEnter={() => store.fetchInvestigations({name: store.investigationName})}/></SearchForm.Item>
      <SearchForm.Item span={5} title="调查状态"><Select allowClear style={{width: '100%'}} value={store.investigationStatus} options={Object.keys(STATUS_LABELS).map(value => ({value, label: STATUS_LABELS[value]}))} onChange={value => {store.investigationStatus = value; store.fetchInvestigations({status: value});}}/></SearchForm.Item>
      <SearchForm.Item span={24}><Button type="primary" icon={<SearchOutlined/>} onClick={() => store.fetchInvestigations({name: store.investigationName, status: store.investigationStatus})}>查询</Button></SearchForm.Item>
    </SearchForm>
    <TableCard tKey="interferenceInvestigations" title="规律调查" rowKey="id" loading={store.investigationsLoading} dataSource={store.investigations} onReload={store.fetchInvestigations} columns={columns} scroll={{x: 1000}} actions={[<AuthButton key="add" auth="interference.investigation.add" type="primary" icon={<PlusOutlined/>} onClick={() => store.showInvestigation({})}>新建调查</AuthButton>]} pagination={{current: store.page, pageSize: store.pageSize, total: store.total, showSizeChanger: true, onChange: (page, pageSize) => {store.page = page; store.pageSize = pageSize; store.fetchInvestigations();}}}/>
    {store.investigationModalVisible && <InvestigationForm/>}
  </AuthDiv>;
}

export default observer(InvestigationsPage);
