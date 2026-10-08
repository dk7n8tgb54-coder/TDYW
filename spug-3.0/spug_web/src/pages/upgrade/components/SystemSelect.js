/**
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect } from 'react';
import { observer } from 'mobx-react';
import { Select } from 'antd';
import store from '../store';

const { Option } = Select;

/**
 * 升级系统选择器（系统档案）
 *
 * 升级管理挂接系统档案（2026-09）后，"升级系统"改为系统档案
 * （equipment_lifecycle LifecycleSystem）的正式外键：候选来源为
 * store.systems（/api/upgrade/candidate-systems/，本租户可用系统），
 * 表单值与提交一律为系统 ID，页面显示 编号｜名称｜安装地点。
 * 新增/停用系统请到「设备运行维护管理 → 系统档案」维护。
 */
function SystemSelect({ placeholder = '请选择升级系统', disabled, style, ...rest }) {
  useEffect(() => {
    store.fetchSystems();
  }, []);

  const systems = store.systems || [];

  return (
    <Select
      showSearch
      allowClear
      disabled={disabled}
      style={style}
      placeholder={placeholder}
      notFoundContent={store.systemsFetching ? '加载中...' : '暂无可用系统（请先在系统档案维护）'}
      optionFilterProp="children"
      {...rest}
    >
      {systems.map(item => (
        <Option value={item.id} key={item.id}>
          {item.name}{item.install_location ? `｜${item.install_location}` : ''}
        </Option>
      ))}
    </Select>
  );
}

export default observer(SystemSelect);
