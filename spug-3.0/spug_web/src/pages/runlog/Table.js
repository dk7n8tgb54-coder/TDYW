/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Modal, message, DatePicker, Select, Tag, Statistic, Card, Row, Col, Image, Button, Dropdown, Menu } from 'antd';
import { PlusOutlined, DeleteOutlined, CheckCircleOutlined, FilePdfOutlined, FileExcelOutlined, FileOutlined, SettingOutlined, DownOutlined } from '@ant-design/icons';
import { http, hasPermission, Permission, exportFile } from 'libs';
import { Action, TableCard, AuthButton } from "components";
import store from './store';

const { RangePicker } = DatePicker;
const { Option } = Select;

@observer
class ComTable extends React.Component {
  abortController = null;
  _isMounted = false;

  state = {
    expandedRowsData: {},  // 存储展开行的动态数据
  }

  componentDidMount() {
    this._isMounted = true;
    window.addEventListener('runlog:changed', this.refreshList);
    this.abortController = new AbortController();
    store.fetchRecords()
      .then(() => {
        // 注释掉自动展开功能，避免大量并发请求
        // this.autoExpandInProgressRows()
      })
    store.fetchStatistics(this.abortController.signal)
  }

  componentWillUnmount() {
    this._isMounted = false;
    window.removeEventListener('runlog:changed', this.refreshList);
    if (this.abortController) {
      this.abortController.abort();
    }
  }

  refreshList = () => {
    this.setState({ expandedRowsData: {}, expandedRowKeys: [] });
    store.fetchRecords();
    store.fetchStatistics();
  };

  // 自动展开处理中的行
  autoExpandInProgressRows = () => {
    const inProgressIds = store.dataSource
      .filter(item => item.status === 'in_progress' && item.update_count > 0)
      .map(item => item.id);

    if (inProgressIds.length === 0) return;

    // 先设置展开的行ID列表（只设置一次）
    this.setState({ expandedRowKeys: inProgressIds });

    // 批量加载动态数据
    inProgressIds.forEach(id => {
      this.setState({ [`loading_${id}`]: true });
      http.get('/api/runlog/detail/', {params: {id, _t: Date.now()}})
        .then(res => {
          this.setState(prevState => ({
            expandedRowsData: {
              ...prevState.expandedRowsData,
              [id]: res.updates || []
            },
            [`loading_${id}`]: false
          }));
        })
        .catch(e => {
          console.error('[跨日事项跟踪] 获取动态列表失败:', e);
          this.setState({ [`loading_${id}`]: false });
        });
    });
  }

  handleDelete = (text) => {
    Modal.confirm({
      title: '删除确认',
      content: `确定要删除【${text.event_title}】的事件?`,
      onOk: () => {
        return http.delete('/api/runlog/', {params: {id: text.id}})
          .then(() => {
            message.success('删除成功');
            this.refreshList()
          })
      }
    })
  };

  handleExportPDF = async () => {
    // PDF 导出复用原有逻辑：POST body 传筛选条件
    await exportFile({
      url: '/api/runlog/export/pdf/',
      method: 'post',
      data: store.getExportParams(),
      defaultFilename: '跨日事项跟踪报告.pdf',
      timeout: 60000,
      loadingText: '正在生成PDF...',
    });
  };

  handleExportExcel = async () => {
    // Excel 明细导出：GET query 传筛选条件，主从结构（事件行 + 动态行）
    await exportFile({
      url: '/api/runlog/export/excel/',
      method: 'get',
      params: store.getExportParams(),
      defaultFilename: '跨日事项跟踪明细.xlsx',
      timeout: 60000,
      loadingText: '正在生成Excel...',
    });
  };

  handleExportMenuClick = ({ key }) => {
    if (key === 'pdf') {
      this.handleExportPDF();
    } else if (key === 'excel') {
      this.handleExportExcel();
    }
  };

  // 渲染状态标签（可点击切换）
  renderStatusTag = (text, record) => {
    const config = {
      'in_progress': { color: 'orange', text: '处理中' },
      'resolved': { color: 'green', text: '已解决' }
    };
    const status = record.status || text;
    const { color, text: label } = config[status] || { color: 'default', text: status };

    const handleStatusClick = (e) => {
      e.stopPropagation(); // 阻止冒泡，不触发行双击编辑
      const newStatus = status === 'in_progress' ? 'resolved' : 'in_progress';
      const newStatusText = newStatus === 'in_progress' ? '处理中' : '已解决';

      Modal.confirm({
        title: '状态修改确认',
        content: `确定要将状态从【${label}】修改为【${newStatusText}】吗？`,
        onOk: () => {
          return http.put('/api/runlog/', { id: record.id, status: newStatus })
            .then(() => {
              message.success('状态修改成功');
              this.refreshList();
            })
        }
      });
    };

    // 无编辑权限时渲染普通标签，不绑定点击、不显示 pointer 光标
    if (!hasPermission('runlog.runlog.edit')) {
      return <Tag color={color}>{label}</Tag>;
    }

    return (
      <Tag
        color={color}
        onClick={handleStatusClick}
        style={{ cursor: 'pointer' }}
      >
        {label}
      </Tag>
    );
  };

