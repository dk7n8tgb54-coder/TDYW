/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备管理 → 系统配置（独立维护入口，2026-10-19）。
 * 一个页面承载全部配置写操作：选择系统 → 引用系统档案信息（只读）→
 * 初始建档 → 参数定义维护 → 当前配置（按 硬件规格/运行参数 分类）→
 * 记录与处理配置变更（复用 systemConfig 的 Modal/Drawer）。
 * 「系统详情 → 配置」页签自本入口上线起改为只读展示并跳转到这里。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Select, Table, Tag, Empty, Button, Divider, Descriptions, Alert, Spin} from 'antd';
import {PlusOutlined} from '@ant-design/icons';
import {AuthButton, AuthDiv} from 'components';
import maintainStore from './store';
import SystemConfigBaselineModal from './SystemConfigBaselineModal';
import SystemConfigParamModal from './SystemConfigParamModal';
import sharedStore from '../systemConfig/store';
import SystemConfigChangeModal from '../systemConfig/SystemConfigChangeModal';
import SystemConfigChangeDetail from '../systemConfig/SystemConfigChangeDetail';
import {buildConfigColumns, buildChangeColumns, renderCategoryTag} from '../systemConfig/shared';
import {PERM, PARAM_CATEGORY_HARDWARE, PARAM_CATEGORY_RUNTIME, CONFIG_CHANGE_STATUS_OPTIONS} from '../constants';

const {Option} = Select;

@observer
class SystemConfigMaintain extends React.Component {
  state = {detailId: null};

  componentDidMount() {
    maintainStore.fetchSystemOptions();
    maintainStore.fetchParams();
    // 支持 ?system=<id> 直达（系统档案配置页签"前往维护"跳转携带）
    const preselect = new URLSearchParams(this.props.location?.search || '').get('system');
    if (preselect && /^\d+$/.test(preselect)) {
      maintainStore.selectSystem(Number(preselect));
    }
  }

  componentWillUnmount() {
    // 卸载清空全部视图数据（含共享的当前配置/变更），避免污染其他系统展示
    maintainStore.reset();
  }

  fetchChanges = () => {
    sharedStore.page = 1;
    sharedStore.fetchChanges(maintainStore.systemId);
  };

  handlePageChange = (page) => {
    sharedStore.page = page;
    sharedStore.fetchChanges(maintainStore.systemId);
  };

  showDetail = (changeId) => {
    this.setState({detailId: changeId});
  };

  handleCloseDetail = () => {
    this.setState({detailId: null});
    sharedStore.refreshAll(maintainStore.systemId);
  };

  configColumns = buildConfigColumns({showSource: true});

  changeColumns = buildChangeColumns(changeId => this.showDetail(changeId));

  paramColumns = [
    {title: '参数编码', dataIndex: 'param_code', width: 150},
    {title: '参数名称', dataIndex: 'param_name', width: 160},
    {title: '分类', dataIndex: 'category', width: 90,
      render: text => renderCategoryTag(text)},
    {title: '数据类型', dataIndex: 'data_type_text', width: 80},
    {title: '单位', dataIndex: 'unit', width: 70, render: text => text || '-'},
    {title: '适用范围', dataIndex: 'scope_type_text', width: 90},
    {title: '必填', dataIndex: 'is_required', width: 60,
      render: text => (text ? <Tag color="orange">必填</Tag> : '-')},
    {title: '状态', dataIndex: 'is_enabled', width: 70,
      render: text => (text ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>)},
    {title: '备注', dataIndex: 'remark', ellipsis: true, render: text => text || '-'},
    {title: '操作', width: 60,
      render: (text, record) => (
        <AuthButton auth={PERM.CONFIG_TEMPLATE} type="link"
          onClick={() => maintainStore.showParamForm(record)}>编辑</AuthButton>
      )},
  ];

