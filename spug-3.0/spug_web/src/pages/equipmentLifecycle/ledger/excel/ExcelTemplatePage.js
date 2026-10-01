/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * Excel 上传版维护台账模板页（2026-09-28 试点；2026-09-29 批量绑定；2026-09-29 删除）。
 *
 * 两种视图：
 * - 列表：上传新模板（名称/类型/文件）→ 进入绑定工作区；模板行可配置
 *   绑定、查看版本、删除（Popconfirm 二次确认，del 权限 + 启用状态才
 *   显示；逻辑删除/停用，成功后重取列表）；已停用模板不显示删除按钮；
 * - 绑定工作区：布局预览（合并/行高列宽/样式，LayoutTable）+
 *   字段绑定面板（FieldPanel，单格）+ 批量绑定面板（Ctrl 加选/
 *   拖拽矩形多选后统一配置）+ 发布按钮 + 版本抽屉；已删除（停用）模板
 *   仅供查看，重传/发布/选格编辑入口全部冻结（后端独立校验兜底）；
 *   草稿 PDF 预览按钮（有草稿可用，新窗口打开发布前真实打印效果）+
 *   兼容性检查提示（error=须处理后才能发布，warning=可能有格式差异）；
 *   PDF 参数抽屉（2026-09-30）：纸张/方向/边距/缩放/重复表头行/分页
 *   设置模板级配置，发布随版本快照固定；列表状态四态（草稿/已发布/
 *   已使用/已删除），已使用模板删除时提示引用台账数。
 *
 * 不支持的文件特性（公式/图表/图片/外部链接/透视表）由后端显式拒绝，
 * 错误信息逐项列出（公共拦截器提示，不静默导入）。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {
  Alert, Button, Card, Drawer, Empty, Input, Popconfirm, Select,
  Space, Spin, Table, Tag, Upload, message,
} from 'antd';
import {
  ArrowLeftOutlined, CloudUploadOutlined, DeleteOutlined, DownloadOutlined,
  FilePdfOutlined, PrinterOutlined, UploadOutlined,
} from '@ant-design/icons';
import {hasPermission, history} from 'libs';

import excelTemplateStore from './excelTemplateStore';
import {PERM_L} from '../constants';
import LayoutTable, {bindBlockReason} from './components/LayoutTable';
import FieldPanel from './components/FieldPanel';
import BatchBindingPanel from './BatchBindingPanel';
import PdfParamsForm from './PdfParamsForm';

const LEDGER_TYPE_TEXT = {week_month: '周月维护', seasonal: '季维护'};
const TEMPLATE_STATUS = {
  draft: {text: '草稿', color: 'default'},
  published: {text: '已发布', color: 'blue'},
  used: {text: '已使用', color: 'green'},
  deleted: {text: '已删除', color: 'red'},
};

@observer
class ExcelTemplatePage extends React.Component {
  get store() {
    return this.props.store || excelTemplateStore;
  }

  componentDidMount() {
    this.store.fetchList().catch(() => {});
    // 拖拽矩形选区在表格任意位置松开鼠标即结束
    this._handleMouseUp = () => this.store.endDrag();
    document.addEventListener('mouseup', this._handleMouseUp);
  }

  componentWillUnmount() {
    if (this._handleMouseUp) {
      document.removeEventListener('mouseup', this._handleMouseUp);
      this._handleMouseUp = null;
    }
  }

  handleUpload = file => {
    if (!/\.xlsx$/i.test(file.name)) {
      message.error('仅支持 .xlsx 文件（暂不支持 .xls 与 WPS 私有格式）');
      return false;
    }
    const store = this.store;
    if (!store.uploadName || !store.uploadType) {
      message.warning('请先填写模板名称并选择维护类型');
      return false;
    }
    store.upload({name: store.uploadName, ledger_type: store.uploadType}, file)
      .then(() => message.success('模板解析成功，请绑定可填写单元格'))
      .catch(() => {});
    return false;
  };

  handleReupload = file => {
    if (!/\.xlsx$/i.test(file.name)) {
      message.error('仅支持 .xlsx 文件');
      return false;
    }
    this.store.reuploadFile(file)
      .then(() => message.success('源文件已更新，原绑定已清空，请重新绑定'))
      .catch(() => {});
    return false;
  };