  // 渲染级别标签
  renderSeverityTag = (text, record) => {
    const config = {
      'P0': { color: 'red', text: 'P0' },
      'P1': { color: 'orange', text: 'P1' },
      'P2': { color: 'green', text: 'P2' }
    };
    const severity = record.severity || text;
    const { color, text: label } = config[severity] || { color: 'default', text: severity };
    return <Tag color={color}>{label}</Tag>;
  };

  // 处理行展开事件
  handleRowExpand = (expanded, record) => {
    const expandedRowKeys = [...(this.state.expandedRowKeys || [])];

    if (expanded) {
      // 展开行
      if (!expandedRowKeys.includes(record.id)) {
        expandedRowKeys.push(record.id);
      }
      // 每次展开都重新加载动态数据，避免添加/编辑后显示旧缓存
      this.setState({ [`loading_${record.id}`]: true });
      http.get('/api/runlog/detail/', {params: {id: record.id, _t: Date.now()}})
        .then(res => {
          this.setState(prevState => ({
            expandedRowsData: {
              ...prevState.expandedRowsData,
              [record.id]: res.updates || []
            },
            [`loading_${record.id}`]: false
          }));
        })
        .catch(e => {
          console.error('[跨日事项跟踪] 获取动态列表失败:', e);
          this.setState({ [`loading_${record.id}`]: false });
        });
    } else {
      // 收起行
      const index = expandedRowKeys.indexOf(record.id);
      if (index > -1) {
        expandedRowKeys.splice(index, 1);
      }
    }

    this.setState({ expandedRowKeys });
  };

