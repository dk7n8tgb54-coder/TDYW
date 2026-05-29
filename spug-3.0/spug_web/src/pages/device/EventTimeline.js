/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Timeline, Tag, Button, Empty, Modal, message, Radio, Pagination } from 'antd';
import { AuthButton } from 'components';
import store from './store';
import EventForm from './EventForm';
import { EVENT_TYPE_MAP } from './constants';

/**
 * 事件时间线组件
 * 职责：展示设备事件列表，支持筛选、展开/收起详情、编辑删除操作
 */
export default observer(function () {
  const handleDelete = (eventId) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除该事件记录吗？',
      okText: '确定',
      cancelText: '取消',
      onOk: () => {
        store.handleDeleteEvent(eventId).then(() => message.success('删除成功'));
      }
    });
  };

  const handleFilterChange = (value) => {
    store.setEventTypeFilter(value, store.record?.id);
  };

  const handlePageChange = (page, pageSize) => {
    store.eventPage = page;
    store.eventPageSize = pageSize;
    store.fetchEvents(store.record?.id);
  };

  const handleToggleExpand = (event) => {
    const index = store.eventRecords.findIndex(r => r.id === event.id);
    if (index !== -1) {
      // 响应式更新：使用 mobx 的响应式特性，直接修改数组元素属性会触发更新
      // 确保事件对象是可观察的
      if (!store.eventRecords[index].hasOwnProperty('expanded')) {
        store.eventRecords[index] = { ...store.eventRecords[index], expanded: true };
      } else {
        store.eventRecords[index].expanded = !store.eventRecords[index].expanded;
      }
    }
  };

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Radio.Group
          value={store.eventTypeFilter === null ? '' : store.eventTypeFilter}
          onChange={(e) => handleFilterChange(e.target.value === '' ? null : e.target.value)}
          buttonStyle="solid"
        >
          <Radio.Button value="">全部事件</Radio.Button>
          <Radio.Button value="1">重大故障维修</Radio.Button>
          <Radio.Button value="2">设备更新</Radio.Button>
          <Radio.Button value="3">设备检修</Radio.Button>
        </Radio.Group>
      </div>

      {!store.eventRecords || store.eventRecords.length === 0 ? (
        <Empty description="暂无事件记录" style={{ marginTop: 32 }} />
      ) : (
        <React.Fragment>
          <Timeline mode="left">
            {store.eventRecords.map(event => {
              const config = EVENT_TYPE_MAP[event.event_type] || { text: '未知', color: 'default' };
              return (
                <Timeline.Item key={event.id} color={config.color}>
                  <div style={{ marginBottom: 8 }}>
                    <Tag color={config.color}>{config.text}</Tag>
                    <span style={{ fontWeight: 500, marginLeft: 8 }}>{event.event_title || '-'}</span>
                  </div>
                  <div style={{ color: '#999', fontSize: 12, marginBottom: 8 }}>
                    事件时间: {event.event_time || '-'} | 记录人: {event.related_user_name || '-'}
                  </div>
                  {event.expanded && (
                    <div style={{ background: '#f5f5f5', padding: 12, borderRadius: 4, marginTop: 8 }}>
                      {String(event.event_type) === '3' && (
                        <React.Fragment>
                          <p><strong>故障件:</strong> {event.fault_part || '-'}</p>
                          <p><strong>故障现象及原因:</strong> {event.fault_phenomenon_cause || '-'}</p>
                          <p><strong>检修措施:</strong> {event.maintenance_measures || '-'}</p>
                          <p><strong>修复时间:</strong> {event.repair_time || '-'}</p>
                        </React.Fragment>
                      )}
                      {String(event.event_type) !== '3' && (
                        <p><strong>简要情况:</strong> {event.maintenance_measures || '-'}</p>
                      )}
                      {event.remark && <p><strong>备注:</strong> {event.remark}</p>}
                      <div style={{ marginTop: 12 }}>
                        <AuthButton
                          auth="device.device_resume.history_edit"
                          type="link"
                          size="small"
                          onClick={() => EventForm.show(store.record, event)}
                        >
                          编辑
                        </AuthButton>
                        <AuthButton
                          auth="device.device_resume.history_delete"
                          type="link"
                          size="small"
                          danger
                          onClick={() => handleDelete(event.id)}
                        >
                          删除
                        </AuthButton>
                      </div>
                    </div>
                  )}
                  <Button
                    type="link"
                    size="small"
                    onClick={() => handleToggleExpand(event)}
                  >
                    {event.expanded ? '收起详情' : '展开详情'}
                  </Button>
                </Timeline.Item>
              );
            })}
          </Timeline>
          {store.eventTotal > store.eventPageSize && (
            <div style={{ marginTop: 24, textAlign: 'center' }}>
              <Pagination
                current={store.eventPage}
                pageSize={store.eventPageSize}
                total={store.eventTotal}
                showSizeChanger
                showQuickJumper
                showTotal={(total) => `共 ${total} 条`}
                pageSizeOptions={['10', '20', '50', '100']}
                onChange={handlePageChange}
              />
            </div>
          )}
        </React.Fragment>
      )}
    </div>
  );
})