  handlePublish = () => {
    const store = this.store;
    if (!store.bindings.length) {
      message.warning('请先绑定至少一个可填写字段再发布');
      return;
    }
    store.publish().catch(() => {});
  };

  showVersions = () => {
    this.store.fetchVersions().then(() => {
      this.store.versionsVisible = true;
    }).catch(() => {});
  };

  _renderUploadPanel() {
    const store = this.store;
    return (
      <Space style={{marginBottom: 12}} wrap>
        <Input data-testid="tpl-name" placeholder="模板名称" maxLength={100}
               style={{width: 200}}
               value={store.uploadName}
               onChange={e => store.setUploadField('uploadName', e.target.value)}/>
        <Select data-testid="tpl-type" placeholder="维护类型" style={{width: 140}}
                value={store.uploadType}
                onChange={value => store.setUploadField('uploadType', value)}>
          <Select.Option value="week_month">周月维护</Select.Option>
          <Select.Option value="seasonal">季维护</Select.Option>
        </Select>
        <Upload accept=".xlsx" showUploadList={false} beforeUpload={this.handleUpload}>
          <Button data-testid="tpl-upload" icon={<UploadOutlined/>}
                  loading={store.uploading}>
            上传 .xlsx 模板
          </Button>
        </Upload>
        <Button icon={<DownloadOutlined/>} onClick={() => store.downloadSample()}>
          下载验收样例
        </Button>
        <Button data-testid="tpl-back-list" icon={<ArrowLeftOutlined/>}
                onClick={() => store.applyDetail(null)}>返回列表</Button>
      </Space>
    );
  }

  _renderHeaderText(sheet, coordinate) {
    if (!sheet || !coordinate) return '';
    const match = /^([A-Z]+)([0-9]+)$/.exec(coordinate);
    if (!match) return '';
    const header = (sheet.cells || {})[`${match[1]}1`];
    return header && header.v ? String(header.v) : '';
  }

  /** 草稿兼容性检查提示（error=须处理后才能发布；warning=可能有格式差异）。 */
  _renderCompatibilityAlert() {
    const compat = this.store.compatibility;
    if (!compat || compat.status === 'ok') return null;
    const messages = [
      ...(compat.warnings || []),
      ...(compat.unsupported && compat.unsupported.length
        ? [`包含平台暂不支持的特性：${compat.unsupported.join('、')}，请处理后重新上传源文件`]
        : []),
    ];
    if (!messages.length) return null;
    return (
      <Alert data-testid="tpl-compat" showIcon style={{marginBottom: 12}}
             type={compat.status === 'error' ? 'error' : 'warning'}
             message={compat.status === 'error'
               ? '模板草稿存在问题，处理后才能发布'
               : '模板可能存在格式差异'}
             description={messages.join('；')}/>
    );
  }

