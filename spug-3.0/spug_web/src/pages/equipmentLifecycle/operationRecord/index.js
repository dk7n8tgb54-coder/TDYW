/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行与故障记录中心页（2026-10-11 合并改造）。
 * 合并原"故障处置"与"运行记录"两个菜单为统一入口"运行与故障记录"：
 * 一张统一主表承载 日常运行/异常事件/正式故障 三类记录。
 * 页签：全部记录 / 待办（跟进中）/ 统计（只读）。
 * 筛选：记录类型 / 状态（默认不含已撤销）/ 系统 / 异常类别 / 关键词 /
 * 发生时间范围。不混入维护台账、系统升级、配置变更记录（各自模块负责）。
 * 跨页跳转：?detail=<ID> 直达详情（系统档案页签、台账来源跳转入口）。
 */
import React, {useEffect} from 'react';
import {observer} from 'mobx-react';
import {Input, Select, Button, Tag, Table, DatePicker, Tabs} from 'antd';
import {PlusOutlined} from '@ant-design/icons';
import {SearchForm, AuthDiv, AuthButton, Breadcrumb, ExportButton} from 'components';
import RecordForm from './RecordForm';
import RecordDetail from './RecordDetail';
import RecordTodo from './RecordTodo';
import RecordStatistics from './RecordStatistics';
import store from './store';
import {
  PERM, RECORD_STATUS_OPTIONS, RECORD_STATUS_TEXT, RECORD_STATUS_COLOR,
  RECORD_CATEGORY_OPTIONS, RECORD_TYPE_OPTIONS,
  RECORD_TYPE_TEXT, RECORD_TYPE_COLOR,
  FAULT_IMPACT_TEXT, FAULT_IMPACT_COLOR, API_PREFIX,
} from '../constants';

const {RangePicker} = DatePicker;
const {TabPane} = Tabs;

// 状态标签（已撤销使用虚线灰样式，与进行态明显区分）
function StatusTag({status}) {
  if (status === 'cancelled') {
    return (
      <Tag
        color="default"
        style={{borderStyle: 'dashed', color: 'rgba(0, 0, 0, 0.45)'}}
      >
        {RECORD_STATUS_TEXT[status] || status}
      </Tag>
    );
  }
  return <Tag color={RECORD_STATUS_COLOR[status]}>{RECORD_STATUS_TEXT[status] || status}</Tag>;
}

@observer
class RecordTable extends React.Component {
  componentDidMount() {
    store.fetchSystems();
    store.fetchRecords();
  }