  // 渲染展开行（动态列表）
  renderExpandedRow = (record) => {
    const { expandedRowsData } = this.state;
    const updates = expandedRowsData[record.id];
    const loading = this.state[`loading_${record.id}`];

    if (loading || !updates) {
      return <div style={{ padding: '16px', textAlign: 'center' }}>加载中...</div>;
    }

    return (
      <div style={{ padding: '16px', backgroundColor: '#f5f5f5' }}>
        <h4>动态记录（{record.update_count}条）</h4>
        {updates.map(update => (
          <div key={update.id} style={{
            marginBottom: 12,
            padding: 12,
            backgroundColor: 'white',
            borderRadius: 4
          }}>
            <div style={{ marginBottom: 8, color: '#666' }}>
              <span style={{ fontWeight: 'bold' }}>📅 {update.update_date}</span>
              <span style={{ marginLeft: 8 }}>序号: {update.sequence}</span>
              <span style={{ marginLeft: 8 }}>👤 {update.recorder}</span>
              {update.duty_person && (
                <span style={{ marginLeft: 8 }}>🛡 值班人：{update.duty_person}</span>
              )}
            </div>
            <div>{update.detail_content}</div>
            {/* 显示附件 */}
            {update.attachments && update.attachments.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>附件：</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {update.attachments.map((url, idx) => {
                    const fileName = url.split('/').pop() || `附件${idx + 1}`;
                    const isImage = /\.(jpg|jpeg|png|gif|webp)$/i.test(fileName);
                    if (isImage) {
                      return (
                        <Image
                          key={idx}
                          src={url}
                          width={100}
                          height={100}
                          style={{ objectFit: 'cover' }}
                        />
                      );
                    } else {
                      // 非图片文件显示文件名链接，点击下载
                      return (
                        <a
                          key={idx}
                          href={url}
                          target="_blank"
                          rel="noopener noreferrer"
                          download
                          title="点击下载"
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            width: 100,
                            height: 100,
                            border: '1px solid #d9d9d9',
                            borderRadius: 4,
                            textAlign: 'center',
                            fontSize: 12,
                            color: '#1890ff',
                            textDecoration: 'none',
                            padding: 8,
                            overflow: 'hidden',
                            cursor: 'pointer',
                          }}
                        >
                          <FileOutlined style={{ fontSize: 24, marginBottom: 4, display: 'block' }} />
                          <span>{fileName}</span>
                        </a>
                      );
                    }
                  })}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    );
  };

  render() {
    const { statistics } = store;
    const actions = [
      <AuthButton key="add" auth="runlog.runlog.add" type="primary" icon={<PlusOutlined/>} onClick={() => store.showForm({}, false)}>新建</AuthButton>,
      Permission.isSuper ? <Button key="typeAdmin" icon={<SettingOutlined/>} onClick={() => store.showEventTypeModal()}>类型管理</Button> : null,
      <span key="filter-system" style={{ marginRight: 8 }}>
        <Select placeholder="系统名称" style={{ width: 150 }} allowClear showSearch onChange={value => store.setFilter('system_name', value)} open={this._isMounted ? undefined : false}>
          {store.systemNames && store.systemNames.map(item => <Option value={item} key={item}>{item}</Option>)}
        </Select>
      </span>,
      <span key="filter-status" style={{ marginRight: 8 }}>
        <Select placeholder="处理状态" style={{ width: 120 }} allowClear onChange={value => store.setFilter('status', value)} open={this._isMounted ? undefined : false}>
          <Option value="in_progress">处理中</Option>
          <Option value="resolved">已解决</Option>
        </Select>
      </span>,
      <span key="filter-severity" style={{ marginRight: 8 }}>
        <Select placeholder="事件级别" style={{ width: 100 }} allowClear onChange={value => store.setFilter('severity', value)} open={this._isMounted ? undefined : false}>
          <Option value="P0">P0紧急</Option>
          <Option value="P1">P1重要</Option>
          <Option value="P2">P2一般</Option>
        </Select>
      </span>,
      <RangePicker key="date-range-picker" placeholder={['创建日期', '结束日期']} onChange={dates => store.setFilter('date_range', dates)} style={{ marginRight: 8, width: 260 }} open={this._isMounted ? undefined : false} />,
      hasPermission('runlog.runlog.view') ? (
        <Dropdown
          key="export"
          overlay={
            <Menu onClick={this.handleExportMenuClick}>
              <Menu.Item key="pdf" icon={<FilePdfOutlined/>}>导出 PDF</Menu.Item>
              <Menu.Item key="excel" icon={<FileExcelOutlined/>}>导出 Excel</Menu.Item>
            </Menu>
          }
          trigger={['click']}
        >
          <Button icon={<FileOutlined/>}>导出 <DownOutlined/></Button>
        </Dropdown>
      ) : null,
    ];

    return (
      <div>
        {/* 统计面板 */}
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={12}>
            <Card>
              <Statistic
                title="处理中"
                value={statistics?.status_stats?.in_progress?.count || 0}
                valueStyle={{ color: '#fa8c16' }}
              />
            </Card>
          </Col>
          <Col span={12}>
            <Card>
              <Statistic
                title="已解决"
                value={statistics?.status_stats?.resolved?.count || 0}
                valueStyle={{ color: '#52c41a' }}
              />
            </Card>
          </Col>
        </Row>

        <TableCard
          tKey="rl"
          title="跨日事项跟踪列表"
          rowKey="id"
          loading={store.isFetching}
          dataSource={store.dataSource}
          onReload={this.refreshList}
          onRow={record => ({
            onDoubleClick: () => {
              store.showForm(record, true);
            }
          })}
          actions={actions}
          pagination={{
            current: store.pagination.page,
            pageSize: store.pagination.page_size,
            total: store.pagination.total_count,
            showSizeChanger: true,
            showLessItems: true,
            showTotal: total => `共 ${total} 条`,
            pageSizeOptions: ['10', '20', '50', '100'],
            onChange: (page, pageSize) => store.setPage(page, pageSize),
            onShowSizeChange: (current, size) => store.setPage(1, size)
          }}
          expandable={{
            expandedRowRender: record => this.renderExpandedRow(record),
            onExpand: this.handleRowExpand,
            expandedRowKeys: this.state.expandedRowKeys || [],
            rowExpandable: record => record.update_count > 0 && hasPermission('runlog.runlog.update_view')
          }}>
          <Table.Column title="事件标题" dataIndex="event_title" ellipsis width={200}/>
          <Table.Column title="事件类型" dataIndex="event_type" width={100}/>
          <Table.Column title="级别" render={this.renderSeverityTag} width={80}/>
          <Table.Column title="状态" render={this.renderStatusTag} width={100}/>
          <Table.Column title="系统名称" dataIndex="system_name" width={120}/>
          <Table.Column title="责任人" dataIndex="responsible_user_name" width={100}/>
          <Table.Column title="动态数" dataIndex="update_count" width={80} align="center"/>
          <Table.Column title="最新动态日期" dataIndex="last_update_date" width={120}/>
          {hasPermission('runlog.runlog.update_add|runlog.runlog.edit|runlog.runlog.del') && (
          <Table.Column title="操作" render={info => (
            <Action>
              <Action.Button
                  auth="runlog.runlog.update_add"
                  onClick={() => store.showAddUpdateForm(info)}
                  size="small">添加动态</Action.Button>
              <Action.Button auth="runlog.runlog.edit" onClick={() => store.showForm(info, false)}>编辑</Action.Button>
              <Action.Button danger auth="runlog.runlog.del" onClick={() => this.handleDelete(info)}>删除</Action.Button>
            </Action>
          )}/>
        )}
      </TableCard>
    </div>
    )
  }
}

export default ComTable
