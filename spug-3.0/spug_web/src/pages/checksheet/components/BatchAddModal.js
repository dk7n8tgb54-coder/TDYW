/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Modal, Input, message } from 'antd';

/**
 * 批量添加检查内容弹窗组件
 * P2-6 修复：从 TemplateForm 中提取，缩短主组件行数
 */
export default function BatchAddModal({ visible, onClose, onConfirm }) {
  const [inputText, setInputText] = React.useState(
    '导航设备运行情况;通信设备运行情况;自动化设备运行情况'
  );

  const handleConfirm = () => {
    if (inputText) {
      const newItems = inputText
        .replace(/；/g, ';')
        .split(';')
        .map(item => item.trim())
        .filter(item => item);
      onConfirm(newItems);
    }
    setInputText('导航设备运行情况;通信设备运行情况;自动化设备运行情况');
    onClose();
  };

  const handleClose = () => {
    setInputText('导航设备运行情况;通信设备运行情况;自动化设备运行情况');
    onClose();
  };

  return (
    <Modal
      title="批量添加检查内容"
      open={visible}
      onOk={handleConfirm}
      onCancel={handleClose}
      okText="确认添加"
      cancelText="取消"
    >
      <p style={{ marginBottom: 8 }}>请输入多个检查内容，使用分号<strong>;</strong>分隔：</p>
      <Input.TextArea
        rows={4}
        placeholder="示例：导航设备运行情况;通信设备运行情况;自动化设备运行情况"
        value={inputText}
        onChange={(e) => setInputText(e.target.value)}
      />
    </Modal>
  );
}
