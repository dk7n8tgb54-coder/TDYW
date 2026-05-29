/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Tag } from 'antd';

const STATUS_COLOR_MAP = {
  '处理中': 'processing',
  '已完成': 'success',
};

export default function StatusTag({ status }) {
  return <Tag color={STATUS_COLOR_MAP[status] || 'default'}>{status}</Tag>;
}
