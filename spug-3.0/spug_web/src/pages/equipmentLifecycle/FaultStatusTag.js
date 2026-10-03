/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 故障状态标签（2026-10-03 撤销登记改版）：
 * - 已撤销（cancelled）使用虚线边框的中性灰样式——明显区别于处置中
 *   （geekblue 实色）与已关闭（灰实线），但不用红/橙等告警色，保持克制；
 * - 其余状态沿用 FAULT_STATUS_COLOR 配色。
 */
import React from 'react';
import { Tag } from 'antd';
import { FAULT_STATUS_TEXT, FAULT_STATUS_COLOR } from './constants';

export default function FaultStatusTag({status}) {
  if (status === 'cancelled') {
    return (
      <Tag
        color="default"
        style={{borderStyle: 'dashed', color: 'rgba(0, 0, 0, 0.45)'}}
      >
        {FAULT_STATUS_TEXT[status] || status}
      </Tag>
    );
  }
  return (
    <Tag color={FAULT_STATUS_COLOR[status]}>
      {FAULT_STATUS_TEXT[status] || status}
    </Tag>
  );
}
