/**
 * 公共导出按钮组件
 *
 * 职责：
 * - 统一按钮样式与图标
 * - 统一权限控制（复用 hasPermission，与 AuthButton 行为一致）
 * - 统一 loading 状态
 * - 内部调用 exportFile 完成下载，调用方只需提供 url/params/filename
 *
 * 示例：
 *   <ExportButton
 *     auth="fault.faultrecord.view"
 *     url="/api/fault/faultrecord/export/"
 *     params={store.getExportParams()}
 *     filename="故障处置记录.xlsx">
 *     导出
 *   </ExportButton>
 *
 * 如需 POST 方式导出（如 PDF 传 body），指定 method="post" 并传 data。
 */
import React from 'react';
import { Button } from 'antd';
import { ExportOutlined } from '@ant-design/icons';
import { hasPermission, Permission, exportFile } from 'libs';

export default class ExportButton extends React.Component {
  state = { loading: false };

  handleClick = async () => {
    const { url, method, params, data, filename, beforeExport, onError } = this.props;
    // 导出前钩子，可用于参数校验或二次确认
    if (typeof beforeExport === 'function') {
      const result = beforeExport();
      if (result === false) return;
    }
    this.setState({ loading: true });
    try {
      await exportFile({
        url,
        method,
        params,
        data,
        defaultFilename: filename,
      });
    } catch (e) {
      if (typeof onError === 'function') onError(e);
    } finally {
      this.setState({ loading: false });
    }
  };

  render() {
    const { isSuper } = Permission;
    const {
      auth,
      children,
      url,
      params,
      data,
      filename,
      beforeExport,
      onError,
      icon,
      ...buttonProps
    } = this.props;
    const hasAuth = !auth || isSuper || hasPermission(auth);
    if (!hasAuth) return null;
    return (
      <Button
        icon={icon || <ExportOutlined/>}
        loading={this.state.loading}
        onClick={this.handleClick}
        {...buttonProps}>
        {children || '导出'}
      </Button>
    );
  }
}