  _renderWorkspace() {
    const store = this.store;
    const sheet = store.currentSheet;
    const draft = store.draft;
    // 已删除（停用）模板仅供查看：禁用重传/发布入口，选格编辑一并冻结
    const deleted = !store.current.is_active;
    return (
      <Card bordered={false}
            title={`模板绑定：${store.current.name}（${LEDGER_TYPE_TEXT[store.current.ledger_type] || store.current.ledger_type}）`}
            extra={
              <Space>
                {deleted && <Tag color="red" data-testid="tpl-deleted-tag">已删除（停用），仅供查看</Tag>}
                {draft && <span>源文件：{draft.source_filename}</span>}
                <Tag>绑定字段 {store.bindings.length} 个</Tag>
                <Tag color="blue">版本 v{store.current.latest_version_no || 0}（共 {store.current.versions_count || 0} 个）</Tag>
                <Upload accept=".xlsx" showUploadList={false} beforeUpload={this.handleReupload}>
                  <Button icon={<UploadOutlined/>} loading={store.uploading}
                          disabled={deleted}>重传源文件</Button>
                </Upload>
                <Button data-testid="tpl-pdf-preview" icon={<FilePdfOutlined/>}
                        disabled={!draft} loading={store.previewing}
                        onClick={() => store.previewPdf().catch(() => {})}>
                  PDF预览
                </Button>
                <Button data-testid="tpl-pdf-params" icon={<PrinterOutlined/>}
                        disabled={!draft || deleted}
                        onClick={() => store.openPdfDrawer()}>
                  PDF参数
                </Button>
                <Button onClick={this.showVersions}>版本列表</Button>
                <Popconfirm title="发布后版本与源文件不可修改，确认发布当前草稿？"
                            onConfirm={this.handlePublish} okText="发布" cancelText="取消">
                  <Button data-testid="tpl-publish" type="primary" loading={store.publishing}
                          disabled={deleted}>
                    发布版本
                  </Button>
                </Popconfirm>
              </Space>
            }>
        {this._renderUploadPanel()}
        <Spin spinning={store.loading || store.uploading}
              tip={store.uploading ? `上传解析中 ${store.uploadProgress}%` : '加载中...'}>
          {this._renderCompatibilityAlert()}
          {draft && draft.layout ? (
            <div style={{display: 'flex', gap: 16, alignItems: 'flex-start'}}>
              <div style={{flex: 1, minWidth: 0}}>
                <LayoutTable
                  sheet={sheet}
                  bindingByCell={store.bindingByCell}
                  fillMode={false}
                  selectedCell={store.selectedCell}
                  selectedCells={store.selectedCells}
                  onSelectCell={(coord, event) => {
                    if (deleted) return;
                    store.handleCellClick(coord, event);
                  }}
                  onCellMouseDown={(coord, event) => {
                    if (deleted) return;
                    store.beginDrag(coord, event);
                  }}
                  onCellMouseEnter={coord => store.extendDrag(coord)}/>
              </div>
              {store.selectedCells.length > 0 ? (
                <BatchBindingPanel
                  selectedCells={store.selectedCells}
                  saving={store.saving}
                  onSave={form => store.saveBatchBinding(form)}
                  onClear={() => store.clearSelection()}/>
              ) : (
                <FieldPanel
                  key={`${store.activeSheet}!${store.selectedCell}!${store.selectedBinding ? store.selectedBinding.field_id : 'none'}`}
                  coord={store.selectedCell}
                  binding={store.selectedBinding}
                  blockReason={store.selectedCell && !store.selectedBinding
                    ? bindBlockReason(sheet, store.selectedCell) : null}
                  headerText={this._renderHeaderText(sheet, store.selectedCell)}
                  saving={store.saving}
                  onSave={form => store.saveBinding(form)}
                  onRemove={() => store.selectedBinding
                    && store.removeBinding(store.selectedBinding.field_id)}/>
              )}
            </div>
          ) : (
            <Empty description="当前模板没有草稿源文件，请上传 .xlsx"
                   style={{padding: 60}}/>
          )}
        </Spin>
      </Card>
    );
  }

