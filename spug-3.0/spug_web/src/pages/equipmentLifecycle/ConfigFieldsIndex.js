/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——配置字段页面（系统管理）。
 * 独立入口的"字段定义"管理：选择系统后复用系统详情的配置字段页签能力
 * （模板字段只读展示、自定义字段定义管理）；
 * 字段值不在此填写——统一在新增/编辑系统页面录入（步骤二聚合提交）。
 */
import React, { useState } from 'react';
import { Select, Empty, Spin } from 'antd';
import { AuthDiv, Breadcrumb } from 'components';
import { http } from 'libs';
import ConfigArchiveTab from './ConfigArchiveTab';
import store from './store';
import { PERM, API_PREFIX } from './constants';

function ConfigFieldsIndex() {
  const [options, setOptions] = useState([]);
  const [selectedId, setSelectedId] = useState(undefined);
  const [searching, setSearching] = useState(false);
  const [loading, setLoading] = useState(false);

  function searchSystems(keyword) {
    setSearching(true);
    http.get(`${API_PREFIX}/systems/`, {params: {keyword, page_size: 50, is_active: true}})
      .then(res => {
        setOptions((res.data || []).map(item => ({
          id: item.id,
          label: `${item.system_code} ${item.name}`,
        })));
      })
      .catch(() => {})
      .finally(() => setSearching(false));
  }

  function handleSelect(systemId) {
    setSelectedId(systemId);
    if (!systemId) {
      store.detailId = null;
      store.detail = {};
      return;
    }
    setLoading(true);
    store.detailId = systemId;
    store.detail = {};
    store.fetchDetail()
      .catch(() => {})
      .finally(() => setLoading(false));
  }

  return (
    <AuthDiv auth={`${PERM.SYS_VIEW}|${PERM.CFG_VIEW}`}>
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>设备全生命周期</Breadcrumb.Item>
        <Breadcrumb.Item>系统管理</Breadcrumb.Item>
        <Breadcrumb.Item>配置字段</Breadcrumb.Item>
      </Breadcrumb>
      <div style={{marginBottom: 12}}>
        <Select
          showSearch
          allowClear
          style={{width: 360}}
          value={selectedId}
          placeholder="选择系统（按编号/名称搜索）"
          filterOption={false}
          notFoundContent={searching ? <Spin size="small"/> : <Empty description="无匹配系统" image={Empty.PRESENTED_IMAGE_SIMPLE}/>}
          onSearch={searchSystems}
          onFocus={() => {if (!options.length) searchSystems();}}
          onChange={handleSelect}
        >
          {options.map(item => (
            <Select.Option value={item.id} key={item.id}>{item.label}</Select.Option>
          ))}
        </Select>
        <span style={{color: '#999', marginLeft: 8}}>
          字段值在新增或编辑系统页面填写，本页仅管理字段定义
        </span>
      </div>
      {selectedId && loading ? <Spin/> : null}
      {selectedId && !loading ? <ConfigArchiveTab/> : null}
    </AuthDiv>
  );
}

export default ConfigFieldsIndex;