  renderSystemSelector() {
    return (
      <div style={{display: 'flex', alignItems: 'center', marginBottom: 12}}>
        <span style={{marginRight: 8, flexShrink: 0}}>选择系统：</span>
        <Select
          showSearch
          allowClear
          optionFilterProp="children"
          style={{width: 360}}
          placeholder="按系统名称/编号搜索"
          value={maintainStore.systemId}
          loading={maintainStore.isOptionsFetching}
          onChange={v => maintainStore.selectSystem(v)}
        >
          {maintainStore.systemOptions.map(system => (
            <Option value={system.id} key={system.id}>
              {system.name}（{system.system_code}{system.is_active ? '' : '，已停用'}）
            </Option>
          ))}
        </Select>
        <span style={{marginLeft: 12, color: '#888', fontSize: 12}}>
          型号、厂家等档案字段在本页只读引用；如需修改请前往系统档案。
        </span>
      </div>
    );
  }

  renderSystemArchiveInfo() {
    const system = maintainStore.currentSystem;
    if (!system) return null;
    // 引用系统档案固定字段：已填写展示值，未填写明确标"未核实"，不重复录入
    const refItem = (label, value) => (
      <Descriptions.Item label={label}>
        {value ? value : <Tag>未核实</Tag>}
      </Descriptions.Item>
    );
    return (
      <Descriptions bordered size="small" column={3} style={{marginBottom: 12}}>
        <Descriptions.Item label="系统编号">{system.system_code}</Descriptions.Item>
        <Descriptions.Item label="系统名称">{system.name}</Descriptions.Item>
        <Descriptions.Item label="状态">
          {system.is_active ? <Tag color="green">可用</Tag> : <Tag color="red">已停用</Tag>}
        </Descriptions.Item>
        {refItem('型号', system.system_model)}
        {refItem('厂家', system.manufacturer)}
        {refItem('安装地点', system.install_location)}
        {refItem('呼号', system.callsign)}
        {refItem('工作频率', system.work_frequency)}
      </Descriptions>
    );
  }

  renderBaselineSection() {
    const baseline = maintainStore.baseline;
    if (baseline) {
      return (
        <Descriptions bordered size="small" column={3} style={{marginBottom: 12}}>
          <Descriptions.Item label="建档状态">
            <Tag color="blue">已建档</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="建档来源">{baseline.source}</Descriptions.Item>
          <Descriptions.Item label="建档时间">{baseline.established_at}</Descriptions.Item>
          <Descriptions.Item label="建档人">{baseline.established_by_name}</Descriptions.Item>
          <Descriptions.Item label="基线参数数" span={2}>
            {(baseline.items || []).length} 项
            {baseline.remark ? `（备注：${baseline.remark}）` : ''}
          </Descriptions.Item>
        </Descriptions>
      );
    }
    if (!maintainStore.canEstablish) {
      return <Alert type="warning" showIcon style={{marginBottom: 12}} message={maintainStore.blockReason}/>;
    }
    return (
      <Alert type="info" showIcon style={{marginBottom: 12}}
        message={
          <span>
            该系统尚未建立初始配置。
            <AuthButton auth={PERM.CONFIG_BASELINE} type="primary" size="small" style={{marginLeft: 8}}
              onClick={() => maintainStore.showBaselineForm()}>建立初始配置</AuthButton>
          </span>
        }
        description="初始建档记录基线值、建档人、建档时间与来源；建档后参数修改一律走配置变更流程。"/>
    );
  }

  renderConfigSection() {
    const hardwareItems = sharedStore.configItems.filter(
      item => item.category === PARAM_CATEGORY_HARDWARE);
    const runtimeItems = sharedStore.configItems.filter(
      item => item.category !== PARAM_CATEGORY_HARDWARE);
    const renderTable = items => (
      <Table
        rowKey="param"
        size="small"
        loading={sharedStore.isConfigFetching}
        pagination={false}
        dataSource={items}
        columns={this.configColumns}
        locale={{emptyText: <Empty description="暂无该分类下的配置参数" image={Empty.PRESENTED_IMAGE_SIMPLE}/>}}
      />
    );
    return (
      <div>
        <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
          <Divider orientation="left" plain
            style={{fontSize: 13, margin: '0 0 8px', flex: 1, minWidth: 0}}>当前配置</Divider>
          <AuthButton auth={PERM.CONFIG_ADD} type="primary" size="small"
            style={{marginBottom: 8, flexShrink: 0}} onClick={() => sharedStore.showForm()}>
            记录配置变更
          </AuthButton>
        </div>
        <Divider orientation="left" plain style={{fontSize: 12, margin: '4px 0 6px'}}>
          {renderCategoryTag(PARAM_CATEGORY_HARDWARE)}（引用系统档案视角，实测值记录在运行处置记录）
        </Divider>
        {renderTable(hardwareItems)}
        <Divider orientation="left" plain style={{fontSize: 12, margin: '12px 0 6px'}}>
          {renderCategoryTag(PARAM_CATEGORY_RUNTIME)}（可调整的设定值）
        </Divider>
        {renderTable(runtimeItems)}
      </div>
    );
  }