  _renderList() {
    const store = this.store;
    const columns = [
      {title: '模板名称', dataIndex: 'name'},
      {title: '维护类型', dataIndex: 'ledger_type',
       render: value => LEDGER_TYPE_TEXT[value] || value},
      {title: '说明', dataIndex: 'description', ellipsis: true},
      {title: '草稿源文件', dataIndex: 'draft_source_filename',
       render: (value, record) => value ? (
         <span>
           {value}
           {record.draft_updated_at ? (
             <span style={{color: '#999'}}>（{record.draft_updated_at}）</span>
           ) : null}
         </span>
       ) : <Tag>未上传</Tag>},
      {title: '版本', dataIndex: 'latest_version_no',
       render: (value, record) => `v${value || 0} / 共 ${record.versions_count || 0} 个`},
      {title: '状态', dataIndex: 'status',
       render: value => {
         const conf = TEMPLATE_STATUS[value] || {text: value || '—'};
         return <Tag color={conf.color}>{conf.text}</Tag>;
       }},
      {title: '操作', key: 'actions', render: (_, record) => (
        <Space>
          <Button type="link" size="small" data-testid="tpl-open"
                  onClick={() => store.fetchDetail(record.id).catch(() => {})}>
            {record.draft_source_filename ? '配置绑定' : '上传源文件'}
          </Button>
          {record.is_active && hasPermission(PERM_L.TPL_DEL) && (
            <Popconfirm
              title={record.ledgers_count > 0
                ? `该模板已被 ${record.ledgers_count} 个台账引用：删除后将停止新台账使用，历史台账仍可查看与导出。确定删除吗？`
                : '删除后将停止该模板使用，历史台账仍可查看，确定删除吗？'}
              okText="确定" cancelText="取消"
              onConfirm={() => store.deleteTemplate(record.id).catch(() => {})}>
              <Button type="link" size="small" data-testid="tpl-delete"
                      icon={<DeleteOutlined/>} style={{color: '#f5222d'}}
                      loading={store.deletingId === record.id}>
                删除
              </Button>
            </Popconfirm>
          )}
        </Space>
      )},
    ];
    return (
      <Card bordered={false}
            title="Excel 维护台账模板（WPS/Excel 上传试点）"
            extra={
              <Space>
                <Button icon={<DownloadOutlined/>} onClick={() => store.downloadSample()}>
                  下载验收样例
                </Button>
                <Button data-testid="tpl-to-ledger" type="primary"
                        onClick={() => history.push('/el/excel-ledgers')}>
                  去 Excel 台账填写
                </Button>
              </Space>
            }>
        {this._renderUploadPanel()}
        <Table rowKey="id" columns={columns} dataSource={store.list}
               loading={store.loading} pagination={false}/>
        <div style={{color: '#999', marginTop: 8}}>
          仅支持固定行列、固定填写位置的 .xlsx；公式、图表、图片、外部链接、
          透视表与宏会在上传时被明确拒绝，不会静默丢失。
        </div>
      </Card>
    );
  }

  _renderVersionsDrawer() {
    const store = this.store;
    const columns = [
      {title: '版本', dataIndex: 'version_no', render: v => `v${v}`},
      {title: '模板名称快照', dataIndex: 'template_name'},
      {title: '源文件', dataIndex: 'source_filename'},
      {title: 'SHA-256', dataIndex: 'source_hash',
       render: v => <span style={{fontFamily: 'monospace'}}>{String(v).slice(0, 16)}…</span>},
      {title: '字段数', dataIndex: 'field_count'},
      {title: '发布时间', dataIndex: 'published_at'},
    ];
    return (
      <Drawer title="已发布版本（不可变）" width={720} visible={store.versionsVisible}
              onClose={() => {
                store.versionsVisible = false;
              }}>
        <Table rowKey="id" columns={columns} dataSource={store.versions}
               pagination={false} size="small"/>
      </Drawer>
    );
  }

  _renderPdfParamsDrawer() {
    const store = this.store;
    return (
      <Drawer title="PDF 打印参数" width={520} visible={store.pdfDrawerVisible}
              onClose={() => store.closePdfDrawer()}>
        <div style={{color: '#999', marginBottom: 12}}>
          导出 PDF 与草稿预览默认使用以下参数；发布后随版本快照固定，
          历史台账不受后续修改影响。
        </div>
        {store.pdfForm && (
          <PdfParamsForm value={store.pdfForm}
                         onChange={form => store.setPdfForm(form)}/>
        )}
        <div style={{textAlign: 'right', marginTop: 8}}>
          <Space>
            <Button onClick={() => store.closePdfDrawer()}>取消</Button>
            <Button data-testid="tpl-pdf-params-save" type="primary"
                    loading={store.savingPdfParams}
                    onClick={() => store.savePdfParams().catch(() => {})}>
              保存
            </Button>
          </Space>
        </div>
      </Drawer>
    );
  }

  render() {
    const store = this.store;
    if (!store.current) {
      return (
        <div className="excel-template-page">
          {this._renderList()}
        </div>
      );
    }
    return (
      <div className="excel-template-page">
        {this._renderWorkspace()}
        {this._renderVersionsDrawer()}
        {this._renderPdfParamsDrawer()}
      </div>
    );
  }
}

export default ExcelTemplatePage;
