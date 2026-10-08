/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行处置/故障处置列表页（步骤 3.1）。
 * 业务关联一律使用系统 ID，页面仅展示系统名称。
 * 撤销登记改版（2026-10-03）：默认列表只含有效故障（处置中/已关闭），
 * 后端默认排除已撤销记录；通过"状态"筛选显式选择"已撤销"时才查询
 * 已撤销记录（后端独立排除，前端不自行过滤）；已撤销状态使用虚线灰
 * 标签（FaultStatusTag），明显区别于处置中/已关闭。
 */
import React, { useEffect } from 'react';
import { observer } from 'mobx-react';
import { Input, Select, Button, Tag, Table, DatePicker } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { SearchForm, AuthDiv, AuthButton, Breadcrumb, ExportButton } from 'components';
import ComForm from './FaultForm';
import FaultDetail from './FaultDetail';
import FaultStatusTag from './FaultStatusTag';
import store from './faultStore';
import {
  API_PREFIX, PERM, FAULT_STATUS_OPTIONS,
  FAULT_IMPACT_TEXT, FAULT_IMPACT_COLOR,
} from './constants';

const { RangePicker } = DatePicker;

@observer
class FaultTable extends React.Component {
  componentDidMount() {
    store.fetchSystems();
    store.fetchRecords();
  }

  columns = [{
    title: '故障编号',
    dataIndex: 'fault_no',
    width: 160,
  }, {
    title: '故障系统',
    dataIndex: 'system_name',
    width: 200,
    ellipsis: true,
  }, {
    title: '系统影响程度',
    dataIndex: 'impact_status',
    width: 130,
    render: (text, record) => (
      record.affects_system_operation ? (
        <Tag color={FAULT_IMPACT_COLOR[text]}>{FAULT_IMPACT_TEXT[text] || text}</Tag>
      ) : (
        // 部件故障/离线维修：不影响系统对外服务，独立于系统运行状态展示
        <Tag>不影响运行</Tag>
      )
    ),
  }, {
    title: '处置状态',
    dataIndex: 'status',
    width: 90,
    render: (text) => <FaultStatusTag status={text}/>,
  }, {
    title: '发生时间',
    dataIndex: 'occurred_at',
    width: 140,
  }, {
    title: '故障现象',
    dataIndex: 'phenomenon',
    ellipsis: true,
  }, {
    title: '故障登记人',
    dataIndex: 'registrar_name',
    width: 100,
    render: (text) => text || '-',
  }, {
    // 处置记录数：后端列表聚合统计（handling_record_count，只读，不提供
    // 可编辑的"节点数"字段）；已关闭/已撤销故障同样保留历史数量。
    // 点击数量打开故障详情并定位到"处置记录"页签
    title: '处置记录数',
    dataIndex: 'handling_record_count',
    width: 100,
    render: (text, record) => (
      <a onClick={() => store.showDetail(record, 'handling')}>
        {record.handling_record_count ?? 0} 条
      </a>
    ),
  }, {
    title: '操作',
    width: 100,
    render: (text, record) => (
      <span>
        <AuthButton
          auth={PERM.FAULT_VIEW}
          type="link"
          size="small"
          style={{padding: 0}}
          onClick={() => store.showDetail(record)}
        >
          详情
        </AuthButton>
        {/* 处置中是唯一可编辑状态（已关闭/已撤销均只读，后端同样拒绝） */}
        {record.status === 'handling' && (
          <AuthButton
            auth={PERM.FAULT_EDIT}
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
        locale={{emptyText: '暂无故障记录'}}
      />
    );
  }
}

function FaultIndex(props) {
  useEffect(() => {
    // 跨页跳转直达详情（台账详情跳入）
    const params = new URLSearchParams(props.location ? props.location.search : '');
    const detailId = params.get('detail');
    if (detailId && /^\d+$/.test(detailId)) {
      store.showDetail(parseInt(detailId, 10));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <AuthDiv auth={PERM.FAULT_VIEW}>
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>设备运行维护管理</Breadcrumb.Item>
        <Breadcrumb.Item>运行处置</Breadcrumb.Item>
        <Breadcrumb.Item>故障处置</Breadcrumb.Item>
      </Breadcrumb>
      <SearchForm>
        <SearchForm.Item span={6} title="故障编号/现象">
          <Input
            allowClear
            value={store.f_keyword}
            onChange={e => store.f_keyword = e.target.value}
            placeholder="请输入故障编号或现象关键词"
            onPressEnter={() => {store.page = 1; store.fetchRecords();}}
          />
        </SearchForm.Item>
        <SearchForm.Item span={6} title="故障系统">
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
            placeholder="默认不含已撤销"
          >
            {FAULT_STATUS_OPTIONS.map(item => (
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
      <div style={{marginBottom: 12}}>
        <AuthButton
          auth={PERM.FAULT_ADD}
          type="primary"
          icon={<PlusOutlined/>}
          onClick={() => store.showForm()}
        >
          新增故障
        </AuthButton>
        <ExportButton
          auth={PERM.FAULT_EXPORT}
          style={{marginLeft: 8}}
          url={`${API_PREFIX}/faults/export/`}
          filename="故障列表.csv"
        >
          导出
        </ExportButton>
      </div>
      <FaultTable/>
      {store.formVisible && <ComForm/>}
      {store.detailVisible && <FaultDetail/>}
    </AuthDiv>
  );
}

export default observer(FaultIndex);
