/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Tag, Modal, Tooltip, message} from 'antd';
import {EditOutlined, DeleteOutlined, EyeOutlined, CheckCircleOutlined, RollbackOutlined} from '@ant-design/icons';
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

  handleReturn = () => {
    const record = store.record;
    store._returnSubmitting = true;
    http.post(`/api/department-duty-log/records/${record.id}/return/`)
      .then(() => {
        message.success('退回成功，记录已恢复为草稿');
        store.returnVisible = false;
        store.fetchRecords();
      })
      .finally(() => store._returnSubmitting = false);
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
      {title: '值班人员', dataIndex: 'duty_person_name', key: 'duty_person_name', width: 100},
      {title: '天气情况', dataIndex: 'weather', key: 'weather', width: 80,
        render: v => v || '--'},
      {title: '值班记录', dataIndex: 'duty_record_summary', key: 'duty_record_summary',
        render: this.renderSummary},
      {title: '上级工作要求', dataIndex: 'remark', key: 'remark', width: 150,
        render: v => v ? (
          <Tooltip title={v.length > 50 ? v : ''}>
            <span style={{whiteSpace: 'pre-wrap', display: '-webkit-box',
              WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden'}}>
              {v}
            </span>
          </Tooltip>
        ) : '无'},
      {title: '状态', dataIndex: 'status', key: 'status', width: 90,
        render: this.renderStatus},
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
              {record.can_return && (
                <Action.Button auth="department_duty_log.department_duty_log.return"
                  icon={<RollbackOutlined/>} danger onClick={() => {store.record = record; store.returnVisible = true;}}>退回</Action.Button>
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
          scroll={{x: 860}}
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

        {store.returnVisible && (
          <Modal
            title="退回已签记录"
            visible={store.returnVisible}
            onCancel={() => {store.returnVisible = false;}}
            onOk={this.handleReturn}
            confirmLoading={store._returnSubmitting}
            okText="确认退回"
            okButtonProps={{danger: true}}
          >
            <p>退回后记录将恢复为草稿状态，原签署信息将被清除。值班人员可重新编辑并签署。</p>
          </Modal>
        )}
      </>
    );
  }
}

export default DepartmentDutyLogTable;
