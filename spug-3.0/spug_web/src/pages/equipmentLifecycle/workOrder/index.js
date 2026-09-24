/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行维护/工单管理列表页（步骤 3.3）。
 * 业务关联一律使用系统 ID，页面仅展示系统名称；
 * 支持 /el/work-orders?detail=<id> 跨页跳转直达详情。
 */
import React, { useEffect } from 'react';
import { observer } from 'mobx-react';
import { Input, Select, Button, Tag, Table } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { SearchForm, AuthDiv, AuthButton, Breadcrumb, ExportButton } from 'components';
import ComForm from './WorkOrderForm';
import WorkOrderDetail from './WorkOrderDetail';
import store from './store';
import {
  WO_PERM, WORK_TYPE_OPTIONS, WORK_TYPE_TEXT, WO_STATUS_OPTIONS, WO_STATUS_TEXT,
  WO_STATUS_COLOR, PRIORITY_OPTIONS, PRIORITY_TEXT, PRIORITY_COLOR, WO_SOURCE_TEXT,
} from './constants';

@observer
class WorkOrderTable extends React.Component {
  componentDidMount() {
    store.fetchRecords();
  }

  columns = [{
    title: '工单编号',
    dataIndex: 'work_no',
    width: 150,
  }, {
    title: '标题',
    dataIndex: 'title',
    width: 200,
    ellipsis: true,
  }, {
    title: '类型',
    dataIndex: 'work_type',
    width: 90,
    render: (text) => WORK_TYPE_TEXT[text] || text,
  }, {
    title: '优先级',
    dataIndex: 'priority',
    width: 70,
    render: (text) => <Tag color={PRIORITY_COLOR[text]}>{PRIORITY_TEXT[text] || text}</Tag>,
  }, {
    title: '状态',
    dataIndex: 'status',
    width: 90,
    render: (text) => (
      <Tag color={WO_STATUS_COLOR[text]}>{WO_STATUS_TEXT[text] || text}</Tag>
    ),
  }, {
    title: '作业系统',
    dataIndex: 'system_name',
    width: 180,
    ellipsis: true,
  }, {
    title: '来源',
    dataIndex: 'source_type',
    width: 140,
    ellipsis: true,
    render: (text, record) => (
      <span>
        <span>{WO_SOURCE_TEXT[text] || text}</span>
        {record.source_no && <span style={{color: '#999', marginLeft: 6}}>{record.source_no}</span>}
      </span>
    ),
  }, {
    title: '负责人',
    dataIndex: 'owner_name',
    width: 90,
    render: (text) => text || '-',
  }, {
    title: '计划开始',
    dataIndex: 'planned_start',
    width: 130,
    render: (text) => text || '-',
  }, {
    title: '操作',
    width: 100,
    render: (text, record) => (
      <span>
        <AuthButton
          auth={WO_PERM.VIEW}
          type="link"
          size="small"
          style={{padding: 0}}
          onClick={() => store.showDetail(record)}
        >
          详情
        </AuthButton>
        {record.status === 'pending_dispatch' && (
          <AuthButton
            auth={WO_PERM.EDIT}
            type="link"
            size="small"
            style={{padding: 0, marginLeft: 8}}
            onClick={() => this.editOrder(record)}
          >
            编辑
          </AuthButton>
        )}
      </span>
    ),
  }];

  editOrder = (record) => {
    // 编辑回填需要详情数据（作业系统、影响运行标记），先取真实详情再打开表单
    store.fetchDetail(record.id).then(() => {
      store.showForm(store.detail);
    });
  };

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
        locale={{emptyText: '暂无工单'}}
      />
    );
  }
}

function WorkOrderIndex(props) {
  useEffect(() => {
    // 跨页跳转直达详情（故障详情/台账详情/系统详情跳入）
    const params = new URLSearchParams(props.location ? props.location.search : '');
    const detailId = params.get('detail');
    if (detailId && /^\d+$/.test(detailId)) {
      store.showDetail(parseInt(detailId, 10));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <AuthDiv auth={WO_PERM.VIEW}>
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>设备全生命周期管理</Breadcrumb.Item>
        <Breadcrumb.Item>运行维护</Breadcrumb.Item>
        <Breadcrumb.Item>工单管理</Breadcrumb.Item>
      </Breadcrumb>
      <SearchForm>
        <SearchForm.Item span={6} title="编号/标题/系统">
          <Input
            allowClear
            value={store.f_keyword}
            onChange={e => store.f_keyword = e.target.value}
            placeholder="请输入工单编号、标题或系统名称"
            onPressEnter={() => {store.page = 1; store.fetchRecords();}}
          />
        </SearchForm.Item>
        <SearchForm.Item span={4} title="状态">
          <Select
            allowClear
            style={{width: '100%'}}
            value={store.f_status}
            onChange={v => {store.f_status = v; store.page = 1; store.fetchRecords();}}
            placeholder="请选择状态"
          >
            {WO_STATUS_OPTIONS.map(item => (
              <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={4} title="类型">
          <Select
            allowClear
            style={{width: '100%'}}
            value={store.f_work_type}
            onChange={v => {store.f_work_type = v; store.page = 1; store.fetchRecords();}}
            placeholder="请选择类型"
          >
            {WORK_TYPE_OPTIONS.map(item => (
              <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={4} title="优先级">
          <Select
            allowClear
            style={{width: '100%'}}
            value={store.f_priority}
            onChange={v => {store.f_priority = v; store.page = 1; store.fetchRecords();}}
            placeholder="请选择优先级"
          >
            {PRIORITY_OPTIONS.map(item => (
              <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={3} title="来源">
          <Select
            allowClear
            style={{width: '100%'}}
            value={store.f_source_type}
            onChange={v => {store.f_source_type = v; store.page = 1; store.fetchRecords();}}
            placeholder="来源"
          >
            {Object.entries(WO_SOURCE_TEXT).map(([value, label]) => (
              <Select.Option value={value} key={value}>{label}</Select.Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={3}>
          <Button type="primary" onClick={() => {store.page = 1; store.fetchRecords();}}>查询</Button>
          <Button style={{marginLeft: 8}} onClick={() => {store.resetFilter(); store.fetchRecords();}}>
            重置
          </Button>
        </SearchForm.Item>
      </SearchForm>
      <div style={{marginBottom: 12}}>
        <AuthButton
          auth={WO_PERM.ADD}
          type="primary"
          icon={<PlusOutlined/>}
          onClick={() => store.showForm()}
        >
          新增工单
        </AuthButton>
        <ExportButton
          auth={WO_PERM.EXPORT}
          style={{marginLeft: 8}}
          url="/api/equipment-lifecycle/work-orders/export/"
          filename="工单列表.csv"
        >
          导出
        </ExportButton>
      </div>
      <WorkOrderTable/>
      {store.formVisible && (
        <ComForm
          visible={store.formVisible}
          onClose={() => {store.formVisible = false}}
          isEdit={!!store.record.id}
        />
      )}
      {store.detailVisible && (
        <WorkOrderDetail
          woId={store.detailId}
          visible={store.detailVisible}
          onClose={() => store.closeDetail()}
        />
      )}
    </AuthDiv>
  );
}

export default observer(WorkOrderIndex);
