/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——系统列表页（步骤二）。
 * 支持跨页跳转直达详情：/el/systems?detail=<系统ID>（当前运行状态/履历页跳入）。
 */
import React, { useEffect } from 'react';
import { observer } from 'mobx-react';
import { Input, Select, Button, message, Popconfirm, Tag } from 'antd';
import {PlusOutlined} from '@ant-design/icons';
import { SearchForm, AuthDiv, Breadcrumb, AuthButton, ExportButton } from 'components';
import ComTable from './Table';
import ComForm from './SystemForm';
import SystemDetail from './SystemDetail';
import store from './store';
import { API_PREFIX, HEALTH_STATUS_OPTIONS, PERM } from './constants';

function SystemIndex(props) {
  useEffect(() => {
    // 跨页跳转直达详情（当前运行状态/履历页跳入：?detail=<系统ID>）
    const params = new URLSearchParams(props.location ? props.location.search : '');
    const detailId = params.get('detail');
    if (detailId && /^\d+$/.test(detailId)) {
      store.showDetail({id: parseInt(detailId, 10)});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <AuthDiv auth={PERM.SYS_VIEW}>
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>设备全生命周期管理</Breadcrumb.Item>
        <Breadcrumb.Item>系统档案</Breadcrumb.Item>
        <Breadcrumb.Item>系统列表</Breadcrumb.Item>
      </Breadcrumb>
      <SearchForm>
        <SearchForm.Item span={6} title="系统编号/名称">
          <Input
            allowClear
            value={store.f_keyword}
            onChange={e => store.f_keyword = e.target.value}
            placeholder="请输入系统编号或名称"
            onPressEnter={() => {store.page = 1; store.fetchRecords();}}
          />
        </SearchForm.Item>
        <SearchForm.Item span={6} title="运行健康状态">
          <Select
            allowClear
            style={{width: '100%'}}
            value={store.f_health_status}
            onChange={v => {store.f_health_status = v; store.page = 1; store.fetchRecords();}}
            placeholder="请选择状态"
          >
            {HEALTH_STATUS_OPTIONS.map(item => (
              <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={6} title="是否可用">
          <Select
            allowClear
            style={{width: '100%'}}
            value={store.f_is_active}
            onChange={v => {store.f_is_active = v; store.page = 1; store.fetchRecords();}}
            placeholder="请选择"
          >
            <Select.Option value={true}>可用</Select.Option>
            <Select.Option value={false}>已停用</Select.Option>
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={6} title="使用单位">
          <Input
            allowClear
            value={store.f_use_unit}
            onChange={e => store.f_use_unit = e.target.value}
            placeholder="请输入使用单位"
            onPressEnter={() => {store.page = 1; store.fetchRecords();}}
          />
        </SearchForm.Item>
        <SearchForm.Item span={6} title="安装地点">
          <Input
            allowClear
            value={store.f_install_location}
            onChange={e => store.f_install_location = e.target.value}
            placeholder="请输入安装地点"
            onPressEnter={() => {store.page = 1; store.fetchRecords();}}
          />
        </SearchForm.Item>
        <SearchForm.Item span={12}>
          <Button type="primary" onClick={() => {store.page = 1; store.fetchRecords();}}>查询</Button>
          <Button
            style={{marginLeft: 8}}
            onClick={() => {store.resetFilter(); store.fetchRecords();}}
          >
            重置
          </Button>
        </SearchForm.Item>
      </SearchForm>
      <div style={{marginBottom: 12}}>
        <AuthButton
          auth={PERM.SYS_ADD}
          type="primary"
          icon={<PlusOutlined/>}
          onClick={() => store.showForm()}
        >
          新增系统
        </AuthButton>
        <ExportButton
          auth={PERM.SYS_EXPORT}
          style={{marginLeft: 8}}
          url={`${API_PREFIX}/systems/export/`}
          filename="系统列表.csv"
        >
          导出
        </ExportButton>
      </div>
      <ComTable/>
      {store.formVisible && <ComForm/>}
      {store.detailVisible && <SystemDetail/>}
    </AuthDiv>
  );
}

export default observer(SystemIndex);
