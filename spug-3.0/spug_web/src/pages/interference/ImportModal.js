/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 *
 * 干扰管理双业务类型（地面/空中）Excel 导入弹窗。
 *
 * 流程：选择文件 -> 预校验（后端只解析校验，不写库）-> 展示统计与错误/警告
 * -> 用户确认后才提交导入。
 * - 存在任何错误时「确认导入」按钮禁用；
 * - 错误至少展示：Excel 行号 / 字段 / 错误原因 / 原始值摘要；
 * - 「下载错误报告」为与原文件字段一致、额外增加「Excel行号」「错误原因」
 *   两列的 .xlsx 文件；
 * - 业务错误提示由 libs/http 拦截器统一处理，此处不重复提示（HTTP 200 + error）；
 * - 预校验通过后凭 validate_token 提交，防止重复提交。
 */
import React from 'react';
import {Modal, Button, Upload, Alert, Table, Descriptions, message} from 'antd';
import {InboxOutlined, ExportOutlined} from '@ant-design/icons';
import {http, exportFile} from 'libs';

const BUSINESS_META = {
  bridge: {
    label: '地面无线电通信异常/干扰',
    apiBase: '/api/interference/bridge/import',
    errorReportName: '地面干扰导入错误报告.xlsx',
  },
  air: {
    label: '空中干扰',
    apiBase: '/api/interference/air/import',
    errorReportName: '空中干扰导入错误报告.xlsx',
  },
};

const ERROR_COLUMNS = [
  {title: 'Excel行号', dataIndex: 'row', width: 90},
  {title: '字段', dataIndex: 'field', width: 110},
  {title: '错误原因', dataIndex: 'message'},
  {title: '原始值', dataIndex: 'value', ellipsis: true, width: 180},
];

export default class ImportModal extends React.Component {
  state = {file: null, validating: false, importing: false, reportLoading: false, result: null};

  get meta() {
    return BUSINESS_META[this.props.business] || BUSINESS_META.bridge;
  }

  get fileList() {
    const {file} = this.state;
    return file ? [{uid: 'import-file', name: file.name, status: 'done'}] : [];
  }

  get canConfirm() {
    const {file, result, importing} = this.state;
    return !!file && !!result && result.error_count === 0
      && result.total_rows > 0 && !importing;
  }

  handleBeforeUpload = (file) => {
    if (!file.name || !file.name.toLowerCase().endsWith('.xlsx')) {
      message.error('仅支持 .xlsx 格式的 Excel 文件');
      return false;
    }
    // 阻止自动上传：文件仅暂存，预校验/导入由用户显式触发
    this.setState({file, result: null});
    return false;
  };

  handleRemove = () => {
    this.setState({file: null, result: null});
  };

  handleValidate = () => {
    const {file} = this.state;
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    this.setState({validating: true});
    http.post(`${this.meta.apiBase}/validate/`, formData)
      .then(result => this.setState({result: result || null}))
      .catch(() => {
        // 错误提示由 http 拦截器统一处理
      })
      .finally(() => this.setState({validating: false}));
  };

  handleDownloadReport = () => {
    const {file} = this.state;
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    this.setState({reportLoading: true});
    exportFile({
      url: `${this.meta.apiBase}/error-report/`,
      method: 'post',
      data: formData,
      defaultFilename: this.meta.errorReportName,
    }).finally(() => this.setState({reportLoading: false}));
  };

  handleConfirm = () => {
    const {file, result} = this.state;
    if (!this.canConfirm) return;
    const formData = new FormData();
    formData.append('file', file);
    formData.append('validate_token', result.validate_token || '');
    this.setState({importing: true});
    http.post(`${this.meta.apiBase}/commit/`, formData)
      .then(data => {
        message.success(`成功导入 ${data && data.imported_count || 0} 条记录`);
        this.props.onSuccess && this.props.onSuccess(data && data.imported_count || 0);
      })
      .catch(() => {
        // 错误提示由 http 拦截器统一处理
      })
      .finally(() => this.setState({importing: false}));
  };

