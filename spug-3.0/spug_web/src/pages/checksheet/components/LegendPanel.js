/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Space } from 'antd';

export default function LegendPanel() {
  return (
    <div className="legend-section">
      <h4>图例说明</h4>
      <Space size="large">
        <span><span style={{ color: '#52c41a', fontWeight: 'bold', fontSize: '16px' }}>√</span> 正常</span>
        <span><span style={{ color: '#ff4d4f', fontWeight: 'bold', fontSize: '16px' }}>×</span> 异常（点击状态可填写备注）</span>
        <span><span style={{ color: '#d9d9d9', fontWeight: 'bold', fontSize: '16px' }}>—</span> 未检查</span>
        <span>💡 操作提示：左键点击状态切换正常/未检查，右键点击状态设置为异常</span>
      </Space>
    </div>
  );
}
