/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——系统列表页（步骤二）。
 * 支持跨页跳转直达详情：/el/systems?detail=<系统ID>（履历页跳入）。
 */
import React, { useEffect } from 'react';
import { observer } from 'mobx-react';
import { Input, Select, message, Popconfirm, Tag } from 'antd';
import {PlusOutlined} from '@ant-design/icons';
import {SearchForm, AuthDiv, AuthButton, ExportButton} from 'components';
import ComTable from './Table';
import ComForm from './SystemForm';
import SystemDetail from './SystemDetail';
import store from './store';
import { API_PREFIX, HEALTH_STATUS_OPTIONS, PERM } from './constants';

/**
 * 筛选区（2026-10-20 统一交互，参照运行处置记录 RecordFilters）：
 * 常驻 系统名称（草稿，查询/回车提交）/运行健康状态/是否可用，使用单位/
 * 安装地点收入"更多筛选"；下拉变更即查询但不代提交文本草稿；重置清空
 * 全部条件及草稿并回到第 1 页；展开收起本身不触发请求，收起时显示折叠区
 * 已启用条件数量。
 */
function SystemIndex(props) {
  const [advancedOpen, setAdvancedOpen] = React.useState(false);
  const advancedCount = [
    store.input_use_unit,
    store.input_install_location,
  ].filter(Boolean).length;

  useEffect(() => {
    // 跨页跳转直达详情（履历页跳入：?detail=<系统ID>）
    const params = new URLSearchParams(props.location ? props.location.search : '');
    const detailId = params.get('detail');
    if (detailId && /^\d+$/.test(detailId)) {
      store.showDetail({id: parseInt(detailId, 10)});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <AuthDiv auth={PERM.SYS_VIEW}>
      <SearchForm>
        <SearchForm.Item span={6} title="系统名称">
          <Input
            allowClear
            value={store.input_keyword}
            onChange={e => store.setKeywordInput(e.target.value)}
            placeholder="请输入系统名称"
            onPressEnter={() => store.commitFilters()}
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
        <SearchForm.Item span={4} title="是否可用">
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
        <SearchForm.Actions
          onSearch={() => store.commitFilters()}
          onReset={() => {store.resetFilter(); store.fetchRecords();}}
          advancedOpen={advancedOpen}
          advancedCount={advancedCount}
          onToggleAdvanced={() => setAdvancedOpen(!advancedOpen)}
        />
        {advancedOpen && (
          <React.Fragment>
            <SearchForm.Item span={6} title="使用单位">
              <Input
                allowClear
                value={store.input_use_unit}
                onChange={e => store.setUseUnitInput(e.target.value)}
                placeholder="请输入使用单位"
                onPressEnter={() => store.commitFilters()}
              />
            </SearchForm.Item>
            <SearchForm.Item span={6} title="安装地点">
              <Input
                allowClear
                value={store.input_install_location}
                onChange={e => store.setInstallLocationInput(e.target.value)}
                placeholder="请输入安装地点"
                onPressEnter={() => store.commitFilters()}
              />
            </SearchForm.Item>
          </React.Fragment>
        )}
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
