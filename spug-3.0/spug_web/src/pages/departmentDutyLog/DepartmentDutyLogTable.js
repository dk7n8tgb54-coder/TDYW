/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Tag, Modal, Tooltip, message, Input} from 'antd';
import {EditOutlined, DeleteOutlined, EyeOutlined, CheckCircleOutlined, StopOutlined} from '@ant-design/icons';
import {http, X_TOKEN} from 'libs';
import {TableCard, Action} from 'components';
import store from './departmentDutyLogStore';

@observer
class DepartmentDutyLogTable extends React.Component {
  componentDidMount() {
    store.fetchRecords();
    store.fetchOptions();
  }

  handleDelete = (record) => {
    Modal.confirm({
      title: '删除确认',
      content: `确定要删除草稿【${record.duty_date}】吗？`,
      onOk: () => {
        return http.delete(`/api/department-duty-log/records/${record.id}/`)
          .then(() => {
            message.success('删除成功');
            store.fetchRecords();
          });
      },
    });
  };

  handleVoid = () => {
    const record = store.record;
    const reason = store._voidReason;
    if (!reason || !reason.trim()) {
      message.error('请填写作废原因');
      return;
    }
    store._voidSubmitting = true;
    http.post(`/api/department-duty-log/records/${record.id}/void/`, {reason: reason.trim()})
      .then(() => {
        message.success('作废成功');
        store.voidVisible = false;
        store._voidReason = '';
        store.fetchRecords();
      })
      .finally(() => store._voidSubmitting = false);
  };

  renderStatus = (status) => {
    const tagInfo = store.statusTagMap[status] || store.statusTagMap.draft;
    return <Tag color={tagInfo.color}>{tagInfo.text}</Tag>;
  };

  renderSummary = (text) => {
    if (!text) return '--';
    return (
      <Tooltip title={text.length > 100 ? text.slice(0, 200) + '...' : text}>
        <span style={{whiteSpace: 'pre-wrap', display: '-webkit-box',
          WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden'}}>
          {text}
        </span>
      </Tooltip>
    );
  };

  render() {
    const columns = [
      {title: '日期', dataIndex: 'duty_date', key: 'duty_date', width: 110},
      {title: '值班员', dataIndex: 'duty_person_name', key: 'duty_person_name', width: 100},
      {title: '市电电压', dataIndex: 'mains_voltage', key: 'mains_voltage', width: 90,
        render: v => v || '--'},
      {title: 'UPS电压', dataIndex: 'ups_voltage', key: 'ups_voltage', width: 90,
        render: v => v || '--'},
      {title: '天气情况', dataIndex: 'weather', key: 'weather', width: 80,
        render: v => v || '--'},
      {title: '值班记录', dataIndex: 'duty_record_summary', key: 'duty_record_summary',
        render: this.renderSummary},
      {title: '状态', dataIndex: 'status', key: 'status', width: 90,
        render: this.renderStatus},
      {title: '签署时间', dataIndex: 'signed_at', key: 'signed_at', width: 160,
        render: v => v || '--'},
      {title: '操作', key: 'action', width: 180, fixed: 'right',
        render: (_, record) => {
          return (
            <Action>
              <Action.Button auth="department_duty_log.department_duty_log.view"
                icon={<EyeOutlined/>} onClick={() => store.showDetail(record)}>查看</Action.Button>
              {record.can_edit && (
                <Action.Button auth="department_duty_log.department_duty_log.edit"
                  icon={<EditOutlined/>} onClick={() => store.showForm(record)}>编辑</Action.Button>
              )}
              {record.can_sign && (
                <Action.Button auth="department_duty_log.department_duty_log.sign"
                  icon={<CheckCircleOutlined/>} onClick={() => store.showSign(record)}>签署</Action.Button>
              )}
              {record.can_delete && (
                <Action.Button auth="department_duty_log.department_duty_log.del"
                  icon={<DeleteOutlined/>} danger onClick={() => this.handleDelete(record)}>删除</Action.Button>
              )}
              {record.can_void && (
                <Action.Button auth="department_duty_log.department_duty_log.void"
                  icon={<StopOutlined/>} danger onClick={() => {store.record = record; store.voidVisible = true;}}>作废</Action.Button>
              )}
            </Action>
          );
        }},
    ];

    return (
      <>
        <TableCard
          rowKey="id"
          columns={columns}
          dataSource={store.records}
          loading={store.isFetching}
          scroll={{x: 1200}}
          pagination={{
            current: store.pageNum,
            pageSize: store.pageSize,
            total: store.total,
            showSizeChanger: true,
            showTotal: total => `共 ${total} 条`,
            onChange: (page, pageSize) => {
              store.pageNum = page;
              store.pageSize = pageSize;
              store.fetchRecords();
            },
          }}
          onReload={() => store.fetchRecords()}
        />

        {store.voidVisible && (
          <Modal
            title="作废已签记录"
            visible={store.voidVisible}
            onCancel={() => {store.voidVisible = false; store._voidReason = '';}}
            onOk={this.handleVoid}
            confirmLoading={store._voidSubmitting}
            okText="确认作废"
            okButtonProps={{danger: true}}
          >
            <p>作废后记录将标记为"已作废"，原签署证据保留不可变。</p>
            <Input.TextArea
              rows={3}
              placeholder="请填写作废原因（必填）"
              maxLength={500}
              showCount
              value={store._voidReason}
              onChange={e => store._voidReason = e.target.value}
            />
          </Modal>
        )}
      </>
    );
  }
}

export default DepartmentDutyLogTable;