  renderChangeSection() {
    const paramOptions = sharedStore.configItems.map(item => (
      <Option value={item.param} key={item.param}>
        {item.param_name}（{item.param_code}）
      </Option>
    ));
    return (
      <div>
        <Divider orientation="left" plain style={{fontSize: 13, marginTop: 16, marginBottom: 8}}>配置变更历史</Divider>
        <div style={{marginBottom: 10}}>
          <Select
            allowClear
            showSearch
            optionFilterProp="children"
            placeholder="按参数筛选"
            style={{width: 200, marginRight: 8}}
            value={sharedStore.f_param}
            onChange={v => {
              sharedStore.f_param = v;
              this.fetchChanges();
            }}
          >
            {paramOptions}
          </Select>
          <Select
            allowClear
            placeholder="状态"
            style={{width: 110, marginRight: 8}}
            value={sharedStore.f_status}
            onChange={v => {
              sharedStore.f_status = v;
              this.fetchChanges();
            }}
          >
            {CONFIG_CHANGE_STATUS_OPTIONS.map(item => (
              <Option value={item.value} key={item.value}>{item.label}</Option>
            ))}
          </Select>
          <Button onClick={this.fetchChanges}>查询</Button>
        </div>
        <Table
          rowKey="id"
          size="small"
          loading={sharedStore.isChangesFetching}
          pagination={{
            current: sharedStore.page,
            pageSize: sharedStore.pageSize,
            total: sharedStore.total,
            showTotal: total => `共 ${total} 条`,
            onChange: this.handlePageChange,
          }}
          dataSource={sharedStore.changes}
          columns={this.changeColumns}
          locale={{emptyText: <Empty description="当前系统暂无配置变更记录" image={Empty.PRESENTED_IMAGE_SIMPLE}/>}}
        />
      </div>
    );
  }

  renderSelected() {
    if (!maintainStore.systemId) {
      return <Empty description="请先选择要维护配置的系统" style={{marginTop: 48}}/>;
    }
    return (
      <Spin spinning={maintainStore.isBaselineFetching}>
        {this.renderSystemArchiveInfo()}
        <Divider orientation="left" plain style={{fontSize: 13, marginTop: 4, marginBottom: 8}}>初始建档</Divider>
        {this.renderBaselineSection()}
        <Divider orientation="left" plain style={{fontSize: 13, marginTop: 8, marginBottom: 8}}>
          参数定义维护
        </Divider>
        <div style={{marginBottom: 8}}>
          <AuthButton auth={PERM.CONFIG_TEMPLATE} type="primary" size="small"
            onClick={() => maintainStore.showParamForm()}>
            <PlusOutlined/> 新增参数
          </AuthButton>
        </div>
        <Table
          rowKey="id"
          size="small"
          loading={maintainStore.isParamsFetching}
          pagination={false}
          dataSource={maintainStore.params}
          columns={this.paramColumns}
          locale={{emptyText: <Empty description="暂无配置参数定义，请先新增" image={Empty.PRESENTED_IMAGE_SIMPLE}/>}}
        />
        {this.renderConfigSection()}
        {this.renderChangeSection()}
        <SystemConfigChangeModal systemId={maintainStore.systemId}/>
        <SystemConfigBaselineModal/>
        <SystemConfigParamModal/>
        {this.state.detailId && (
          <SystemConfigChangeDetail
            changeId={this.state.detailId}
            systemId={maintainStore.systemId}
            onClose={this.handleCloseDetail}
          />
        )}
      </Spin>
    );
  }

  render() {
    return (
      <AuthDiv auth={PERM.CONFIG_VIEW}>
        {this.renderSystemSelector()}
        {this.renderSelected()}
      </AuthDiv>
    );
  }
}

export default SystemConfigMaintain;
