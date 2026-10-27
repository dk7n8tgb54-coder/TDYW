import React, {useEffect, useState} from 'react';
import {Button, Input, Modal, Select, message} from 'antd';
import {DeleteOutlined, EditOutlined, PlusOutlined, SearchOutlined} from '@ant-design/icons';
import {observer} from 'mobx-react';
import {http} from 'libs';
import {Action, AuthButton, AuthDiv, SearchForm, TableCard} from 'components';
import store from './store';
import InvestigationForm from './InvestigationForm';
import {CancelInvestigationModal, FinishInvestigationModal} from './InvestigationActions';

// 调查状态三态生命周期（2026-10-26）：状态由生命周期动作（结束/取消调查）
// 推进，列表不再提供内联状态编辑；旧六态（draft/observing/measuring/
// concluded/closed）已随后端退役。
const STATUS_LABELS = {
  investigating: '调查中',
  ended: '已结束',
  cancelled: '已取消',
};

function InvestigationsPage() {
  const [finishRecord, setFinishRecord] = useState(null);
  const [cancelRecord, setCancelRecord] = useState(null);
  useEffect(() => { store.investigationPage = 1; store.fetchInvestigations(); }, []);
  // 对称卸载清理（2026-10-26 审查R1）：事件页接通 InvestigationForm 后，本页
  // 打开查看/编辑弹窗未关闭即切走时，store 单例的遗留弹窗状态会在事件页意外
  // 渲染出弹窗。布局是标准 <Switch><Route>，切页即卸载，与 events.js 同要求
  // 卸载即清理；对已关闭态是 no-op，安全。
  useEffect(() => () => { store.closeInvestigation(); }, []);

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
    {title: '调查状态', dataIndex: 'status', width: 100, render: value => STATUS_LABELS[value] || value},
    {title: '关联事件数', dataIndex: 'event_count', width: 100},
    {title: '首次发生时间', dataIndex: 'first_event_datetime', width: 170, render: value => value ? String(value).replace('T', ' ').slice(0, 19) : '-'},
    {title: '最近发生时间', dataIndex: 'last_event_datetime', width: 170, render: value => value ? String(value).replace('T', ' ').slice(0, 19) : '-'},
    {title: '主要地点', dataIndex: 'primary_location', width: 140, ellipsis: true, render: value => value || '-'},
    {title: '主要频率', dataIndex: 'primary_frequency', width: 120, ellipsis: true, render: value => value || '-'},
    {title: '负责人', dataIndex: 'owner', width: 120},
    {title: '操作', width: 240, fixed: 'right', render: record => <Action>
      <Action.Button auth="interference.investigation.view" onClick={() => store.showInvestigation({...record, isViewMode: true})}>查看</Action.Button>
      <Action.Button auth="interference.investigation.edit" icon={<EditOutlined/>} onClick={() => store.showInvestigation(record)}>编辑</Action.Button>
      {/* 生命周期动作：仅调查中的行可结束/取消，权限与编辑一致（investigation.edit） */}
      {record.status === 'investigating' && <Action.Button auth="interference.investigation.edit" onClick={() => setFinishRecord(record)}>结束调查</Action.Button>}
      {record.status === 'investigating' && <Action.Button auth="interference.investigation.edit" onClick={() => setCancelRecord(record)}>取消调查</Action.Button>}
      <Action.Button danger auth="interference.investigation.del" icon={<DeleteOutlined/>} onClick={() => remove(record)}>删除</Action.Button>
    </Action>},
  ];

  return <AuthDiv auth="interference.investigation.view">
    <SearchForm>
      <SearchForm.Item span={7} title="调查名称"><Input allowClear value={store.investigationName} onChange={event => {store.investigationName = event.target.value;}} onPressEnter={() => store.fetchInvestigations({name: store.investigationName})}/></SearchForm.Item>
      <SearchForm.Item span={5} title="调查状态"><Select allowClear style={{width: '100%'}} value={store.investigationStatus} options={Object.keys(STATUS_LABELS).map(value => ({value, label: STATUS_LABELS[value]}))} onChange={value => {store.investigationStatus = value; store.fetchInvestigations({status: value});}}/></SearchForm.Item>
      <SearchForm.Item span={24}><Button type="primary" icon={<SearchOutlined/>} onClick={() => store.fetchInvestigations({name: store.investigationName, status: store.investigationStatus})}>查询</Button></SearchForm.Item>
    </SearchForm>
    <TableCard tKey="interferenceInvestigations" title="规律调查" rowKey="id" loading={store.investigationsLoading} dataSource={store.investigations} onReload={store.fetchInvestigations} columns={columns} scroll={{x: 1000}} actions={[<AuthButton key="add" auth="interference.investigation.add|interference.interference.add" type="primary" icon={<PlusOutlined/>} onClick={() => store.showInvestigation({})}>新建调查</AuthButton>]} pagination={{current: store.investigationPage, pageSize: store.investigationPageSize, total: store.investigationTotal, showSizeChanger: true, onChange: (page, pageSize) => {store.investigationPage = page; store.investigationPageSize = pageSize; store.fetchInvestigations();}}}/>
    {store.investigationModalVisible && <InvestigationForm/>}
    <FinishInvestigationModal record={finishRecord} onClose={() => setFinishRecord(null)} onSaved={() => store.fetchInvestigations()}/>
    <CancelInvestigationModal record={cancelRecord} onClose={() => setCancelRecord(null)} onSaved={() => store.fetchInvestigations()}/>
  </AuthDiv>;
}

export default observer(InvestigationsPage);