  columns = [{
    title: '编号',
    dataIndex: 'record_no',
    width: 150,
  }, {
    title: '记录类型',
    dataIndex: 'record_type',
    width: 90,
    render: text => (
      <Tag color={RECORD_TYPE_COLOR[text]}>{RECORD_TYPE_TEXT[text] || text}</Tag>
    ),
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
  }, {
    title: '状态',
    dataIndex: 'status',
    width: 90,
    render: (text) => <StatusTag status={text}/>,
  }, {
    title: '影响程度',
    dataIndex: 'impact_status',
    width: 110,
    render: (text, record) => (
      record.record_type === 'fault' ? (
        record.affects_system_operation ? (
          <Tag color={FAULT_IMPACT_COLOR[text]}>{FAULT_IMPACT_TEXT[text] || text}</Tag>
        ) : (
          // 部件故障/离线维修：不影响系统对外服务，独立于系统运行状态展示
          <Tag>不影响运行</Tag>
        )
      ) : '-'
    ),
  }, {
    title: '发生时间',
    dataIndex: 'occurred_at',
    width: 140,
  }, {
    title: '登记人',
    dataIndex: 'registrar_name',
    width: 100,
    render: (text) => text || '-',
  }, {
    // 统一进展数：后端列表聚合统计（progress_count，只读）；
    // 点击数量打开详情并定位到"统一进展"页签
    title: '进展数',
    dataIndex: 'progress_count',
    width: 80,
    render: (text, record) => (
      <a onClick={() => store.showDetail(record, 'progress')}>
        {record.progress_count ?? 0} 条
      </a>
    ),
  }, {
    title: '操作',
    width: 100,
    render: (text, record) => (
      <span>
        <AuthButton
          auth={PERM.OP_VIEW}
          type="link"
          size="small"
          style={{padding: 0}}
          onClick={() => store.showDetail(record)}
        >
          详情
        </AuthButton>
        {/* 日常运行恒可编辑；异常事件三状态可编辑；正式故障仅处置中可编辑
            （终态只读，后端同样拒绝；编辑按钮权限差异由详情页内收敛） */}
        {record.status !== 'closed' && record.status !== 'cancelled' && (
          <AuthButton
            auth={PERM.OP_EDIT}
            type="link"
            size="small"
            style={{padding: 0, marginLeft: 8}}
            onClick={() => store.showForm(record)}
          >
            编辑
          </AuthButton>
        )}
      </span>
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
        locale={{emptyText: '暂无记录'}}
      />
    );
  }
}

// 筛选区（读取 store 筛选字段，变更即重置页码并刷新）
function RecordFilters() {
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
            <SearchForm.Item span={4} title="记录类型">
              <Select
                allowClear
                style={{width: '100%'}}
                value={store.f_record_type}
                onChange={v => {store.f_record_type = v; store.page = 1; store.fetchRecords();}}
                placeholder="请选择"
              >
                {RECORD_TYPE_OPTIONS.map(item => (
                  <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
                ))}
              </Select>
            </SearchForm.Item>
            <SearchForm.Item span={4} title="状态">
              <Select
                allowClear
                style={{width: '100%'}}
                value={store.f_status}
                onChange={v => {store.f_status = v; store.page = 1; store.fetchRecords();}}
                placeholder="默认不含已撤销"
              >
                {RECORD_STATUS_OPTIONS.map(item => (
                  <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
                ))}
              </Select>
            </SearchForm.Item>
            <SearchForm.Item span={4} title="异常类别">
              <Select
                allowClear
                style={{width: '100%'}}
                value={store.f_category}
                onChange={v => {store.f_category = v; store.page = 1; store.fetchRecords();}}
                placeholder="请选择"
              >
                {RECORD_CATEGORY_OPTIONS.map(item => (
                  <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
                ))}
              </Select>
            </SearchForm.Item>
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

// 操作区：新增记录 + 导出
function ActionBar() {
  return (
    <div style={{marginBottom: 12}}>
      {/* 日常运行/异常事件用"新增记录"；直接登记正式故障须单独授权
          （add_fault），两种入口统一走同一表单按类型校验 */}
      <AuthButton
        auth={PERM.OP_ADD}
        type="primary"
        icon={<PlusOutlined/>}
        onClick={() => store.showForm()}
      >
        新增记录
      </AuthButton>
      <ExportButton
        auth={PERM.OP_EXPORT}
        style={{marginLeft: 8}}
        url={`${API_PREFIX}/records/export/`}
        filename="运行与故障记录.csv"
      >
        导出
      </ExportButton>
    </div>
  );
}

function RecordIndex(props) {
  useEffect(() => {
    // 跨页跳转直达详情（系统档案页签/台账详情跳入）
    const params = new URLSearchParams(props.location ? props.location.search : '');
    const detailId = params.get('detail');
    if (detailId && /^\d+$/.test(detailId)) {
      store.showDetail(parseInt(detailId, 10));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <AuthDiv auth={PERM.OP_VIEW}>
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>设备管理</Breadcrumb.Item>
        <Breadcrumb.Item>运行与故障记录</Breadcrumb.Item>
      </Breadcrumb>
      <Tabs defaultActiveKey="records">
        <TabPane tab="全部记录" key="records">
          <RecordFilters/>
          <ActionBar/>
          <RecordTable/>
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

export default observer(RecordIndex);
