/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行记录中心页（2026-10 第一版 + 第二版）。
 * 异常与运行情况的统一录入入口：用户反馈、值班发现、短暂中断或恢复、
 * 已处理的小问题、需要后续跟进的运行情况。
 * 页签：全部记录 / 待办（跟进中）/ 统计（只读）。
 * 不混入巡视与维护、系统升级、配置变更记录（各自模块负责）；
 * 支持按系统/状态/需要跟进/重要程度/影响程度/异常类别/重复发生/时间范围筛选。
 */
import React, { useEffect } from 'react';
import { observer } from 'mobx-react';
import { Input, Select, Button, Tag, Table, DatePicker, Tabs } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { SearchForm, AuthDiv, AuthButton, Breadcrumb } from 'components';
import RecordForm from './RecordForm';
import RecordDetail from './RecordDetail';
import RecordTodo from './RecordTodo';
import RecordStatistics from './RecordStatistics';
import store from './store';
import {
  PERM, RUNTIME_STATUS_OPTIONS, RUNTIME_STATUS_TEXT, RUNTIME_STATUS_COLOR,
  RUNTIME_IMPORTANCE_OPTIONS, RUNTIME_CATEGORY_OPTIONS,
  FAULT_IMPACT_OPTIONS, RUNTIME_IMPACT_TEXT, RUNTIME_IMPACT_COLOR,
} from '../constants';

const { RangePicker } = DatePicker;
const { TabPane } = Tabs;

// 异常类别 / 重复发生筛选（第二版新增，独立小组件避免筛选区过长）
function CategoryAndRepeatedFilters() {
  return (
    <>
      <SearchForm.Item span={4} title="异常类别">
        <Select
          allowClear
          style={{width: '100%'}}
          value={store.f_category}
          onChange={v => {store.f_category = v; store.page = 1; store.fetchRecords();}}
          placeholder="请选择"
        >
          {RUNTIME_CATEGORY_OPTIONS.map(item => (
            <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
          ))}
        </Select>
      </SearchForm.Item>
      <SearchForm.Item span={4} title="重复发生">
        <Select
          allowClear
          style={{width: '100%'}}
          value={store.f_repeated}
          onChange={v => {store.f_repeated = v; store.page = 1; store.fetchRecords();}}
          placeholder="请选择"
        >
          <Select.Option value={true}>重复发生</Select.Option>
          <Select.Option value={false}>非重复</Select.Option>
        </Select>
      </SearchForm.Item>
    </>
  );
}

// 搜索筛选区（读取 store 筛选字段，变更即重置页码并刷新）
function RuntimeRecordFilters() {
  return (
    <SearchForm>
      <SearchForm.Item span={6} title="关键词">
        <Input
          allowClear
          value={store.f_keyword}
          onChange={e => store.f_keyword = e.target.value}
          placeholder="编号/标题/描述/系统名称"
          onPressEnter={() => {store.page = 1; store.fetchRecords();}}
        />
      </SearchForm.Item>
      <SearchForm.Item span={6} title="所属系统">
        <Select
          allowClear
          showSearch
          optionFilterProp="children"
          style={{width: '100%'}}
          value={store.f_system}
          onChange={v => {store.f_system = v; store.page = 1; store.fetchRecords();}}
          placeholder="请选择系统"
        >
          {store.systems.map(s => (
            <Select.Option value={s.id} key={s.id}>
              {s.name}
            </Select.Option>
          ))}
        </Select>
      </SearchForm.Item>
      <SearchForm.Item span={4} title="状态">
        <Select
          allowClear
          style={{width: '100%'}}
          value={store.f_status}
          onChange={v => {store.f_status = v; store.page = 1; store.fetchRecords();}}
          placeholder="请选择状态"
        >
          {RUNTIME_STATUS_OPTIONS.map(item => (
            <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
          ))}
        </Select>
      </SearchForm.Item>
      <SearchForm.Item span={4} title="需要跟进">
        <Select
          allowClear
          style={{width: '100%'}}
          value={store.f_follow}
          onChange={v => {store.f_follow = v; store.page = 1; store.fetchRecords();}}
          placeholder="请选择"
        >
          <Select.Option value={true}>需要跟进</Select.Option>
          <Select.Option value={false}>不需要</Select.Option>
        </Select>
      </SearchForm.Item>
      <SearchForm.Item span={4} title="重要程度">
        <Select
          allowClear
          style={{width: '100%'}}
          value={store.f_importance}
          onChange={v => {store.f_importance = v; store.page = 1; store.fetchRecords();}}
          placeholder="请选择"
        >
          {RUNTIME_IMPORTANCE_OPTIONS.map(item => (
            <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
          ))}
        </Select>
      </SearchForm.Item>
      <SearchForm.Item span={4} title="影响程度">
        <Select
          allowClear
          style={{width: '100%'}}
          value={store.f_impact}
          onChange={v => {store.f_impact = v; store.page = 1; store.fetchRecords();}}
          placeholder="请选择"
        >
          {FAULT_IMPACT_OPTIONS.map(item => (
            <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
          ))}
        </Select>
      </SearchForm.Item>
      <CategoryAndRepeatedFilters/>
      <SearchForm.Item span={6} title="发生时间">
        <RangePicker
          showTime={{format: 'HH:mm'}}
          format="YYYY-MM-DD HH:mm"
          style={{width: '100%'}}
          value={store.f_occurred_range}
          onChange={v => {store.f_occurred_range = v; store.page = 1; store.fetchRecords();}}
          placeholder={['发生时间起', '发生时间止']}
        />
      </SearchForm.Item>
      <SearchForm.Item span={4}>
        <Button type="primary" onClick={() => {store.page = 1; store.fetchRecords();}}>查询</Button>
        <Button style={{marginLeft: 8}} onClick={() => {store.resetFilter(); store.fetchRecords();}}>
          重置
        </Button>
      </SearchForm.Item>
    </SearchForm>
  );
}

