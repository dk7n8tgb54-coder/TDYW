/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——当前运行状态页面（履历与状态）。
 * 只读聚合：按健康状态统计 + 系统状态列表；点击状态卡片即按该状态筛选列表。
 * 健康状态唯一来源为后端故障/工单统一计算（fault_services），本页不提供修改入口。
 */
import React, { useEffect } from 'react';
import { observer } from 'mobx-react';
import { Card, Tag } from 'antd';
import { AuthDiv, Breadcrumb } from 'components';
import ComTable from './Table';
import { summaryStore, listStore } from './store';
import { PERM, HEALTH_STATUS_OPTIONS, HEALTH_STATUS_TEXT, HEALTH_STATUS_COLOR } from '../constants';

function StatusCard({status, count, active, onClick}) {
  return (
    <Card
      size="small"
      hoverable
      onClick={onClick}
      style={{
        textAlign: 'center', cursor: 'pointer', minWidth: 110,
        borderColor: active ? '#1890ff' : undefined,
      }}
    >
      <div style={{fontSize: 22, fontWeight: 600}}>
        <Tag color={HEALTH_STATUS_COLOR[status]} style={{fontSize: 15, padding: '2px 10px', margin: 0}}>
          {HEALTH_STATUS_TEXT[status]}
        </Tag>
      </div>
      <div style={{marginTop: 6, color: '#666'}}>{count} 套</div>
    </Card>
  );
}

function SystemStatusIndex() {
  useEffect(() => {
    summaryStore.fetchSummary();
    listStore.fetchRecords();
  }, []);

  return (
    <AuthDiv auth={PERM.SYS_VIEW}>
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>设备全生命周期管理</Breadcrumb.Item>
        <Breadcrumb.Item>履历与状态</Breadcrumb.Item>
        <Breadcrumb.Item>当前运行状态</Breadcrumb.Item>
      </Breadcrumb>
      <Card
        size="small"
        loading={summaryStore.isSummaryFetching}
        style={{marginBottom: 12}}
      >
        <div style={{display: 'flex', gap: 12, flexWrap: 'wrap'}}>
          {HEALTH_STATUS_OPTIONS.map(item => (
            <StatusCard
              key={item.value}
              status={item.value}
              count={summaryStore.summary[item.value] || 0}
              active={listStore.f_health_status === item.value}
              onClick={() => listStore.filterByStatus(
                listStore.f_health_status === item.value ? undefined : item.value)}
            />
          ))}
          <Card size="small" style={{textAlign: 'center'}}>
            <div style={{fontSize: 22, fontWeight: 600}}>{summaryStore.total}</div>
            <div style={{marginTop: 6, color: '#666'}}>
              系统总数（可用 {summaryStore.activeTotal} / 停用 {summaryStore.inactiveTotal}）
            </div>
          </Card>
        </div>
      </Card>
      <ComTable/>
    </AuthDiv>
  );
}

export default observer(SystemStatusIndex);
