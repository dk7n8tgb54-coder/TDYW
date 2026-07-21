/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 部门值班日志 - PDF 导出按钮
 *
 * 设计：
 * - 复用公共 exportFile（libs/exportFile.js）完成二进制下载、文件名解析、错误透传；
 * - 自己管理 Modal：让用户勾选 include_void（是否包含已作废记录）；
 * - 导出参数继承列表页当前筛选条件（日期范围/值班员/关键字）；
 * - 仅 export 权限可见。
 *
 * 提示词第 10.2 条：有 can_export 时显示"导出 PDF"按钮；不得显示 Excel/Word。
 * 提示词第 10.7 条：单次最多 500 条，超过时后端返回明确错误。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Button, Modal, Checkbox, message} from 'antd';
import {ExportOutlined} from '@ant-design/icons';
import {hasPermission, Permission, exportFile} from 'libs';
import store from './departmentDutyLogStore';

@observer
class DepartmentDutyLogExportButton extends React.Component {
  state = {
    visible: false,
    includeVoid: false,
    exporting: false,
  };

  handleOpen = () => {
    this.setState({visible: true, includeVoid: false});
  };

  handleCancel = () => {
    if (this.state.exporting) return; // 导出中禁止关闭
    this.setState({visible: false});
  };

  buildExportData = () => {
    const data = {
      include_void: this.state.includeVoid,
    };
    // 继承列表页当前筛选条件
    if (store.f_start_date) data.start_date = store.f_start_date.format('YYYY-MM-DD');
    if (store.f_end_date) data.end_date = store.f_end_date.format('YYYY-MM-DD');
    if (store.f_duty_person_name) data.duty_person_name = store.f_duty_person_name;
    if (store.f_keyword) data.keyword = store.f_keyword;
    return data;
  };

  handleExport = async () => {
    this.setState({exporting: true});
    try {
      await exportFile({
        url: '/api/department-duty-log/export/pdf/',
        method: 'post',
        data: this.buildExportData(),
        defaultFilename: '部门值班日志.pdf',
        timeout: 120000, // PDF 生成可能较慢，延长到 2 分钟
        loadingText: '正在生成 PDF，请稍候...',
      });
      this.setState({visible: false});
    } catch (e) {
      // http 拦截器已处理错误提示
    } finally {
      this.setState({exporting: false});
    }
  };

  render() {
    const {isSuper} = Permission;
    const hasAuth = isSuper || hasPermission('department_duty_log.department_duty_log.export');
    if (!hasAuth) return null;

    return (
      <>
        <Button
          icon={<ExportOutlined/>}
          onClick={this.handleOpen}
        >
          导出 PDF
        </Button>

        <Modal
          title="导出部门值班日志 PDF"
          visible={this.state.visible}
          onCancel={this.handleCancel}
          onOk={this.handleExport}
          confirmLoading={this.state.exporting}
          okText="开始导出"
          cancelText="取消"
          maskClosable={false}
          width={480}
        >
          <p style={{marginBottom: 12}}>
            将按当前筛选条件导出<strong>已签署</strong>的部门值班日志为 PDF 文件，
            包含值班记录、签署信息、固定版本签名图片。
          </p>

          <div style={{marginBottom: 12}}>
            <Checkbox
              checked={this.state.includeVoid}
              onChange={e => this.setState({includeVoid: e.target.checked})}
            >
              同时包含已作废记录
            </Checkbox>
          </div>

          <div style={{
            background: '#fafafa',
            padding: 12,
            borderRadius: 4,
            fontSize: 12,
            color: '#666',
          }}>
            <div style={{marginBottom: 4, fontWeight: 500, color: '#333'}}>导出范围：</div>
            {store.f_start_date && store.f_end_date ? (
              <div>日期：{store.f_start_date.format('YYYY-MM-DD')} ~ {store.f_end_date.format('YYYY-MM-DD')}</div>
            ) : (
              <div>日期：不限</div>
            )}
            {store.f_duty_person_name && <div>值班员：{store.f_duty_person_name}</div>}
            {store.f_keyword && <div>关键字：{store.f_keyword}</div>}
            <div>状态：已签署{this.state.includeVoid ? ' + 已作废' : ''}</div>
            <div style={{marginTop: 8, color: '#999'}}>
              单次最多 500 条，超过请缩小筛选范围。
            </div>
          </div>

          <p style={{marginTop: 12, marginBottom: 0, fontSize: 12, color: '#999'}}>
            注：PDF 仅为系统签署证据的可读归档输出，不代表法定可靠电子签名凭证。
          </p>
        </Modal>
      </>
    );
  }
}

export default DepartmentDutyLogExportButton;