@observer
class RuntimeRecordTable extends React.Component {
  componentDidMount() {
    store.fetchSystems();
    store.fetchRecords();
  }

  columns = [{
    title: '编号',
    dataIndex: 'record_no',
    width: 150,
  }, {
    title: '所属系统',
    dataIndex: 'system_name',
    width: 170,
    ellipsis: true,
  }, {
    title: '标题',
    dataIndex: 'title',
    width: 200,
    ellipsis: true,
    render: (text, record) => (
      <span>
        {record.importance === 'important' && (
          <Tag color="red" style={{marginRight: 4}}>重要</Tag>
        )}
        {record.is_repeated && (
          <Tag color="volcano" style={{marginRight: 4}}>重复</Tag>
        )}
        {text}
      </span>
    ),
  }, {
    title: '异常类别',
    dataIndex: 'category_text',
    width: 100,
    render: text => text || <Tag>未归类</Tag>,
  }, {
    title: '影响状态',
    dataIndex: 'impact_status',
    width: 100,
    render: (text, record) => (
      record.affects_system_operation ? (
        <Tag color={RUNTIME_IMPACT_COLOR[text]}>{RUNTIME_IMPACT_TEXT[text] || text}</Tag>
      ) : (
        <Tag>不影响运行</Tag>
      )
    ),
  }, {
    title: '状态',
    dataIndex: 'status',
    width: 90,
    render: (text) => (
      <Tag color={RUNTIME_STATUS_COLOR[text]}>{RUNTIME_STATUS_TEXT[text] || text}</Tag>
    ),
  }, {
    title: '关联',
    dataIndex: 'duplicate_count',
    width: 70,
    render: (text) => (text ? <Tag color="volcano">{text}</Tag> : '-'),
  }, {
    title: '发生时间',
    dataIndex: 'occurred_at',
    width: 140,
  }, {
    title: '操作',
    width: 80,
    render: (text, record) => (
      <AuthButton
        auth={PERM.RUNTIME_VIEW}
        type="link"
        size="small"
        style={{padding: 0}}
        onClick={() => store.showDetail(record)}
      >
        详情
      </AuthButton>
    ),
  }];

  render() {
    return (
      <Table
        rowKey="id"
        loading={store.isFetching}
        pagination={{
          current: store.page,
          pageSize: store.pageSize,
          total: store.total,
          showSizeChanger: true,
          onChange: (page, pageSize) => {
            store.page = page;
            store.pageSize = pageSize;
            store.fetchRecords();
          },
          showTotal: total => `共 ${total} 条`,
        }}
        dataSource={store.records}
        columns={this.columns}
        locale={{emptyText: '暂无运行记录'}}
      />
    );
  }
}

function RuntimeRecordIndex() {
  useEffect(() => {
    // 跨页跳转直达详情（系统详情页签等入口）
    const params = new URLSearchParams(window.location.search);
    const detailId = params.get('detail');
    if (detailId && /^\d+$/.test(detailId)) {
      store.showDetail(parseInt(detailId, 10));
    }
  }, []);
  return (
    <AuthDiv auth={PERM.RUNTIME_VIEW}>
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>设备全生命周期管理</Breadcrumb.Item>
        <Breadcrumb.Item>运行处置</Breadcrumb.Item>
        <Breadcrumb.Item>运行记录</Breadcrumb.Item>
      </Breadcrumb>
      <Tabs defaultActiveKey="records">
        <TabPane tab="全部记录" key="records">
          <RuntimeRecordFilters/>
          <div style={{marginBottom: 12}}>
            <AuthButton
              auth={PERM.RUNTIME_ADD}
              type="primary"
              icon={<PlusOutlined/>}
              onClick={() => store.showForm()}
            >
              新增运行记录
            </AuthButton>
          </div>
          <RuntimeRecordTable/>
        </TabPane>
        <TabPane tab="待办（跟进中）" key="todo">
          <RecordTodo/>
        </TabPane>
        <TabPane tab="统计" key="statistics">
          <RecordStatistics/>
        </TabPane>
      </Tabs>
      {store.formVisible && <RecordForm/>}
      {store.detailVisible && <RecordDetail/>}
    </AuthDiv>
  );
}

export default observer(RuntimeRecordIndex);
