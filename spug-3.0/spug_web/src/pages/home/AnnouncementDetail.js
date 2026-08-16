/**
 * 公告详情抽屉（用户端）
 * 打开时调用详情接口自动标记已读，并刷新父级未读数据。
 */
import React, { useState, useEffect } from 'react';
import { Drawer, Spin, Tag, Descriptions, Empty, Button } from 'antd';
import { PaperClipOutlined } from '@ant-design/icons';
import { http } from 'libs';
import AttachmentManager from 'components/AttachmentManager';

const STATUS_TAG = {
  unpublished: { color: 'default', text: '未发布' },
  published: { color: 'green', text: '已发布' },
  expired: { color: 'red', text: '已过期' },
};

export default function AnnouncementDetail({ visible, announcementId, onClose, onAfterRead }) {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(null);

  useEffect(() => {
    if (!visible || !announcementId) return;
    setLoading(true);
    http.get(`/api/home/announcement/${announcementId}/`)
      .then(res => {
        setData(res);
        if (onAfterRead) onAfterRead();
      })
      .catch(() => { setData(null); /* 错误已由 http 拦截器统一提示 */ })
      .finally(() => setLoading(false));
  }, [visible, announcementId]);

  const status = data ? STATUS_TAG[data.computed_status] || STATUS_TAG.unpublished : null;

  return (
    <Drawer
      title={data ? data.title : '公告详情'}
      width={640}
      visible={visible}
      onClose={onClose}
      bodyStyle={{ paddingBottom: 24 }}
    >
      {loading && <Spin style={{ display: 'block', marginTop: 60, marginBottom: 60 }} />}
      {!loading && !data && <Empty description="公告不存在或无权限访问" />}
      {!loading && data && (
        <div>
          <div style={{ marginBottom: 12 }}>
            {data.is_important && <Tag color="gold" style={{ marginRight: 6 }}>重要</Tag>}
            {data.is_new && <Tag color="red" style={{ marginRight: 6 }}>新公告</Tag>}
            {status && <Tag color={status.color}>{status.text}</Tag>}
            {data.is_read && <Tag color="blue">已读</Tag>}
          </div>
          <Descriptions column={1} size="small" bordered style={{ marginBottom: 16 }}>
            <Descriptions.Item label="发布部门">{data.publish_department_name || '-'}</Descriptions.Item>
            <Descriptions.Item label="生效时间">
              {data.effective_start_at || '-'}{data.effective_end_at ? ` 至 ${data.effective_end_at}` : '（长期）'}
            </Descriptions.Item>
            <Descriptions.Item label="发布时间">{data.published_at || '-'}</Descriptions.Item>
            <Descriptions.Item label="发布人">{data.published_by_name || '-'}</Descriptions.Item>
          </Descriptions>
          <div
            style={{
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              background: '#fafafa',
              border: '1px solid #f0f0f0',
              borderRadius: 4,
              padding: 12,
              minHeight: 80,
              marginBottom: 16,
            }}
          >
            {data.content}
          </div>
          <div style={{ marginBottom: 8, fontWeight: 500 }}>
            <PaperClipOutlined style={{ marginRight: 6 }} />附件（{data.attachment_count || 0}）
          </div>
          <AttachmentManager
            module="announcement"
            recordId={data.id}
            listUrl={`/api/home/announcement/${data.id}/attachments/`}
            downloadUrlPrefix="/api/home/announcement/attachments/"
            previewUrlPrefix="/api/home/announcement/attachments/"
            readOnly
          />
          <div style={{ marginTop: 16, textAlign: 'right' }}>
            <Button onClick={onClose}>关闭</Button>
          </div>
        </div>
      )}
    </Drawer>
  );
}
