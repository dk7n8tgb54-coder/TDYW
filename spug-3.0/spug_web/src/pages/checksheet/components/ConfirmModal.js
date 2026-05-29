/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Modal, Input } from 'antd';

export default function ConfirmModal({ visible, onOk, onCancel, currentUser }) {
  return (
    <Modal
      title="签字确认"
      visible={visible}
      onOk={onOk}
      onCancel={onCancel}
      okText="确认"
      cancelText="取消"
      width={400}
      destroyOnClose={true}
    >
      <div style={{ marginTop: 20 }}>
        <label style={{ display: 'block', marginBottom: 8, fontWeight: 'bold' }}>值班人员：</label>
        <Input
          value={currentUser}
          disabled
          style={{ backgroundColor: '#f5f5f5', color: '#000', fontWeight: 'bold' }}
        />
        <p style={{ marginTop: 16, color: '#999', fontSize: '12px' }}>
          * 确认后您的姓名将被记录为值班人员，签字确认后才能进行保存操作
        </p>
      </div>
    </Modal>
  );
}
