/**
 * 操作审计日志页面
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Input, DatePicker, Button, Select, Tag, Tooltip } from 'antd';
import { SearchForm, AuthDiv, Breadcrumb } from 'components';
import ComTable from './Table';
import store from './store';

const { RangePicker } = DatePicker;
const { Option } = Select;

export default observer(function () {
  // 非超管查看"登录"动作时给出说明：未知账号的登录失败仅超管可见（见后端 account/views.py 登录失败租户归属策略）
  const isSupper = JSON.parse(localStorage.getItem('is_supper') || 'false');
  const showLoginHint = !isSupper && store.f_action === 'login';

  return (
    <AuthDiv auth="system.audit.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>系统管理</Breadcrumb.Item>
        <Breadcrumb.Item>操作审计</Breadcrumb.Item>
      </Breadcrumb>
      <SearchForm>
        <SearchForm.Item span={6} title="操作人">
          <Input allowClear value={store.f_username} onChange={e => store.f_username = e.target.value} placeholder="请输入用户名"/>
        </SearchForm.Item>
        <SearchForm.Item span={6} title="操作类型">
          <Select
            allowClear
            style={{width: '100%'}}
            placeholder="请选择操作类型"
            value={store.f_action || undefined}
            onChange={val => { store.f_action = val || ''; store.fetchRecords(); }}
          >
            {store.actionOptions.map(item => (
              <Option key={item.value} value={item.value}>{item.label}</Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={6} title="对象类型">
          <Select
            allowClear
            style={{width: '100%'}}
            placeholder="请选择对象类型"
            value={store.f_target_type || undefined}
            onChange={val => { store.f_target_type = val || ''; store.fetchRecords(); }}
          >
            {store.targetTypeOptions.map(item => (
              <Option key={item.value} value={item.value}>{item.label}</Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={6} title="关键词">
          <Input allowClear value={store.f_keyword} onChange={e => store.f_keyword = e.target.value} placeholder="搜索用户名/对象/详情"/>
        </SearchForm.Item>
        <SearchForm.Item span={8} title="时间范围">
          <RangePicker
            showTime
            value={store.f_time_range}
            onChange={dates => store.f_time_range = dates}
            style={{width: '100%'}}
          />
        </SearchForm.Item>
        <SearchForm.Item span={8}>
          <Button type="primary" onClick={store.fetchRecords}>查询</Button>
          <Button style={{marginLeft: 8}} onClick={store.resetFilters}>重置</Button>
          <Button style={{marginLeft: 8}} onClick={() => window.print()}>打印当前页</Button>
        </SearchForm.Item>
        {showLoginHint && (
          <SearchForm.Item span={24}>
            <Tooltip title="未知账号的登录失败仅超管可见">
              <Tag color="orange">提示：未知账号的登录失败审计仅超管可见，本租户列表可能不完整</Tag>
            </Tooltip>
          </SearchForm.Item>
        )}
      </SearchForm>
      <ComTable/>
    </AuthDiv>
  )
})
