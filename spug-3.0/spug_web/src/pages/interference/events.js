import React, {useEffect, useState} from 'react';
import {Button, DatePicker, Input, Modal, Radio, Select, message} from 'antd';
import {DeleteOutlined, EditOutlined, PlusOutlined, SearchOutlined} from '@ant-design/icons';
import {observer} from 'mobx-react';
import {http} from 'libs';
import {Action, AuthButton, AuthDiv, Breadcrumb, SearchForm, TableCard} from 'components';
import store from './store';
import EventForm from './EventForm';

const SCENE_LABELS = {ground: '地面', air: '空中', cross: '跨场景', unknown: '未知'};

function EventsPage() {
  const [selectedRowKeys, setSelectedRowKeys] = useState([]);
  const [range, setRange] = useState(null);
  const [joinVisible, setJoinVisible] = useState(false);
  const [joinInvestigationId, setJoinInvestigationId] = useState(undefined);
  const [joinLoading, setJoinLoading] = useState(false);
  const [investigationOptions, setInvestigationOptions] = useState([]);

  useEffect(() => { store.page = 1; store.fetchEvents(); }, []);

  function updateFilter(key, value) {
    store.eventFilters = {...store.eventFilters, [key]: value || undefined};
    store.page = 1;
    store.fetchEvents();
  }

  function reset() {
    store.eventFilters = {};
    setRange(null);
    store.page = 1;
    store.fetchEvents();
  }

  function remove(record) {
    Modal.confirm({
      title: '删除干扰事件',
      content: '删除后该事件将不再出现在列表和统计中，确定继续吗？',
      onOk: () => http.delete(`/api/interference/events/${record.id}/`).then(() => {
        message.success('删除成功');
        return store.fetchEvents();
      }).catch(() => {}),
    });
  }

  function createInvestigation() {
    store.showInvestigation({event_ids: selectedRowKeys});
  }

  function openJoinDialog() {
    setJoinInvestigationId(undefined);
    setJoinVisible(true);
    store.fetchInvestigations({page: 1, page_size: 100}).then(records => {
      setInvestigationOptions((records || []).map(item => ({
        value: item.id,
        label: `${item.name}（已关联 ${item.event_count || 0} 条）`,
      })));
    }).catch(() => {});
  }

  function closeJoinDialog() {
    if (joinLoading) return;
    setJoinVisible(false);
    setJoinInvestigationId(undefined);
  }

  function joinExistingInvestigation() {
    if (joinLoading || !joinInvestigationId || !selectedRowKeys.length) return;
    setJoinLoading(true);
    http.post(`/api/interference/investigations/${joinInvestigationId}/events/`, {
      event_ids: selectedRowKeys,
    }).then(() => {
      message.success('事件已加入调查');
      setSelectedRowKeys([]);
      closeJoinDialog();
      return store.fetchEvents();
    }).catch(() => {}).finally(() => setJoinLoading(false));
  }

  const columns = [
    {title: '发生时间', dataIndex: 'datetime', width: 170, render: value => value ? String(value).replace('T', ' ').slice(0, 19) : '-'},
    {title: '发生场景', dataIndex: 'scene_code', width: 90, render: value => SCENE_LABELS[value] || value},
    {title: '具体干扰类型', dataIndex: 'interference_kind_text', width: 120},
    {title: '受影响系统', dataIndex: 'affected_system_text', width: 110},
    {title: '疑似干扰源', dataIndex: 'source_type_text', width: 110},
    {title: '航班号', dataIndex: 'flight_number', width: 100},
    {title: '机号', dataIndex: 'aircraft_no', width: 100},
    {title: '现象摘要', dataIndex: 'phenomenon', ellipsis: true},
    {title: '调查状态', dataIndex: 'investigation_status', width: 100, render: value => value || '未加入'},
    {title: '操作', width: 150, fixed: 'right', render: record => <Action>
      <Action.Button auth="interference.interference.view" onClick={() => store.showEvent({...record, isViewMode: true})}>查看</Action.Button>
      <Action.Button auth="interference.interference.edit" icon={<EditOutlined/>} onClick={() => store.showEvent(record)}>编辑</Action.Button>
      <Action.Button danger auth="interference.interference.del" icon={<DeleteOutlined/>} onClick={() => remove(record)}>删除</Action.Button>
    </Action>},
  ];

  return <AuthDiv auth="interference.interference.view">
    <Breadcrumb><Breadcrumb.Item>首页</Breadcrumb.Item><Breadcrumb.Item>干扰管理</Breadcrumb.Item><Breadcrumb.Item>干扰记录</Breadcrumb.Item></Breadcrumb>
    <SearchForm>
      <SearchForm.Item span={5} title="场景"><Radio.Group value={store.eventFilters.scene_code || ''} onChange={event => updateFilter('scene_code', event.target.value || undefined)} optionType="button" buttonStyle="solid"><Radio.Button value="">全部</Radio.Button><Radio.Button value="ground">地面</Radio.Button><Radio.Button value="air">空中</Radio.Button><Radio.Button value="cross">跨场景</Radio.Button><Radio.Button value="unknown">未知</Radio.Button></Radio.Group></SearchForm.Item>
      <SearchForm.Item span={4} title="分类"><Select allowClear value={store.eventFilters.classification_status} onChange={value => updateFilter('classification_status', value)} options={[{value: 'pending', label: '待分类'}, {value: 'confirmed', label: '已确认'}]} style={{width: '100%'}}/></SearchForm.Item>
      <SearchForm.Item span={4} title="航班号"><Input allowClear value={store.eventFilters.flight_number} onChange={event => store.eventFilters = {...store.eventFilters, flight_number: event.target.value}} onPressEnter={() => store.fetchEvents()} /></SearchForm.Item>
      <SearchForm.Item span={4} title="机号"><Input allowClear value={store.eventFilters.aircraft_no} onChange={event => store.eventFilters = {...store.eventFilters, aircraft_no: event.target.value}} onPressEnter={() => store.fetchEvents()} /></SearchForm.Item>
      <SearchForm.Item span={7} title="发生时间"><DatePicker.RangePicker allowClear value={range} onChange={dates => {setRange(dates); updateFilter('datetime_start', dates && dates[0] ? dates[0].format('YYYY-MM-DD') : undefined); if (dates && dates[1]) updateFilter('datetime_end', dates[1].format('YYYY-MM-DD'));}} style={{width: '100%'}}/></SearchForm.Item>
      <SearchForm.Item span={24}><Button type="primary" icon={<SearchOutlined/>} onClick={() => {store.page = 1; store.fetchEvents();}}>查询</Button><Button style={{marginLeft: 8}} onClick={reset}>重置</Button></SearchForm.Item>
    </SearchForm>
    <TableCard
      tKey="interferenceEvents"
      title="干扰记录"
      rowKey="id"
      loading={store.eventsLoading}
      dataSource={store.events}
      onReload={store.fetchEvents}
      columns={columns}
      rowSelection={{selectedRowKeys, onChange: setSelectedRowKeys}}
      actions={[
        <AuthButton key="add" auth="interference.interference.add" type="primary" icon={<PlusOutlined/>} onClick={() => store.showEvent({})}>新建事件</AuthButton>,
        <AuthButton key="investigation" auth="interference.investigation.add" disabled={!selectedRowKeys.length} onClick={createInvestigation}>创建调查</AuthButton>,
        <AuthButton key="join-investigation" auth="interference.investigation.edit" disabled={!selectedRowKeys.length} onClick={openJoinDialog}>加入已有调查</AuthButton>,
      ]}
      pagination={{current: store.page, pageSize: store.pageSize, total: store.total, showSizeChanger: true, onChange: (page, pageSize) => {store.page = page; store.pageSize = pageSize; store.fetchEvents();}}}
      scroll={{x: 1250}}
      onRow={record => ({onDoubleClick: () => store.showEvent(record)})}
    />
    {store.eventModalVisible && <EventForm/>}
    <Modal
      visible={joinVisible}
      title="加入已有调查"
      onCancel={closeJoinDialog}
      maskClosable={false}
      destroyOnClose
      confirmLoading={joinLoading}
      onOk={joinExistingInvestigation}
    >
      <Select
        showSearch
        allowClear
        optionFilterProp="label"
        placeholder="请选择调查"
        value={joinInvestigationId}
        options={investigationOptions}
        onChange={setJoinInvestigationId}
        style={{width: '100%'}}
      />
    </Modal>
  </AuthDiv>;
}

export default observer(EventsPage);
