/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 系统详情 → 配置页签（2026-10）。
 * 一个页签、两个信息区域：当前配置 + 配置变更历史；"记录配置变更"只是
 * Modal 操作，变更详情是 Drawer——不新增任何一级菜单或独立页面。
 * 普通配置变更只留变更历史与审计；重要变更由后端在应用时写入系统履历。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Table, Tag, Empty, Button, Select, DatePicker, Divider} from 'antd';
import {AuthButton, AuthDiv} from 'components';
import store from './store';
import SystemConfigChangeModal from './SystemConfigChangeModal';
import SystemConfigChangeDetail from './SystemConfigChangeDetail';
import {
  PERM, PARAM_TYPE_TEXT, CONFIG_CHANGE_STATUS_OPTIONS, CONFIG_CHANGE_STATUS_TEXT,
  CONFIG_CHANGE_STATUS_COLOR, CONFIG_VERIFY_STATUS_TEXT, CONFIG_VERIFY_STATUS_COLOR,
} from '../constants';

const {RangePicker} = DatePicker;

@observer
class SystemConfigTab extends React.Component {
  state = {detailId: null};

  componentDidMount() {
    store.resetFilters();
    store.refreshAll(this.props.systemId);
  }

  componentWillUnmount() {
    // 页签切换即卸载：清空 store 中的数据，避免污染其他系统的展示
    store.configItems = [];
    store.changes = [];
    store.total = 0;
    store.page = 1;
  }

  fetchChanges = () => {
    store.page = 1;
    store.fetchChanges(this.props.systemId);
  };

  handlePageChange = (page) => {
    store.page = page;
    store.fetchChanges(this.props.systemId);
  };

  showDetail = (changeId) => {
    this.setState({detailId: changeId});
  };

  handleCloseDetail = () => {
    this.setState({detailId: null});
    store.refreshAll(this.props.systemId);
  };

  configColumns = [{
    title: '参数名称',
    dataIndex: 'param_name',
    width: 160,
    render: (text, record) => (
      <span>
        {record.is_required && <Tag color="orange" style={{marginRight: 4}}>必填</Tag>}
        {text}
      </span>
    ),
  }, {
    title: '参数编码',
    dataIndex: 'param_code',
    width: 140,
  }, {
    title: '当前值',
    dataIndex: 'display_value',
    width: 130,
    render: (text, record) => {
      if (text === '未设置') return <Tag>未设置</Tag>;
      if (record.data_type === 'bool') return record.value_bool === true ? '是' : '否';
      return text;
    },
  }, {
    title: '单位',
    dataIndex: 'unit',
    width: 70,
    render: text => text || '-',
  }, {
    title: '数据类型',
    dataIndex: 'data_type',
    width: 80,
    render: text => PARAM_TYPE_TEXT[text] || text,
  }, {
    title: '最后生效时间',
    dataIndex: 'effective_at',
    width: 140,
    render: text => text || '-',
  }, {
    title: '最后变更人',
    dataIndex: 'last_changed_by_name',
    width: 100,
    render: text => text || '-',
  }];

  changeColumns = [{
    title: '变更编号',
    dataIndex: 'change_no',
    width: 130,
  }, {
    title: '变更原因',
    dataIndex: 'reason',
    ellipsis: true,
  }, {
    title: '状态',
    dataIndex: 'status',
    width: 80,
    render: text => <Tag color={CONFIG_CHANGE_STATUS_COLOR[text]}>{CONFIG_CHANGE_STATUS_TEXT[text] || text}</Tag>,
  }, {
    title: '验证状态',
    dataIndex: 'verify_status',
    width: 90,
    render: (text) => (
      <Tag color={CONFIG_VERIFY_STATUS_COLOR[text || '']}>
        {CONFIG_VERIFY_STATUS_TEXT[text || ''] || '未验证'}
      </Tag>
    ),
  }, {
    title: '系统履历',
    dataIndex: 'include_in_history',
    width: 80,
    render: value => (value ? <Tag color="red">已纳入</Tag> : <Tag>未纳入</Tag>),
  }, {
    title: '操作人',
    dataIndex: 'created_by_name',
    width: 100,
  }, {
    title: '变更时间',
    dataIndex: 'created_at',
    width: 140,
  }, {
    title: '操作',
    width: 60,
    render: (text, record) => <a onClick={() => this.showDetail(record.id)}>详情</a>,
  }];

  render() {
    const paramOptions = store.configItems.map(item => (
      <Select.Option value={item.param} key={item.param}>
        {item.param_name}（{item.param_code}）
      </Select.Option>
    ));
    return (
      <AuthDiv auth={PERM.CONFIG_VIEW}>
        <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
          {/* Divider 自身内容宽度会撑满容器，必须允许收缩，否则把右侧按钮挤出可视区产生横向滚动 */}
          <Divider orientation="left" plain
            style={{fontSize: 13, margin: '0 0 8px', flex: 1, minWidth: 0}}>当前配置</Divider>
          <AuthButton auth={PERM.CONFIG_ADD} type="primary" size="small"
            style={{marginBottom: 8, flexShrink: 0}} onClick={() => store.showForm()}>
            记录配置变更
          </AuthButton>
        </div>
        <Table
          rowKey="param"
          size="small"
          loading={store.isConfigFetching}
          pagination={false}
          dataSource={store.configItems}
          columns={this.configColumns}
          locale={{emptyText: <Empty description="当前系统暂无适用的配置参数" image={Empty.PRESENTED_IMAGE_SIMPLE}/>}}
        />
        <Divider orientation="left" plain style={{fontSize: 13, marginTop: 16, marginBottom: 8}}>配置变更历史</Divider>
        <div style={{marginBottom: 10}}>
          <Select
            allowClear
            showSearch
            optionFilterProp="children"
            placeholder="按参数筛选"
            style={{width: 200, marginRight: 8}}
            value={store.f_param}
            onChange={v => {
              store.f_param = v;
              this.fetchChanges();
            }}
          >
            {paramOptions}
          </Select>
          <Select
            allowClear
            placeholder="状态"
            style={{width: 110, marginRight: 8}}
            value={store.f_status}
            onChange={v => {
              store.f_status = v;
              this.fetchChanges();
            }}
          >
            {CONFIG_CHANGE_STATUS_OPTIONS.map(item => (
              <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
            ))}
          </Select>
          <RangePicker
            showTime={{format: 'HH:mm'}}
            format="YYYY-MM-DD HH:mm"
            style={{width: 320, marginRight: 8}}
            value={store.f_created_range || null}
            onChange={v => {
              store.f_created_range = v;
            }}
            placeholder={['变更时间起', '变更时间止']}
          />
          <Button onClick={this.fetchChanges}>查询</Button>
        </div>
        <Table
          rowKey="id"
          size="small"
          loading={store.isChangesFetching}
          pagination={{
            current: store.page,
            pageSize: store.pageSize,
            total: store.total,
            showTotal: total => `共 ${total} 条`,
            onChange: this.handlePageChange,
          }}
          dataSource={store.changes}
          columns={this.changeColumns}
          locale={{emptyText: <Empty description="当前系统暂无配置变更记录" image={Empty.PRESENTED_IMAGE_SIMPLE}/>}}
        />
        <SystemConfigChangeModal systemId={this.props.systemId}/>
        {this.state.detailId && (
          <SystemConfigChangeDetail
            changeId={this.state.detailId}
            systemId={this.props.systemId}
            onClose={this.handleCloseDetail}
          />
        )}
      </AuthDiv>
    );
  }
}

export default SystemConfigTab;
