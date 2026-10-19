/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 系统详情 → 配置页签（2026-10-19 起只读）。
 * 展示三个信息区域：建档信息 + 当前配置（按 硬件规格/运行参数 分类）+
 * 配置变更历史；变更详情为只读 Drawer（隐藏写操作）。
 * 全部写操作（初始建档/维护参数定义/记录与处理配置变更）集中在
 * 「设备管理 → 系统配置」维护入口，本页签右上角提供跳转链接。
 * 普通配置变更只留变更历史与审计（系统履历已随 2026-10-11 合并改造退役）。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Link} from 'react-router-dom';
import {Table, Tag, Empty, Button, Select, DatePicker, Divider} from 'antd';
import {AuthDiv} from 'components';
import store from './store';
import {buildConfigColumns, buildChangeColumns, renderCategoryTag} from './shared';
import SystemConfigChangeDetail from './SystemConfigChangeDetail';
import {PERM, PARAM_CATEGORY_HARDWARE, PARAM_CATEGORY_RUNTIME, CONFIG_CHANGE_STATUS_OPTIONS} from '../constants';

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
    store.clearView();
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

  // 按"分类展示"拆分：硬件规格（系统级静态规格）在前，其余归运行参数
  get hardwareItems() {
    return store.configItems.filter(item => item.category === PARAM_CATEGORY_HARDWARE);
  }

  get runtimeItems() {
    return store.configItems.filter(item => item.category !== PARAM_CATEGORY_HARDWARE);
  }

  configColumns = buildConfigColumns({showSource: true});

  changeColumns = buildChangeColumns(changeId => this.showDetail(changeId));

  renderConfigTable(items) {
    return (
      <Table
        rowKey="param"
        size="small"
        loading={store.isConfigFetching}
        pagination={false}
        dataSource={items}
        columns={this.configColumns}
        locale={{emptyText: <Empty description="暂无该分类下的配置参数" image={Empty.PRESENTED_IMAGE_SIMPLE}/>}}
      />
    );
  }

  renderBaselineLine() {
    const baseline = store.configBaseline;
    if (!baseline) return <Tag>未建档</Tag>;
    return (
      <span style={{fontSize: 12, color: '#888'}}>
        初始建档：{baseline.source}
        （{baseline.established_by_name} · {baseline.established_at}）
      </span>
    );
  }

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
          <div style={{flexShrink: 0, marginBottom: 8, marginLeft: 8}}>
            {this.renderBaselineLine()}
            <Link to={`/el/system-config?system=${this.props.systemId}`}>
              <Button size="small" type="primary" ghost style={{marginLeft: 8}}>
                前往系统配置维护
              </Button>
            </Link>
          </div>
        </div>
        <Divider orientation="left" plain style={{fontSize: 12, margin: '4px 0 6px'}}>
          {renderCategoryTag(PARAM_CATEGORY_HARDWARE)}（引用系统档案视角，实测值记录在运行处置记录）
        </Divider>
        {this.renderConfigTable(this.hardwareItems)}
        <Divider orientation="left" plain style={{fontSize: 12, margin: '12px 0 6px'}}>
          {renderCategoryTag(PARAM_CATEGORY_RUNTIME)}（可调整的设定值）
        </Divider>
        {this.renderConfigTable(this.runtimeItems)}
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
        {this.state.detailId && (
          <SystemConfigChangeDetail
            changeId={this.state.detailId}
            systemId={this.props.systemId}
            readOnly
            onClose={this.handleCloseDetail}
          />
        )}
      </AuthDiv>
    );
  }
}

export default SystemConfigTab;
