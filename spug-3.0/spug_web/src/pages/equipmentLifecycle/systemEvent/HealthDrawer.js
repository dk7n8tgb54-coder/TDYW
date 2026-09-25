/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——系统健康状态变化二级面板（按系统）。
 * 健康状态事件默认不进入主履历事项列表，经分组头"状态变化"入口在此查看；
 * 数据来自系统详情履历接口（event_type=health），SystemEvent 原样保留。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Drawer, Timeline, Spin, Empty } from 'antd';
import store from './groupStore';
import { formatDateTime } from './constants';

@observer
class HealthDrawer extends React.Component {
  renderRecords() {
    const drawer = store.healthDrawer;
    if (drawer.loading) return <Spin style={{display: 'block', marginTop: 48}}/>;
    if (drawer.failed) {
      return <Empty style={{marginTop: 48}} description="健康状态加载失败，请重试"/>;
    }
    if (!drawer.records.length) {
      return <Empty style={{marginTop: 48}} description="该系统暂无健康状态变化记录"/>;
    }
    return (
      <Timeline>
        {drawer.records.map(record => (
          <Timeline.Item key={record.id}>
            <div>
              <span style={{marginRight: 8}}>{formatDateTime(record.occurred_at)}</span>
              <span>{record.title}</span>
            </div>
            {record.created_by_name ? (
              <span style={{color: '#999'}}>记录人：{record.created_by_name}</span>
            ) : null}
          </Timeline.Item>
        ))}
      </Timeline>
    );
  }

  render() {
    const drawer = store.healthDrawer;
    return (
      <Drawer
        title={`健康状态变化 - ${drawer.systemName || ''}`}
        visible={drawer.visible}
        width={520}
        onClose={store.closeHealthDrawer}
      >
        {this.renderRecords()}
      </Drawer>
    );
  }
}

export default HealthDrawer;
