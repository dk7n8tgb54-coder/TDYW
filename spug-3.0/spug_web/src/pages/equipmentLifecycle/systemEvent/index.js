/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——系统履历页面（按系统分组、按业务事项聚合）。
 * 履历由业务动作（故障、台账异常、升级）自动生成，只读展示：
 * 不支持手工新增、修改或删除；来源详情跳转由来源页面重新鉴权。
 * 健康状态与配置快照事件不进入主事项列表，健康状态经分组头"状态变化"
 * 面板查看；底层 SystemEvent 事件原样保留用于审计追溯。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Input, Select, Button, Tag, DatePicker } from 'antd';
import { ExportButton } from 'components';
import { AuthDiv, Breadcrumb, SearchForm } from 'components';
import GroupTable from './GroupTable';
import HealthDrawer from './HealthDrawer';
import store from './groupStore';
import { PERM, API_PREFIX, MAIN_EVENT_TYPE_OPTIONS, MAIN_SOURCE_TYPE_OPTIONS } from './constants';

const {RangePicker} = DatePicker;

function SystemEventIndex() {
  return (
    <AuthDiv auth={PERM.EVENT_VIEW}>
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>设备运行维护管理</Breadcrumb.Item>
        <Breadcrumb.Item>系统履历</Breadcrumb.Item>
      </Breadcrumb>
      <SearchForm>
        <SearchForm.Item span={6} title="关键词">
          <Input
            allowClear
            value={store.f_keyword}
            onChange={e => store.f_keyword = e.target.value}
            placeholder="摘要、事项编号、系统名称"
            onPressEnter={() => {store.page = 1; store.fetchGroups();}}
          />
        </SearchForm.Item>
        <SearchForm.Item span={5} title="事项类型">
          <Select
            allowClear
            style={{width: '100%'}}
            value={store.f_event_type}
            onChange={v => {store.f_event_type = v; store.page = 1; store.fetchGroups();}}
            placeholder="请选择事项类型"
          >
            {MAIN_EVENT_TYPE_OPTIONS.map(item => (
              <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={5} title="来源类型">
          <Select
            allowClear
            style={{width: '100%'}}
            value={store.f_source_type}
            onChange={v => {store.f_source_type = v; store.page = 1; store.fetchGroups();}}
            placeholder="请选择来源类型"
          >
            {MAIN_SOURCE_TYPE_OPTIONS.map(item => (
              <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={8} title="发生时间">
          <RangePicker
            showTime={{format: 'YYYY-MM-DD HH:mm'}}
            format="YYYY-MM-DD HH:mm"
            style={{width: '100%'}}
            value={store.f_range}
            onChange={v => {store.f_range = v; store.page = 1;}}
          />
        </SearchForm.Item>
        <SearchForm.Item span={24}>
          <Button type="primary" onClick={() => {store.page = 1; store.fetchGroups();}}>查询</Button>
          <Button
            style={{marginLeft: 8}}
            onClick={() => {store.resetFilter(); store.fetchGroups();}}
          >
            重置
          </Button>
        </SearchForm.Item>
      </SearchForm>
      <div style={{marginBottom: 12}}>
        <ExportButton
          auth={PERM.EVENT_EXPORT}
          url={`${API_PREFIX}/system-event-groups/export/`}
          filename="系统履历事项.csv"
        >
          导出
        </ExportButton>
        <Tag style={{marginLeft: 8}}>履历由业务动作自动生成，按系统与业务事项聚合展示</Tag>
      </div>
      <GroupTable/>
      <HealthDrawer/>
    </AuthDiv>
  );
}

export default observer(SystemEventIndex);
