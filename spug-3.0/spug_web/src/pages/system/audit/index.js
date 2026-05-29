/**
 * 操作审计日志页面
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Input, DatePicker, Button } from 'antd';
import { SearchForm, AuthDiv, Breadcrumb } from 'components';
import ComTable from './Table';
import store from './store';

const { RangePicker } = DatePicker;

export default observer(function () {
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
          <Input allowClear value={store.f_action} onChange={e => store.f_action = e.target.value} placeholder="创建/更新/删除等"/>
        </SearchForm.Item>
        <SearchForm.Item span={6} title="对象类型">
          <Input allowClear value={store.f_target_type} onChange={e => store.f_target_type = e.target.value} placeholder="用户/角色/设备等"/>
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
        <SearchForm.Item span={4}>
          <Button type="primary" onClick={store.fetchRecords}>查询</Button>
          <Button style={{marginLeft: 8}} onClick={() => window.print()}>打印</Button>
        </SearchForm.Item>
      </SearchForm>
      <ComTable/>
    </AuthDiv>
  )
})
