/**
 * 台站频率批复列表。
 *
 * 设计方案 9.1：
 * - 列：文件名称 / 文件编号 / 批复频率 / 起始日期 / 截止日期
 *       剩余天数与状态 / 责任人 / 附件数 / 创建时间 / 操作
 * - 状态展示读取 computed_status（实时计算），剩余天数读取 days_left
 * - 删除接口：DELETE /api/radio-license/approvals/?id=X
 * - 深链 ?id=xxx 打开详情
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Modal, Tag, message } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { http, hasPermission } from 'libs';
import { Action, TableCard, AuthButton, AttachmentCountBadge } from 'components';
import store from './store';

const STATUS_TAG_MAP = {
  normal: { color: 'green', text: '正常' },
  expiring: { color: 'orange', text: '即将到期' },
  expired: { color: 'red', text: '已过期' },
};

@observer
class ComTable extends React.Component {
  componentDidMount() {
    // 标记页面组件已挂载：卸载后 store 的异步回调不得再写入页面状态
    store.setActive(true);
    store.fetchRecords();
    // 深链 ?id=xxx 打开详情
    const params = new URLSearchParams(this.props.location?.search);
    const id = params.get('id');
    if (id) {
      store.loadDetail(id).then(() => store.showDetail(store.record)).catch(() => {});
    }
  }

  componentWillUnmount() {
    store.setActive(false);
  }

  handleDelete = (text) => {
    Modal.confirm({
      title: '删除确认',
      content: `确定要删除批复「${text.name}」吗？关联附件将被软删，提醒确认记录将被级联删除。`,
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: () => {
        return http.delete('/api/radio-license/approvals/', { params: { id: text.id } })
          .then(() => {
            message.success('删除成功');
            store.fetchRecords();
          });
      }
    });
  };

  renderStatus = (computed_status) => {
    const tagInfo = STATUS_TAG_MAP[computed_status] || STATUS_TAG_MAP.normal;
    return <Tag color={tagInfo.color}>{tagInfo.text}</Tag>;
  };

  renderDaysLeft = (days_left) => {
    if (days_left == null) return '-';
    if (days_left < 0) {
      return <span style={{ color: '#ff4d4f' }}>已过期 {Math.abs(days_left)} 天</span>;
    }
    if (days_left <= 60) {
      return <span style={{ color: '#fa8c16' }}>{days_left} 天</span>;
    }
    return <span style={{ color: '#52c41a' }}>{days_left} 天</span>;
  };

  renderAttachmentCount = (text, record) => {
    return <AttachmentCountBadge count={record.attachment_count} onClick={() => store.showDetail(record)} />;
  };

  render() {
    return (
      <TableCard
        tKey="sfa"
        resizable
        title="批复列表"
        rowKey="id"
        loading={store.isFetching}
        dataSource={store.records}
        onReload={store.fetchRecords}
        onRow={record => ({
          onDoubleClick: () => store.showDetail(record),
          style: { cursor: 'pointer' }
        })}
        actions={[
          <AuthButton
            key="add"
            auth="radio_license.approval.add"
            type="primary"
            icon={<PlusOutlined/>}
            onClick={() => store.showForm({})}>新建</AuthButton>,
        ]}
        pagination={{
          current: store.pageNum,
          pageSize: store.pageSize,
          total: store.total,
          showSizeChanger: true,
          showLessItems: true,
          showTotal: total => `共 ${total} 条`,
          pageSizeOptions: ['10', '20', '50', '100'],
          onChange: (page, pageSize) => {
            store.pageNum = page;
            store.pageSize = pageSize;
            store.fetchRecords();
          }
        }}>
        <Table.Column title="文件名称" dataIndex="name" width={200} ellipsis/>
        <Table.Column title="文件编号" dataIndex="doc_no" width={140} ellipsis/>
        <Table.Column title="批复频率" dataIndex="frequency_text" width={140} ellipsis/>
        <Table.Column title="起始日期" dataIndex="valid_from" width={110}/>
        <Table.Column title="截止日期" dataIndex="valid_to" width={110}/>
        <Table.Column title="剩余天数" width={120} render={(text, record) => this.renderDaysLeft(record.days_left)}/>
        <Table.Column title="状态" width={100} render={(text, record) => this.renderStatus(record.computed_status)}/>
        <Table.Column title="责任人" dataIndex="responsible_user_name" width={100}/>
        <Table.Column title="附件" width={70} render={this.renderAttachmentCount}/>
        <Table.Column title="创建时间" dataIndex="created_at" width={160} ellipsis/>
        {hasPermission('radio_license.approval.edit|radio_license.approval.del') && (
          <Table.Column title="操作" width={200} fixed="right" render={info => (
            <Action>
              <Action.Button auth="radio_license.approval.view" onClick={() => store.showDetail(info)}>查看</Action.Button>
              <Action.Button auth="radio_license.approval.edit" onClick={() => store.showForm(info)}>编辑</Action.Button>
              <Action.Button danger auth="radio_license.approval.del" onClick={() => this.handleDelete(info)}>删除</Action.Button>
            </Action>
          )}/>
        )}
      </TableCard>
    );
  }
}

export default ComTable;
