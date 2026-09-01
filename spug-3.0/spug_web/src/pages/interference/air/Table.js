/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Modal, message } from 'antd';
import { PlusOutlined, UploadOutlined, DownloadOutlined } from '@ant-design/icons';
import { http } from 'libs';
import { Action, TableCard, AuthButton, AttachmentCountBadge, ExportButton } from "components";
import store from './store';
import ImportModal from '../ImportModal';

@observer
class ComTable extends React.Component {
  state = {importVisible: false};

  componentDidMount() {
    store.fetchRecords()
  }

  handleDelete = (text) => {
    const logInfo = `${text['flight_number'] || ''} - ${text['datetime'] || ''}`;
    Modal.confirm({
      title: '删除确认',
      content: `确定要删除【${logInfo}】的空中干扰记录?`,
      onOk: () => {
        return http.delete('/api/interference/air/', {params: {id: text.id}})
          .then(() => {
            message.success('删除成功');
            store.fetchRecords()
          })
          .catch(() => {
            // 错误提示由 http 拦截器统一处理
          })
      }
    })
  };

  render() {
    return (
      <>
      <TableCard
        tKey="airInterference"
        title="空中干扰"
        rowKey="id"
        loading={store.isFetching}
        dataSource={store.dataSource}
        onReload={store.fetchRecords}
        onRow={record => ({
          onDoubleClick: () => {
            store.showForm(record, true);
          },
          style: { cursor: 'pointer' }
        })}
        actions={[
          <AuthButton
            auth="interference.interference.add"
            type="primary"
            icon={<PlusOutlined/>}
            onClick={() => store.showForm({}, false)}>新建</AuthButton>,
          <AuthButton
            auth="interference.interference.add"
            icon={<UploadOutlined/>}
            onClick={() => this.setState({importVisible: true})}>导入 Excel</AuthButton>,
          <ExportButton
            auth="interference.interference.view"
            icon={<DownloadOutlined/>}
            url="/api/interference/air/import/template/"
            filename="空中干扰导入模板.xlsx">下载导入模板</ExportButton>,
          <ExportButton
            auth="interference.interference.view"
            url="/api/interference/air/export/"
            params={store.getExportParams()}
            filename="空中干扰信息.xlsx">导出</ExportButton>
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
        <Table.Column title="日期时间" dataIndex="datetime" width={140}
                      render={text => (text || '').slice(0, 16)}/>
        <Table.Column title="航班号" dataIndex="flight_number"/>
        <Table.Column title="航线" dataIndex="route" ellipsis/>
        <Table.Column title="告警摘要" dataIndex="alert_summary" ellipsis width={200}/>
        <Table.Column title="持续时间" dataIndex="duration_text" width={90}/>
        <Table.Column title="原因分析" dataIndex="cause_analysis" ellipsis width={180}/>
        <Table.Column title="附件" width={70} render={info => (
          <AttachmentCountBadge count={info.attachment_count} onClick={() => store.showForm(info, true)}/>
        )}/>
        <Table.Column title="操作" width={150} render={info => (
          <Action>
            <Action.Button auth="interference.interference.view" onClick={() => store.showForm(info, true)}>查看</Action.Button>
            <Action.Button auth="interference.interference.edit" onClick={() => store.showForm(info, false)}>编辑</Action.Button>
            <Action.Button danger auth="interference.interference.del" onClick={() => this.handleDelete(info)}>删除</Action.Button>
          </Action>
        )}/>
      </TableCard>
      {this.state.importVisible && (
        <ImportModal
          business="air"
          visible
          onClose={() => this.setState({importVisible: false})}
          onSuccess={() => {
            this.setState({importVisible: false});
            store.fetchRecords();
          }}/>
      )}
      </>
    )
  }
}

export default ComTable;
