/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 附件数量徽标组件（列表页轻量展示）
 *
 * 用法：
 *   <AttachmentCountBadge
 *     count={record.attachment_count}
 *     onClick={() => openDetail(record)}
 *   />
 *
 * 展示规则：
 *   无附件（count=0 或 undefined）：显示 -
 *   有附件：显示 📎 图标 + 数量，可点击
 *
 * 该组件只负责展示数量和触发跳转，不负责上传、下载、删除。
 * 真正的附件管理仍由详情页里的 AttachmentManager 完成。
 */
import React from 'react';
import { Space, Badge } from 'antd';
import { PaperClipOutlined } from '@ant-design/icons';

export default function AttachmentCountBadge({ count, onClick }) {
  if (!count || count === 0) {
    return <span style={{ color: '#999' }}>-</span>;
  }

  const content = (
    <Space size={4} style={{ cursor: onClick ? 'pointer' : 'default', color: '#1890ff' }}>
      <PaperClipOutlined />
      <span>{count}</span>
    </Space>
  );

  if (onClick) {
    return (
      <a onClick={onClick} style={{ textDecoration: 'none' }}>
        <Badge count={count} size="small" offset={[6, -2]}>
          {content}
        </Badge>
      </a>
    );
  }

  return content;
}
