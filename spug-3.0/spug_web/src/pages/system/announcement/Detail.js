/**
 * 发布公告详情抽屉（管理端）
 * 展示完整内容 + 附件管理（上传/删除），并支持发布/撤回/删除操作。
 */
import React, { useState, useEffect } from 'react';
import { Drawer, Spin, Tag, Descriptions, Empty, Button, Popconfirm, Space, notification } from 'antd';
import { PaperClipOutlined } from '@ant-design/icons';
import { http, hasPermission } from 'libs';
import AttachmentManager from 'components/AttachmentManager';

const STATUS_TAG = {
  unpublished: { color: 'default', text: '未发布' },
  published: { color: 'green', text: '已发布' },
  expired: { color: 'red', text: '已过期' },
};

export default function AnnouncementDetail({ announcementId, onClose, onChanged }) {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(null);

  useEffect(() => {
    if (!announcementId) return;
    setLoading(true);
    http.get(`/api/home/announcement/admin/${announcementId}/`)
      .then(res => setData(res))
      .catch(e => { setData(null); notification.error({ message: '加载失败', description: e.message || String(e) }); })
      .finally(() => setLoading(false));
  }, [announcementId]);

  const doPublish = () => {
    http.post(`/api/home/announcement/admin/${announcementId}/publish/`)
      .then(() => { notification.success({ message: '发布成功' }); setData({ ...data, computed_status: 'published' }); if (onChanged) onChanged(); })
      .catch(e => notification.error({ message: '发布失败', description: e.message || String(e) }));
  };
  const doWithdraw = () => {
    http.post(`/api/home/announcement/admin/${announcementId}/withdraw/`)
      .then(() => { notification.success({ message: '已撤回' }); setData({ ...data, computed_status: 'unpublished' }); if (onChanged) onChanged(); })
      .catch(e => notification.error({ message: '撤回失败', description: e.message || String(e) }));
  };
  const doDelete = () => {
    http.delete(`/api/home/announcement/admin/${announcementId}/`)
      .then(() => { notification.success({ message: '已删除' }); if (onChanged) onChanged(); onClose(); })
      .catch(e => notification.error({ message: '删除失败', description: e.message || String(e) }));
  };

  const status = data ? STATUS_TAG[data.computed_status] || STATUS_TAG.unpublished : null;
  const canEdit = hasPermission('home.announcement.edit');
  const canPublish = hasPermission('home.announcement.publish');
  const canWithdraw = hasPermission('home.announcement.withdraw');
  const canDelete = hasPermission('home.announcement.delete');

  return (
    <Drawer
      title={data ? data.title : '公告详情'}
      width={680}
      visible={!!announcementId}
      onClose={onClose}
      bodyStyle={{ paddingBottom: 24 }}
    >
      {loading && <Spin style={{ display: 'block', marginTop: 60, marginBottom: 60 }} />}
      {!loading && !data && <Empty description="公告不存在" />}
      {!loading && data && (
        <div>
          <div style={{ marginBottom: 12 }}>
            {data.is_important && <Tag color="gold" style={{ marginRight: 6 }}>重要</Tag>}
            {data.is_new && <Tag color="red" style={{ marginRight: 6 }}>新公告</Tag>}
            {status && <Tag color={status.color}>{status.text}</Tag>}
          </div>
          <Descriptions column={1} size="small" bordered style={{ marginBottom: 16 }}>
            <Descriptions.Item label="发布范围">{data.scope_label}</Descriptions.Item>
            <Descriptions.Item label="发布部门">{data.publish_department_name || '-'}</Descriptions.Item>
            <Descriptions.Item label="生效时间">
              {data.effective_start_at || '-'}{data.effective_end_at ? ` 至 ${data.effective_end_at}` : '（长期）'}
            </Descriptions.Item>
            <Descriptions.Item label="发布时间">{data.published_at || '-'}</Descriptions.Item>
            <Descriptions.Item label="发布人">{data.published_by_name || '-'}</Descriptions.Item>
            {data.withdrawn_by_name && <Descriptions.Item label="撤回人">{data.withdrawn_by_name}</Descriptions.Item>}
          </Descriptions>
          <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: '#fafafa', border: '1px solid #f0f0f0', borderRadius: 4, padding: 12, minHeight: 80, marginBottom: 16 }}>
            {data.content}
          </div>
          <div style={{ marginBottom: 8, fontWeight: 500 }}>
            <PaperClipOutlined style={{ marginRight: 6 }} />附件（{data.attachment_count || 0}）
          </div>
          <AttachmentManager
            module="announcement"
            recordId={data.id}
            listUrl={`/api/home/announcement/admin/${data.id}/attachments/`}
            uploadUrl={`/api/home/announcement/admin/${data.id}/attachments/`}
            deleteUrl="/api/home/announcement/admin/attachments/"
            downloadUrlPrefix="/api/home/announcement/attachments/"
            previewUrlPrefix="/api/home/announcement/attachments/"
          />
          <div style={{ marginTop: 16, textAlign: 'right' }}>
            <Space>
              {data.computed_status !== 'published' && canPublish && (
                <Button type="primary" onClick={doPublish}>{data.computed_status === 'expired' ? '重新发布' : '发布'}</Button>
              )}
              {data.computed_status === 'published' && canWithdraw && <Button onClick={doWithdraw}>撤回</Button>}
              <Button onClick={onClose}>关闭</Button>
              {canDelete && (
                <Popconfirm title="确定删除该公告？" onConfirm={doDelete}>
                  <Button danger>删除</Button>
                </Popconfirm>
              )}
            </Space>
          </div>
        </div>
      )}
    </Drawer>
  );
}
