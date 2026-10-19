/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * Excel 上传版维护台账页（2026-09-28 试点；2026-10 详情视图抽出复用）。
 *
 * 2026-10 起 Excel 台账创建/查询统一并入正式周月/季维护台账页面
 * （LedgerIndex），本试点页保留为独立兼容入口；填写详情视图抽至
 * ExcelLedgerDetail 共用（正式列表点击 Excel 来源记录渲染同一组件）。
 *
 * 三种视图：
 * - 列表：Excel 路线台账（created_from=excel_template），按类型/状态筛选；
 * - 创建：选择已发布 Excel 模板版本（周月/季类型边界由后端校验，前端按
 *   模板类型回显；执行日期由台账表格内容承载，2026-10-19 起创建不再单列）；
 * - 详情：委托 ExcelLedgerDetail（版式回放/保存/提交/复核/作废/导出）。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {
  Button, Card, Modal,
  Select, Table, Tag, message,
} from 'antd';
import {PlusOutlined} from '@ant-design/icons';

import excelLedgerStore from './excelLedgerStore';
import ExcelLedgerDetail, {
  LEDGER_TYPE_TEXT, STATUS_COLOR, STATUS_TEXT,
} from './ExcelLedgerDetail';

@observer
class ExcelLedgerPage extends React.Component {
  detailRef = React.createRef();

  get store() {
    return this.props.store || excelLedgerStore;
  }

  state = {
    createVisible: false,
    form: {ledger_type: undefined, version_id: undefined},
  };

  componentDidMount() {
    this.store.fetchList().catch(() => {});
  }

  handleCreate = () => {
    const {form} = this.state;
    if (!form.version_id) {
      message.warning('请选择模板版本');
      return;
    }
    this.store.createLedger({
      version_id: form.version_id,
      ledger_type: form.ledger_type || '',
      client_token: `excel-${form.version_id}-${Date.now()}`,
    }).then(detail => {
      this.setState({createVisible: false});
      return this.store.fetchDetail(detail.id);
    }).catch(() => {});
  };

  handleOpenDetail = record => {
    this.store.fetchDetail(record.id).catch(() => {});
  };

  handleBack = () => {
    // 返回列表（试点页缺省行为）：清空详情并刷新列表
    this.store.applyDetail(null);
    this.store.fetchList().catch(() => {});
  };

  /** 组件级入口：打开高级 PDF 设置（委托详情视图，与菜单项同一处理函数）。 */
  handleOpenPdfAdvanced = () => {
    if (this.detailRef && this.detailRef.current) {
      this.detailRef.current.openPdfAdvanced();
    }
  };

  _renderCreateModal() {
    const store = this.store;
    const {form} = this.state;
    const templates = store.available.filter(
      t => !form.ledger_type || t.ledger_type === form.ledger_type);
    const selectedTemplate = templates.find(t =>
      (t.versions || []).some(v => v.id === form.version_id));
    return (
      <Modal title="创建 Excel 维护台账" visible={this.state.createVisible}
             confirmLoading={store.creating} onOk={this.handleCreate}
             onCancel={() => this.setState({createVisible: false})} destroyOnClose>
        <div style={{marginBottom: 10}}>维护类型</div>
        <Select data-testid="ledger-type" placeholder="全部类型" style={{width: '100%'}}
                value={form.ledger_type || ''}
                onChange={value => this.setState({
                  form: {...form, ledger_type: value, version_id: undefined}})}>
          <Select.Option value="">全部类型</Select.Option>
          <Select.Option value="week_month">周月维护</Select.Option>
          <Select.Option value="seasonal">季维护</Select.Option>
        </Select>
        <div style={{marginBottom: 10, marginTop: 12}}>模板版本（发布后不可变）</div>
        <Select data-testid="ledger-version" placeholder="选择已发布版本" style={{width: '100%'}}
                value={form.version_id}
                onChange={value => this.setState({form: {...form, version_id: value}})}>
          {templates.map(t => (t.versions || []).map(v => (
            <Select.Option key={v.id} value={v.id}>
              {t.name} v{v.version_no}（{LEDGER_TYPE_TEXT[t.ledger_type] || t.ledger_type}，{v.field_count} 字段）
            </Select.Option>
          )))}
        </Select>
        {selectedTemplate && (
          <div style={{color: '#999', marginTop: 4}}>
            源文件：{selectedTemplate.versions.find(v => v.id === form.version_id).source_filename}
          </div>
        )}
      </Modal>
    );
  }

  _renderList() {
    const store = this.store;
    const columns = [
      {title: '台账编号', dataIndex: 'ledger_no'},
      {title: '类型', dataIndex: 'ledger_type',
       render: value => LEDGER_TYPE_TEXT[value] || value},
      {title: '模板版本', key: 'version',
       render: (_, record) => record.excel
         ? `${record.excel.template_name} v${record.excel.version_no}` : '—'},
      {title: '状态', dataIndex: 'status',
       render: value => <Tag color={STATUS_COLOR[value]}>{STATUS_TEXT[value] || value}</Tag>},
      {title: '操作', key: 'actions', render: (_, record) => (
        <Button type="link" size="small" data-testid="ledger-open"
                onClick={() => this.handleOpenDetail(record)}>
          {record.status === 'draft' ? '继续填写' : '查看历史'}
        </Button>
      )},
    ];
    return (
      <Card bordered={false} title="Excel 维护台账（WPS/Excel 上传试点）"
            extra={
              <Button data-testid="ledger-create" type="primary" icon={<PlusOutlined/>}
                      onClick={() => {
                        this.store.fetchAvailable().catch(() => {});
                        this.setState({createVisible: true});
                      }}>
                创建台账
              </Button>
            }>
        <Table rowKey="id" columns={columns} dataSource={store.list}
               loading={store.loading} pagination={{total: store.total}}
               onChange={pagination => store.setPage(pagination.current).catch(() => {})}/>
      </Card>
    );
  }

  render() {
    const store = this.store;
    return (
      <div className="excel-ledger-page">
        {store.detail
          ? <ExcelLedgerDetail ref={this.detailRef} store={store} onBack={this.handleBack}/>
          : this._renderList()}
        {this._renderCreateModal()}
      </div>
    );
  }
}

export default ExcelLedgerPage;