  handleClose = () => {
    if (this.state.importing) return;
    this.setState({file: null, result: null});
    this.props.onClose && this.props.onClose();
  };

  renderStats() {
    const {result} = this.state;
    return (
      <Descriptions size="small" column={4} bordered className="import-stats">
        <Descriptions.Item label="总行数">{result.total_rows}</Descriptions.Item>
        <Descriptions.Item label="可导入">
          <span style={{color: '#52c41a'}}>{result.valid_count}</span>
        </Descriptions.Item>
        <Descriptions.Item label="错误">
          <span style={{color: result.error_count > 0 ? '#f5222d' : undefined}}>
            {result.error_count}
          </span>
        </Descriptions.Item>
        <Descriptions.Item label="警告">
          <span style={{color: result.warning_count > 0 ? '#faad14' : undefined}}>
            {result.warning_count}
          </span>
        </Descriptions.Item>
      </Descriptions>
    );
  }

  renderResult() {
    const {result} = this.state;
    if (!result) return null;
    return (
      <div className="import-result">
        {this.renderStats()}
        {result.error_count > 0 ? (
          <Alert type="error" showIcon style={{marginTop: 12}}
                 message={`预校验发现 ${result.error_count} 个错误，请修正后重新上传`}
                 description="存在错误时无法导入，可下载错误报告定位问题。"/>
        ) : (
          <Alert type="success" showIcon style={{marginTop: 12}}
                 message={`预校验通过，可导入 ${result.valid_count} 条记录`}
                 description="请核对统计与警告信息，点击「确认导入」完成导入。"/>
        )}
        {result.warning_count > 0 && (
          <Alert type="warning" showIcon style={{marginTop: 12}}
                 message={`共 ${result.warning_count} 条警告`}
                 description={
                   <ul style={{margin: 0, paddingLeft: 18}}>
                     {result.warnings.map((w, index) => (
                       <li key={index}>{w.row ? `第 ${w.row} 行：` : ''}{w.message}</li>
                     ))}
                   </ul>
                 }/>
        )}
        {result.error_count > 0 && (
          <Table
            style={{marginTop: 12}}
            size="small"
            rowKey={(record, index) => index}
            columns={ERROR_COLUMNS}
            dataSource={result.errors}
            pagination={false}
            scroll={{y: 240}}
          />
        )}
      </div>
    );
  }

  render() {
    const {visible} = this.props;
    const {file, validating, importing, reportLoading, result} = this.state;
    return (
      <Modal
        title={`${this.meta.label} - 导入 Excel`}
        visible={visible}
        onCancel={this.handleClose}
        maskClosable={false}
        width={760}
        destroyOnClose
        footer={[
          result && result.error_count > 0 && (
            <Button key="report" icon={<ExportOutlined/>} loading={reportLoading}
                    onClick={this.handleDownloadReport}>下载错误报告</Button>
          ),
          <Button key="cancel" disabled={importing} onClick={this.handleClose}>取消</Button>,
          <Button key="confirm" type="primary" loading={importing}
                  disabled={!this.canConfirm}
                  onClick={this.handleConfirm}>确认导入</Button>,
        ]}>
        <Alert type="info" showIcon style={{marginBottom: 12}}
               message="请先在列表页下载导入模板，按模板填写后在此上传"
               description="上传后先预校验（不会写入数据），确认无误后再导入；地面与空中干扰的模板互不通用。"/>
        <Upload.Dragger
          accept=".xlsx"
          maxCount={1}
          fileList={this.fileList}
          beforeUpload={this.handleBeforeUpload}
          onRemove={this.handleRemove}>
          <p className="ant-upload-drag-icon"><InboxOutlined/></p>
          <p className="ant-upload-text">点击或拖拽 .xlsx 文件到此处</p>
        </Upload.Dragger>
        <div style={{marginTop: 12}}>
          <Button type="primary" disabled={!file} loading={validating}
                  onClick={this.handleValidate}>开始预校验</Button>
        </div>
        {this.renderResult()}
      </Modal>
    );
  }
}
